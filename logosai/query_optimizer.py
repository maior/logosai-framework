"""
LogosAI 쿼리 최적화 시스템

에이전트별로 쿼리를 최적화하고 적합성을 판단하는 시스템
"""

import asyncio
import re
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum
from loguru import logger

# LLMClient import
try:
    from logosai.utils.llm_client import LLMClient, LLMMessage
except ImportError as e:
    logger.warning(f"LLMClient import failed: {str(e)}, using fallback")
    LLMClient = None
    LLMMessage = None


class AgentType(Enum):
    """에이전트 타입 정의"""
    RAG = "rag"
    SEARCH = "search"
    ANALYSIS = "analysis"
    CODING = "coding"
    MATH = "math"
    GENERAL = "general"
    DOCUMENT = "document"
    WEATHER = "weather"
    CALCULATOR = "calculator"
    INTERNET = "internet"


@dataclass
class QueryOptimizationResult:
    """쿼리 최적화 결과"""
    original_query: str
    optimized_query: str
    optimized_query_en: Optional[str] = None
    suitability_score: float = 0.0
    is_suitable: bool = False
    optimization_reason: str = ""
    agent_type: Optional[AgentType] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class QueryOptimizer:
    """에이전트별 쿼리 최적화 및 적합성 판단 시스템"""
    
    def __init__(self):
        self.llm_client = None
        self._initialize_llm()
        
        # 에이전트별 최적화 전략
        self.optimization_strategies = {
            AgentType.RAG: self._optimize_for_rag,
            AgentType.SEARCH: self._optimize_for_search,
            AgentType.ANALYSIS: self._optimize_for_analysis,
            AgentType.CODING: self._optimize_for_coding,
            AgentType.MATH: self._optimize_for_math,
            AgentType.DOCUMENT: self._optimize_for_document,
            AgentType.WEATHER: self._optimize_for_weather,
            AgentType.CALCULATOR: self._optimize_for_calculator,
            AgentType.INTERNET: self._optimize_for_internet,
            AgentType.GENERAL: self._optimize_for_general,
        }
        
        # 에이전트별 적합성 패턴
        self.suitability_patterns = {
            AgentType.RAG: [
                r"(문서|자료|파일|pdf|doc|검색|찾아|조회)",
                r"(데이터베이스|db|정보|지식|학습)",
                r"(질문|답변|qa|qna)"
            ],
            AgentType.SEARCH: [
                r"(검색|찾아|search|find)",
                r"(구글|google|웹|web|인터넷)",
                r"(최신|뉴스|정보)"
            ],
            AgentType.ANALYSIS: [
                r"(분석|해석|평가|검토)",
                r"(데이터|통계|차트|그래프)",
                r"(트렌드|패턴|경향)"
            ],
            AgentType.CODING: [
                r"(코드|프로그래밍|개발|함수)",
                r"(python|javascript|java|c\+\+)",
                r"(버그|오류|디버그)"
            ],
            AgentType.MATH: [
                r"(수학|계산|공식|방정식)",
                r"(적분|미분|행렬|벡터)",
                r"(\d+.*[\+\-\*/].*\d+)"
            ],
            AgentType.DOCUMENT: [
                r"(문서|파일|pdf|doc|docx|ppt)",
                r"(다운로드|업로드|변환)",
                r"(텍스트|추출|요약)"
            ],
            AgentType.WEATHER: [
                r"(날씨|기온|온도|비|눈|바람)",
                r"(오늘|내일|이번주|다음주)",
                r"(서울|부산|대구|광주|인천)"
            ],
            AgentType.CALCULATOR: [
                r"(\d+.*[\+\-\*/].*\d+)",
                r"(계산|더하기|빼기|곱하기|나누기)",
                r"(퍼센트|percent|%)"
            ],
            AgentType.INTERNET: [
                r"(인터넷|웹|url|http|https)",
                r"(웹사이트|사이트|페이지)",
                r"(크롤링|스크래핑)"
            ]
        }

    def _initialize_llm(self):
        """LLM 클라이언트 초기화"""
        try:
            if LLMClient:
                self.llm_client = LLMClient(
                    provider="google",
                    model="gemini-2.5-flash-lite",
                    temperature=0.3
                )
                logger.info("LLM 클라이언트 초기화 성공 (Google Gemini)")
        except Exception as e:
            logger.warning(f"LLM 클라이언트 초기화 실패: {e}")
            self.llm_client = None

    async def optimize_query_for_agent(
        self, 
        query: str, 
        agent_type: AgentType,
        agent_id: str = None,
        context: Dict[str, Any] = None
    ) -> QueryOptimizationResult:
        """
        에이전트별로 쿼리를 최적화하고 적합성을 판단
        
        Args:
            query: 원본 쿼리
            agent_type: 에이전트 타입
            agent_id: 에이전트 ID (선택사항)
            context: 추가 컨텍스트 (선택사항)
            
        Returns:
            QueryOptimizationResult: 최적화 결과
        """
        try:
            # 1. 적합성 점수 계산
            suitability_score = self._calculate_suitability_score(query, agent_type)
            is_suitable = suitability_score >= 0.3  # 30% 이상이면 적합
            
            # 2. 에이전트별 쿼리 최적화
            if agent_type in self.optimization_strategies:
                optimization_func = self.optimization_strategies[agent_type]
                optimized_query, optimized_query_en, reason = await optimization_func(
                    query, context or {}
                )
            else:
                optimized_query, optimized_query_en, reason = await self._optimize_for_general(
                    query, context or {}
                )
            
            # 3. 결과 생성
            result = QueryOptimizationResult(
                original_query=query,
                optimized_query=optimized_query,
                optimized_query_en=optimized_query_en,
                suitability_score=suitability_score,
                is_suitable=is_suitable,
                optimization_reason=reason,
                agent_type=agent_type,
                metadata={
                    "agent_id": agent_id,
                    "context": context,
                    "optimization_timestamp": asyncio.get_event_loop().time()
                }
            )
            
            logger.info(f"쿼리 최적화 완료 - 에이전트: {agent_type.value}, 적합성: {suitability_score:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"쿼리 최적화 실패: {e}")
            return QueryOptimizationResult(
                original_query=query,
                optimized_query=query,
                suitability_score=0.0,
                is_suitable=False,
                optimization_reason=f"최적화 실패: {str(e)}",
                agent_type=agent_type
            )

    def _calculate_suitability_score(self, query: str, agent_type: AgentType) -> float:
        """에이전트 타입에 대한 쿼리 적합성 점수 계산"""
        if agent_type not in self.suitability_patterns:
            return 0.5  # 기본 점수
        
        patterns = self.suitability_patterns[agent_type]
        total_score = 0.0
        
        for pattern in patterns:
            if re.search(pattern, query, re.IGNORECASE):
                total_score += 1.0
        
        # 정규화 (0.0 ~ 1.0)
        normalized_score = min(total_score / len(patterns), 1.0)
        
        # 추가 보정: 키워드 밀도 고려
        query_words = len(query.split())
        if query_words > 0:
            keyword_density = sum(
                len(re.findall(pattern, query, re.IGNORECASE)) 
                for pattern in patterns
            ) / query_words
            normalized_score = min(normalized_score + keyword_density * 0.2, 1.0)
        
        return normalized_score

    async def _optimize_for_rag(self, query: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """RAG 에이전트용 쿼리 최적화"""
        # RAG는 구체적이고 상세한 쿼리가 좋음
        optimized_query = query
        reason = "RAG 검색 최적화"
        
        if self.llm_client and LLMMessage:
            try:
                messages = [
                    LLMMessage(role="system", content="""
당신은 RAG 시스템용 쿼리 최적화 전문가입니다.
사용자 쿼리를 RAG 검색에 최적화된 형태로 변환해주세요.

최적화 원칙:
1. 구체적이고 상세한 키워드 추가
2. 동의어와 관련 용어 포함
3. 검색 효율성을 높이는 구조화
4. 한국어와 영어 버전 모두 제공

출력 형식:
한국어: [최적화된 한국어 쿼리]
영어: [최적화된 영어 쿼리]
"""),
                    LLMMessage(role="user", content=f"원본 쿼리: {query}")
                ]
                
                response = await self.llm_client.invoke_messages(messages)
                result = response.content.strip()
                
                # 응답 파싱
                korean_match = re.search(r'한국어:\s*(.+?)(?=영어:|$)', result, re.DOTALL)
                english_match = re.search(r'영어:\s*(.+?)$', result, re.DOTALL)
                
                if korean_match:
                    optimized_query = korean_match.group(1).strip()
                
                optimized_query_en = None
                if english_match:
                    optimized_query_en = english_match.group(1).strip()
                
                reason = "LLM 기반 RAG 최적화"
                
            except Exception as e:
                logger.warning(f"LLM 기반 RAG 최적화 실패: {e}")
                # 폴백: 규칙 기반 최적화
                optimized_query = f"{query} 관련 문서 자료 정보 데이터"
                optimized_query_en = f"{query} related documents materials information data"
                reason = "규칙 기반 RAG 최적화 (LLM 실패)"
        else:
            # LLM 없이 규칙 기반 최적화
            optimized_query = f"{query} 관련 문서 자료 정보"
            optimized_query_en = f"{query} related documents information"
            reason = "규칙 기반 RAG 최적화"
        
        return optimized_query, optimized_query_en, reason

    async def _optimize_for_search(self, query: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """검색 에이전트용 쿼리 최적화"""
        # 검색어 키워드 최적화
        optimized_query = query.strip()
        
        # 불용어 제거 및 핵심 키워드 추출
        stopwords = ['은', '는', '이', '가', '을', '를', '에', '서', '로', '와', '과', '한', '하는']
        words = optimized_query.split()
        filtered_words = [word for word in words if word not in stopwords]
        
        if filtered_words:
            optimized_query = ' '.join(filtered_words)
        
        optimized_query_en = None
        if self.llm_client:
            try:
                messages = [
                    LLMMessage(role="system", content="한국어 검색어를 영어로 번역해주세요. 검색에 적합한 키워드 형태로 변환하세요."),
                    LLMMessage(role="user", content=optimized_query)
                ]
                response = await self.llm_client.invoke_messages(messages)
                optimized_query_en = response.content.strip()
            except Exception as e:
                logger.warning(f"검색어 영어 번역 실패: {e}")
        
        return optimized_query, optimized_query_en, "검색 키워드 최적화"

    async def _optimize_for_analysis(self, query: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """분석 에이전트용 쿼리 최적화"""
        # 분석 목적과 방법을 명확히 함
        optimized_query = query
        
        if "분석" not in query:
            optimized_query = f"{query}에 대한 상세 분석"
        
        optimized_query_en = f"Detailed analysis of {query}"
        
        return optimized_query, optimized_query_en, "분석 목적 명확화"

    async def _optimize_for_coding(self, query: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """코딩 에이전트용 쿼리 최적화"""
        # 프로그래밍 언어와 요구사항 명확화
        optimized_query = query
        
        # 프로그래밍 언어 감지 및 추가
        languages = ['python', 'javascript', 'java', 'c++', 'c#', 'go', 'rust']
        detected_lang = None
        
        for lang in languages:
            if lang in query.lower():
                detected_lang = lang
                break
        
        if not detected_lang and "코드" in query:
            optimized_query = f"Python {query}"  # 기본값으로 Python 사용
        
        optimized_query_en = f"Programming code: {query}"
        
        return optimized_query, optimized_query_en, "프로그래밍 요구사항 명확화"

    async def _optimize_for_math(self, query: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """수학 에이전트용 쿼리 최적화"""
        # 수학 기호와 표현 정규화
        optimized_query = query
        
        # 수학 표현 정규화
        math_replacements = {
            "곱하기": "*",
            "나누기": "/",
            "더하기": "+",
            "빼기": "-",
            "제곱": "^2",
        }
        
        for korean, symbol in math_replacements.items():
            optimized_query = optimized_query.replace(korean, symbol)
        
        optimized_query_en = f"Mathematical calculation: {optimized_query}"
        
        return optimized_query, optimized_query_en, "수학 표현 정규화"

    async def _optimize_for_document(self, query: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """문서 처리 에이전트용 쿼리 최적화"""
        return await self._optimize_for_rag(query, context)  # RAG와 유사한 최적화

    async def _optimize_for_weather(self, query: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """날씨 에이전트용 쿼리 최적화"""
        optimized_query = query
        
        # 날씨 관련 키워드 정규화
        if "날씨" not in query and any(word in query for word in ["기온", "온도", "비", "눈"]):
            optimized_query = f"{query} 날씨"
        
        optimized_query_en = f"Weather: {query}"
        
        return optimized_query, optimized_query_en, "날씨 정보 요청 명확화"

    async def _optimize_for_calculator(self, query: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """계산기 에이전트용 쿼리 최적화"""
        return await self._optimize_for_math(query, context)  # 수학과 동일한 최적화

    async def _optimize_for_internet(self, query: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """인터넷 에이전트용 쿼리 최적화"""
        return await self._optimize_for_search(query, context)  # 검색과 유사한 최적화

    async def _optimize_for_general(self, query: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """일반 에이전트용 쿼리 최적화"""
        # 기본적인 정리만 수행
        optimized_query = query.strip()
        optimized_query_en = None
        
        if self.llm_client:
            try:
                messages = [
                    LLMMessage(role="system", content="다음 쿼리를 영어로 번역해주세요."),
                    LLMMessage(role="user", content=optimized_query)
                ]
                response = await self.llm_client.invoke_messages(messages)
                optimized_query_en = response.content.strip()
            except Exception as e:
                logger.warning(f"일반 쿼리 영어 번역 실패: {e}")
        
        return optimized_query, optimized_query_en, "기본 정리"


# 전역 인스턴스
_query_optimizer = None

def get_query_optimizer() -> QueryOptimizer:
    """쿼리 최적화기 인스턴스 반환 (싱글톤)"""
    global _query_optimizer
    if _query_optimizer is None:
        _query_optimizer = QueryOptimizer()
    return _query_optimizer


# 편의 함수들
async def optimize_query_for_agent(
    query: str,
    agent_type: str,
    agent_id: str = None,
    context: Dict[str, Any] = None
) -> QueryOptimizationResult:
    """
    에이전트용 쿼리 최적화 편의 함수
    
    Args:
        query: 원본 쿼리
        agent_type: 에이전트 타입 (문자열)
        agent_id: 에이전트 ID
        context: 추가 컨텍스트
        
    Returns:
        QueryOptimizationResult: 최적화 결과
    """
    try:
        # 문자열을 AgentType으로 변환
        if isinstance(agent_type, str):
            agent_type = AgentType(agent_type.lower())
        
        optimizer = get_query_optimizer()
        return await optimizer.optimize_query_for_agent(
            query=query,
            agent_type=agent_type,
            agent_id=agent_id,
            context=context
        )
    except Exception as e:
        logger.error(f"쿼리 최적화 편의 함수 실행 실패: {e}")
        return QueryOptimizationResult(
            original_query=query,
            optimized_query=query,
            suitability_score=0.5,
            is_suitable=True,  # 기본적으로는 처리 가능하다고 가정
            optimization_reason=f"최적화 실패, 원본 쿼리 사용: {str(e)}"
        )


async def check_agent_suitability(query: str, agent_type: str) -> Tuple[bool, float]:
    """
    에이전트 적합성 간단 체크 함수
    
    Args:
        query: 쿼리
        agent_type: 에이전트 타입
        
    Returns:
        Tuple[bool, float]: (적합 여부, 적합성 점수)
    """
    try:
        result = await optimize_query_for_agent(query, agent_type)
        return result.is_suitable, result.suitability_score
    except Exception as e:
        logger.error(f"적합성 체크 실패: {e}")
        return True, 0.5  # 기본값