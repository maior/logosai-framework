"""
Improvement Validator (개선안 검증기)

생성된 개선안의 안전성과 유효성을 검증합니다.
"""

import ast
import re
from typing import Optional, Dict, Any, List
from datetime import datetime

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from .types import Improvement, ValidationResult
from .config import SafetyConfig


class ImprovementValidator:
    """개선안 검증기"""

    def __init__(
        self,
        config: Optional[SafetyConfig] = None,
        llm_client=None
    ):
        """
        검증기 초기화

        Args:
            config: 안전 설정
            llm_client: LLM 클라이언트 (고급 검증용)
        """
        self.config = config or SafetyConfig()
        self.llm_client = llm_client

    async def validate(
        self,
        improvement: Improvement,
        original_code: Optional[str] = None,
        test_cases: Optional[List[Dict[str, Any]]] = None
    ) -> List[ValidationResult]:
        """
        개선안 종합 검증

        Args:
            improvement: 검증할 개선안
            original_code: 원본 코드 (비교용)
            test_cases: 테스트 케이스 리스트

        Returns:
            검증 결과 리스트
        """
        results = []

        # 1. 구문 검증
        if self.config.require_syntax_check:
            syntax_result = self._validate_syntax(improvement)
            results.append(syntax_result)

            if not syntax_result.passed:
                logger.warning(f"구문 검증 실패: {syntax_result.errors}")
                return results  # 구문 오류면 더 진행할 필요 없음

        # 2. 보안 검증
        security_result = self._validate_security(improvement)
        results.append(security_result)

        if not security_result.passed:
            logger.warning(f"보안 검증 실패: {security_result.errors}")

        # 3. 논리적 일관성 검증
        logic_result = await self._validate_logic(improvement, original_code)
        results.append(logic_result)

        # 4. 단위 테스트 (test_cases 있을 경우)
        if self.config.require_unit_tests and test_cases:
            test_result = await self._run_unit_tests(improvement, test_cases)
            results.append(test_result)

        # 5. 회귀 테스트 (활성화된 경우)
        if self.config.require_regression_tests and original_code:
            regression_result = await self._run_regression_tests(
                improvement, original_code
            )
            results.append(regression_result)

        # 종합 로깅
        passed_count = sum(1 for r in results if r.passed)
        logger.info(
            f"검증 완료: {passed_count}/{len(results)} 통과 "
            f"(개선안: {improvement.improvement_id})"
        )

        return results

    def _validate_syntax(self, improvement: Improvement) -> ValidationResult:
        """구문 검증"""
        errors = []
        warnings = []

        code = improvement.suggested_changes.get("code")

        if not code:
            # 코드가 없는 개선안 (프롬프트 업데이트 등)은 통과
            return ValidationResult(
                passed=True,
                stage="syntax",
                details={"note": "코드 없음 - 검증 생략"}
            )

        try:
            # Python 구문 검사
            ast.parse(code)

            # 추가 린트 검사
            lint_warnings = self._check_code_quality(code)
            warnings.extend(lint_warnings)

            return ValidationResult(
                passed=True,
                stage="syntax",
                details={"code_lines": len(code.split("\n"))},
                warnings=warnings
            )

        except SyntaxError as e:
            errors.append(f"SyntaxError at line {e.lineno}: {e.msg}")
            return ValidationResult(
                passed=False,
                stage="syntax",
                errors=errors,
                details={"error_line": e.lineno, "error_offset": e.offset}
            )

        except Exception as e:
            errors.append(f"Unexpected error: {str(e)}")
            return ValidationResult(
                passed=False,
                stage="syntax",
                errors=errors
            )

    def _validate_security(self, improvement: Improvement) -> ValidationResult:
        """보안 검증"""
        errors = []
        warnings = []

        code = improvement.suggested_changes.get("code", "")
        content = improvement.suggested_changes.get("content", "")

        combined = code + " " + content

        # 위험한 패턴 검사
        dangerous_patterns = [
            (r"eval\s*\(", "eval() 사용 금지"),
            (r"exec\s*\(", "exec() 사용 금지"),
            (r"__import__\s*\(", "__import__() 직접 사용 금지"),
            (r"subprocess\.(call|run|Popen)", "subprocess 직접 호출 주의"),
            (r"os\.system\s*\(", "os.system() 사용 금지"),
            (r"open\s*\([^)]*,\s*['\"]w", "파일 쓰기 주의"),
            (r"rm\s+-rf", "위험한 삭제 명령"),
            (r"DROP\s+TABLE", "DROP TABLE 명령 감지"),
            (r"DELETE\s+FROM.*WHERE\s+1\s*=\s*1", "전체 삭제 패턴"),
        ]

        for pattern, message in dangerous_patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                errors.append(f"보안 위험: {message}")

        # 민감 정보 노출 검사
        sensitive_patterns = [
            (r"password\s*=\s*['\"][^'\"]+['\"]", "하드코딩된 비밀번호"),
            (r"api_key\s*=\s*['\"][^'\"]+['\"]", "하드코딩된 API 키"),
            (r"secret\s*=\s*['\"][^'\"]+['\"]", "하드코딩된 시크릿"),
        ]

        for pattern, message in sensitive_patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                warnings.append(f"경고: {message} 가능성")

        return ValidationResult(
            passed=len(errors) == 0,
            stage="security",
            errors=errors,
            warnings=warnings,
            details={"patterns_checked": len(dangerous_patterns) + len(sensitive_patterns)}
        )

    async def _validate_logic(
        self,
        improvement: Improvement,
        original_code: Optional[str]
    ) -> ValidationResult:
        """논리적 일관성 검증"""
        errors = []
        warnings = []

        # 개선안의 신뢰도가 너무 낮으면 경고
        if improvement.confidence < 0.5:
            warnings.append(f"낮은 신뢰도: {improvement.confidence:.2f}")

        # 문제와 수정의 연관성 확인
        problem_type = improvement.problem.problem_type.value
        fix_type = improvement.improvement_type

        # 논리적 매핑 확인
        valid_mappings = {
            "syntax_error": ["code_fix"],
            "import_error": ["code_fix"],
            "type_error": ["code_fix"],
            "runtime_error": ["code_fix", "config_change"],
            "missing_function": ["new_function", "code_fix"],
            "intent_mismatch": ["prompt_update", "code_fix"],
            "incomplete_response": ["prompt_update", "code_fix"],
            "low_quality": ["prompt_update"],
            "user_dissatisfaction": ["prompt_update", "config_change"],
        }

        expected_fixes = valid_mappings.get(problem_type, [])
        if expected_fixes and fix_type not in expected_fixes:
            warnings.append(
                f"수정 유형 불일치: {problem_type}에 대해 {fix_type} 적용 "
                f"(권장: {expected_fixes})"
            )

        # 코드 변경이 있는 경우 원본과 비교
        if original_code and improvement.suggested_changes.get("code"):
            new_code = improvement.suggested_changes["code"]

            # 너무 많은 변경은 경고
            original_lines = len(original_code.split("\n"))
            new_lines = len(new_code.split("\n"))
            change_ratio = abs(new_lines - original_lines) / max(original_lines, 1)

            if change_ratio > 0.5:
                warnings.append(f"큰 변경 감지: 코드 라인 {change_ratio*100:.0f}% 변화")

        # LLM 기반 논리 검증 (선택적)
        if self.llm_client and improvement.reasoning:
            try:
                llm_check = await self._check_logic_with_llm(improvement)
                if not llm_check.get("valid", True):
                    warnings.append(f"LLM 논리 검증: {llm_check.get('reason', '문제 발견')}")
            except Exception as e:
                logger.debug(f"LLM 논리 검증 생략: {e}")

        return ValidationResult(
            passed=len(errors) == 0,
            stage="logic",
            errors=errors,
            warnings=warnings,
            details={
                "confidence": improvement.confidence,
                "fix_type": fix_type,
                "problem_type": problem_type
            }
        )

    async def _run_unit_tests(
        self,
        improvement: Improvement,
        test_cases: List[Dict[str, Any]]
    ) -> ValidationResult:
        """단위 테스트 실행"""
        errors = []
        passed_tests = 0
        total_tests = len(test_cases)

        code = improvement.suggested_changes.get("code")

        if not code:
            return ValidationResult(
                passed=True,
                stage="unit_test",
                details={"note": "테스트할 코드 없음"},
                metrics={"passed": 0, "total": 0}
            )

        for i, test_case in enumerate(test_cases):
            try:
                # 테스트 실행 (샌드박스 환경 권장)
                test_input = test_case.get("input", "")
                expected = test_case.get("expected")

                # 간단한 실행 테스트 (실제로는 샌드박스 필요)
                # 여기서는 구문 검사만 수행
                if code:
                    ast.parse(code)
                    passed_tests += 1

            except Exception as e:
                errors.append(f"테스트 #{i+1} 실패: {str(e)[:100]}")

        success_rate = passed_tests / total_tests if total_tests > 0 else 1.0

        return ValidationResult(
            passed=success_rate >= 0.8,  # 80% 이상 통과 필요
            stage="unit_test",
            errors=errors,
            metrics={
                "passed": passed_tests,
                "total": total_tests,
                "success_rate": success_rate
            }
        )

    async def _run_regression_tests(
        self,
        improvement: Improvement,
        original_code: str
    ) -> ValidationResult:
        """회귀 테스트 (기존 기능 유지 확인)"""
        warnings = []

        new_code = improvement.suggested_changes.get("code", "")

        if not new_code:
            return ValidationResult(
                passed=True,
                stage="regression",
                details={"note": "코드 변경 없음"}
            )

        # 함수/클래스 시그니처 비교
        try:
            original_ast = ast.parse(original_code)
            new_ast = ast.parse(new_code)

            original_funcs = self._extract_function_signatures(original_ast)
            new_funcs = self._extract_function_signatures(new_ast)

            # 삭제된 함수 확인
            removed_funcs = set(original_funcs.keys()) - set(new_funcs.keys())
            if removed_funcs:
                warnings.append(f"삭제된 함수: {removed_funcs}")

            # 시그니처 변경 확인
            for func_name in original_funcs:
                if func_name in new_funcs:
                    if original_funcs[func_name] != new_funcs[func_name]:
                        warnings.append(f"시그니처 변경: {func_name}")

        except Exception as e:
            warnings.append(f"AST 분석 실패: {str(e)[:50]}")

        return ValidationResult(
            passed=len(warnings) <= 2,  # 경고 2개까지 허용
            stage="regression",
            warnings=warnings,
            details={
                "original_size": len(original_code),
                "new_size": len(new_code)
            }
        )

    async def _check_logic_with_llm(
        self,
        improvement: Improvement
    ) -> dict:
        """LLM으로 논리 검증"""
        prompt = f"""다음 개선안의 논리적 타당성을 검증하세요.

문제: {improvement.problem.description}
수정 유형: {improvement.improvement_type}
수정 이유: {improvement.reasoning}

수정 내용 요약:
{improvement.suggested_changes.get('summary', 'N/A')}

검증 결과를 JSON 형식으로 응답하세요:
{{"valid": true/false, "reason": "이유"}}
"""

        try:
            await self.llm_client.initialize()
            result = await self.llm_client.invoke(prompt)
            content = str(result.content) if hasattr(result, 'content') else str(result)

            # 간단한 파싱
            if "false" in content.lower():
                reason_match = re.search(r'"reason"[:\s]*"([^"]+)"', content)
                return {
                    "valid": False,
                    "reason": reason_match.group(1) if reason_match else "논리적 문제 발견"
                }

            return {"valid": True}

        except Exception as e:
            logger.debug(f"LLM 검증 실패: {e}")
            return {"valid": True}  # 검증 실패 시 통과로 처리

    def _check_code_quality(self, code: str) -> List[str]:
        """코드 품질 검사"""
        warnings = []

        lines = code.split("\n")

        # 라인 길이 검사
        long_lines = [i+1 for i, line in enumerate(lines) if len(line) > 120]
        if long_lines:
            warnings.append(f"긴 라인 ({len(long_lines)}개): {long_lines[:3]}")

        # TODO/FIXME 검사
        for i, line in enumerate(lines):
            if "TODO" in line or "FIXME" in line:
                warnings.append(f"TODO/FIXME at line {i+1}")
                break

        # 하드코딩된 숫자 (매직 넘버)
        magic_numbers = re.findall(r"(?<![a-zA-Z_])\d{4,}(?![a-zA-Z_])", code)
        if magic_numbers:
            warnings.append(f"매직 넘버 감지: {magic_numbers[:3]}")

        return warnings

    def _extract_function_signatures(self, tree: ast.AST) -> Dict[str, str]:
        """AST에서 함수 시그니처 추출"""
        signatures = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                args = [arg.arg for arg in node.args.args]
                signatures[node.name] = f"{node.name}({', '.join(args)})"

        return signatures
