"""
LLM 기반 자동 자가평가 시스템

사용자가 복잡한 자가평가 로직을 구현할 필요 없이,
에이전트의 설명과 능력만 제공하면 LLM이 자동으로 적합성을 평가하는 시스템
"""

import asyncio
import json
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from loguru import logger

from logosai.agent_self_assessment import (
    CapabilityLevel, AssessmentReason, SelfAssessmentResult
)


@dataclass
class LLMSelfAssessmentConfig:
    """LLM 기반 자가평가 설정"""
    agent_name: str
    agent_description: str
    capabilities: List[str]
    domain_expertise: List[str]
    example_queries: List[str] = None  # 에이전트가 잘 처리할 수 있는 예시 쿼리
    limitations: List[str] = None      # 에이전트의 한계
    confidence_threshold: float = 0.5   # 처리 가능 판단 임계값


class LLMBasedSelfAssessment:
    """LLM 기반 자동 자가평가 시스템"""
    
    def __init__(self, config: LLMSelfAssessmentConfig, llm_client):
        self.config = config
        self.llm_client = llm_client
        self.assessment_history = []  # 평가 이력 저장
        
        # 안전장치: 최소/최대 신뢰도 제한
        self.min_confidence = 0.1
        self.max_confidence = 0.95
        
    async def assess_request_compatibility(self, request: str, context: Dict[str, Any] = None) -> SelfAssessmentResult:
        """
        LLM을 사용한 자동 적합성 평가
        
        Args:
            request: 사용자 요청
            context: 추가 컨텍스트
            
        Returns:
            SelfAssessmentResult: 평가 결과
        """
        try:
            logger.info(f"🤖 {self.config.agent_name} LLM 기반 자가평가 시작")
            
            # 1. LLM 프롬프트 생성
            assessment_prompt = self._create_assessment_prompt(request, context)
            
            # 2. LLM 호출
            llm_response = await self._call_llm_for_assessment(assessment_prompt)
            
            # 3. LLM 응답 파싱
            parsed_result = self._parse_llm_response(llm_response)
            
            # 4. 안전장치 적용
            validated_result = self._apply_safety_guards(parsed_result, request)
            
            # 5. 결과 구성
            result = self._create_assessment_result(validated_result, request)
            
            # 6. 이력 저장
            self._save_assessment_history(request, result)
            
            logger.info(f"✅ LLM 자가평가 완료: {result.capability_level.value} ({result.confidence_score:.2f})")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ LLM 자가평가 실패: {str(e)}")
            return self._create_safe_fallback_result(request, str(e))
    
    def _create_assessment_prompt(self, request: str, context: Dict[str, Any] = None) -> str:
        """자가평가용 LLM 프롬프트 생성"""
        
        examples_text = ""
        if self.config.example_queries:
            examples_text = f"""
잘 처리할 수 있는 예시 질문들:
{chr(10).join(f"- {example}" for example in self.config.example_queries)}
"""
        
        limitations_text = ""
        if self.config.limitations:
            limitations_text = f"""
알려진 한계사항들:
{chr(10).join(f"- {limitation}" for limitation in self.config.limitations)}
"""
        
        context_text = ""
        if context:
            context_text = f"""
추가 컨텍스트:
{json.dumps(context, indent=2, ensure_ascii=False)}
"""
        
        prompt = f"""당신은 "{self.config.agent_name}" 에이전트입니다.

에이전트 설명:
{self.config.agent_description}

주요 능력들:
{chr(10).join(f"- {capability}" for capability in self.config.capabilities)}

전문 분야:
{chr(10).join(f"- {domain}" for domain in self.config.domain_expertise)}

{examples_text}{limitations_text}{context_text}

사용자 요청: "{request}"

위 요청에 대해 당신의 적합성을 정직하고 정확하게 평가해주세요.

평가 기준:
1. 요청이 내 전문 분야에 해당하는가?
2. 내가 가진 능력으로 처리할 수 있는가?
3. 품질 높은 결과를 제공할 수 있는가?
4. 다른 에이전트가 더 적합할 수 있는가?

응답 형식 (JSON):
{{
  "can_handle": true/false,
  "confidence_score": 0.0-1.0,
  "capability_level": "expert/proficient/competent/limited/unsuitable",
  "reasoning": ["이유1", "이유2", "이유3"],
  "suggestions": ["제안1", "제안2"],
  "alternative_agents": ["다른_에이전트1", "다른_에이전트2"],
  "estimated_success_rate": 0.0-1.0,
  "required_resources": ["리소스1", "리소스2"]
}}

정직하고 겸손한 평가를 해주세요. 확실하지 않으면 낮은 점수를 주는 것이 좋습니다."""

        return prompt
    
    async def _call_llm_for_assessment(self, prompt: str) -> str:
        """LLM 호출하여 평가 수행"""
        try:
            from logosai.utils.llm_client import LLMMessage
            
            if not hasattr(self.llm_client, '_initialized') or not self.llm_client._initialized:
                await self.llm_client.initialize()
            
            messages = [LLMMessage(role="user", content=prompt)]
            response = await self.llm_client.invoke_messages(messages)
            
            return response.content
            
        except Exception as e:
            logger.error(f"LLM 호출 실패: {e}")
            raise
    
    def _parse_llm_response(self, llm_response: str) -> Dict[str, Any]:
        """LLM 응답 파싱"""
        try:
            # JSON 부분 추출
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                json_text = json_match.group(0)
                parsed = json.loads(json_text)
                return parsed
            else:
                # JSON이 없으면 텍스트에서 정보 추출
                return self._extract_from_text(llm_response)
                
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 파싱 실패, 텍스트 파싱 시도: {e}")
            return self._extract_from_text(llm_response)
    
    def _extract_from_text(self, text: str) -> Dict[str, Any]:
        """JSON 파싱 실패시 텍스트에서 정보 추출"""
        # 기본값
        result = {
            "can_handle": False,
            "confidence_score": 0.3,
            "capability_level": "limited",
            "reasoning": ["LLM 응답 파싱 어려움"],
            "suggestions": ["더 명확한 요청 필요"],
            "alternative_agents": [],
            "estimated_success_rate": 0.3,
            "required_resources": []
        }
        
        text_lower = text.lower()
        
        # 긍정적/부정적 키워드로 can_handle 판단
        positive_keywords = ["가능", "할 수 있", "적합", "처리", "yes", "true"]
        negative_keywords = ["불가능", "할 수 없", "부적합", "어려움", "no", "false"]
        
        positive_count = sum(1 for keyword in positive_keywords if keyword in text_lower)
        negative_count = sum(1 for keyword in negative_keywords if keyword in text_lower)
        
        if positive_count > negative_count:
            result["can_handle"] = True
            result["confidence_score"] = min(0.7, 0.4 + positive_count * 0.1)
            result["capability_level"] = "competent"
        
        # 신뢰도 관련 숫자 추출
        confidence_matches = re.findall(r'(\d+(?:\.\d+)?)\s*(?:%|점|정도)', text)
        if confidence_matches:
            try:
                confidence = float(confidence_matches[0])
                if confidence > 1:  # 퍼센트로 입력된 경우
                    confidence /= 100
                result["confidence_score"] = confidence
            except:
                pass
        
        return result
    
    def _apply_safety_guards(self, parsed_result: Dict[str, Any], request: str) -> Dict[str, Any]:
        """안전장치 적용 - 과도한 자신감 방지"""
        
        # 신뢰도 제한
        confidence = parsed_result.get("confidence_score", 0.5)
        confidence = max(self.min_confidence, min(self.max_confidence, confidence))
        parsed_result["confidence_score"] = confidence
        
        # 능력 수준과 신뢰도 일치성 검사
        capability_level = parsed_result.get("capability_level", "limited")
        if capability_level == "expert" and confidence < 0.8:
            parsed_result["capability_level"] = "proficient"
            parsed_result["reasoning"].append("신뢰도와 능력 수준 불일치로 조정됨")
        
        # 짧은 요청에 대한 과도한 자신감 방지
        if len(request.split()) < 3 and confidence > 0.8:
            parsed_result["confidence_score"] = min(confidence, 0.7)
            parsed_result["reasoning"].append("짧은 요청에 대한 신뢰도 조정")
        
        # can_handle과 confidence 일치성 검사
        can_handle = parsed_result.get("can_handle", False)
        if can_handle and confidence < self.config.confidence_threshold:
            parsed_result["can_handle"] = False
            parsed_result["reasoning"].append("신뢰도 임계값 미달로 처리 불가 판정")
        
        return parsed_result
    
    def _create_assessment_result(self, validated_result: Dict[str, Any], request: str) -> SelfAssessmentResult:
        """평가 결과 객체 생성"""
        
        # 능력 수준 매핑
        capability_mapping = {
            "expert": CapabilityLevel.EXPERT,
            "proficient": CapabilityLevel.PROFICIENT,
            "competent": CapabilityLevel.COMPETENT,
            "limited": CapabilityLevel.LIMITED,
            "unsuitable": CapabilityLevel.UNSUITABLE
        }
        
        capability_level = capability_mapping.get(
            validated_result.get("capability_level", "limited"),
            CapabilityLevel.LIMITED
        )
        
        return SelfAssessmentResult(
            agent_id=f"{self.config.agent_name.lower().replace(' ', '_')}_agent",
            agent_name=self.config.agent_name,
            capability_level=capability_level,
            confidence_score=validated_result.get("confidence_score", 0.3),
            can_handle=validated_result.get("can_handle", False),
            reasoning=validated_result.get("reasoning", ["LLM 기반 평가"]),
            suggestions=validated_result.get("suggestions", []),
            estimated_success_rate=validated_result.get("estimated_success_rate", 0.3),
            estimated_processing_time=None,
            required_resources=validated_result.get("required_resources", []),
            alternative_agents=validated_result.get("alternative_agents", []),
            collaborative_agents=[]
        )
    
    def _create_safe_fallback_result(self, request: str, error_msg: str) -> SelfAssessmentResult:
        """안전한 대체 결과 생성"""
        return SelfAssessmentResult(
            agent_id=f"{self.config.agent_name.lower().replace(' ', '_')}_agent",
            agent_name=self.config.agent_name,
            capability_level=CapabilityLevel.LIMITED,
            confidence_score=0.3,
            can_handle=False,
            reasoning=[f"평가 중 오류 발생: {error_msg}"],
            suggestions=["시스템 관리자에게 문의"],
            estimated_success_rate=0.3,
            estimated_processing_time=None,
            required_resources=["오류 해결"],
            alternative_agents=[],
            collaborative_agents=[]
        )
    
    def _save_assessment_history(self, request: str, result: SelfAssessmentResult):
        """평가 이력 저장 (학습 개선용)"""
        history_entry = {
            "timestamp": asyncio.get_event_loop().time(),
            "request": request[:100],  # 개인정보 보호를 위해 일부만 저장
            "confidence": result.confidence_score,
            "capability_level": result.capability_level.value,
            "can_handle": result.can_handle
        }
        
        self.assessment_history.append(history_entry)
        
        # 최근 100개만 유지
        if len(self.assessment_history) > 100:
            self.assessment_history = self.assessment_history[-100:]


def create_llm_based_self_assessment(
    agent_name: str,
    agent_description: str,
    capabilities: List[str],
    domain_expertise: List[str],
    llm_client,
    example_queries: List[str] = None,
    limitations: List[str] = None,
    confidence_threshold: float = 0.5
) -> LLMBasedSelfAssessment:
    """LLM 기반 자가평가 시스템 생성 편의 함수"""
    
    config = LLMSelfAssessmentConfig(
        agent_name=agent_name,
        agent_description=agent_description,
        capabilities=capabilities,
        domain_expertise=domain_expertise,
        example_queries=example_queries,
        limitations=limitations,
        confidence_threshold=confidence_threshold
    )
    
    return LLMBasedSelfAssessment(config, llm_client)


# 에이전트 기본 클래스에 쉽게 통합할 수 있는 믹스인
class LLMSelfAssessmentMixin:
    """에이전트에 LLM 기반 자가평가 기능을 추가하는 믹스인"""
    
    def setup_llm_self_assessment(self, 
                                 agent_description: str,
                                 capabilities: List[str],
                                 domain_expertise: List[str],
                                 example_queries: List[str] = None,
                                 limitations: List[str] = None):
        """LLM 기반 자가평가 설정"""
        
        if not hasattr(self, 'llm_client') or self.llm_client is None:
            logger.warning("LLM 클라이언트가 없어 기본 자가평가 시스템 사용")
            return
        
        self._llm_self_assessment = create_llm_based_self_assessment(
            agent_name=getattr(self, 'name', self.__class__.__name__),
            agent_description=agent_description,
            capabilities=capabilities,
            domain_expertise=domain_expertise,
            llm_client=self.llm_client,
            example_queries=example_queries,
            limitations=limitations
        )
        
        # 기존 _self_assessment를 LLM 기반으로 교체
        self._self_assessment = self._llm_self_assessment
        
        logger.info(f"✅ {self.name} LLM 기반 자가평가 시스템 설정 완료")


if __name__ == "__main__":
    # 사용 예시
    async def test_llm_self_assessment():
        from logosai.utils.llm_client import LLMClient
        
        # LLM 클라이언트 생성
        llm_client = LLMClient(provider="google", model="gemini-2.5-flash-lite")
        await llm_client.initialize()
        
        # LLM 기반 자가평가 시스템 생성
        assessment = create_llm_based_self_assessment(
            agent_name="테스트 계산기",
            agent_description="기본적인 수학 계산을 수행하는 에이전트",
            capabilities=["덧셈", "뺄셈", "곱셈", "나눗셈", "단위 변환"],
            domain_expertise=["산술 연산", "기초 수학"],
            llm_client=llm_client,
            example_queries=["2 + 2는?", "5km를 m로 변환해줘"],
            limitations=["복잡한 미적분은 처리할 수 없음"]
        )
        
        # 테스트 쿼리들
        test_queries = [
            "123 + 456은?",
            "미적분을 사용해서 함수를 분석해줘",
            "파이썬 코드를 작성해줘",
            "5 x 10"
        ]
        
        for query in test_queries:
            print(f"\n쿼리: {query}")
            result = await assessment.assess_request_compatibility(query)
            print(f"결과: {result.can_handle}, 신뢰도: {result.confidence_score:.2f}, 수준: {result.capability_level.value}")
            print(f"이유: {', '.join(result.reasoning[:2])}")
    
    # 테스트 실행
    # asyncio.run(test_llm_self_assessment())