"""
결과 품질 평가 시스템

사용자 쿼리와 에이전트 처리 결과의 품질을 LLM이 자동으로 평가하는 시스템
"""

import asyncio
import json
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from loguru import logger

class QualityDimension(Enum):
    """품질 평가 차원"""
    RELEVANCE = "relevance"           # 관련성
    ACCURACY = "accuracy"             # 정확성
    COMPLETENESS = "completeness"     # 완전성
    CLARITY = "clarity"               # 명확성
    USEFULNESS = "usefulness"         # 유용성
    CORRECTNESS = "correctness"       # 올바름


@dataclass
class QualityScore:
    """품질 점수"""
    overall_score: float              # 전체 점수 (0.0-1.0)
    dimension_scores: Dict[str, float]  # 차원별 점수
    reasoning: List[str]              # 평가 이유
    strengths: List[str]              # 강점
    weaknesses: List[str]             # 약점
    confidence: float                 # 평가 신뢰도
    evaluation_time: float            # 평가 소요시간


@dataclass
class EvaluationRequest:
    """평가 요청"""
    query: str                        # 원본 쿼리
    result: Any                       # 에이전트 결과
    agent_id: str                     # 에이전트 ID
    context: Dict[str, Any] = None    # 추가 컨텍스트
    expected_format: str = None       # 기대 형식
    quality_criteria: List[str] = None  # 품질 기준


class ResultQualityEvaluator:
    """결과 품질 평가기"""
    
    def __init__(self, llm_client, config: Dict[str, Any] = None):
        self.llm_client = llm_client
        self.config = config or {}
        
        # 설정값들
        self.min_score_threshold = self.config.get("min_score_threshold", 0.7)
        self.evaluation_timeout = self.config.get("evaluation_timeout", 10.0)
        self.cache_evaluations = self.config.get("cache_evaluations", True)
        
        # 캐시 (동일한 쿼리-결과 조합 재평가 방지)
        self._evaluation_cache = {} if self.cache_evaluations else None
        
        # 성능 메트릭
        self.evaluation_count = 0
        self.cache_hits = 0
        
        logger.info("🎯 결과 품질 평가기 초기화 완료")
    
    async def evaluate_result(self, request: EvaluationRequest) -> QualityScore:
        """
        결과 품질 평가 수행
        
        Args:
            request: 평가 요청
            
        Returns:
            QualityScore: 품질 점수
        """
        start_time = time.time()
        
        try:
            # 캐시 확인
            cache_key = self._get_cache_key(request)
            if self._evaluation_cache and cache_key in self._evaluation_cache:
                self.cache_hits += 1
                cached_result = self._evaluation_cache[cache_key]
                logger.debug(f"📋 캐시된 평가 결과 사용: {cached_result.overall_score:.2f}")
                return cached_result
            
            # LLM 평가 수행
            quality_score = await self._perform_llm_evaluation(request)
            
            # 캐시 저장
            if self._evaluation_cache:
                self._evaluation_cache[cache_key] = quality_score
                
                # 캐시 크기 제한 (최근 1000개만 유지)
                if len(self._evaluation_cache) > 1000:
                    old_keys = list(self._evaluation_cache.keys())[:-1000]
                    for key in old_keys:
                        del self._evaluation_cache[key]
            
            self.evaluation_count += 1
            quality_score.evaluation_time = time.time() - start_time
            
            logger.info(f"✅ 품질 평가 완료: {quality_score.overall_score:.2f} (시간: {quality_score.evaluation_time:.2f}s)")
            
            return quality_score
            
        except Exception as e:
            logger.error(f"❌ 품질 평가 실패: {str(e)}")
            return self._create_fallback_score(request, str(e))
    
    def _get_cache_key(self, request: EvaluationRequest) -> str:
        """캐시 키 생성"""
        query_hash = hash(request.query)
        result_hash = hash(str(request.result)[:200])  # 결과 일부만 해시
        return f"{query_hash}_{result_hash}_{request.agent_id}"
    
    async def _perform_llm_evaluation(self, request: EvaluationRequest) -> QualityScore:
        """LLM을 사용한 품질 평가"""
        
        # 프롬프트 생성
        evaluation_prompt = self._create_evaluation_prompt(request)
        
        # LLM 호출
        try:
            if not hasattr(self.llm_client, '_initialized') or not self.llm_client._initialized:
                await self.llm_client.initialize()
            
            # 타임아웃 설정
            llm_response = await asyncio.wait_for(
                self.llm_client.invoke(evaluation_prompt),
                timeout=self.evaluation_timeout
            )
            
            response_text = llm_response.content
            
            # 응답 파싱
            quality_score = self._parse_evaluation_response(response_text)
            
            return quality_score
            
        except asyncio.TimeoutError:
            logger.warning(f"⏰ LLM 평가 타임아웃 ({self.evaluation_timeout}s)")
            return self._create_timeout_score(request)
        except Exception as e:
            logger.error(f"❌ LLM 평가 호출 실패: {str(e)}")
            return self._create_fallback_score(request, str(e))
    
    def _create_evaluation_prompt(self, request: EvaluationRequest) -> str:
        """평가 프롬프트 생성"""
        
        # 결과 형식 변환
        result_text = self._format_result_for_evaluation(request.result)
        
        # 컨텍스트 정보
        context_text = ""
        if request.context:
            context_text = f"""
컨텍스트:
{json.dumps(request.context, indent=2, ensure_ascii=False)}
"""
        
        # 품질 기준
        criteria_text = ""
        if request.quality_criteria:
            criteria_text = f"""
특별 품질 기준:
{chr(10).join(f"- {criterion}" for criterion in request.quality_criteria)}
"""
        
        # 기대 형식
        format_text = ""
        if request.expected_format:
            format_text = f"""
기대 형식: {request.expected_format}
"""
        
        prompt = f"""당신은 에이전트 결과 품질 평가 전문가입니다.

사용자 쿼리: "{request.query}"

에이전트 ID: {request.agent_id}
에이전트 결과:
{result_text}

{context_text}{format_text}{criteria_text}

다음 기준으로 결과의 품질을 평가해주세요:

1. 관련성 (Relevance): 결과가 사용자 쿼리와 얼마나 관련있는가?
2. 정확성 (Accuracy): 제공된 정보가 얼마나 정확한가?
3. 완전성 (Completeness): 사용자가 원하는 정보를 충분히 제공했는가?
4. 명확성 (Clarity): 결과가 이해하기 쉽게 작성되었는가?
5. 유용성 (Usefulness): 실제로 사용자에게 도움이 되는가?
6. 올바름 (Correctness): 논리적/사실적 오류가 없는가?

응답 형식 (JSON):
{{
  "overall_score": 0.0-1.0,
  "dimension_scores": {{
    "relevance": 0.0-1.0,
    "accuracy": 0.0-1.0,
    "completeness": 0.0-1.0,
    "clarity": 0.0-1.0,
    "usefulness": 0.0-1.0,
    "correctness": 0.0-1.0
  }},
  "reasoning": ["이유1", "이유2", "이유3"],
  "strengths": ["강점1", "강점2"],
  "weaknesses": ["약점1", "약점2"],
  "confidence": 0.0-1.0,
  "recommendation": "accept/reject/retry"
}}

정직하고 객관적인 평가를 해주세요. 불확실하면 낮은 점수를 주는 것이 좋습니다."""

        return prompt
    
    def _format_result_for_evaluation(self, result: Any) -> str:
        """결과를 평가용 텍스트로 변환"""
        if isinstance(result, str):
            return result
        elif isinstance(result, dict):
            # 딕셔너리인 경우 주요 필드 추출
            if 'content' in result:
                content = result['content']
                if isinstance(content, dict):
                    message = content.get('message', content.get('result', content.get('answer', str(content))))
                else:
                    message = str(content)
                return message
            elif 'message' in result:
                return str(result['message'])
            elif 'result' in result:
                return str(result['result'])
            else:
                return json.dumps(result, indent=2, ensure_ascii=False)
        else:
            return str(result)
    
    def _parse_evaluation_response(self, response_text: str) -> QualityScore:
        """LLM 응답 파싱"""
        try:
            # JSON 부분 추출
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_text = json_match.group(0)
                parsed = json.loads(json_text)
                
                return QualityScore(
                    overall_score=parsed.get("overall_score", 0.5),
                    dimension_scores=parsed.get("dimension_scores", {}),
                    reasoning=parsed.get("reasoning", []),
                    strengths=parsed.get("strengths", []),
                    weaknesses=parsed.get("weaknesses", []),
                    confidence=parsed.get("confidence", 0.5),
                    evaluation_time=0.0  # 나중에 설정
                )
            else:
                # JSON이 없으면 텍스트에서 추출
                return self._extract_from_text_response(response_text)
                
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 파싱 실패: {e}")
            return self._extract_from_text_response(response_text)
    
    def _extract_from_text_response(self, text: str) -> QualityScore:
        """JSON 파싱 실패시 텍스트에서 정보 추출"""
        
        # 기본값
        overall_score = 0.5
        dimension_scores = {}
        reasoning = ["텍스트 응답에서 추출됨"]
        strengths = []
        weaknesses = []
        confidence = 0.5
        
        text_lower = text.lower()
        
        # 점수 관련 키워드로 대략적 평가
        positive_keywords = ["좋", "적절", "정확", "완전", "명확", "유용", "excellent", "good", "적합"]
        negative_keywords = ["나쁘", "부적절", "부정확", "불완전", "불명확", "무용", "poor", "bad", "부적합"]
        
        positive_count = sum(1 for keyword in positive_keywords if keyword in text_lower)
        negative_count = sum(1 for keyword in negative_keywords if keyword in text_lower)
        
        if positive_count > negative_count:
            overall_score = min(0.8, 0.5 + positive_count * 0.1)
        elif negative_count > positive_count:
            overall_score = max(0.2, 0.5 - negative_count * 0.1)
        
        # 숫자 추출 시도
        import re
        numbers = re.findall(r'(\d+(?:\.\d+)?)', text)
        if numbers:
            try:
                score = float(numbers[0])
                if score > 1:  # 퍼센트로 입력된 경우
                    score /= 100
                overall_score = min(1.0, max(0.0, score))
            except (ValueError, IndexError):
                pass
        
        return QualityScore(
            overall_score=overall_score,
            dimension_scores=dimension_scores,
            reasoning=reasoning,
            strengths=strengths,
            weaknesses=weaknesses,
            confidence=confidence,
            evaluation_time=0.0
        )
    
    def _create_fallback_score(self, request: EvaluationRequest, error_msg: str) -> QualityScore:
        """평가 실패시 대체 점수 생성"""
        return QualityScore(
            overall_score=0.3,  # 보수적 점수
            dimension_scores={},
            reasoning=[f"평가 실패: {error_msg}"],
            strengths=[],
            weaknesses=["평가 불가"],
            confidence=0.1,
            evaluation_time=0.0
        )
    
    def _create_timeout_score(self, request: EvaluationRequest) -> QualityScore:
        """타임아웃시 대체 점수 생성"""
        return QualityScore(
            overall_score=0.4,  # 중간 점수
            dimension_scores={},
            reasoning=["평가 타임아웃으로 기본 점수 적용"],
            strengths=[],
            weaknesses=["평가 시간 초과"],
            confidence=0.2,
            evaluation_time=self.evaluation_timeout
        )
    
    def is_result_acceptable(self, quality_score: QualityScore) -> bool:
        """결과가 수용 가능한지 판단"""
        return quality_score.overall_score >= self.min_score_threshold
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """평가기 성능 통계"""
        cache_hit_rate = self.cache_hits / max(self.evaluation_count, 1)
        
        return {
            "total_evaluations": self.evaluation_count,
            "cache_hits": self.cache_hits,
            "cache_hit_rate": cache_hit_rate,
            "cache_size": len(self._evaluation_cache) if self._evaluation_cache else 0
        }


# 편의 함수들
def create_evaluation_request(query: str, result: Any, agent_id: str, 
                            context: Dict[str, Any] = None,
                            expected_format: str = None,
                            quality_criteria: List[str] = None) -> EvaluationRequest:
    """평가 요청 생성 편의 함수"""
    return EvaluationRequest(
        query=query,
        result=result,
        agent_id=agent_id,
        context=context,
        expected_format=expected_format,
        quality_criteria=quality_criteria
    )


# 사용 예시
if __name__ == "__main__":
    async def test_quality_evaluator():
        from logosai.utils.llm_client import LLMClient

        # LLM 클라이언트 생성
        llm_client = LLMClient(provider="google", model="gemini-2.5-flash-lite")
        await llm_client.initialize()

        # 품질 평가기 생성
        evaluator = ResultQualityEvaluator(llm_client, {
            "min_score_threshold": 0.7,
            "evaluation_timeout": 10.0
        })

        # 테스트 케이스들
        test_cases = [
            {
                "query": "123 + 456을 계산해주세요",
                "result": {"message": "계산 결과: 579", "answer": "579"},
                "agent_id": "calculator_agent"
            },
            {
                "query": "파이썬 코드를 작성해주세요",
                "result": {"message": "죄송합니다. 코드 작성은 제 전문분야가 아닙니다."},
                "agent_id": "calculator_agent"
            },
            {
                "query": "이 문서를 요약해주세요",
                "result": {"message": "문서가 제공되지 않았습니다. 요약할 문서를 첨부해주세요."},
                "agent_id": "text_agent"
            }
        ]

        for i, case in enumerate(test_cases, 1):
            logger.info(f"\n=== 테스트 케이스 {i} ===")
            logger.info(f"쿼리: {case['query']}")
            logger.info(f"결과: {case['result']}")

            request = create_evaluation_request(
                query=case["query"],
                result=case["result"],
                agent_id=case["agent_id"]
            )

            quality_score = await evaluator.evaluate_result(request)

            logger.info(f"품질 점수: {quality_score.overall_score:.2f}")
            logger.info(f"수용 가능: {evaluator.is_result_acceptable(quality_score)}")
            logger.info(f"이유: {quality_score.reasoning}")

        # 성능 통계
        stats = evaluator.get_performance_stats()
        logger.info(f"\n=== 성능 통계 ===")
        logger.info(f"총 평가 수: {stats['total_evaluations']}")
        logger.info(f"캐시 적중률: {stats['cache_hit_rate']:.2%}")

    # 테스트 실행
    # asyncio.run(test_quality_evaluator())