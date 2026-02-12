"""
Problem Detector (문제 감지기)

에이전트 실행 결과에서 문제를 감지합니다.
- Self-Healing: 에러, 예외, 구문 오류
- Self-Growing: 기능 부재, 의도 불일치, 불완전 응답
"""

import re
import traceback
from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from .types import (
    ProblemType,
    Severity,
    DetectedProblem,
    EvolutionMode
)
from .config import EvolutionConfig, DetectionConfig


@dataclass
class IntentAnalysis:
    """의도 분석 결과"""
    score: float  # 0.0 ~ 1.0
    matched: bool
    query_intent: str
    response_intent: str
    mismatch_details: Optional[str] = None


class ProblemDetector:
    """문제 감지기"""

    def __init__(
        self,
        config: Optional[DetectionConfig] = None,
        llm_client=None
    ):
        """
        문제 감지기 초기화

        Args:
            config: 감지 설정
            llm_client: LLM 클라이언트 (의도 분석용)
        """
        self.config = config or DetectionConfig()
        self.llm_client = llm_client

        # 에러 패턴 정의
        self._error_patterns = {
            ProblemType.SYNTAX_ERROR: [
                r"SyntaxError:",
                r"IndentationError:",
                r"TabError:",
            ],
            ProblemType.IMPORT_ERROR: [
                r"ImportError:",
                r"ModuleNotFoundError:",
                r"cannot import name",
            ],
            ProblemType.TYPE_ERROR: [
                r"TypeError:",
                r"AttributeError:",
            ],
            ProblemType.RUNTIME_ERROR: [
                r"RuntimeError:",
                r"ValueError:",
                r"KeyError:",
                r"IndexError:",
                r"ZeroDivisionError:",
            ]
        }

        # 기능 부재 키워드
        self._missing_function_patterns = [
            r"기능이 없습니다",
            r"지원하지 않습니다",
            r"처리할 수 없습니다",
            r"not supported",
            r"not implemented",
            r"cannot handle",
            r"unknown command",
        ]

    async def detect(
        self,
        query: str,
        response: Any,
        error: Optional[Exception] = None,
        user_feedback: Optional[str] = None,
        mode: EvolutionMode = EvolutionMode.BOTH
    ) -> List[DetectedProblem]:
        """
        문제 감지 수행

        Args:
            query: 사용자 쿼리
            response: 에이전트 응답
            error: 발생한 예외 (선택)
            user_feedback: 사용자 피드백 (선택)
            mode: 감지 모드

        Returns:
            감지된 문제 목록
        """
        problems = []

        # 응답을 문자열로 변환
        response_str = self._extract_response_text(response)

        # 1. 명시적 에러 감지 (Self-Healing)
        if mode in [EvolutionMode.HEALING, EvolutionMode.BOTH]:
            if error:
                error_problems = self._detect_from_exception(error, query)
                problems.extend(error_problems)

            # 응답에서 에러 패턴 검색
            response_error_problems = self._detect_from_response_errors(response_str, query)
            problems.extend(response_error_problems)

        # 2. 기능 부재 및 의도 불일치 감지 (Self-Growing)
        if mode in [EvolutionMode.GROWING, EvolutionMode.BOTH]:
            if self.config.detect_missing_functions:
                missing_problems = self._detect_missing_functions(response_str, query)
                problems.extend(missing_problems)

            if self.config.detect_intent_mismatch and self.llm_client:
                intent_problems = await self._detect_intent_mismatch(query, response_str)
                problems.extend(intent_problems)

        # 3. 사용자 피드백 분석
        if user_feedback:
            feedback_problems = await self._analyze_user_feedback(
                user_feedback, query, response_str
            )
            problems.extend(feedback_problems)

        # 중복 제거
        problems = self._deduplicate_problems(problems)

        if problems:
            logger.info(f"감지된 문제: {len(problems)}개")
            for p in problems:
                logger.debug(f"  - {p.problem_type.value}: {p.description[:50]}...")

        return problems

    def detect_from_error(
        self,
        error: Exception,
        query: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> List[DetectedProblem]:
        """
        예외에서 문제 감지 (동기 버전)

        Args:
            error: 발생한 예외
            query: 관련 쿼리
            context: 추가 컨텍스트

        Returns:
            감지된 문제 목록
        """
        return self._detect_from_exception(error, query, context)

    def detect_from_response(
        self,
        query: str,
        response: str,
        user_feedback: Optional[str] = None
    ) -> List[DetectedProblem]:
        """
        응답 텍스트에서 문제 감지 (동기 버전)

        Args:
            query: 사용자 쿼리
            response: 에이전트 응답 텍스트
            user_feedback: 사용자 피드백 (선택)

        Returns:
            감지된 문제 목록
        """
        problems = []

        # 응답에서 에러 패턴 검색
        response_error_problems = self._detect_from_response_errors(response, query)
        problems.extend(response_error_problems)

        # 기능 부재 감지
        if self.config.detect_missing_functions:
            missing_problems = self._detect_missing_functions(response, query)
            problems.extend(missing_problems)

        # 사용자 피드백이 있으면 불만족 감지
        if user_feedback:
            negative_patterns = [
                r"틀[렸린]", r"잘못", r"아니[야요]", r"다시",
                r"wrong", r"incorrect", r"not what I"
            ]
            is_negative = any(
                re.search(p, user_feedback, re.IGNORECASE)
                for p in negative_patterns
            )

            if is_negative:
                problems.append(DetectedProblem(
                    problem_type=ProblemType.INTENT_MISMATCH,
                    severity=Severity.MEDIUM,
                    description=f"의도 불일치 (사용자 피드백): {user_feedback[:100]}",
                    details={
                        "feedback": user_feedback,
                        "original_query": query
                    },
                    query=query,
                    response=response[:500]
                ))

        return self._deduplicate_problems(problems)

    def _detect_from_exception(
        self,
        error: Exception,
        query: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> List[DetectedProblem]:
        """예외에서 문제 감지"""
        problems = []
        error_str = str(error)
        error_type = type(error).__name__
        stack = traceback.format_exception(type(error), error, error.__traceback__)
        stack_trace = "".join(stack)

        # 에러 유형 분류
        problem_type = self._classify_error_type(error_type, error_str)
        severity = self._determine_severity(problem_type, error_str)

        problems.append(DetectedProblem(
            problem_type=problem_type,
            severity=severity,
            description=f"{error_type}: {error_str[:200]}",
            details={
                "error_type": error_type,
                "error_message": error_str,
                "context": context
            },
            query=query,
            error_message=error_str,
            stack_trace=stack_trace
        ))

        return problems

    def _detect_from_response_errors(
        self,
        response: str,
        query: str
    ) -> List[DetectedProblem]:
        """응답 텍스트에서 에러 패턴 감지"""
        problems = []

        for problem_type, patterns in self._error_patterns.items():
            for pattern in patterns:
                if re.search(pattern, response, re.IGNORECASE):
                    # 에러 메시지 추출
                    match = re.search(f"{pattern}.*", response)
                    error_msg = match.group() if match else pattern

                    problems.append(DetectedProblem(
                        problem_type=problem_type,
                        severity=Severity.HIGH,
                        description=f"응답에서 에러 패턴 감지: {error_msg[:100]}",
                        details={"pattern": pattern, "matched_text": error_msg},
                        query=query,
                        response=response[:500],
                        error_message=error_msg
                    ))
                    break  # 한 유형당 하나만

        return problems

    def _detect_missing_functions(
        self,
        response: str,
        query: str
    ) -> List[DetectedProblem]:
        """기능 부재 감지"""
        problems = []

        for pattern in self._missing_function_patterns:
            if re.search(pattern, response, re.IGNORECASE):
                problems.append(DetectedProblem(
                    problem_type=ProblemType.MISSING_FUNCTION,
                    severity=Severity.MEDIUM,
                    description=f"기능 부재 감지: {pattern}",
                    details={
                        "pattern": pattern,
                        "response_snippet": response[:300]
                    },
                    query=query,
                    response=response[:500]
                ))
                break

        return problems

    async def _detect_intent_mismatch(
        self,
        query: str,
        response: str
    ) -> List[DetectedProblem]:
        """의도 불일치 감지 (LLM 기반)"""
        problems = []

        if not self.llm_client:
            return problems

        try:
            analysis = await self._analyze_intent(query, response)

            if not analysis.matched and analysis.score < self.config.intent_match_threshold:
                problems.append(DetectedProblem(
                    problem_type=ProblemType.INTENT_MISMATCH,
                    severity=Severity.MEDIUM,
                    description=f"의도 불일치 (일치율: {analysis.score:.2f})",
                    details={
                        "score": analysis.score,
                        "query_intent": analysis.query_intent,
                        "response_intent": analysis.response_intent,
                        "mismatch_details": analysis.mismatch_details
                    },
                    query=query,
                    response=response[:500]
                ))

        except Exception as e:
            logger.warning(f"의도 분석 실패: {e}")

        return problems

    async def _analyze_intent(self, query: str, response: str) -> IntentAnalysis:
        """LLM을 사용하여 의도 분석"""
        prompt = f"""다음 사용자 쿼리와 에이전트 응답을 분석하여 의도 일치 여부를 판단하세요.

사용자 쿼리: {query}

에이전트 응답: {response[:1000]}

다음 형식으로 응답하세요:
- 쿼리 의도: [사용자가 원하는 것]
- 응답 의도: [응답이 제공하는 것]
- 일치율: [0.0 ~ 1.0 사이 숫자]
- 불일치 사유: [있다면 설명]

예시:
- 쿼리 의도: 2026년 1월 전체 일정 조회
- 응답 의도: 2026년 1월 1일 일정 조회
- 일치율: 0.3
- 불일치 사유: 월 전체가 아닌 특정 날짜만 조회함
"""

        try:
            await self.llm_client.initialize()
            result = await self.llm_client.invoke(prompt)
            content = str(result.content) if hasattr(result, 'content') else str(result)

            # 응답 파싱
            score = self._extract_score(content)
            query_intent = self._extract_field(content, "쿼리 의도")
            response_intent = self._extract_field(content, "응답 의도")
            mismatch = self._extract_field(content, "불일치 사유")

            return IntentAnalysis(
                score=score,
                matched=score >= self.config.intent_match_threshold,
                query_intent=query_intent,
                response_intent=response_intent,
                mismatch_details=mismatch if mismatch else None
            )

        except Exception as e:
            logger.error(f"의도 분석 LLM 호출 실패: {e}")
            return IntentAnalysis(
                score=1.0,
                matched=True,
                query_intent="분석 실패",
                response_intent="분석 실패"
            )

    async def _analyze_user_feedback(
        self,
        feedback: str,
        query: str,
        response: str
    ) -> List[DetectedProblem]:
        """사용자 피드백 분석"""
        problems = []

        # 부정적 키워드 감지
        negative_patterns = [
            r"틀[렸린]",
            r"잘못",
            r"아니[야요]",
            r"다시",
            r"wrong",
            r"incorrect",
            r"not what I",
        ]

        is_negative = any(
            re.search(p, feedback, re.IGNORECASE)
            for p in negative_patterns
        )

        if is_negative:
            problems.append(DetectedProblem(
                problem_type=ProblemType.USER_DISSATISFACTION,
                severity=Severity.MEDIUM,
                description=f"사용자 불만족: {feedback[:100]}",
                details={
                    "feedback": feedback,
                    "original_query": query
                },
                query=query,
                response=response[:500]
            ))

        return problems

    def _classify_error_type(self, error_type: str, error_str: str) -> ProblemType:
        """에러 유형 분류"""
        error_lower = error_type.lower()

        if "syntax" in error_lower or "indent" in error_lower:
            return ProblemType.SYNTAX_ERROR
        elif "import" in error_lower or "module" in error_lower:
            return ProblemType.IMPORT_ERROR
        elif "type" in error_lower or "attribute" in error_lower:
            return ProblemType.TYPE_ERROR
        else:
            return ProblemType.RUNTIME_ERROR

    def _determine_severity(self, problem_type: ProblemType, error_str: str) -> Severity:
        """심각도 결정"""
        critical_keywords = ["critical", "fatal", "corruption", "data loss"]

        if any(k in error_str.lower() for k in critical_keywords):
            return Severity.CRITICAL

        severity_map = {
            ProblemType.SYNTAX_ERROR: Severity.HIGH,
            ProblemType.IMPORT_ERROR: Severity.HIGH,
            ProblemType.TYPE_ERROR: Severity.MEDIUM,
            ProblemType.RUNTIME_ERROR: Severity.MEDIUM,
            ProblemType.MISSING_FUNCTION: Severity.MEDIUM,
            ProblemType.INTENT_MISMATCH: Severity.MEDIUM,
            ProblemType.USER_DISSATISFACTION: Severity.LOW,
        }

        return severity_map.get(problem_type, Severity.MEDIUM)

    def _extract_response_text(self, response: Any) -> str:
        """응답에서 텍스트 추출"""
        if isinstance(response, str):
            return response
        elif hasattr(response, "content"):
            return str(response.content)
        elif hasattr(response, "message"):
            return str(response.message)
        elif isinstance(response, dict):
            return str(response.get("content", response.get("message", str(response))))
        else:
            return str(response)

    def _extract_score(self, content: str) -> float:
        """LLM 응답에서 점수 추출"""
        match = re.search(r"일치율[:\s]*([0-9.]+)", content)
        if match:
            try:
                score = float(match.group(1))
                return min(1.0, max(0.0, score))
            except ValueError:
                pass
        return 1.0  # 기본값

    def _extract_field(self, content: str, field_name: str) -> str:
        """LLM 응답에서 필드 추출"""
        pattern = rf"{field_name}[:\s]*(.+?)(?:\n|$)"
        match = re.search(pattern, content)
        return match.group(1).strip() if match else ""

    def _deduplicate_problems(
        self,
        problems: List[DetectedProblem]
    ) -> List[DetectedProblem]:
        """중복 문제 제거"""
        seen = set()
        unique = []

        for p in problems:
            key = (p.problem_type, p.description[:50])
            if key not in seen:
                seen.add(key)
                unique.append(p)

        return unique
