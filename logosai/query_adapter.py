"""
Query Adapter 모듈

에이전트 간 협업 시 쿼리를 각 에이전트의 예상 입력 형식에 맞게 변환합니다.
Tiered Approach를 사용하여 성능을 최적화합니다:
1. 패턴 매칭 (1-5ms) - 이미 올바른 형식인 경우
2. 룰 기반 변환 (5-10ms) - 간단한 변환이 필요한 경우
3. LLM 기반 변환 (200-500ms) - 복잡한 자연어 처리가 필요한 경우

사용 예시:
    adapter = QueryAdapter()

    # 스키마 정의
    schema = {
        "expression": {
            "type": "string",
            "description": "수학 표현식 (예: 1+1, 2*3)",
            "pattern": r"^[\\d\\s\\+\\-\\*\\/\\(\\)\\.]+$"
        }
    }

    # 쿼리 적응
    result = await adapter.adapt("1+1 계산해줘", schema)
    # result: {"expression": "1+1"}
"""

import re
import json
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
import hashlib

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class AdaptationMethod(Enum):
    """적응 방법"""
    PATTERN_MATCH = "pattern_match"  # 패턴 매칭 (가장 빠름)
    RULE_BASED = "rule_based"        # 룰 기반 변환
    LLM_BASED = "llm_based"          # LLM 기반 변환 (가장 정확)
    PASSTHROUGH = "passthrough"      # 변환 없이 통과


@dataclass
class AdaptationResult:
    """적응 결과"""
    success: bool
    adapted_input: Dict[str, Any]
    method: AdaptationMethod
    confidence: float = 1.0
    original_query: str = ""
    processing_time_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class InputSchema:
    """에이전트 입력 스키마"""
    fields: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    examples: List[Dict[str, Any]] = field(default_factory=list)
    patterns: Dict[str, str] = field(default_factory=dict)  # field_name -> regex pattern
    extraction_rules: Dict[str, str] = field(default_factory=dict)  # field_name -> extraction rule

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InputSchema':
        """딕셔너리에서 스키마 생성"""
        return cls(
            fields=data.get('fields', data.get('properties', {})),
            examples=data.get('examples', []),
            patterns=data.get('patterns', {}),
            extraction_rules=data.get('extraction_rules', {})
        )


class QueryAdapter:
    """
    쿼리 적응기

    에이전트의 입력 스키마에 맞게 자연어 쿼리를 구조화된 입력으로 변환합니다.
    """

    # LLM 설정
    DEFAULT_PROVIDER = "google"
    DEFAULT_MODEL = "gemini-2.0-flash-lite"  # 빠른 모델 사용

    # 공통 패턴
    COMMON_PATTERNS = {
        "math_expression": r'[\d\s\+\-\*\/\(\)\.%\^]+',
        "number": r'-?\d+(?:\.\d+)?',
        "date": r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',
        "email": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        "url": r'https?://[^\s]+',
        "currency": r'[\d,]+(?:\.\d{2})?\s*(?:원|달러|엔|유로|USD|KRW|JPY|EUR)',
    }

    # 한국어 → 영어 연산자 매핑
    OPERATOR_MAPPINGS = {
        '더하기': '+', '플러스': '+', '합': '+',
        '빼기': '-', '마이너스': '-', '차': '-',
        '곱하기': '*', '곱': '*', '배': '*',
        '나누기': '/', '나눈': '/',
        '제곱': '**', '승': '**',
    }

    def __init__(
        self,
        provider: str = None,
        model: str = None,
        temperature: float = 0.1,
        cache_enabled: bool = True,
        max_cache_size: int = 1000
    ):
        """
        QueryAdapter 초기화

        Args:
            provider: LLM 프로바이더 (기본: google)
            model: LLM 모델 (기본: gemini-2.0-flash-lite)
            temperature: LLM temperature (낮을수록 일관성 있음)
            cache_enabled: 캐시 활성화 여부
            max_cache_size: 최대 캐시 크기
        """
        self.provider = provider or self.DEFAULT_PROVIDER
        self.model = model or self.DEFAULT_MODEL
        self.temperature = temperature
        self.cache_enabled = cache_enabled
        self._cache: Dict[str, AdaptationResult] = {}
        self._max_cache_size = max_cache_size
        self._llm_client = None

        logger.info(f"QueryAdapter 초기화: provider={self.provider}, model={self.model}")

    def _get_cache_key(self, query: str, schema: InputSchema) -> str:
        """캐시 키 생성"""
        schema_str = json.dumps(schema.fields, sort_keys=True)
        combined = f"{query}::{schema_str}"
        return hashlib.md5(combined.encode()).hexdigest()

    async def _get_llm_client(self):
        """LLM 클라이언트 가져오기 (lazy loading)"""
        if self._llm_client is None:
            try:
                from .utils.llm_client import LLMClient
                self._llm_client = LLMClient(
                    provider=self.provider,
                    model=self.model,
                    temperature=self.temperature
                )
                logger.debug(f"LLM 클라이언트 초기화 완료: {self.provider}/{self.model}")
            except Exception as e:
                logger.error(f"LLM 클라이언트 초기화 실패: {e}")
                raise
        return self._llm_client

    async def adapt(
        self,
        query: str,
        schema: Optional[InputSchema] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> AdaptationResult:
        """
        쿼리를 에이전트 입력 스키마에 맞게 변환

        Args:
            query: 원본 쿼리
            schema: 에이전트 입력 스키마
            context: 추가 컨텍스트 정보

        Returns:
            AdaptationResult: 적응 결과
        """
        import time
        start_time = time.time()

        # 스키마가 없으면 passthrough
        if schema is None or not schema.fields:
            return AdaptationResult(
                success=True,
                adapted_input={"query": query},
                method=AdaptationMethod.PASSTHROUGH,
                original_query=query,
                processing_time_ms=(time.time() - start_time) * 1000
            )

        # 캐시 확인
        if self.cache_enabled:
            cache_key = self._get_cache_key(query, schema)
            if cache_key in self._cache:
                cached = self._cache[cache_key]
                logger.debug(f"캐시 히트: {query[:30]}...")
                return AdaptationResult(
                    success=cached.success,
                    adapted_input=cached.adapted_input,
                    method=cached.method,
                    confidence=cached.confidence,
                    original_query=query,
                    processing_time_ms=(time.time() - start_time) * 1000
                )

        try:
            # 1단계: 패턴 매칭 시도
            pattern_result = self._try_pattern_match(query, schema)
            if pattern_result.success:
                self._update_cache(cache_key, pattern_result) if self.cache_enabled else None
                pattern_result.processing_time_ms = (time.time() - start_time) * 1000
                return pattern_result

            # 2단계: 룰 기반 변환 시도
            rule_result = self._try_rule_based(query, schema)
            if rule_result.success:
                self._update_cache(cache_key, rule_result) if self.cache_enabled else None
                rule_result.processing_time_ms = (time.time() - start_time) * 1000
                return rule_result

            # 3단계: LLM 기반 변환
            llm_result = await self._try_llm_based(query, schema, context)
            if self.cache_enabled:
                self._update_cache(cache_key, llm_result)
            llm_result.processing_time_ms = (time.time() - start_time) * 1000
            return llm_result

        except Exception as e:
            logger.error(f"쿼리 적응 중 오류: {e}")
            return AdaptationResult(
                success=False,
                adapted_input={"query": query},
                method=AdaptationMethod.PASSTHROUGH,
                original_query=query,
                processing_time_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )

    def _try_pattern_match(self, query: str, schema: InputSchema) -> AdaptationResult:
        """
        1단계: 패턴 매칭 시도 (가장 빠름, 1-5ms)
        """
        result = {}
        all_matched = True

        for field_name, field_info in schema.fields.items():
            # 스키마에 정의된 패턴 확인
            pattern = schema.patterns.get(field_name) or field_info.get('pattern')

            if pattern:
                # 쿼리 전체가 패턴과 일치하는지 확인
                if re.fullmatch(pattern, query.strip()):
                    result[field_name] = query.strip()
                    logger.debug(f"패턴 매칭 성공 (fullmatch): field={field_name}, value={query.strip()}")
                    continue

                # 패턴에 해당하는 부분 추출
                match = re.search(pattern, query)
                if match:
                    result[field_name] = match.group().strip()
                    logger.debug(f"패턴 매칭 성공 (search): field={field_name}, value={match.group().strip()}")
                    continue

            # 공통 패턴 확인
            field_type = field_info.get('type', 'string')
            common_pattern = self._get_common_pattern(field_type, field_info)
            logger.debug(f"공통 패턴 조회: field={field_name}, type={field_type}, pattern={common_pattern}")

            if common_pattern:
                match = re.search(common_pattern, query)
                if match:
                    matched_value = match.group().strip()
                    # 의미 있는 매칭인지 확인 (최소 연산자 포함 또는 충분한 길이)
                    if matched_value and len(matched_value) >= 2 and any(op in matched_value for op in ['+', '-', '*', '/', '%', '^']):
                        result[field_name] = matched_value
                        logger.debug(f"공통 패턴 매칭 성공: field={field_name}, value={matched_value}")
                        continue
                    # 쿼리 전체가 수식인 경우도 허용
                    elif matched_value == query.strip():
                        result[field_name] = matched_value
                        logger.debug(f"공통 패턴 매칭 성공 (전체 일치): field={field_name}, value={matched_value}")
                        continue

            logger.debug(f"패턴 매칭 실패: field={field_name}")
            all_matched = False

        if result and all_matched:
            return AdaptationResult(
                success=True,
                adapted_input=result,
                method=AdaptationMethod.PATTERN_MATCH,
                confidence=0.95,
                original_query=query
            )

        return AdaptationResult(
            success=False,
            adapted_input={},
            method=AdaptationMethod.PATTERN_MATCH,
            original_query=query
        )

    def _get_common_pattern(self, field_type: str, field_info: Dict) -> Optional[str]:
        """필드 타입에 맞는 공통 패턴 반환"""
        # 필드 설명에서 힌트 찾기
        description = field_info.get('description', '').lower()
        field_name_lower = field_info.get('name', '').lower() if 'name' in field_info else ''

        # 수학 표현식 관련 키워드
        math_keywords = ['math', 'expression', '수식', '계산', '표현식', '연산', 'calculate', 'formula']
        if any(kw in description or kw in field_name_lower for kw in math_keywords):
            return self.COMMON_PATTERNS['math_expression']

        if 'number' in field_type or '숫자' in description:
            return self.COMMON_PATTERNS['number']
        if 'date' in description or '날짜' in description:
            return self.COMMON_PATTERNS['date']
        if 'email' in description or '이메일' in description:
            return self.COMMON_PATTERNS['email']
        if 'url' in description or 'link' in description:
            return self.COMMON_PATTERNS['url']
        if 'currency' in description or '금액' in description or '원' in description:
            return self.COMMON_PATTERNS['currency']

        return None

    def _try_rule_based(self, query: str, schema: InputSchema) -> AdaptationResult:
        """
        2단계: 룰 기반 변환 (5-10ms)
        """
        result = {}

        for field_name, field_info in schema.fields.items():
            description = field_info.get('description', '').lower()

            # 수학 표현식 추출 규칙
            math_keywords = ['math', 'expression', '수식', '계산', '표현식', '연산']
            if any(kw in description for kw in math_keywords):
                extracted = self._extract_math_expression(query)
                if extracted:
                    result[field_name] = extracted
                    logger.debug(f"룰 기반 추출 성공: field={field_name}, value={extracted}")
                    continue

            # 숫자 목록 추출 규칙
            if 'numbers' in description or 'list' in description or '숫자' in description:
                numbers = re.findall(r'-?\d+(?:\.\d+)?', query)
                if numbers:
                    result[field_name] = numbers
                    continue

            # 날짜 추출 규칙
            if 'date' in description or '날짜' in description:
                extracted = self._extract_date(query)
                if extracted:
                    result[field_name] = extracted
                    continue

        if result:
            return AdaptationResult(
                success=True,
                adapted_input=result,
                method=AdaptationMethod.RULE_BASED,
                confidence=0.85,
                original_query=query
            )

        return AdaptationResult(
            success=False,
            adapted_input={},
            method=AdaptationMethod.RULE_BASED,
            original_query=query
        )

    def _extract_math_expression(self, query: str) -> Optional[str]:
        """쿼리에서 수학 표현식 추출"""
        # 먼저 쿼리에서 모든 숫자 추출
        numbers = re.findall(r'-?\d+(?:\.\d+)?', query)

        if not numbers:
            return None

        # 한국어 연산자 확인 및 변환
        processed = query
        operator_found = None

        for korean, symbol in self.OPERATOR_MAPPINGS.items():
            if korean in processed:
                operator_found = symbol
                processed = processed.replace(korean, f' {symbol} ')

        # "X과 Y", "X와 Y" 패턴 처리 (예: "10과 20의 합")
        if len(numbers) >= 2 and ('과' in query or '와' in query):
            # "합" 키워드가 있으면 더하기
            if '합' in query:
                return '+'.join(numbers)
            # "차" 키워드가 있으면 빼기
            elif '차' in query:
                return '-'.join(numbers)
            # "곱" 키워드가 있으면 곱하기
            elif '곱' in query:
                return '*'.join(numbers)

        # 숫자와 연산자만 추출
        parts = []
        tokens = processed.split()

        for token in tokens:
            # 숫자인 경우
            if re.match(r'^-?\d+(?:\.\d+)?$', token):
                parts.append(token)
            # 연산자인 경우
            elif token in ['+', '-', '*', '/', '**', '%', '(', ')']:
                parts.append(token)
            # 숫자+연산자 혼합 (예: "10+20")
            elif re.match(r'^[\d\s\+\-\*\/\(\)\.%\^]+$', token):
                parts.append(token)

        if parts:
            expression = ' '.join(parts)
            # 연속된 공백 제거 및 정리
            expression = re.sub(r'\s+', '', expression)
            # 유효한 수학 표현식인지 확인 (최소한 숫자+연산자+숫자)
            if re.match(r'^[\d\+\-\*\/\(\)\.%\^]+$', expression) and len(expression) >= 3:
                return expression

        # 쿼리에서 직접 수식 부분 찾기
        match = re.search(r'[\d\s\+\-\*\/\(\)\.]+[\d\)]', query)
        if match:
            expression = re.sub(r'\s+', '', match.group())
            if re.match(r'^[\d\+\-\*\/\(\)\.]+$', expression) and len(expression) >= 3:
                return expression

        return None

    def _extract_date(self, query: str) -> Optional[str]:
        """쿼리에서 날짜 추출"""
        # YYYY-MM-DD 또는 YYYY/MM/DD 형식
        match = re.search(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', query)
        if match:
            return match.group()

        # 한국어 날짜 형식 (예: 2024년 1월 15일)
        match = re.search(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일', query)
        if match:
            return f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"

        return None

    async def _try_llm_based(
        self,
        query: str,
        schema: InputSchema,
        context: Optional[Dict[str, Any]] = None
    ) -> AdaptationResult:
        """
        3단계: LLM 기반 변환 (가장 정확, 200-500ms)
        """
        try:
            llm_client = await self._get_llm_client()

            # 스키마를 프롬프트용 문자열로 변환
            schema_description = self._schema_to_prompt(schema)

            # 예시가 있으면 추가
            examples_str = ""
            if schema.examples:
                examples_str = "\n\n예시:\n"
                for ex in schema.examples[:3]:  # 최대 3개 예시
                    examples_str += f"- 입력: \"{ex.get('raw', '')}\"\n  출력: {json.dumps(ex.get('adapted', {}), ensure_ascii=False)}\n"

            prompt = f"""다음 쿼리에서 필요한 정보를 추출하여 JSON 형식으로 반환하세요.

쿼리: "{query}"

추출해야 할 필드:
{schema_description}
{examples_str}

규칙:
1. 반드시 유효한 JSON만 반환하세요
2. 추출할 수 없는 필드는 null로 설정하세요
3. 코드 블록 없이 순수 JSON만 반환하세요

JSON 응답:"""

            response = await llm_client.invoke(prompt)

            # 응답 파싱
            response_text = response.content if hasattr(response, 'content') else str(response)

            # JSON 추출
            adapted = self._parse_json_response(response_text)

            if adapted:
                return AdaptationResult(
                    success=True,
                    adapted_input=adapted,
                    method=AdaptationMethod.LLM_BASED,
                    confidence=0.9,
                    original_query=query
                )
            else:
                return AdaptationResult(
                    success=False,
                    adapted_input={"query": query},
                    method=AdaptationMethod.LLM_BASED,
                    confidence=0.5,
                    original_query=query,
                    error="LLM 응답 파싱 실패"
                )

        except Exception as e:
            logger.error(f"LLM 기반 변환 실패: {e}")
            return AdaptationResult(
                success=False,
                adapted_input={"query": query},
                method=AdaptationMethod.LLM_BASED,
                original_query=query,
                error=str(e)
            )

    def _schema_to_prompt(self, schema: InputSchema) -> str:
        """스키마를 프롬프트용 문자열로 변환"""
        lines = []
        for field_name, field_info in schema.fields.items():
            field_type = field_info.get('type', 'string')
            description = field_info.get('description', '설명 없음')
            extraction_hint = schema.extraction_rules.get(field_name, '')

            line = f"- {field_name} ({field_type}): {description}"
            if extraction_hint:
                line += f" [추출 힌트: {extraction_hint}]"
            lines.append(line)

        return '\n'.join(lines)

    def _parse_json_response(self, response: str) -> Optional[Dict[str, Any]]:
        """LLM 응답에서 JSON 파싱"""
        # 코드 블록 제거
        response = re.sub(r'```json\s*', '', response)
        response = re.sub(r'```\s*', '', response)
        response = response.strip()

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # JSON 부분만 추출 시도
            match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        return None

    def _update_cache(self, key: str, result: AdaptationResult):
        """캐시 업데이트"""
        if len(self._cache) >= self._max_cache_size:
            # 오래된 항목 삭제 (FIFO)
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[key] = result

    def clear_cache(self):
        """캐시 초기화"""
        self._cache.clear()
        logger.info("QueryAdapter 캐시 초기화됨")


# 전역 인스턴스 (싱글톤 패턴)
_default_adapter: Optional[QueryAdapter] = None


def get_query_adapter() -> QueryAdapter:
    """기본 QueryAdapter 인스턴스 반환"""
    global _default_adapter
    if _default_adapter is None:
        _default_adapter = QueryAdapter()
    return _default_adapter


async def adapt_query(
    query: str,
    schema: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None
) -> AdaptationResult:
    """
    편의 함수: 쿼리 적응

    Args:
        query: 원본 쿼리
        schema: 에이전트 입력 스키마 (dict)
        context: 추가 컨텍스트

    Returns:
        AdaptationResult
    """
    adapter = get_query_adapter()
    input_schema = InputSchema.from_dict(schema) if schema else None
    return await adapter.adapt(query, input_schema, context)
