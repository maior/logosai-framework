"""
에이전트 대화 프로토콜

에이전트가 대화에 참여하고 상호작용하기 위한 표준 프로토콜입니다.
모든 LogosAI 에이전트는 이 프로토콜을 구현하여 대화 능력을 갖추게 됩니다.
"""

import asyncio
from typing import Dict, Any, List, Optional, Callable, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass
from loguru import logger

from .agent_dialogue_manager import (
    DialogueType, DialogueTurn, DialogueMessage,
    get_dialogue_manager
)
from .message_bus import Message


@dataclass
class DialogueCapability:
    """에이전트의 대화 능력"""
    can_ask_questions: bool = True      # 질문 가능
    can_make_proposals: bool = True     # 제안 가능
    can_negotiate: bool = True          # 협상 가능
    can_brainstorm: bool = True         # 브레인스토밍 가능
    can_clarify: bool = True            # 명확화 요청 가능
    preferred_dialogue_types: List[DialogueType] = None
    dialogue_style: str = "collaborative"  # collaborative, assertive, analytical, creative
    

class DialogueProtocol(ABC):
    """에이전트 대화 프로토콜 인터페이스"""
    
    def __init__(self, agent_id: str, agent_name: str):
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.dialogue_manager = get_dialogue_manager()
        self.active_dialogues: Dict[str, Dict[str, Any]] = {}
        self.dialogue_capability = DialogueCapability()
        self._handlers_registered = False
        
        # 대화 핸들러는 첫 사용시 등록 (lazy initialization)
    
    async def _ensure_handlers_registered(self):
        """핸들러가 등록되었는지 확인하고 필요시 등록"""
        if not self._handlers_registered:
            await self._register_dialogue_handlers()
            self._handlers_registered = True
    
    @abstractmethod
    async def on_dialogue_invite(self, session_id: str, topic: str, 
                               participants: List[str], context: Dict[str, Any]) -> bool:
        """
        대화 초대를 받았을 때 처리
        
        Args:
            session_id: 대화 세션 ID
            topic: 대화 주제
            participants: 참여자 목록
            context: 대화 컨텍스트
            
        Returns:
            참여 여부 (True/False)
        """
        pass
    
    @abstractmethod
    async def on_dialogue_message(self, session_id: str, message: DialogueMessage):
        """
        대화 메시지를 받았을 때 처리
        
        Args:
            session_id: 대화 세션 ID
            message: 받은 메시지
        """
        pass
    
    @abstractmethod
    async def generate_dialogue_response(self, session_id: str, 
                                       context: List[DialogueMessage]) -> Optional[DialogueMessage]:
        """
        대화 컨텍스트를 기반으로 응답 생성
        
        Args:
            session_id: 대화 세션 ID
            context: 이전 대화 내역
            
        Returns:
            생성된 응답 메시지 (없으면 None)
        """
        pass
    
    async def _register_dialogue_handlers(self):
        """대화 관련 메시지 핸들러 등록"""
        # 대화 초대
        await self.dialogue_manager.message_bus.subscribe(
            f"dialogue/{self.agent_id}/invite",
            self._handle_invite
        )
        
        # 대화 메시지
        await self.dialogue_manager.message_bus.subscribe(
            f"dialogue/{self.agent_id}/message",
            self._handle_message
        )
    
    async def _handle_invite(self, message: Message):
        """대화 초대 메시지 처리"""
        data = message.data
        session_id = data.get("session_id")
        topic = data.get("topic")
        participants = data.get("participants", [])
        context = data.get("context", {})
        
        # 에이전트에게 참여 의사 확인
        will_participate = await self.on_dialogue_invite(
            session_id, topic, participants, context
        )
        
        if will_participate:
            self.active_dialogues[session_id] = {
                "topic": topic,
                "participants": participants,
                "context": context,
                "joined_at": asyncio.get_event_loop().time()
            }
            
            logger.info(f"🤝 {self.agent_name}이(가) 대화에 참여: {topic}")
            
            # 참여 메시지 전송
            await self.dialogue_manager.add_message(
                session_id,
                DialogueMessage(
                    speaker=self.agent_id,
                    turn_type=DialogueTurn.SUMMARY,
                    content=f"{self.agent_name}이(가) 대화에 참여했습니다.",
                    metadata={"joined": True}
                )
            )
    
    async def _handle_message(self, message: Message):
        """대화 메시지 처리"""
        data = message.data
        session_id = data.get("session_id")
        
        if session_id not in self.active_dialogues:
            return
        
        # DialogueMessage 객체로 변환
        msg_data = data.get("message", {})
        dialogue_message = DialogueMessage(
            speaker=msg_data.get("speaker"),
            turn_type=DialogueTurn(msg_data.get("turn_type")),
            content=msg_data.get("content"),
            timestamp=msg_data.get("timestamp"),
            metadata=msg_data.get("metadata", {}),
            message_id=msg_data.get("message_id"),
            in_reply_to=msg_data.get("in_reply_to")
        )
        
        # 에이전트에게 메시지 전달
        await self.on_dialogue_message(session_id, dialogue_message)
        
        # 자동 응답 생성 고려
        if self._should_respond(dialogue_message):
            # 대화 컨텍스트 가져오기
            context = self.dialogue_manager.get_session_messages(session_id)
            
            # 응답 생성
            response = await self.generate_dialogue_response(session_id, context)
            
            if response:
                await self.dialogue_manager.add_message(session_id, response)
    
    def _should_respond(self, message: DialogueMessage) -> bool:
        """응답해야 하는지 판단"""
        # 자신에게 직접 온 질문
        if message.turn_type == DialogueTurn.QUESTION:
            if f"@{self.agent_id}" in message.content:
                return True
            if message.metadata.get("target_agent") == self.agent_id:
                return True
        
        # 명확화 요청
        if message.turn_type == DialogueTurn.CLARIFICATION:
            return True
        
        # 제안에 대한 의견 요청
        if message.turn_type == DialogueTurn.PROPOSAL:
            return self.dialogue_capability.can_negotiate
        
        return False
    
    # 대화 참여 헬퍼 메서드들
    
    async def ask_in_dialogue(self, session_id: str, question: str, 
                            target_agent: Optional[str] = None) -> str:
        """대화에서 질문하기"""
        await self._ensure_handlers_registered()
        
        if not self.dialogue_capability.can_ask_questions:
            logger.warning(f"{self.agent_name}은(는) 질문 능력이 없습니다.")
            return None
            
        return await self.dialogue_manager.ask_question(
            session_id, self.agent_id, question, target_agent
        )
    
    async def propose_in_dialogue(self, session_id: str, proposal: str, 
                                reasoning: str = None) -> str:
        """대화에서 제안하기"""
        await self._ensure_handlers_registered()
        
        if not self.dialogue_capability.can_make_proposals:
            logger.warning(f"{self.agent_name}은(는) 제안 능력이 없습니다.")
            return None
            
        return await self.dialogue_manager.make_proposal(
            session_id, self.agent_id, proposal, reasoning
        )
    
    async def clarify_in_dialogue(self, session_id: str, about: str, 
                                question: str) -> str:
        """대화에서 명확화 요청"""
        await self._ensure_handlers_registered()
        
        if not self.dialogue_capability.can_clarify:
            logger.warning(f"{self.agent_name}은(는) 명확화 요청 능력이 없습니다.")
            return None
            
        return await self.dialogue_manager.request_clarification(
            session_id, self.agent_id, about, question
        )
    
    async def agree_with_proposal(self, session_id: str, proposal_id: str, 
                                comment: str = None) -> str:
        """제안에 동의"""
        return await self.dialogue_manager.respond_to_proposal(
            session_id, self.agent_id, proposal_id, True, comment
        )
    
    async def disagree_with_proposal(self, session_id: str, proposal_id: str, 
                                   reason: str) -> str:
        """제안에 반대"""
        return await self.dialogue_manager.respond_to_proposal(
            session_id, self.agent_id, proposal_id, False, reason
        )
    
    async def answer_in_dialogue(self, session_id: str, question_id: str, 
                               answer: str) -> str:
        """질문에 답변"""
        return await self.dialogue_manager.answer_question(
            session_id, self.agent_id, question_id, answer
        )
    
    def leave_dialogue(self, session_id: str):
        """대화에서 나가기"""
        if session_id in self.active_dialogues:
            del self.active_dialogues[session_id]
            logger.info(f"👋 {self.agent_name}이(가) 대화를 떠났습니다.")


class SimpleDialogueProtocol(DialogueProtocol):
    """간단한 대화 프로토콜 구현 (기본 구현)"""
    
    def __init__(self, agent_id: str, agent_name: str, 
                 auto_participate: bool = True):
        super().__init__(agent_id, agent_name)
        self.auto_participate = auto_participate
    
    async def on_dialogue_invite(self, session_id: str, topic: str, 
                               participants: List[str], context: Dict[str, Any]) -> bool:
        """대화 초대 자동 수락"""
        if self.auto_participate:
            logger.info(f"✅ {self.agent_name}이(가) 대화 초대 수락: {topic}")
            return True
        
        # 주제나 참여자에 따라 선택적 참여 로직 구현 가능
        return False
    
    async def on_dialogue_message(self, session_id: str, message: DialogueMessage):
        """메시지 로깅"""
        logger.debug(f"💬 [{message.speaker}] {message.content}")
    
    async def generate_dialogue_response(self, session_id: str, 
                                       context: List[DialogueMessage]) -> Optional[DialogueMessage]:
        """간단한 응답 생성"""
        if not context:
            return None
        
        last_message = context[-1]
        
        # 질문에 대한 기본 응답
        if last_message.turn_type == DialogueTurn.QUESTION:
            if f"@{self.agent_id}" in last_message.content:
                return DialogueMessage(
                    speaker=self.agent_id,
                    turn_type=DialogueTurn.ANSWER,
                    content=f"죄송합니다. 아직 구체적인 답변을 생성할 수 없습니다.",
                    in_reply_to=last_message.message_id
                )
        
        return None