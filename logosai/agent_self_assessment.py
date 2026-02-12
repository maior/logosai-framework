"""
에이전트 자기평가 프로토콜

모든 LogosAI 에이전트가 자신의 적합성을 스스로 판단하고
매니저와 협상할 수 있는 인터페이스를 제공합니다.
"""

import asyncio
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from loguru import logger

class CapabilityLevel(Enum):
    """에이전트 능력 수준"""
    EXPERT = "expert"           # 전문가 수준 (90-100%)
    PROFICIENT = "proficient"   # 능숙함 (70-89%)
    COMPETENT = "competent"     # 처리 가능 (50-69%)
    LIMITED = "limited"         # 제한적 (30-49%)
    UNSUITABLE = "unsuitable"   # 부적합 (0-19%)  # 수정: 임계값 낮춤

class AssessmentReason(Enum):
    """평가 이유 카테고리"""
    DOMAIN_MATCH = "domain_match"           # 도메인 일치
    CAPABILITY_MATCH = "capability_match"   # 능력 일치
    EXPERIENCE = "experience"               # 경험/성능 데이터
    RESOURCE_AVAILABILITY = "resource_availability"  # 리소스 가용성
    COMPLEXITY_ANALYSIS = "complexity_analysis"      # 복잡도 분석
    ALTERNATIVE_SUGGESTION = "alternative_suggestion" # 대안 제안

@dataclass
class SelfAssessmentResult:
    """에이전트 자기평가 결과"""
    agent_id: str
    agent_name: str
    capability_level: CapabilityLevel
    confidence_score: float  # 0.0 - 1.0
    can_handle: bool
    reasoning: List[str]
    suggestions: List[str]  # 개선/대안 제안
    estimated_success_rate: float
    estimated_processing_time: Optional[float]
    required_resources: List[str]
    alternative_agents: List[str]  # 더 적합한 에이전트 제안
    collaborative_agents: List[str]  # 협력 가능한 에이전트

class AgentSelfAssessment:
    """에이전트 자기평가 인터페이스"""
    
    def __init__(self, agent_id: str, agent_name: str, llm_client=None, 
                 domain_matching_config: Dict[str, Any] = None):
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.llm_client = llm_client
        self.domain_keywords = {}
        self.capability_descriptions = []
        self.performance_history = {}
        
        # 도메인 매칭 설정 (부스트, 패턴 매칭 등)
        self.domain_matching_config = domain_matching_config or {}
        
    def set_domain_keywords(self, domain_keywords: Dict[str, List[str]]):
        """도메인별 키워드 설정"""
        self.domain_keywords = domain_keywords
        
    def set_capabilities(self, capabilities: List[str]):
        """에이전트 능력 설명 설정"""
        self.capability_descriptions = capabilities
        
    def update_performance_history(self, performance_data: Dict[str, Any]):
        """성능 이력 업데이트"""
        self.performance_history = performance_data

    async def assess_request_compatibility(self, request: str, context: Dict[str, Any] = None) -> SelfAssessmentResult:
        """
        요청에 대한 자기 적합성 평가
        
        Args:
            request: 사용자 요청
            context: 추가 컨텍스트 정보
            
        Returns:
            SelfAssessmentResult: 자기평가 결과
        """
        try:
            logger.info(f"🤔 {self.agent_name} 자기평가 시작: '{request[:50]}...'")
            
            # 1. 기본 도메인 매칭 분석
            domain_analysis = self._analyze_domain_match(request)
            
            # 2. 능력 기반 매칭 분석  
            capability_analysis = self._analyze_capability_match(request)
            
            # 3. 복잡도 분석
            complexity_analysis = self._analyze_request_complexity(request)
            
            # 4. 리소스 요구사항 분석
            resource_analysis = self._analyze_resource_requirements(request, context)
            
            # 5. LLM 기반 심화 분석 (선택적)
            llm_analysis = await self._llm_based_assessment(request, context) if self.llm_client else None
            
            # 6. 종합 평가 및 결과 생성
            result = self._generate_assessment_result(
                request, domain_analysis, capability_analysis, 
                complexity_analysis, resource_analysis, llm_analysis
            )
            
            logger.info(f"🎯 {self.agent_name} 자기평가 완료: {result.capability_level.value} ({result.confidence_score:.2f})")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ {self.agent_name} 자기평가 실패: {str(e)}")
            # 안전한 기본 결과 반환
            return SelfAssessmentResult(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                capability_level=CapabilityLevel.LIMITED,
                confidence_score=0.3,
                can_handle=False,
                reasoning=[f"평가 중 오류 발생: {str(e)}"],
                suggestions=["매니저에게 다른 에이전트 요청 권장"],
                estimated_success_rate=0.3,
                estimated_processing_time=None,
                required_resources=["오류 복구"],
                alternative_agents=[],
                collaborative_agents=[]
            )

    def _analyze_domain_match(self, request: str) -> Dict[str, Any]:
        """도메인 매칭 분석"""
        request_lower = request.lower()
        
        # 설정 기반 도메인 부스트 확인
        if self.domain_matching_config.get("boost_patterns"):
            for boost_config in self.domain_matching_config["boost_patterns"]:
                pattern = boost_config.get("pattern", "")
                if pattern and any(p in request_lower for p in pattern.split("|")):
                    return {
                        "matched_domains": boost_config.get("domains", []),
                        "match_scores": {d: boost_config.get("score", 0.9) for d in boost_config.get("domains", [])},
                        "best_domain": boost_config.get("domains", ["unknown"])[0],
                        "best_score": boost_config.get("score", 0.9),
                        "domain_confidence": boost_config.get("score", 0.9),
                        "boost_applied": True
                    }
        
        matched_domains = []
        match_scores = {}
        
        for domain, keywords in self.domain_keywords.items():
            matches = sum(1 for keyword in keywords if keyword.lower() in request_lower)
            if matches > 0:
                match_scores[domain] = matches / len(keywords)
                matched_domains.append(domain)
        
        best_domain = max(match_scores.items(), key=lambda x: x[1]) if match_scores else ("unknown", 0.0)
        
        return {
            "matched_domains": matched_domains,
            "match_scores": match_scores,
            "best_domain": best_domain[0],
            "best_score": best_domain[1],
            "domain_confidence": min(best_domain[1] * 2, 1.0)
        }

    def _analyze_capability_match(self, request: str) -> Dict[str, Any]:
        """능력 기반 매칭 분석"""
        request_words = set(request.lower().split())
        capability_scores = []
        
        for capability in self.capability_descriptions:
            capability_words = set(capability.lower().split())
            intersection = len(request_words & capability_words)
            union = len(request_words | capability_words)
            jaccard_similarity = intersection / union if union > 0 else 0
            capability_scores.append(jaccard_similarity)
        
        max_score = max(capability_scores) if capability_scores else 0.0
        avg_score = sum(capability_scores) / len(capability_scores) if capability_scores else 0.0
        
        return {
            "max_capability_score": max_score,
            "avg_capability_score": avg_score,
            "capability_confidence": (max_score + avg_score) / 2
        }

    def _analyze_request_complexity(self, request: str) -> Dict[str, Any]:
        """요청 복잡도 분석"""
        complexity_indicators = {
            "length": len(request.split()),
            "has_multiple_questions": request.count("?") > 1,
            "has_conditions": any(word in request.lower() for word in ["if", "when", "unless", "provided", "조건", "만약", "경우"]),
            "has_comparisons": any(word in request.lower() for word in ["compare", "vs", "versus", "difference", "비교", "차이"]),
            "has_calculations": any(word in request.lower() for word in ["calculate", "compute", "sum", "계산", "산출"]),
            "has_multiple_docs": any(word in request.lower() for word in ["documents", "files", "papers", "문서들", "파일들"])
        }
        
        complexity_score = (
            min(complexity_indicators["length"] / 20, 1.0) * 0.3 +
            (1.0 if complexity_indicators["has_multiple_questions"] else 0.0) * 0.2 +
            (1.0 if complexity_indicators["has_conditions"] else 0.0) * 0.15 +
            (1.0 if complexity_indicators["has_comparisons"] else 0.0) * 0.15 +
            (1.0 if complexity_indicators["has_calculations"] else 0.0) * 0.1 +
            (1.0 if complexity_indicators["has_multiple_docs"] else 0.0) * 0.1
        )
        
        return {
            "complexity_indicators": complexity_indicators,
            "complexity_score": complexity_score,
            "complexity_level": "high" if complexity_score > 0.7 else "medium" if complexity_score > 0.4 else "low"
        }

    def _analyze_resource_requirements(self, request: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """리소스 요구사항 분석"""
        required_resources = []
        
        # 기본 리소스 분석
        if any(word in request.lower() for word in ["pdf", "document", "file", "문서", "파일"]):
            required_resources.append("document_processing")
            
        if any(word in request.lower() for word in ["search", "find", "lookup", "검색", "찾"]):
            required_resources.append("search_engine")
            
        if any(word in request.lower() for word in ["calculate", "compute", "math", "계산", "수학"]):
            required_resources.append("computation_engine")
            
        if any(word in request.lower() for word in ["image", "chart", "graph", "이미지", "차트", "그래프"]):
            required_resources.append("image_processing")
            
        if any(word in request.lower() for word in ["web", "internet", "online", "웹", "인터넷"]):
            required_resources.append("web_access")
        
        # 컨텍스트 기반 추가 분석
        if context:
            if context.get("user_email"):
                required_resources.append("user_context")
            if context.get("project_id"):
                required_resources.append("project_access")
        
        return {
            "required_resources": required_resources,
            "resource_complexity": len(required_resources),
            "resource_availability": 1.0  # 기본적으로 모든 리소스 사용 가능으로 가정
        }

    async def _llm_based_assessment(self, request: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """LLM 기반 심화 평가"""
        if not self.llm_client:
            return {"llm_confidence": 0.0, "llm_reasoning": []}
        
        try:
            from logosai.utils.llm_client import LLMMessage
            
            system_prompt = f"""당신은 {self.agent_name} 에이전트입니다.
            
에이전트 능력:
{chr(10).join(f"- {cap}" for cap in self.capability_descriptions)}

도메인 전문성:
{chr(10).join(f"- {domain}: {', '.join(keywords)}" for domain, keywords in self.domain_keywords.items())}

사용자 요청을 분석하여 다음을 평가해주세요:
1. 내가 이 요청을 처리할 수 있는가? (0-100%)
2. 처리할 수 있다면 얼마나 잘할 수 있는가?
3. 처리하기 어렵다면 이유는?
4. 더 적합한 다른 에이전트가 있는가?

정직하고 정확한 평가를 해주세요."""

            user_prompt = f"""
사용자 요청: {request}

컨텍스트: {context if context else "없음"}

위 요청에 대한 나의 적합성을 평가해주세요.
응답 형식:
적합성: [0-100]%
이유: [구체적인 이유]
대안: [더 적합한 에이전트 제안이 있다면]
"""

            messages = [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt)
            ]
            
            response = await self.llm_client.invoke_messages(messages)
            content = response.content
            
            # 간단한 파싱 (실제로는 더 정교한 파싱 필요)
            llm_confidence = 0.5  # 기본값
            llm_reasoning = []
            
            if "적합성:" in content:
                try:
                    confidence_line = [line for line in content.split("\n") if "적합성:" in line][0]
                    confidence_str = confidence_line.split("적합성:")[1].strip().replace("%", "")
                    llm_confidence = float(confidence_str) / 100.0
                except:
                    pass
            
            llm_reasoning = [content.strip()]
            
            return {
                "llm_confidence": llm_confidence,
                "llm_reasoning": llm_reasoning,
                "llm_full_response": content
            }
            
        except Exception as e:
            logger.warning(f"LLM 기반 평가 실패: {e}")
            return {"llm_confidence": 0.0, "llm_reasoning": [f"LLM 평가 실패: {str(e)}"]}

    def _generate_assessment_result(self, request: str, domain_analysis: Dict, 
                                  capability_analysis: Dict, complexity_analysis: Dict,
                                  resource_analysis: Dict, llm_analysis: Dict = None) -> SelfAssessmentResult:
        """종합 평가 결과 생성"""
        
        # 종합 점수 계산
        base_score = (
            domain_analysis["domain_confidence"] * 0.4 +
            capability_analysis["capability_confidence"] * 0.3 +
            resource_analysis["resource_availability"] * 0.2 +
            (1.0 - complexity_analysis["complexity_score"]) * 0.1  # 복잡도가 낮을수록 좋음
        )
        
        # LLM 분석이 있으면 가중치 적용
        if llm_analysis and llm_analysis["llm_confidence"] > 0:
            final_score = base_score * 0.6 + llm_analysis["llm_confidence"] * 0.4
        else:
            final_score = base_score
        
        # 능력 수준 결정
        if final_score >= 0.9:
            capability_level = CapabilityLevel.EXPERT
        elif final_score >= 0.7:
            capability_level = CapabilityLevel.PROFICIENT
        elif final_score >= 0.5:
            capability_level = CapabilityLevel.COMPETENT
        elif final_score >= 0.3:
            capability_level = CapabilityLevel.LIMITED
        else:
            capability_level = CapabilityLevel.UNSUITABLE
        
        # 처리 가능 여부 결정
        can_handle = final_score >= 0.5
        
        # 이유 생성
        reasoning = []
        if domain_analysis["best_score"] > 0.3:
            reasoning.append(f"도메인 매칭: {domain_analysis['best_domain']} ({domain_analysis['best_score']:.2f})")
        if capability_analysis["max_capability_score"] > 0.3:
            reasoning.append(f"능력 매칭도: {capability_analysis['max_capability_score']:.2f}")
        if complexity_analysis["complexity_level"] == "high":
            reasoning.append(f"고복잡도 요청 ({complexity_analysis['complexity_score']:.2f})")
            
        if llm_analysis and llm_analysis.get("llm_reasoning"):
            reasoning.extend(llm_analysis["llm_reasoning"])
        
        # 제안사항 생성
        suggestions = []
        if not can_handle:
            suggestions.append("다른 전문 에이전트 활용 권장")
            if complexity_analysis["complexity_level"] == "high":
                suggestions.append("복잡한 요청을 단순한 단계로 분할 고려")
        
        # 대안 에이전트 제안 (도메인 기반)
        alternative_agents = []
        if not can_handle:
            if "document" in domain_analysis["matched_domains"]:
                alternative_agents.append("rag_agent")
            if "math" in domain_analysis["matched_domains"]:
                alternative_agents.append("math_agent")
            if "web" in domain_analysis["matched_domains"]:
                alternative_agents.append("web_search_agent")
        
        return SelfAssessmentResult(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            capability_level=capability_level,
            confidence_score=final_score,
            can_handle=can_handle,
            reasoning=reasoning,
            suggestions=suggestions,
            estimated_success_rate=final_score,
            estimated_processing_time=None,  # 에이전트별로 구현
            required_resources=resource_analysis["required_resources"],
            alternative_agents=alternative_agents,
            collaborative_agents=[]  # 에이전트별로 구현
        )

# 편의 함수들
def create_agent_self_assessment(agent_id: str, agent_name: str, 
                                agent_config: Dict[str, Any] = None,
                                llm_client=None) -> AgentSelfAssessment:
    """에이전트 자기평가 인스턴스 생성"""
    assessment = AgentSelfAssessment(agent_id, agent_name, llm_client)
    
    if agent_config:
        # 설정에서 도메인 키워드 추출
        domain_keywords = agent_config.get("domain_keywords", {})
        assessment.set_domain_keywords(domain_keywords)
        
        # 설정에서 능력 설명 추출
        capabilities = agent_config.get("capabilities", [])
        if isinstance(capabilities, dict):
            capabilities = [f"{k}: {v}" for k, v in capabilities.items()]
        assessment.set_capabilities(capabilities)
    
    return assessment