"""
에이전트-매니저 협상 프로토콜

LogosAI framework의 핵심 특장점인 지능형 에이전트 협상 시스템입니다.
매니저와 에이전트가 실시간으로 대화하며 최적의 처리 방법을 찾아갑니다.
"""

import asyncio
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
from loguru import logger
import json
import time

from .agent_self_assessment import AgentSelfAssessment, SelfAssessmentResult, CapabilityLevel

class NegotiationAction(Enum):
    """협상 액션 타입"""
    ASSESS_REQUEST = "assess_request"           # 요청 평가
    ACCEPT_TASK = "accept_task"                 # 작업 수락
    DECLINE_TASK = "decline_task"               # 작업 거절
    SUGGEST_ALTERNATIVE = "suggest_alternative" # 대안 제안
    REQUEST_COLLABORATION = "request_collaboration" # 협력 요청
    NEGOTIATE_SCOPE = "negotiate_scope"         # 범위 협상
    REQUEST_CLARIFICATION = "request_clarification" # 명확화 요청
    PROVIDE_CAPABILITY = "provide_capability"  # 능력 제공
    HANDOFF_TASK = "handoff_task"              # 작업 이관
    PROPOSE_SUBTASK = "propose_subtask"         # 하위 작업 제안
    VOLUNTEER_FOR_TASK = "volunteer_for_task"  # 작업 자원
    NEGOTIATE_DECOMPOSITION = "negotiate_decomposition" # 작업 분해 협상

class NegotiationStatus(Enum):
    """협상 상태"""
    INITIATED = "initiated"         # 협상 시작
    IN_PROGRESS = "in_progress"     # 진행 중
    ACCEPTED = "accepted"           # 수락됨
    DECLINED = "declined"           # 거절됨
    HANDOFF = "handoff"            # 다른 에이전트로 이관
    COLLABORATIVE = "collaborative" # 협력 모드
    COMPLETED = "completed"         # 완료됨
    FAILED = "failed"              # 실패

@dataclass
class NegotiationMessage:
    """협상 메시지"""
    sender: str                    # 발신자 (manager 또는 agent_id)
    receiver: str                  # 수신자
    action: NegotiationAction      # 액션 타입
    content: str                   # 메시지 내용
    data: Dict[str, Any]          # 추가 데이터
    timestamp: float              # 타임스탬프
    conversation_id: str          # 대화 ID

@dataclass
class NegotiationSession:
    """협상 세션"""
    session_id: str
    user_request: str
    primary_agent_id: str
    manager_id: str
    status: NegotiationStatus
    messages: List[NegotiationMessage]
    assessment_results: Dict[str, SelfAssessmentResult]
    final_decision: Optional[Dict[str, Any]]
    start_time: float
    end_time: Optional[float]
    context: Dict[str, Any]

class AgentNegotiationProtocol:
    """에이전트 협상 프로토콜 구현"""
    
    def __init__(self, manager_id: str = "advanced_multi_agent_manager"):
        self.manager_id = manager_id
        self.active_sessions: Dict[str, NegotiationSession] = {}
        self.agent_assessments: Dict[str, AgentSelfAssessment] = {}
        self.conversation_counter = 0
        
    def register_agent_assessment(self, agent_id: str, assessment: AgentSelfAssessment):
        """에이전트 자기평가 시스템 등록"""
        self.agent_assessments[agent_id] = assessment
        logger.info(f"🤝 에이전트 {agent_id} 협상 프로토콜 등록 완료")
    
    async def initiate_negotiation(self, user_request: str, primary_agent_id: str, 
                                 context: Dict[str, Any] = None) -> str:
        """
        협상 세션 시작
        
        Args:
            user_request: 사용자 요청
            primary_agent_id: 1차 담당 에이전트
            context: 추가 컨텍스트
            
        Returns:
            session_id: 생성된 세션 ID
        """
        session_id = f"negotiation_{int(time.time())}_{self.conversation_counter}"
        self.conversation_counter += 1
        
        session = NegotiationSession(
            session_id=session_id,
            user_request=user_request,
            primary_agent_id=primary_agent_id,
            manager_id=self.manager_id,
            status=NegotiationStatus.INITIATED,
            messages=[],
            assessment_results={},
            final_decision=None,
            start_time=time.time(),
            end_time=None,
            context=context or {}
        )
        
        self.active_sessions[session_id] = session
        
        logger.info(f"🚀 협상 세션 시작: {session_id}")
        logger.info(f"   요청: '{user_request[:50]}...'")
        logger.info(f"   1차 에이전트: {primary_agent_id}")
        
        return session_id
    
    async def conduct_negotiation(self, session_id: str) -> Dict[str, Any]:
        """
        협상 실행 (매니저 관점)
        
        Args:
            session_id: 협상 세션 ID
            
        Returns:
            최종 협상 결과
        """
        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"협상 세션을 찾을 수 없음: {session_id}")
        
        try:
            session.status = NegotiationStatus.IN_PROGRESS
            
            # 1단계: 1차 에이전트와 협상
            logger.info(f"💬 1차 에이전트 {session.primary_agent_id}와 협상 시작")
            
            primary_result = await self._negotiate_with_agent(
                session, session.primary_agent_id
            )
            
            # 2단계: 결과에 따른 후속 처리
            if primary_result["accepted"]:
                logger.info(f"✅ {session.primary_agent_id}가 작업 수락")
                session.status = NegotiationStatus.ACCEPTED
                session.final_decision = {
                    "selected_agent": session.primary_agent_id,
                    "mode": "single_agent",
                    "reason": "1차 에이전트가 작업 수락",
                    "assessment": primary_result["assessment"]
                }
                
            elif primary_result.get("alternative_agents"):
                logger.info(f"🔄 {session.primary_agent_id}가 대안 에이전트 제안: {primary_result['alternative_agents']}")
                
                # 제안된 대안 에이전트들과 협상
                best_alternative = await self._negotiate_with_alternatives(
                    session, primary_result["alternative_agents"]
                )
                
                if best_alternative:
                    session.status = NegotiationStatus.HANDOFF
                    session.final_decision = {
                        "selected_agent": best_alternative["agent_id"],
                        "mode": "handoff",
                        "reason": f"{session.primary_agent_id}가 {best_alternative['agent_id']} 추천",
                        "assessment": best_alternative["assessment"],
                        "handoff_reason": primary_result.get("decline_reason", "더 적합한 에이전트 발견")
                    }
                else:
                    # 대안도 없으면 협력 모드 시도
                    collaborative_result = await self._attempt_collaborative_mode(session)
                    if collaborative_result:
                        session.status = NegotiationStatus.COLLABORATIVE
                        session.final_decision = collaborative_result
                    else:
                        session.status = NegotiationStatus.DECLINED
                        session.final_decision = {
                            "selected_agent": None,
                            "mode": "declined",
                            "reason": "적합한 에이전트를 찾을 수 없음"
                        }
            
            elif primary_result.get("collaborative_agents"):
                logger.info(f"🤝 {session.primary_agent_id}가 협력 모드 제안")
                collaborative_result = await self._setup_collaborative_mode(
                    session, primary_result["collaborative_agents"]
                )
                session.status = NegotiationStatus.COLLABORATIVE
                session.final_decision = collaborative_result
                
            else:
                logger.warning(f"❌ {session.primary_agent_id}가 작업 거절, 대안도 없음")
                session.status = NegotiationStatus.DECLINED
                session.final_decision = {
                    "selected_agent": None,
                    "mode": "declined", 
                    "reason": primary_result.get("decline_reason", "에이전트가 작업 거절")
                }
            
            session.end_time = time.time()
            session.status = NegotiationStatus.COMPLETED
            
            # 협상 결과 로깅
            duration = session.end_time - session.start_time
            logger.info(f"🎯 협상 완료 ({duration:.2f}s): {session.final_decision['mode']}")
            
            return session.final_decision
            
        except Exception as e:
            logger.error(f"❌ 협상 중 오류: {str(e)}")
            session.status = NegotiationStatus.FAILED
            session.end_time = time.time()
            return {
                "selected_agent": None,
                "mode": "failed",
                "reason": f"협상 실패: {str(e)}"
            }
    
    async def _negotiate_with_agent(self, session: NegotiationSession, 
                                  agent_id: str) -> Dict[str, Any]:
        """특정 에이전트와 협상"""
        if agent_id not in self.agent_assessments:
            logger.warning(f"⚠️ 에이전트 {agent_id}의 자기평가 시스템 없음")
            return {
                "accepted": False,
                "decline_reason": "자기평가 시스템 없음",
                "alternative_agents": [],
                "collaborative_agents": []
            }
        
        # 1. 매니저가 에이전트에게 요청 평가 요청
        await self._send_message(
            session, self.manager_id, agent_id,
            NegotiationAction.ASSESS_REQUEST,
            f"'{session.user_request}' 요청을 처리할 수 있는지 평가해주세요.",
            {"request": session.user_request, "context": session.context}
        )
        
        # 2. 에이전트 자기평가 수행
        assessment = self.agent_assessments[agent_id]
        assessment_result = await assessment.assess_request_compatibility(
            session.user_request, session.context
        )
        
        session.assessment_results[agent_id] = assessment_result
        
        # 3. 에이전트 응답 생성
        if assessment_result.can_handle:
            await self._send_message(
                session, agent_id, self.manager_id,
                NegotiationAction.ACCEPT_TASK,
                f"이 작업을 처리할 수 있습니다. 능력 수준: {assessment_result.capability_level.value} (확신도: {assessment_result.confidence_score:.2f})",
                {
                    "assessment": assessment_result.__dict__,
                    "estimated_success_rate": assessment_result.estimated_success_rate
                }
            )
            
            return {
                "accepted": True,
                "assessment": assessment_result,
                "agent_id": agent_id
            }
        else:
            decline_reason = "; ".join(assessment_result.reasoning)
            
            await self._send_message(
                session, agent_id, self.manager_id,
                NegotiationAction.DECLINE_TASK,
                f"이 작업은 제가 적합하지 않습니다. 이유: {decline_reason}",
                {
                    "assessment": assessment_result.__dict__,
                    "alternative_agents": assessment_result.alternative_agents,
                    "collaborative_agents": assessment_result.collaborative_agents
                }
            )
            
            return {
                "accepted": False,
                "decline_reason": decline_reason,
                "alternative_agents": assessment_result.alternative_agents,
                "collaborative_agents": assessment_result.collaborative_agents,
                "assessment": assessment_result
            }
    
    async def _negotiate_with_alternatives(self, session: NegotiationSession,
                                         alternative_agents: List[str]) -> Optional[Dict[str, Any]]:
        """대안 에이전트들과 협상"""
        logger.info(f"🔍 {len(alternative_agents)}개 대안 에이전트와 협상 시작")
        
        best_alternative = None
        best_score = 0.0
        
        for agent_id in alternative_agents:
            if agent_id == session.primary_agent_id:  # 이미 시도한 에이전트 제외
                continue
                
            logger.info(f"   🤔 {agent_id}와 협상 중...")
            
            result = await self._negotiate_with_agent(session, agent_id)
            
            if result["accepted"]:
                assessment = result["assessment"]
                if assessment.confidence_score > best_score:
                    best_score = assessment.confidence_score
                    best_alternative = result
                    
                # 높은 확신도면 즉시 선택
                if assessment.confidence_score > 0.8:
                    logger.info(f"   ✅ {agent_id} 높은 확신도로 즉시 선택")
                    break
        
        return best_alternative
    
    async def _attempt_collaborative_mode(self, session: NegotiationSession) -> Optional[Dict[str, Any]]:
        """협력 모드 시도"""
        logger.info("🤝 협력 모드 시도")
        
        # 모든 등록된 에이전트들의 부분적 기여도 평가
        collaborative_agents = []
        
        for agent_id, assessment_system in self.agent_assessments.items():
            if agent_id == session.primary_agent_id:
                continue
                
            assessment_result = await assessment_system.assess_request_compatibility(
                session.user_request, session.context
            )
            
            # 부분적으로라도 기여할 수 있는 에이전트들 수집
            if assessment_result.confidence_score > 0.3:  # 최소 기여도 임계값
                collaborative_agents.append({
                    "agent_id": agent_id,
                    "contribution_score": assessment_result.confidence_score,
                    "capabilities": assessment_result.reasoning
                })
        
        if len(collaborative_agents) >= 2:  # 최소 2개 이상의 에이전트 필요
            return {
                "selected_agent": "collaborative_workflow",
                "mode": "collaborative",
                "participating_agents": collaborative_agents,
                "reason": "여러 에이전트의 협력으로 더 나은 결과 기대"
            }
        
        return None
    
    async def _setup_collaborative_mode(self, session: NegotiationSession,
                                      suggested_agents: List[str]) -> Dict[str, Any]:
        """협력 모드 설정"""
        logger.info(f"🤝 협력 모드 설정: {suggested_agents}")
        
        collaborative_agents = [
            {
                "agent_id": session.primary_agent_id,
                "role": "primary",
                "assessment": session.assessment_results[session.primary_agent_id]
            }
        ]
        
        for agent_id in suggested_agents:
            if agent_id != session.primary_agent_id and agent_id in self.agent_assessments:
                assessment_result = await self.agent_assessments[agent_id].assess_request_compatibility(
                    session.user_request, session.context
                )
                collaborative_agents.append({
                    "agent_id": agent_id,
                    "role": "collaborative",
                    "assessment": assessment_result
                })
        
        return {
            "selected_agent": "collaborative_workflow",
            "mode": "collaborative",
            "participating_agents": collaborative_agents,
            "coordinator": session.primary_agent_id,
            "reason": "에이전트들이 협력하여 최적 결과 도출"
        }
    
    async def _send_message(self, session: NegotiationSession, sender: str, receiver: str,
                          action: NegotiationAction, content: str, data: Dict[str, Any]):
        """협상 메시지 전송"""
        message = NegotiationMessage(
            sender=sender,
            receiver=receiver,
            action=action,
            content=content,
            data=data,
            timestamp=time.time(),
            conversation_id=session.session_id
        )
        
        session.messages.append(message)
        
        logger.debug(f"💬 [{sender} → {receiver}] {action.value}: {content[:100]}...")
    
    def get_negotiation_history(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        """협상 이력 조회"""
        session = self.active_sessions.get(session_id)
        if not session:
            return None
        
        return [
            {
                "timestamp": msg.timestamp,
                "sender": msg.sender,
                "receiver": msg.receiver,
                "action": msg.action.value,
                "content": msg.content,
                "data": msg.data
            }
            for msg in session.messages
        ]
    
    def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """세션 요약 정보"""
        session = self.active_sessions.get(session_id)
        if not session:
            return None
        
        duration = (session.end_time or time.time()) - session.start_time
        
        return {
            "session_id": session_id,
            "user_request": session.user_request,
            "primary_agent": session.primary_agent_id,
            "status": session.status.value,
            "duration": duration,
            "message_count": len(session.messages),
            "final_decision": session.final_decision,
            "participating_agents": list(session.assessment_results.keys())
        }

# 전역 협상 프로토콜 인스턴스
_global_negotiation_protocol = None

def get_negotiation_protocol() -> AgentNegotiationProtocol:
    """전역 협상 프로토콜 인스턴스 반환"""
    global _global_negotiation_protocol
    if _global_negotiation_protocol is None:
        _global_negotiation_protocol = AgentNegotiationProtocol()
    return _global_negotiation_protocol