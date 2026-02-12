"""
LogosAI 에이전트 선택 및 적합성 판단 시스템

사용자 요청에 가장 적합한 에이전트를 선택하고, 
에이전트가 해당 요청을 처리할 수 있는지 판단하는 기능을 제공합니다.
"""

import re
import json
import time
import asyncio
from typing import Dict, List, Any, Tuple, Optional, Union
from dataclasses import dataclass
from enum import Enum
from loguru import logger

# 동적 능력 관리 시스템 임포트
try:
    from .dynamic_capability_manager import DynamicCapabilityManager
    DYNAMIC_CAPABILITY_AVAILABLE = True
except ImportError:
    DYNAMIC_CAPABILITY_AVAILABLE = False
    logger.warning("동적 능력 관리 시스템을 찾을 수 없습니다. 정적 agents.json만 사용됩니다.")


class MatchScore(Enum):
    """매칭 점수 레벨"""
    PERFECT = 1.0      # 완벽한 매치
    EXCELLENT = 0.8    # 매우 적합
    GOOD = 0.6         # 적합
    FAIR = 0.4         # 보통
    POOR = 0.2         # 부적합
    NO_MATCH = 0.0     # 매치 없음


@dataclass
class CapabilityMatch:
    """능력 매칭 결과"""
    capability_id: str
    name: str
    description: str
    score: float
    reason: str


@dataclass
class AgentMatchResult:
    """에이전트 매칭 결과"""
    agent_id: str
    agent_name: str
    overall_score: float
    capability_matches: List[CapabilityMatch]
    reasons: List[str]
    can_handle: bool
    confidence: float


class RequestAnalyzer:
    """사용자 요청 분석기"""

    def __init__(self):
        # 산술 표현식 패턴 (숫자 + 연산자 + 숫자)
        self.arithmetic_pattern = re.compile(
            r'(\d+\.?\d*)\s*([+\-*/×÷])\s*(\d+\.?\d*)'  # 1+1, 2*3, 10/5, 100-50
        )
        # 확장된 수학 패턴
        self.math_patterns = [
            re.compile(r'(\d+)\s*[+\-*/×÷]\s*(\d+)'),  # 기본 연산
            re.compile(r'(\d+)\s*(더하기|빼기|곱하기|나누기)\s*(\d+)'),  # 한국어 연산
            re.compile(r'(\d+)\s*(플러스|마이너스|곱|나눈)\s*(\d+)'),  # 한국어 변형
            re.compile(r'(\d+)\s*과\s*(\d+)\s*(더|빼|곱|나눈)'),  # "5과 3 더해"
            re.compile(r'(\d+)\s*[은는]?\s*[얼마몇]'),  # "1+1은 얼마"
        ]

        # 도메인별 키워드 매핑
        self.domain_keywords = {
            "code_generation": [
                "코드", "프로그램", "구현", "개발", "스크립트", "함수", "클래스", "API", 
                "웹서버", "데이터베이스", "알고리즘", "python", "javascript", "java",
                "코드를", "만들어", "구현해", "작성해", "프로그래밍", "코딩"
            ],
            "document_search": [
                "검색", "찾아", "문서", "자료", "정보", "논문", "PDF", "파일", "문서에서",
                "찾아줘", "검색해", "알려줘", "조회", "탐색", "리서치", "pdf에서", "문서에서 찾아",
                "박사 과정", "학위 논문", "연구 자료", "참고 문헌", "보고서", "데이터셋"
            ],
            "mathematical_analysis": [
                "수학", "계산", "방정식", "적분", "미분", "확률", "통계", "공식", "증명",
                "수치해석", "행렬", "벡터", "대수", "기하", "삼각함수", "로그", "지수",
                "계산해", "풀어", "구해", "답을 구해", "수학 문제"
            ],
            "text_analysis": [
                "분석", "해석", "평가", "리뷰", "검토", "요약", "정리", "감정분석",
                "분석해", "해석해", "평가해", "요약해", "설명해", "텍스트 분석"
            ],
            "generation": [
                "생성", "만들어", "작성", "창작", "제작", "디자인",
                "생성해", "만들어줘", "작성해줘", "그려줘", "디자인해"
            ],
            "communication": [
                "이메일", "메시지", "알림", "전송", "보내", "발송",
                "이메일 보내", "메시지 전송", "알림 발송"
            ],
            "image": [
                "이미지", "그림", "사진", "그래프", "차트", "시각화",
                "이미지 생성", "그림 그려", "차트 만들어"
            ],
            "web": [
                "웹", "사이트", "브라우저", "URL", "인터넷", "온라인",
                "웹사이트", "홈페이지", "웹페이지", "브라우징"
            ]
        }
        
        # 부정 키워드 (할 수 없는 것들)
        self.negative_keywords = {
            "cannot_do": ["못해", "안돼", "불가능", "할 수 없어", "지원하지 않는"]
        }
    
    async def analyze_request(self, request: str) -> Dict[str, Any]:
        """
        사용자 요청을 분석하여 의도와 도메인을 파악
        
        Args:
            request: 사용자 요청 문자열
            
        Returns:
            분석 결과 딕셔너리
        """
        try:
            request_lower = request.lower()

            # 0. 산술 표현식 감지 (키워드 분석 전에 먼저 수행)
            is_arithmetic, arithmetic_info = self._detect_arithmetic_expression(request)

            # 1. 도메인 분석
            domain_scores = {}
            for domain, keywords in self.domain_keywords.items():
                score = 0
                matched_keywords = []

                for keyword in keywords:
                    if keyword in request_lower:
                        score += 1
                        matched_keywords.append(keyword)

                if score > 0:
                    # 정규화 (키워드 수로 나누기)
                    domain_scores[domain] = {
                        "score": score / len(keywords),
                        "matched_keywords": matched_keywords,
                        "raw_score": score
                    }

            # 산술 표현식이 감지되면 mathematical_analysis 도메인에 높은 점수 부여
            if is_arithmetic:
                existing_score = domain_scores.get("mathematical_analysis", {}).get("score", 0)
                domain_scores["mathematical_analysis"] = {
                    "score": max(0.8, existing_score),  # 최소 0.8점 보장
                    "matched_keywords": arithmetic_info.get("matched_patterns", ["arithmetic_expression"]),
                    "raw_score": 5,  # 높은 raw_score
                    "is_arithmetic": True,
                    "expression": arithmetic_info.get("expression", "")
                }
                logger.info(f"🔢 산술 표현식 감지: {arithmetic_info.get('expression', request)}")
            
            # 2. 의도 분석
            intent = self._analyze_intent(request_lower)
            
            # 3. 언어 감지
            language = self._detect_language(request)
            
            # 4. 복잡도 분석
            complexity = self._analyze_complexity(request)
            
            # 5. 긴급도 분석
            urgency = self._analyze_urgency(request_lower)
            
            return {
                "original_request": request,
                "domains": domain_scores,
                "intent": intent,
                "language": language,
                "complexity": complexity,
                "urgency": urgency,
                "keywords": self._extract_keywords(request),
                "primary_domain": max(domain_scores.keys(), key=lambda x: domain_scores[x]["score"]) if domain_scores else "general"
            }
            
        except Exception as e:
            logger.error(f"요청 분석 중 오류: {str(e)}")
            return {
                "original_request": request,
                "domains": {},
                "intent": "unknown",
                "language": "auto",
                "complexity": "medium",
                "urgency": "normal",
                "keywords": [],
                "primary_domain": "general"
            }

    def _detect_arithmetic_expression(self, request: str) -> tuple:
        """
        산술 표현식 감지

        Args:
            request: 사용자 요청 문자열

        Returns:
            (감지 여부, 감지 정보 딕셔너리)
        """
        matched_patterns = []
        expression = None

        # 1. 기본 산술 표현식 패턴 검사 (1+1, 2*3, 10/5, 100-50)
        arithmetic_match = self.arithmetic_pattern.search(request)
        if arithmetic_match:
            matched_patterns.append(f"{arithmetic_match.group(1)}{arithmetic_match.group(2)}{arithmetic_match.group(3)}")
            expression = arithmetic_match.group(0)

        # 2. 확장 수학 패턴 검사
        for pattern in self.math_patterns:
            if pattern.search(request):
                match = pattern.search(request)
                matched_patterns.append(match.group(0))
                if not expression:
                    expression = match.group(0)

        # 3. 숫자가 포함된 간단한 질문 ("2+2는?", "123*456은?")
        simple_arithmetic = re.search(r'(\d+)\s*[+\-*/×÷]\s*(\d+)\s*[은는]?[\?？얼마뭐몇]?', request)
        if simple_arithmetic:
            matched_patterns.append("simple_arithmetic")
            if not expression:
                expression = simple_arithmetic.group(0)

        is_arithmetic = len(matched_patterns) > 0

        return is_arithmetic, {
            "matched_patterns": matched_patterns,
            "expression": expression,
            "pattern_count": len(matched_patterns)
        }

    def _analyze_intent(self, request: str) -> str:
        """의도 분석"""
        # 먼저 산술 표현식 확인 (키워드보다 우선)
        is_arithmetic, _ = self._detect_arithmetic_expression(request)
        if is_arithmetic:
            return "mathematical_analysis"

        intent_patterns = {
            "create": ["만들어", "생성", "작성", "구현", "개발"],
            "document_search": ["찾아", "검색", "알려", "조회", "pdf에서", "문서에서"],
            "mathematical_analysis": ["계산", "풀어", "구해", "수학"],
            "text_analysis": ["분석", "해석", "평가", "검토", "요약"],
            "modify": ["수정", "변경", "업데이트", "개선"],
            "delete": ["삭제", "제거", "지워"],
            "help": ["도움", "도와", "가이드", "설명"]
        }

        for intent, patterns in intent_patterns.items():
            if any(pattern in request for pattern in patterns):
                return intent

        return "general"
    
    def _detect_language(self, text: str) -> str:
        """언어 감지"""
        korean_pattern = re.compile(r'[가-힣]')
        english_pattern = re.compile(r'[a-zA-Z]')
        
        korean_count = len(korean_pattern.findall(text))
        english_count = len(english_pattern.findall(text))
        
        if korean_count > english_count:
            return "korean"
        elif english_count > korean_count:
            return "english"
        else:
            return "mixed"
    
    def _analyze_complexity(self, request: str) -> str:
        """복잡도 분석"""
        # 단어 수, 기술적 용어, 조건문 등을 기반으로 복잡도 판단
        word_count = len(request.split())
        
        technical_terms = ["API", "데이터베이스", "알고리즘", "아키텍처", "프레임워크", "라이브러리"]
        tech_count = sum(1 for term in technical_terms if term in request)
        
        if word_count > 50 or tech_count > 3:
            return "high"
        elif word_count > 20 or tech_count > 1:
            return "medium"
        else:
            return "low"
    
    def _analyze_urgency(self, request: str) -> str:
        """긴급도 분석"""
        urgent_keywords = ["긴급", "급해", "빨리", "즉시", "지금", "당장"]
        
        if any(keyword in request for keyword in urgent_keywords):
            return "high"
        else:
            return "normal"
    
    def _extract_keywords(self, text: str) -> List[str]:
        """키워드 추출"""
        # 간단한 키워드 추출 (실제로는 더 정교한 NLP 기법 사용 가능)
        words = re.findall(r'\w+', text.lower())
        
        # 불용어 제거
        stopwords = {"을", "를", "이", "가", "에", "의", "와", "과", "에서", "으로", "로", "에게", "한테"}
        keywords = [word for word in words if len(word) > 1 and word not in stopwords]
        
        return list(set(keywords))  # 중복 제거


class AgentCompatibilityChecker:
    """에이전트 호환성 검사기"""
    
    def __init__(self, use_dynamic_capabilities: bool = True):
        self.request_analyzer = RequestAnalyzer()
        self.use_dynamic_capabilities = use_dynamic_capabilities and DYNAMIC_CAPABILITY_AVAILABLE
        self.capability_managers = {}  # agent_id -> DynamicCapabilityManager
    
    async def check_agent_compatibility(self, 
                                      request: str, 
                                      agent_data: Dict[str, Any],
                                      analysis_result: Dict[str, Any] = None) -> AgentMatchResult:
        """
        특정 에이전트가 요청을 처리할 수 있는지 확인
        
        Args:
            request: 사용자 요청
            agent_data: 에이전트 정보 (agents.json에서 가져온 데이터)
            analysis_result: 이미 분석된 요청 정보 (선택적)
            
        Returns:
            AgentMatchResult: 매칭 결과
        """
        try:
            # 요청 분석 (캐시된 결과가 있으면 사용)
            if analysis_result is None:
                analysis_result = await self.request_analyzer.analyze_request(request)
            
            agent_id = agent_data.get("agent_id", "")
            agent_name = agent_data.get("name", agent_id or "Unnamed Agent")
            
            # 동적 능력 데이터 가져오기
            dynamic_performance = await self._get_dynamic_performance(agent_id)
            
            # 1. 능력 기반 매칭 (동적 데이터 활용)
            capability_matches = self._match_capabilities(analysis_result, agent_data.get("capabilities", []))
            
            # 2. 태그 기반 매칭
            tag_score = self._match_tags(analysis_result, agent_data.get("tags", []))
            
            # 3. 예시 기반 매칭
            example_score = self._match_examples(analysis_result, agent_data.get("examples", []))
            
            # 4. 메타데이터 기반 매칭
            metadata_score = self._match_metadata(analysis_result, agent_data.get("metadata", {}))
            
            # 5. 동적 성능 점수 계산
            dynamic_score = self._calculate_dynamic_score(analysis_result, dynamic_performance)
            
            # 6. 전체 점수 계산 (동적 데이터 가중치 조정)
            capability_avg = sum(match.score for match in capability_matches) / len(capability_matches) if capability_matches else 0
            
            # 동적 데이터가 있지만 성능이 매우 낮은 경우 (0.0) 기존 방식으로 폴백
            use_static_fallback = False
            if (self.use_dynamic_capabilities and dynamic_performance and 
                dynamic_performance.get("overall_performance", 0) == 0.0 and
                dynamic_performance.get("confidence_level", 0) == 0.0):
                use_static_fallback = True
                logger.debug(f"에이전트 {agent_id}: 동적 데이터가 비어있어 정적 평가로 폴백")
            
            if self.use_dynamic_capabilities and dynamic_performance and not use_static_fallback:
                # 동적 데이터가 있으면 더 높은 가중치 부여
                overall_score = (
                    capability_avg * 0.25 +    # 정적 능력 매칭
                    tag_score * 0.2 +          # 태그 매칭
                    example_score * 0.15 +     # 예시 매칭
                    metadata_score * 0.1 +     # 메타데이터 매칭
                    dynamic_score * 0.3        # 동적 성능 데이터 (가장 중요)
                )
                confidence = dynamic_performance.get("confidence_level", 0.5) * overall_score
            else:
                # 기존 방식 (동적 데이터 없거나 폴백)
                overall_score = (
                    capability_avg * 0.4 +  # 능력 매칭이 가장 중요
                    tag_score * 0.3 +       # 태그 매칭
                    example_score * 0.2 +   # 예시 매칭
                    metadata_score * 0.1    # 메타데이터 매칭
                )
                confidence = overall_score
            
            # 🎯 특별 도메인 처리: RAG/PDF 검색 최적화
            domain_boost = 0.0
            domain_reason = ""
            
            # RAG/문서검색 도메인 감지
            rag_keywords = ["pdf", "문서", "검색", "찾아", "rag", "retrieval", "document", "paper", "논문", "연구", "파일"]
            query_lower = request.lower()
            rag_matches = sum(1 for keyword in rag_keywords if keyword in query_lower)
            
            if agent_id == "rag_agent" and rag_matches > 0:
                # RAG 에이전트에게 도메인 특화 보너스 제공
                domain_boost = min(0.4, rag_matches * 0.15)  # 최대 0.4 보너스
                domain_reason = f"RAG 도메인 특화 보너스 +{domain_boost:.2f} (키워드 {rag_matches}개 매칭)"
                overall_score += domain_boost
                confidence = min(1.0, confidence + domain_boost)
                logger.info(f"🎯 에이전트 {agent_id}: {domain_reason}, 조정된 점수: {overall_score:.3f}")
            
            # 7. 처리 가능 여부 판단 (동적 데이터 + 도메인 고려)
            threshold = 0.3
            
            # RAG 도메인의 경우 더 관대한 임계값 적용
            if agent_id == "rag_agent" and rag_matches > 0:
                threshold = 0.2  # RAG 전문 에이전트는 낮은 임계값
                logger.debug(f"📋 RAG 도메인 감지로 임계값 완화: {threshold}")
            if dynamic_performance:
                # 실제 성능이 좋으면 임계값 낮춤
                if dynamic_performance.get("overall_performance", 0) > 0.7:
                    threshold = 0.25
                elif dynamic_performance.get("overall_performance", 0) < 0.4:
                    threshold = 0.4  # 성능이 낮으면 임계값 높임
            
            can_handle = overall_score >= threshold
            
            # 8. 이유 생성 (동적 데이터 + 도메인 특화 정보 포함)
            reasons = self._generate_reasons_with_dynamic(
                capability_matches, tag_score, example_score, overall_score, 
                dynamic_performance if not use_static_fallback else None,
                domain_reason=domain_reason if domain_boost > 0 else None
            )
            
            return AgentMatchResult(
                agent_id=agent_id,
                agent_name=agent_name,
                overall_score=overall_score,
                capability_matches=capability_matches,
                reasons=reasons,
                can_handle=can_handle,
                confidence=confidence
            )
            
        except Exception as e:
            logger.error(f"에이전트 호환성 검사 중 오류: {str(e)}")
            return AgentMatchResult(
                agent_id=agent_data.get("agent_id", ""),
                agent_name=agent_data.get("name", "Error Agent"),
                overall_score=0.0,
                capability_matches=[],
                reasons=[f"호환성 검사 중 오류 발생: {str(e)}"],
                can_handle=False,
                confidence=0.0
            )
    
    def _match_capabilities(self, analysis: Dict[str, Any], capabilities: List[Dict[str, Any]]) -> List[CapabilityMatch]:
        """능력과 요청 매칭"""
        matches = []
        
        for cap in capabilities:
            cap_id = cap.get("id", "")
            cap_name = cap.get("name", "")
            cap_desc = cap.get("description", "")
            
            # 키워드 매칭
            score = 0.0
            reasons = []
            
            # 요청 키워드와 능력 설명 매칭
            request_keywords = analysis.get("keywords", [])
            cap_text = f"{cap_name} {cap_desc}".lower()
            
            matched_keywords = []
            for keyword in request_keywords:
                if keyword in cap_text:
                    score += 0.1
                    matched_keywords.append(keyword)
            
            # 도메인 매칭
            primary_domain = analysis.get("primary_domain", "")
            if primary_domain and primary_domain in cap_text:
                score += 0.3
                reasons.append(f"도메인 매칭: {primary_domain}")
            
            # 의도 매칭
            intent = analysis.get("intent", "")
            if intent and intent in cap_text:
                score += 0.2
                reasons.append(f"의도 매칭: {intent}")
            
            if matched_keywords:
                reasons.append(f"키워드 매칭: {', '.join(matched_keywords)}")
            
            # 점수 정규화
            score = min(score, 1.0)
            
            if score > 0:
                matches.append(CapabilityMatch(
                    capability_id=cap_id,
                    name=cap_name,
                    description=cap_desc,
                    score=score,
                    reason="; ".join(reasons) if reasons else "부분적 매칭"
                ))
        
        return sorted(matches, key=lambda x: x.score, reverse=True)
    
    def _match_tags(self, analysis: Dict[str, Any], tags: List[str]) -> float:
        """태그 매칭"""
        if not tags:
            return 0.0
        
        request_keywords = analysis.get("keywords", [])
        tag_text = " ".join(tags).lower()
        
        matches = sum(1 for keyword in request_keywords if keyword in tag_text)
        return min(matches / len(tags), 1.0) if tags else 0.0
    
    def _match_examples(self, analysis: Dict[str, Any], examples: List[str]) -> float:
        """예시 매칭"""
        if not examples:
            return 0.0
        
        request_keywords = analysis.get("keywords", [])
        example_text = " ".join(examples).lower()
        
        matches = sum(1 for keyword in request_keywords if keyword in example_text)
        return min(matches / len(request_keywords), 1.0) if request_keywords else 0.0
    
    def _match_metadata(self, analysis: Dict[str, Any], metadata: Dict[str, Any]) -> float:
        """메타데이터 매칭"""
        if not metadata:
            return 0.0

        score = 0.0

        # 도메인 → 에이전트 타입 매핑
        domain_to_agent_types = {
            "mathematical_analysis": ["calculator", "math", "calculation", "arithmetic"],
            "code_generation": ["code_generation", "code", "programming", "developer"],
            "document_search": ["rag", "search", "retrieval", "document"],
            "text_analysis": ["analysis", "text", "nlp", "sentiment"],
            "generation": ["generation", "creative", "content"],
            "communication": ["communication", "email", "message"],
            "image": ["image", "visual", "chart", "visualization"],
            "web": ["web", "internet", "browser", "search"]
        }

        # 에이전트 타입 매칭
        agent_type = metadata.get("agent_type", "").lower()
        primary_domain = analysis.get("primary_domain", "")

        # 직접 매칭
        if primary_domain and primary_domain in agent_type:
            score += 0.5
        # 도메인-타입 매핑을 통한 매칭
        elif primary_domain in domain_to_agent_types:
            matching_types = domain_to_agent_types[primary_domain]
            if any(t in agent_type for t in matching_types):
                score += 0.5
                logger.debug(f"도메인-타입 매핑 매치: {primary_domain} → {agent_type}")
        
        # 전문 분야 매칭
        specializations = metadata.get("specializations", [])
        if specializations:
            spec_text = " ".join(specializations).lower()
            request_keywords = analysis.get("keywords", [])
            matches = sum(1 for keyword in request_keywords if keyword in spec_text)
            score += min(matches / len(specializations), 0.5)
        
        return min(score, 1.0)
    
    def _generate_reasons(self, capability_matches: List[CapabilityMatch], 
                         tag_score: float, example_score: float, overall_score: float) -> List[str]:
        """매칭 이유 생성"""
        reasons = []
        
        if capability_matches:
            best_match = capability_matches[0]
            reasons.append(f"가장 적합한 능력: {best_match.name} (점수: {best_match.score:.2f})")
        
        if tag_score > 0.3:
            reasons.append(f"태그 매칭도 양호 (점수: {tag_score:.2f})")
        
        if example_score > 0.3:
            reasons.append(f"사용 예시와 유사 (점수: {example_score:.2f})")
        
        if overall_score >= 0.8:
            reasons.append("매우 높은 호환성")
        elif overall_score >= 0.6:
            reasons.append("높은 호환성")
        elif overall_score >= 0.4:
            reasons.append("보통 호환성")
        elif overall_score >= 0.2:
            reasons.append("낮은 호환성")
        else:
            reasons.append("호환성 부족")
        
        return reasons
    
    async def _get_dynamic_performance(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """에이전트의 동적 성능 데이터 가져오기"""
        if not self.use_dynamic_capabilities:
            return None
        
        try:
            if agent_id not in self.capability_managers:
                self.capability_managers[agent_id] = DynamicCapabilityManager(agent_id)
            
            manager = self.capability_managers[agent_id]
            return manager.get_capability_summary()
            
        except Exception as e:
            logger.warning(f"에이전트 {agent_id}의 동적 성능 데이터 로드 실패: {e}")
            return None
    
    def _calculate_dynamic_score(self, analysis: Dict[str, Any], 
                               dynamic_performance: Optional[Dict[str, Any]]) -> float:
        """동적 성능 데이터 기반 점수 계산"""
        if not dynamic_performance:
            return 0.0
        
        # 요청 도메인에 해당하는 성능 찾기
        primary_domain = analysis.get("primary_domain", "")
        capabilities = dynamic_performance.get("capabilities", {})
        
        best_score = 0.0
        
        # 정확한 도메인 매칭
        domain_mapping = {
            "code_generation": ["code_generation", "programming"],
            "document_search": ["information_search", "document_search", "search", "rag"],
            "mathematical_analysis": ["math", "calculation", "analysis", "mathematical"],
            "text_analysis": ["text_analysis", "data_analysis", "analysis"],
            "communication": ["communication", "email"],
            "generation": ["content_generation", "creative"],
            "web": ["web_search", "internet_search", "web"],
            "image": ["image_generation", "image_processing"]
        }
        
        mapped_domains = domain_mapping.get(primary_domain, [primary_domain])
        
        for domain in mapped_domains:
            if domain in capabilities:
                metric = capabilities[domain]
                # 성공률, 품질, 만족도를 종합한 점수
                domain_score = (
                    metric.get("success_rate", 0) * 0.4 +
                    metric.get("quality_score", 0) * 0.3 +
                    metric.get("user_satisfaction", 0) * 0.3
                )
                best_score = max(best_score, domain_score)
        
        # 전체 성능도 고려
        overall_performance = dynamic_performance.get("overall_performance", 0)
        
        # 도메인별 점수와 전체 성능의 가중 평균
        final_score = best_score * 0.7 + overall_performance * 0.3
        
        return min(final_score, 1.0)
    
    def _generate_reasons_with_dynamic(self, capability_matches: List[CapabilityMatch], 
                                     tag_score: float, example_score: float, overall_score: float,
                                     dynamic_performance: Optional[Dict[str, Any]],
                                     domain_reason: Optional[str] = None) -> List[str]:
        """동적 데이터를 포함한 매칭 이유 생성"""
        reasons = []
        
        # 🎯 도메인 특화 이유 최우선 표시
        if domain_reason:
            reasons.append(f"🎯 {domain_reason}")
        
        # 기본 이유들
        if capability_matches:
            best_match = capability_matches[0]
            reasons.append(f"가장 적합한 능력: {best_match.name} (점수: {best_match.score:.2f})")
        
        if tag_score > 0.3:
            reasons.append(f"태그 매칭도 양호 (점수: {tag_score:.2f})")
        
        if example_score > 0.3:
            reasons.append(f"사용 예시와 유사 (점수: {example_score:.2f})")
        
        # 동적 성능 데이터 기반 이유
        if dynamic_performance:
            overall_perf = dynamic_performance.get("overall_performance", 0)
            confidence = dynamic_performance.get("confidence_level", 0)
            assessment_count = dynamic_performance.get("assessment_count", 0)
            
            if overall_perf > 0.8:
                reasons.append(f"📊 실제 성능: 우수 ({overall_perf:.1%})")
            elif overall_perf > 0.6:
                reasons.append(f"📊 실제 성능: 양호 ({overall_perf:.1%})")
            elif overall_perf < 0.4:
                reasons.append(f"📊 실제 성능: 부족 ({overall_perf:.1%})")
            
            if confidence > 0.7:
                reasons.append(f"🔍 신뢰도: 높음 ({confidence:.1%}, 평가 {assessment_count}회)")
            elif confidence < 0.3:
                reasons.append(f"⚠️ 신뢰도: 낮음 ({confidence:.1%}) - 추가 검증 필요")
            
            # 도메인별 상세 성능
            capabilities = dynamic_performance.get("capabilities", {})
            if capabilities:
                best_domain = max(capabilities.items(), key=lambda x: x[1].get("success_rate", 0))
                domain_name, domain_perf = best_domain
                success_rate = domain_perf.get("success_rate", 0)
                if success_rate > 0.8:
                    reasons.append(f"💯 {domain_name} 영역: {success_rate:.1%} 성공률")
        else:
            reasons.append("실제 성능 데이터 없음 - 정적 정보만 기반으로 평가")
        
        # 전체 점수 기반 평가 (개선된 메시지)
        if overall_score >= 0.8:
            reasons.append("✅ 매우 높은 호환성 - 최적의 선택")
        elif overall_score >= 0.6:
            reasons.append("✅ 높은 호환성 - 권장")
        elif overall_score >= 0.4:
            reasons.append("✅ 보통 호환성 - 처리 가능")
        elif overall_score >= 0.2:
            reasons.append("⚠️ 낮은 호환성 - 제한적 처리")
        else:
            reasons.append("❌ 호환성 부족 - 다른 에이전트 권장")
        
        # 종합 판정 메시지 추가
        if domain_reason:
            reasons.append(f"📈 도메인 특화 조정 완료 → 최종 점수: {overall_score:.1%}")
        else:
            reasons.append(f"📈 종합 평가 점수: {overall_score:.1%}")
        
        return reasons


class AgentSelector:
    """에이전트 선택기"""
    
    def __init__(self, use_dynamic_capabilities: bool = True):
        self.compatibility_checker = AgentCompatibilityChecker(use_dynamic_capabilities)
        self.request_analyzer = RequestAnalyzer()
        self.use_dynamic_capabilities = use_dynamic_capabilities

    async def _llm_enhanced_agent_selection(self, request: str, results: List) -> List:
        """LLM을 활용한 에이전트 선택 개선"""
        try:
            # LLM을 사용하여 요청의 진짜 의도 파악
            from logosai.utils.llm_client import LLMClient, LLMMessage
            
            llm_client = LLMClient(
                provider="google",
                model="gemini-2.5-flash-lite",
                temperature=0.3
            )
            
            # 에이전트 정보를 LLM에 제공
            agent_info = []
            for result in results[:10]:  # 상위 10개만
                agent_info.append(f"- {result.agent_name} (ID: {result.agent_id}): 점수 {result.overall_score:.2f}")
            
            system_prompt = """당신은 사용자 요청을 분석하여 가장 적합한 AI 에이전트를 선택하는 전문가입니다.

🎯 **도메인별 에이전트 선택 가이드**:

**📄 문서/PDF 검색 도메인 (최우선 정확도):**
- PDF, 문서, 논문, 연구, 보고서, 파일에서 정보 찾기
- 박사과정, 연구자, 학술 자료 관련 검색
- ESG, 기업 보고서, 기술 문서 분석
- → **rag_agent 강력 추천** (문서 검색 전문)

**🔢 수학/계산 도메인:**
- 방정식, 수식, 계산, 수학 문제
- → math_agent 선택

**💻 코드/프로그래밍 도메인:**
- 코드 작성, 프로그래밍, 개발
- → code_agent 선택

**🌐 웹 검색 도메인:**
- 실시간 정보, 최신 뉴스, 인터넷 검색
- → web_search_agent 선택

**🎨 기타 도메인:**
- 이미지 생성, 창작, 일반 대화
- → 적절한 전문 에이전트 선택

**판단 기준:**
1. 요청의 핵심 의도 파악 (키워드보다 의미 중시)
2. 도메인 적합성 (전문성이 가장 중요)
3. 처리 효율성 (최적의 결과 보장)

응답 형식: 선택한 에이전트 ID와 선택 이유를 명확히 제시
예: "rag_agent|PDF 문서 검색 전문성\""""
            
            user_prompt = f"""
사용자 요청: {request}

사용 가능한 에이전트들 (점수순):
{chr(10).join(agent_info)}

위 요청에 가장 적합한 에이전트 ID를 하나만 선택해주세요.
"""
            
            messages = [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt)
            ]
            
            response = await llm_client.invoke_messages(messages)
            llm_response = response.content.strip()
            
            # 🧠 LLM 응답 파싱 (새로운 형식: "agent_id|이유")
            recommended_agent_id = None
            llm_reason = "LLM 추천"
            
            if "|" in llm_response:
                parts = llm_response.split("|", 1)
                recommended_agent_id = parts[0].strip()
                llm_reason = parts[1].strip()
            else:
                recommended_agent_id = llm_response.strip()
            
            # LLM이 추천하지 않거나 잘못된 응답인 경우 처리
            if not recommended_agent_id or recommended_agent_id.lower() in ["none", "unknown", "unknown agent", ""]:
                logger.info("LLM이 특정 에이전트를 추천하지 않음")
                return results
            
            logger.info(f"🧠 LLM 분석 결과: {recommended_agent_id} 추천 - {llm_reason}")
            
            # 🎯 동적 점수 부여 (도메인별 차등 적용)
            rag_domains = ["pdf", "문서", "검색", "찾아", "rag", "retrieval", "document", "논문", "연구"]
            query_lower = request.lower()
            is_rag_domain = any(keyword in query_lower for keyword in rag_domains)
            
            # LLM 추천을 반영하여 점수 조정
            for result in results:
                if result.agent_id == recommended_agent_id:
                    result.original_score = result.overall_score
                    
                    # 도메인별 차등 보너스
                    if recommended_agent_id == "rag_agent" and is_rag_domain:
                        bonus = 0.5  # RAG 도메인에서 RAG 에이전트 추천 시 높은 보너스
                        result.reasons.append(f"🎯 LLM 추천: {llm_reason} (RAG 도메인 특화 +{bonus})")
                    elif recommended_agent_id == "rag_agent":
                        bonus = 0.3  # 일반적인 RAG 에이전트 추천
                        result.reasons.append(f"🧠 LLM 추천: {llm_reason} (+{bonus})")
                    else:
                        bonus = 0.3  # 기본 LLM 추천 보너스
                        result.reasons.append(f"🧠 LLM 추천: {llm_reason} (+{bonus})")
                    
                    result.overall_score = min(result.overall_score + bonus, 1.0)
                    result.llm_recommended = True
                    result.llm_bonus = bonus
                    
                    logger.info(f"✅ {recommended_agent_id} 에이전트 점수 조정: {result.original_score:.3f} → {result.overall_score:.3f} (+{bonus})")
                    break
            else:
                logger.warning(f"⚠️ LLM 추천 에이전트 '{recommended_agent_id}'를 후보에서 찾을 수 없음")
            
            # 점수순으로 재정렬
            results.sort(key=lambda x: x.overall_score, reverse=True)
            
        except Exception as e:
            logger.warning(f"LLM 기반 에이전트 선택 실패: {e}")
        
        return results
    
    async def select_best_agents(self, 
                                request: str, 
                                agent_configs: List[Dict[str, Any]],
                                max_results: int = 3) -> List[AgentMatchResult]:
        """
        요청에 가장 적합한 에이전트들을 선택
        
        Args:
            request: 사용자 요청
            agent_configs: 에이전트 설정 리스트 (agents.json의 agents 부분)
            max_results: 최대 반환할 에이전트 수
            
        Returns:
            매칭 결과 리스트 (점수 순으로 정렬)
        """
        try:
            # 요청 분석 (한 번만 수행)
            analysis_result = await self.request_analyzer.analyze_request(request)
            logger.info(f"요청 분석 완료: 주요 도메인 = {analysis_result.get('primary_domain')}")
            
            # 모든 에이전트에 대해 호환성 검사
            match_results = []
            
            for agent_config in agent_configs:
                try:
                    match_result = await self.compatibility_checker.check_agent_compatibility(
                        request, agent_config, analysis_result
                    )
                    match_results.append(match_result)
                    
                    logger.debug(f"에이전트 {match_result.agent_id} 매칭 점수: {match_result.overall_score:.2f}")
                    
                except Exception as e:
                    logger.error(f"에이전트 {agent_config.get('agent_id')} 호환성 검사 실패: {str(e)}")
                    continue
            
            # 점수순으로 정렬
            sorted_results = sorted(match_results, key=lambda x: x.overall_score, reverse=True)
            
            # LLM 기반 선택 개선 적용
            enhanced_results = await self._llm_enhanced_agent_selection(request, sorted_results)
            
            # 상위 결과만 반환
            top_results = enhanced_results[:max_results]
            
            logger.info(f"에이전트 선택 완료: {len(top_results)}개 에이전트 선택됨")
            for result in top_results:
                llm_note = " (LLM 추천)" if hasattr(result, 'llm_recommended') and result.llm_recommended else ""
                logger.info(f"  - {result.agent_name} (ID: {result.agent_id}): {result.overall_score:.2f}{llm_note}")
            
            return top_results
            
        except Exception as e:
            logger.error(f"에이전트 선택 중 오류: {str(e)}")
            return []
    
    async def should_agent_handle_request(self, 
                                        request: str, 
                                        agent_config: Dict[str, Any],
                                        threshold: float = 0.3) -> Tuple[bool, str, float]:
        """
        특정 에이전트가 요청을 처리해야 하는지 판단
        
        Args:
            request: 사용자 요청
            agent_config: 에이전트 설정
            threshold: 처리 가능 판단 임계값
            
        Returns:
            (처리 가능 여부, 이유, 신뢰도)
        """
        try:
            match_result = await self.compatibility_checker.check_agent_compatibility(request, agent_config)
            
            should_handle = match_result.overall_score >= threshold
            # 이유를 더 읽기 쉽게 포맷팅
            if len(match_result.reasons) > 3:
                # 여러 이유가 있을 때는 줄바꿈으로 구분
                reason = "\n    • " + "\n    • ".join(match_result.reasons)
            else:
                # 적은 이유는 세미콜론으로 구분
                reason = " | ".join(match_result.reasons)
            confidence = match_result.confidence
            
            return should_handle, reason, confidence
            
        except Exception as e:
            logger.error(f"에이전트 처리 가능성 판단 중 오류: {str(e)}")
            return False, f"판단 중 오류 발생: {str(e)}", 0.0
    
    async def update_agent_performance(self, agent_id: str, request: str, 
                                     success: bool, execution_time: float,
                                     user_satisfaction: float = None):
        """실사용 기반 에이전트 성능 업데이트"""
        if not self.use_dynamic_capabilities:
            return
        
        try:
            # 요청 분석으로 태스크 타입 결정
            analysis = await self.request_analyzer.analyze_request(request)
            task_type = analysis.get("primary_domain", "general")
            
            # 동적 능력 관리자 가져오기
            if agent_id not in self.compatibility_checker.capability_managers:
                self.compatibility_checker.capability_managers[agent_id] = DynamicCapabilityManager(agent_id)
            
            manager = self.compatibility_checker.capability_managers[agent_id]
            
            # 성능 업데이트
            await manager.update_capability_from_usage(
                task_type=task_type,
                success=success,
                execution_time=execution_time,
                user_satisfaction=user_satisfaction
            )
            
            logger.info(f"에이전트 {agent_id} 성능 업데이트: {task_type} - 성공: {success}")
            
        except Exception as e:
            logger.error(f"에이전트 성능 업데이트 실패: {e}")
    
    async def trigger_agent_assessment(self, agent_id: str, agent_instance) -> Dict[str, Any]:
        """에이전트 자가 진단 트리거"""
        if not self.use_dynamic_capabilities:
            return {"error": "동적 능력 관리 시스템이 비활성화되어 있습니다"}
        
        try:
            if agent_id not in self.compatibility_checker.capability_managers:
                self.compatibility_checker.capability_managers[agent_id] = DynamicCapabilityManager(agent_id)
            
            manager = self.compatibility_checker.capability_managers[agent_id]
            
            # 재평가가 필요한지 확인
            if manager.should_run_assessment():
                logger.info(f"에이전트 {agent_id} 자가 진단 시작")
                return await manager.run_self_assessment(agent_instance)
            else:
                logger.info(f"에이전트 {agent_id} 재평가 불필요")
                return {"message": "재평가가 필요하지 않습니다", "current_performance": manager.get_capability_summary()}
                
        except Exception as e:
            logger.error(f"에이전트 자가 진단 실패: {e}")
            return {"error": f"자가 진단 실패: {str(e)}"}


class AgentRouter:
    """에이전트 라우터 - 요청을 적절한 에이전트로 라우팅"""
    
    def __init__(self, agent_configs: List[Dict[str, Any]]):
        self.agent_configs = agent_configs
        self.agent_selector = AgentSelector()
        self._create_agent_index()
    
    def _create_agent_index(self):
        """에이전트 인덱스 생성 (빠른 조회를 위해)"""
        self.agent_index = {config["agent_id"]: config for config in self.agent_configs}
        logger.info(f"에이전트 라우터 초기화: {len(self.agent_index)}개 에이전트 등록됨")
    
    async def route_request(self, 
                          request: str, 
                          preferred_agent_id: str = None) -> Dict[str, Any]:
        """
        요청을 적절한 에이전트로 라우팅
        
        Args:
            request: 사용자 요청
            preferred_agent_id: 선호하는 에이전트 ID (선택적)
            
        Returns:
            라우팅 결과
        """
        try:
            result = {
                "request": request,
                "timestamp": time.time(),
                "routing_successful": False,
                "selected_agent_id": None,
                "selected_agent_name": None,
                "confidence": 0.0,
                "alternatives": [],
                "reasons": []
            }
            
            # 1. 선호 에이전트가 지정된 경우 먼저 확인
            if preferred_agent_id and preferred_agent_id in self.agent_index:
                agent_config = self.agent_index[preferred_agent_id]
                should_handle, reason, confidence = await self.agent_selector.should_agent_handle_request(
                    request, agent_config
                )
                
                if should_handle:
                    result.update({
                        "routing_successful": True,
                        "selected_agent_id": preferred_agent_id,
                        "selected_agent_name": agent_config.get("name"),
                        "confidence": confidence,
                        "reasons": [f"선호 에이전트 사용 가능: {reason}"]
                    })
                    return result
                else:
                    result["reasons"].append(f"선호 에이전트 부적합: {reason}")
            
            # 2. 최적의 에이전트 선택
            top_agents = await self.agent_selector.select_best_agents(request, self.agent_configs, max_results=5)
            
            if top_agents and top_agents[0].can_handle:
                best_match = top_agents[0]
                result.update({
                    "routing_successful": True,
                    "selected_agent_id": best_match.agent_id,
                    "selected_agent_name": best_match.agent_name,
                    "confidence": best_match.confidence,
                    "reasons": best_match.reasons,
                    "alternatives": [
                        {
                            "agent_id": match.agent_id,
                            "agent_name": match.agent_name,
                            "score": match.overall_score,
                            "can_handle": match.can_handle
                        }
                        for match in top_agents[1:4]  # 상위 3개 대안
                    ]
                })
            else:
                result["reasons"].append("적합한 에이전트를 찾을 수 없습니다")
                if top_agents:
                    result["alternatives"] = [
                        {
                            "agent_id": match.agent_id,
                            "agent_name": match.agent_name,
                            "score": match.overall_score,
                            "can_handle": match.can_handle,
                            "reasons": match.reasons
                        }
                        for match in top_agents[:3]
                    ]
            
            return result
            
        except Exception as e:
            logger.error(f"요청 라우팅 중 오류: {str(e)}")
            return {
                "request": request,
                "routing_successful": False,
                "selected_agent_id": None,
                "selected_agent_name": None,
                "confidence": 0.0,
                "alternatives": [],
                "reasons": [f"라우팅 중 오류 발생: {str(e)}"]
            }


# 편의 함수들
async def analyze_user_request(request: str) -> Dict[str, Any]:
    """사용자 요청 분석 편의 함수"""
    analyzer = RequestAnalyzer()
    return await analyzer.analyze_request(request)


async def select_best_agent(request: str, agent_configs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """최적의 에이전트 선택 편의 함수"""
    selector = AgentSelector()
    results = await selector.select_best_agents(request, agent_configs, max_results=1)
    return results[0] if results and results[0].can_handle else None


async def check_agent_suitability(request: str, agent_config: Dict[str, Any]) -> Tuple[bool, str]:
    """에이전트 적합성 확인 편의 함수"""
    selector = AgentSelector()
    can_handle, reason, _ = await selector.should_agent_handle_request(request, agent_config)
    return can_handle, reason