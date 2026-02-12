"""
Improvement Generator (개선 생성기)

학습된 패턴과 감지된 문제를 바탕으로 개선안을 생성합니다.
- Self-Healing: 에러 수정 코드 생성
- Self-Growing: 새 기능/프롬프트 개선 생성
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import re
import uuid

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from .types import (
    DetectedProblem,
    LearnedPattern,
    Improvement,
    ProblemType,
    Severity
)
from .config import EvolutionConfig


class ImprovementGenerator:
    """개선안 생성기"""

    def __init__(
        self,
        config: Optional[EvolutionConfig] = None,
        llm_client=None
    ):
        """
        생성기 초기화

        Args:
            config: 진화 설정
            llm_client: LLM 클라이언트
        """
        self.config = config
        self.llm_client = llm_client

        # 수정 유형별 프롬프트 템플릿
        self._fix_templates = {
            "code_fix": self._get_code_fix_prompt,
            "prompt_update": self._get_prompt_update_prompt,
            "new_function": self._get_new_function_prompt,
            "config_change": self._get_config_change_prompt,
        }

    async def generate(
        self,
        problem: DetectedProblem,
        pattern: Optional[LearnedPattern] = None,
        agent_source: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[Improvement]:
        """
        개선안 생성

        Args:
            problem: 감지된 문제
            pattern: 관련 학습된 패턴 (선택)
            agent_source: 에이전트 소스 코드 (선택)
            context: 추가 컨텍스트

        Returns:
            생성된 개선안 또는 None
        """
        if not self.llm_client:
            logger.warning("LLM 클라이언트가 없어 개선안을 생성할 수 없습니다.")
            return None

        # 수정 유형 결정
        fix_type = self._determine_fix_type(problem, pattern)

        # 프롬프트 생성
        prompt = self._build_improvement_prompt(
            problem, pattern, fix_type, agent_source, context
        )

        try:
            await self.llm_client.initialize()
            result = await self.llm_client.invoke(prompt)
            content = str(result.content) if hasattr(result, 'content') else str(result)

            # 응답 파싱
            improvement = self._parse_improvement_response(
                content, problem, pattern, fix_type
            )

            if improvement:
                logger.info(
                    f"개선안 생성: {improvement.improvement_id} "
                    f"(유형: {fix_type}, 신뢰도: {improvement.confidence:.2f})"
                )

            return improvement

        except Exception as e:
            logger.error(f"개선안 생성 실패: {e}")
            return None

    async def generate_from_pattern(
        self,
        pattern: LearnedPattern,
        agent_source: Optional[str] = None
    ) -> Optional[Improvement]:
        """
        학습된 패턴에서 개선안 생성

        Args:
            pattern: 학습된 패턴
            agent_source: 에이전트 소스 코드

        Returns:
            개선안
        """
        # 패턴에서 가상 문제 생성
        problem = DetectedProblem(
            problem_type=pattern.problem_type,
            severity=Severity.MEDIUM,
            description=", ".join(pattern.common_issues[:3]),
            details={
                "pattern_id": pattern.pattern_id,
                "frequency": pattern.frequency,
                "examples": pattern.examples
            }
        )

        return await self.generate(
            problem=problem,
            pattern=pattern,
            agent_source=agent_source
        )

    async def generate_multiple(
        self,
        problems: List[DetectedProblem],
        patterns: Optional[List[LearnedPattern]] = None,
        agent_source: Optional[str] = None,
        max_improvements: int = 5
    ) -> List[Improvement]:
        """
        여러 개선안 생성

        Args:
            problems: 문제 리스트
            patterns: 패턴 리스트
            agent_source: 에이전트 소스 코드
            max_improvements: 최대 생성 개수

        Returns:
            개선안 리스트
        """
        improvements = []

        # 심각도 순으로 정렬
        sorted_problems = sorted(
            problems,
            key=lambda p: ["critical", "high", "medium", "low", "info"].index(p.severity.value)
        )

        for problem in sorted_problems[:max_improvements]:
            # 관련 패턴 찾기
            related_pattern = None
            if patterns:
                for pattern in patterns:
                    if pattern.problem_type == problem.problem_type:
                        related_pattern = pattern
                        break

            improvement = await self.generate(
                problem=problem,
                pattern=related_pattern,
                agent_source=agent_source
            )

            if improvement:
                improvements.append(improvement)

        return improvements

    def _determine_fix_type(
        self,
        problem: DetectedProblem,
        pattern: Optional[LearnedPattern]
    ) -> str:
        """수정 유형 결정"""
        # 패턴에서 제안된 유형 사용
        if pattern and pattern.suggested_fix_type:
            return pattern.suggested_fix_type

        # 문제 유형별 기본 매핑
        type_mapping = {
            ProblemType.SYNTAX_ERROR: "code_fix",
            ProblemType.IMPORT_ERROR: "code_fix",
            ProblemType.TYPE_ERROR: "code_fix",
            ProblemType.RUNTIME_ERROR: "code_fix",
            ProblemType.MISSING_FUNCTION: "new_function",
            ProblemType.INTENT_MISMATCH: "prompt_update",
            ProblemType.INCOMPLETE_RESPONSE: "prompt_update",
            ProblemType.LOW_QUALITY: "prompt_update",
            ProblemType.USER_DISSATISFACTION: "prompt_update",
        }

        return type_mapping.get(problem.problem_type, "prompt_update")

    def _build_improvement_prompt(
        self,
        problem: DetectedProblem,
        pattern: Optional[LearnedPattern],
        fix_type: str,
        agent_source: Optional[str],
        context: Optional[Dict[str, Any]]
    ) -> str:
        """개선안 생성 프롬프트 구성"""
        template_func = self._fix_templates.get(fix_type, self._get_prompt_update_prompt)
        return template_func(problem, pattern, agent_source, context)

    def _get_code_fix_prompt(
        self,
        problem: DetectedProblem,
        pattern: Optional[LearnedPattern],
        agent_source: Optional[str],
        context: Optional[Dict[str, Any]]
    ) -> str:
        """코드 수정 프롬프트"""
        # Build pattern section
        pattern_section = ""
        if pattern:
            pattern_section = "## 유사 문제 패턴\n" + str(pattern.common_issues)

        # Build code section
        code_section = ""
        if agent_source:
            code_preview = agent_source[:2000] if len(agent_source) > 2000 else agent_source
            code_section = "## 현재 코드 (일부)\n```python\n" + code_preview + "\n```"

        stack_trace = (problem.stack_trace or 'N/A')[:500]

        return f"""당신은 Python 코드 수정 전문가입니다.

## 문제
- 유형: {problem.problem_type.value}
- 설명: {problem.description}
- 에러 메시지: {problem.error_message or 'N/A'}
- 스택 트레이스: {stack_trace}

## 관련 쿼리
{problem.query or 'N/A'}

{pattern_section}

{code_section}

## 요청
1. 문제의 원인을 분석하세요.
2. 최소한의 수정으로 문제를 해결하세요.
3. 기존 기능은 반드시 유지하세요.

## 응답 형식
원인 분석:
[문제 원인 설명]

수정 사항:
[수정 내용]

수정 코드:
[수정된 코드]

신뢰도: [0.0 ~ 1.0]
롤백 가능: [예/아니오]
"""

    def _get_prompt_update_prompt(
        self,
        problem: DetectedProblem,
        pattern: Optional[LearnedPattern],
        agent_source: Optional[str],
        context: Optional[Dict[str, Any]]
    ) -> str:
        """프롬프트 업데이트 프롬프트"""
        # Build pattern section
        pattern_section = ""
        if pattern:
            pattern_section = (
                "## 반복되는 문제 패턴\n"
                f"- 빈도: {pattern.frequency}회\n"
                f"- 공통 문제: {pattern.common_issues}"
            )

        response_preview = (problem.response or 'N/A')[:500]

        return f"""당신은 LLM 프롬프트 엔지니어링 전문가입니다.

## 문제
- 유형: {problem.problem_type.value}
- 설명: {problem.description}
- 사용자 쿼리: {problem.query or 'N/A'}
- 에이전트 응답: {response_preview}

{pattern_section}

## 요청
1. 문제의 원인을 분석하세요 (프롬프트가 왜 잘못된 결과를 내는지).
2. 프롬프트를 어떻게 수정하면 좋을지 제안하세요.
3. 수정된 프롬프트가 다른 쿼리에도 잘 작동하도록 일반화하세요.

## 응답 형식
원인 분석:
[문제 원인 - 프롬프트의 어떤 부분이 문제인지]

수정 방향:
[수정 방향 설명]

추가할 프롬프트 내용:
[추가/수정할 프롬프트 텍스트]

신뢰도: [0.0 ~ 1.0]
영향 범위: [수정이 영향을 미치는 쿼리 유형들]
"""

    def _get_new_function_prompt(
        self,
        problem: DetectedProblem,
        pattern: Optional[LearnedPattern],
        agent_source: Optional[str],
        context: Optional[Dict[str, Any]]
    ) -> str:
        """새 기능 추가 프롬프트"""
        # Build code section
        code_section = ""
        if agent_source:
            code_preview = agent_source[:1500] if len(agent_source) > 1500 else agent_source
            code_section = "## 기존 에이전트 코드 (참고용)\n```python\n" + code_preview + "\n```"

        response_preview = (problem.response or 'N/A')[:300]

        return f"""당신은 Python 에이전트 개발 전문가입니다.

## 누락된 기능
- 설명: {problem.description}
- 사용자 쿼리: {problem.query or 'N/A'}
- 현재 응답: {response_preview}

{code_section}

## 요청
1. 필요한 기능을 분석하세요.
2. 기존 에이전트 구조와 호환되는 새 함수/메서드를 설계하세요.
3. 구현 코드를 제공하세요.

## 응답 형식
기능 분석:
[필요한 기능 설명]

설계:
[함수 시그니처 및 동작 설명]

구현 코드:
[새 함수 코드]

통합 방법:
[기존 에이전트에 어떻게 통합하는지]

신뢰도: [0.0 ~ 1.0]
"""

    def _get_config_change_prompt(
        self,
        problem: DetectedProblem,
        pattern: Optional[LearnedPattern],
        agent_source: Optional[str],
        context: Optional[Dict[str, Any]]
    ) -> str:
        """설정 변경 프롬프트"""
        return f"""당신은 시스템 설정 전문가입니다.

## 문제
- 설명: {problem.description}
- 쿼리: {problem.query or 'N/A'}

## 요청
설정 변경으로 이 문제를 해결할 수 있는지 분석하고, 가능하다면 변경 사항을 제안하세요.

## 응답 형식
```
분석:
[문제와 설정 관련성]

권장 설정 변경:
[변경할 설정 항목과 값]

신뢰도: [0.0 ~ 1.0]
```
"""

    def _parse_improvement_response(
        self,
        content: str,
        problem: DetectedProblem,
        pattern: Optional[LearnedPattern],
        fix_type: str
    ) -> Optional[Improvement]:
        """LLM 응답 파싱"""
        improvement_id = str(uuid.uuid4())[:8]

        # 신뢰도 추출
        confidence = 0.7  # 기본값
        confidence_match = re.search(r"신뢰도[:\s]*([0-9.]+)", content)
        if confidence_match:
            try:
                confidence = float(confidence_match.group(1))
                confidence = min(1.0, max(0.0, confidence))
            except ValueError:
                pass

        # 코드 블록 추출
        code_blocks = re.findall(r"```python\n(.*?)```", content, re.DOTALL)
        code = code_blocks[0] if code_blocks else None

        # 원인 분석 추출
        reasoning_match = re.search(r"원인 분석[:\s]*\n?(.*?)(?:\n\n|수정|$)", content, re.DOTALL)
        reasoning = reasoning_match.group(1).strip() if reasoning_match else None

        # 수정 사항 추출
        changes = {
            "fix_type": fix_type,
            "content": content,
            "code": code,
            "summary": self._extract_summary(content)
        }

        # 롤백 계획
        rollback = None
        if "롤백" in content.lower() or "rollback" in content.lower():
            rollback = {
                "possible": "예" in content or "가능" in content,
                "instructions": "이전 버전으로 복원"
            }

        # 영향 분석
        impact = {
            "scope": "unknown",
            "affected_queries": []
        }
        impact_match = re.search(r"영향 범위[:\s]*(.+?)(?:\n|$)", content)
        if impact_match:
            impact["scope"] = impact_match.group(1).strip()

        return Improvement(
            improvement_id=improvement_id,
            pattern_id=pattern.pattern_id if pattern else None,
            problem=problem,
            improvement_type=fix_type,
            suggested_changes=changes,
            confidence=confidence,
            impact_analysis=impact,
            reasoning=reasoning,
            rollback_plan=rollback
        )

    def _extract_summary(self, content: str) -> str:
        """응답에서 요약 추출"""
        lines = content.split("\n")
        for line in lines:
            if line.strip() and not line.startswith("#") and not line.startswith("```"):
                return line.strip()[:200]
        return "개선안 생성됨"
