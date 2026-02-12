"""
에이전트 대화 관리자

LogosAI 에이전트들 간의 실시간 대화를 관리하고 조정하는 시스템입니다.
에이전트들이 서로 질문하고, 제안하고, 협의할 수 있도록 지원합니다.
"""

import asyncio
import uuid
import time
from typing import Dict, List, Any, Optional, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from loguru import logger

from .message_bus import MessageBus, Message
from .agent_self_assessment import AgentSelfAssessment


class DialogueType(Enum):
    """대화 유형"""
    CLARIFICATION = "clarification"      # 명확화 요청
    NEGOTIATION = "negotiation"          # 협상
    BRAINSTORMING = "brainstorming"    # 브레인스토밍
    PROBLEM_SOLVING = "problem_solving"  # 문제 해결
    KNOWLEDGE_SHARING = "knowledge_sharing"  # 지식 공유
    TASK_PLANNING = "task_planning"      # 작업 계획


class DialogueTurn(Enum):
    """대화 턴 타입"""
    QUESTION = "question"        # 질문
    ANSWER = "answer"           # 답변
    PROPOSAL = "proposal"       # 제안
    AGREEMENT = "agreement"     # 동의
    DISAGREEMENT = "disagreement"  # 반대
    CLARIFICATION = "clarification"  # 명확화
    SUMMARY = "summary"         # 요약


@dataclass
class DialogueMessage:
    """대화 메시지"""
    speaker: str                    # 발언자 (에이전트 ID)
    turn_type: DialogueTurn        # 발언 유형
    content: str                   # 발언 내용
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    in_reply_to: Optional[str] = None  # 답변 대상 메시지 ID
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class DialogueSession:
    """대화 세션"""
    session_id: str
    topic: str
    dialogue_type: DialogueType
    participants: Set[str]
    initiator: str
    messages: List[DialogueMessage] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    status: str = "active"  # active, paused, completed, failed
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    consensus: Optional[Dict[str, Any]] = None
    

class AgentDialogueManager:
    """에이전트 대화 관리자"""
    
    def __init__(self, message_bus: Optional[MessageBus] = None):
        """
        대화 관리자 초기화
        
        Args:
            message_bus: 메시지 버스 인스턴스
        """
        self.message_bus = message_bus or MessageBus()
        self.active_sessions: Dict[str, DialogueSession] = {}
        self.agent_handlers: Dict[str, Callable] = {}
        self.dialogue_history: List[DialogueSession] = []
        
        # 대화 관련 메시지 구독 (lazy initialization)
        self._subscriptions_setup = False
        
        logger.info("💬 에이전트 대화 관리자 초기화 완료")
    
    async def _setup_subscriptions(self):
        """메시지 구독 설정"""
        if self._subscriptions_setup:
            return
            
        # 대화 참여 요청
        await self.message_bus.subscribe("dialogue/*/invite", self._handle_dialogue_invite)
        # 대화 메시지
        await self.message_bus.subscribe("dialogue/*/message", self._handle_dialogue_message)
        # 대화 종료
        await self.message_bus.subscribe("dialogue/*/close", self._handle_dialogue_close)
        
        self._subscriptions_setup = True
    
    async def initiate_dialogue(self, 
                               topic: str,
                               participants: List[str],
                               dialogue_type: DialogueType = DialogueType.PROBLEM_SOLVING,
                               initiator: str = "system",
                               context: Dict[str, Any] = None) -> str:
        """
        새로운 대화 세션 시작
        
        Args:
            topic: 대화 주제
            participants: 참여 에이전트 ID 리스트
            dialogue_type: 대화 유형
            initiator: 대화 시작자
            context: 추가 컨텍스트
            
        Returns:
            session_id: 생성된 세션 ID
        """
        # 구독 설정 확인
        await self._setup_subscriptions()
        
        session_id = f"dialogue_{uuid.uuid4().hex[:12]}"
        
        session = DialogueSession(
            session_id=session_id,
            topic=topic,
            dialogue_type=dialogue_type,
            participants=set(participants),
            initiator=initiator,
            context=context or {}
        )
        
        self.active_sessions[session_id] = session
        
        logger.info(f"💬 새 대화 세션 시작: {session_id}")
        logger.info(f"   주제: {topic}")
        logger.info(f"   참여자: {participants}")
        logger.info(f"   유형: {dialogue_type.value}")
        
        # 각 참여자에게 초대 메시지 전송
        for agent_id in participants:
            await self.message_bus.publish(
                f"dialogue/{agent_id}/invite",
                {
                    "session_id": session_id,
                    "topic": topic,
                    "dialogue_type": dialogue_type.value,
                    "participants": list(participants),
                    "initiator": initiator,
                    "context": context
                }
            )
        
        # 대화 시작 메시지
        await self.add_message(
            session_id,
            DialogueMessage(
                speaker=initiator,
                turn_type=DialogueTurn.SUMMARY,
                content=f"대화 세션이 시작되었습니다. 주제: {topic}",
                metadata={"session_start": True}
            )
        )
        
        return session_id
    
    async def add_message(self, session_id: str, message: DialogueMessage):
        """대화에 메시지 추가"""
        # 구독 설정 확인
        await self._setup_subscriptions()
        
        if session_id not in self.active_sessions:
            logger.warning(f"존재하지 않는 세션: {session_id}")
            return
        
        session = self.active_sessions[session_id]
        session.messages.append(message)
        session.updated_at = time.time()
        
        # 다른 참여자들에게 메시지 브로드캐스트
        for participant in session.participants:
            if participant != message.speaker:
                await self.message_bus.publish(
                    f"dialogue/{participant}/message",
                    {
                        "session_id": session_id,
                        "message": {
                            "speaker": message.speaker,
                            "turn_type": message.turn_type.value,
                            "content": message.content,
                            "timestamp": message.timestamp,
                            "metadata": message.metadata,
                            "message_id": message.message_id,
                            "in_reply_to": message.in_reply_to
                        }
                    }
                )
    
    async def request_clarification(self, session_id: str, agent_id: str, 
                                  about: str, question: str) -> str:
        """명확화 요청"""
        message = DialogueMessage(
            speaker=agent_id,
            turn_type=DialogueTurn.CLARIFICATION,
            content=f"명확화 요청 - {about}: {question}",
            metadata={"clarification_about": about}
        )
        
        await self.add_message(session_id, message)
        return message.message_id
    
    async def make_proposal(self, session_id: str, agent_id: str, 
                          proposal: str, reasoning: str = None) -> str:
        """제안하기"""
        metadata = {"proposal": proposal}
        if reasoning:
            metadata["reasoning"] = reasoning
            
        message = DialogueMessage(
            speaker=agent_id,
            turn_type=DialogueTurn.PROPOSAL,
            content=f"제안: {proposal}" + (f"\n이유: {reasoning}" if reasoning else ""),
            metadata=metadata
        )
        
        await self.add_message(session_id, message)
        return message.message_id
    
    async def respond_to_proposal(self, session_id: str, agent_id: str,
                                proposal_id: str, agree: bool, 
                                comment: str = None) -> str:
        """제안에 대한 응답"""
        turn_type = DialogueTurn.AGREEMENT if agree else DialogueTurn.DISAGREEMENT
        content = "동의합니다." if agree else "동의하지 않습니다."
        
        if comment:
            content += f" - {comment}"
        
        message = DialogueMessage(
            speaker=agent_id,
            turn_type=turn_type,
            content=content,
            in_reply_to=proposal_id,
            metadata={"agreement": agree}
        )
        
        await self.add_message(session_id, message)
        return message.message_id
    
    async def ask_question(self, session_id: str, agent_id: str,
                         question: str, target_agent: Optional[str] = None) -> str:
        """질문하기"""
        metadata = {}
        if target_agent:
            metadata["target_agent"] = target_agent
            content = f"@{target_agent} {question}"
        else:
            content = question
        
        message = DialogueMessage(
            speaker=agent_id,
            turn_type=DialogueTurn.QUESTION,
            content=content,
            metadata=metadata
        )
        
        await self.add_message(session_id, message)
        return message.message_id
    
    async def answer_question(self, session_id: str, agent_id: str,
                            question_id: str, answer: str) -> str:
        """질문에 답변"""
        message = DialogueMessage(
            speaker=agent_id,
            turn_type=DialogueTurn.ANSWER,
            content=answer,
            in_reply_to=question_id
        )
        
        await self.add_message(session_id, message)
        return message.message_id
    
    async def summarize_dialogue(self, session_id: str) -> Dict[str, Any]:
        """대화 요약"""
        if session_id not in self.active_sessions:
            return {"error": "세션을 찾을 수 없습니다."}
        
        session = self.active_sessions[session_id]
        
        # 발언 통계
        speaker_stats = {}
        turn_stats = {}
        proposals = []
        agreements = []
        questions = []
        
        for msg in session.messages:
            # 발언자별 통계
            speaker_stats[msg.speaker] = speaker_stats.get(msg.speaker, 0) + 1
            
            # 발언 유형별 통계
            turn_type = msg.turn_type.value
            turn_stats[turn_type] = turn_stats.get(turn_type, 0) + 1
            
            # 주요 내용 추출
            if msg.turn_type == DialogueTurn.PROPOSAL:
                proposals.append({
                    "speaker": msg.speaker,
                    "content": msg.content,
                    "id": msg.message_id
                })
            elif msg.turn_type == DialogueTurn.AGREEMENT:
                agreements.append({
                    "speaker": msg.speaker,
                    "agrees": True,
                    "to": msg.in_reply_to
                })
            elif msg.turn_type == DialogueTurn.QUESTION:
                questions.append({
                    "speaker": msg.speaker,
                    "question": msg.content,
                    "answered": any(m.in_reply_to == msg.message_id 
                                  for m in session.messages)
                })
        
        # 합의 사항 도출
        consensus_items = []
        for proposal in proposals:
            agree_count = sum(1 for a in agreements 
                            if a["to"] == proposal["id"] and a["agrees"])
            if agree_count >= len(session.participants) * 0.5:  # 50% 이상 동의
                consensus_items.append(proposal["content"])
        
        summary = {
            "session_id": session_id,
            "topic": session.topic,
            "dialogue_type": session.dialogue_type.value,
            "participants": list(session.participants),
            "message_count": len(session.messages),
            "duration": time.time() - session.created_at,
            "speaker_stats": speaker_stats,
            "turn_stats": turn_stats,
            "proposals": proposals,
            "consensus_items": consensus_items,
            "unanswered_questions": [q for q in questions if not q["answered"]],
            "status": session.status
        }
        
        # 세션에 합의 사항 저장
        if consensus_items:
            session.consensus = {
                "items": consensus_items,
                "timestamp": time.time()
            }
        
        return summary
    
    async def close_dialogue(self, session_id: str, reason: str = "completed"):
        """대화 종료"""
        if session_id not in self.active_sessions:
            return
        
        session = self.active_sessions[session_id]
        session.status = reason
        
        # 요약 생성
        summary = await self.summarize_dialogue(session_id)
        
        # 종료 메시지
        await self.add_message(
            session_id,
            DialogueMessage(
                speaker="system",
                turn_type=DialogueTurn.SUMMARY,
                content=f"대화가 종료되었습니다. 총 {len(session.messages)}개 메시지 교환",
                metadata={"summary": summary}
            )
        )
        
        # 히스토리에 저장
        self.dialogue_history.append(session)
        
        # 활성 세션에서 제거
        del self.active_sessions[session_id]
        
        logger.info(f"💬 대화 세션 종료: {session_id} (이유: {reason})")
    
    async def _handle_dialogue_invite(self, message: Message):
        """대화 초대 처리"""
        # 에이전트가 구현해야 할 핸들러
        pass
    
    async def _handle_dialogue_message(self, message: Message):
        """대화 메시지 처리"""
        # 에이전트가 구현해야 할 핸들러
        pass
    
    async def _handle_dialogue_close(self, message: Message):
        """대화 종료 처리"""
        session_id = message.data.get("session_id")
        reason = message.data.get("reason", "completed")
        await self.close_dialogue(session_id, reason)
    
    def get_session_messages(self, session_id: str) -> List[DialogueMessage]:
        """세션의 모든 메시지 반환"""
        if session_id in self.active_sessions:
            return self.active_sessions[session_id].messages
        return []
    
    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """활성 세션 목록 반환"""
        return [
            {
                "session_id": session.session_id,
                "topic": session.topic,
                "participants": list(session.participants),
                "message_count": len(session.messages),
                "duration": time.time() - session.created_at
            }
            for session in self.active_sessions.values()
        ]


# 전역 대화 관리자 인스턴스
_dialogue_manager_instance = None


def get_dialogue_manager() -> AgentDialogueManager:
    """전역 대화 관리자 인스턴스 반환"""
    global _dialogue_manager_instance
    if _dialogue_manager_instance is None:
        _dialogue_manager_instance = AgentDialogueManager()
    return _dialogue_manager_instance