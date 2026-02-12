"""
Enhanced LogosAI Agent with Built-in Agentic AI Support

이 모듈은 Agentic AI 기능이 내장된 향상된 LogosAI Agent 기본 클래스를 제공합니다.
생성된 에이전트 코드가 복잡한 Agentic AI 로직을 직접 구현할 필요 없이,
간단한 비즈니스 로직만 구현하면 자동으로 Think-Plan-Act-Reflect 사이클이 적용됩니다.
"""

import logging
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from abc import ABC, abstractmethod

from .agent_types import AgentType, AgentResponse, AgentResponseType
from .config import AgentConfig
from .message_bus import MessageBus, Message, MessageType

# Agentic AI 모듈들을 조건부로 import
try:
    from .agentic import (
        AgenticCore,
        AgenticReasoning,
        AgenticTools,
        AgenticMemory,
        AgenticLearning,
        ThoughtProcess,
        ActionPlan,
        Reflection,
        MemoryImportance,
        FeedbackType
    )
    AGENTIC_AVAILABLE = True
except ImportError:
    AGENTIC_AVAILABLE = False
    logging.warning("Agentic AI modules not available. Running in basic mode.")

logger = logging.getLogger(__name__)


class EnhancedLogosAIAgent(ABC):
    """
    향상된 LogosAI Agent 기본 클래스
    
    이 클래스는 Agentic AI 기능을 Framework 레벨에서 관리합니다.
    하위 클래스는 _process_core_logic 메서드만 구현하면 됩니다.
    """
    
    def __init__(self, config: AgentConfig):
        """에이전트 초기화"""
        self.config = config
        self.logger = logger
        self.initialized = False
        
        # 기본 속성
        self.id = getattr(config, 'agent_id', self.__class__.__name__)
        self.name = getattr(config, 'name', self.__class__.__name__)
        
        # MessageBus를 통한 에이전트 간 통신
        self.message_bus = MessageBus()
        self._message_handlers = {}
        
        # Agentic AI 모듈들 (조건부 초기화)
        self._agentic_enabled = config.config.get('enable_agentic', False) if hasattr(config, 'config') else False
        self._agentic_core = None
        self._agentic_reasoning = None
        self._agentic_memory = None
        self._agentic_learning = None
        self._agentic_tools = None
        
        # Agentic AI 초기화
        if self._agentic_enabled and AGENTIC_AVAILABLE:
            self._init_agentic_features()
    
    def _init_agentic_features(self):
        """Agentic AI 기능 초기화"""
        try:
            agentic_config = self.config.config.get('agentic_config', {})
            
            # Core 모듈 초기화
            self._agentic_core = AgenticCore(
                agent_name=self.name,
                config=agentic_config
            )
            
            # Reasoning 모듈 초기화
            self._agentic_reasoning = AgenticReasoning()
            
            # Memory 모듈 초기화
            memory_capacity = agentic_config.get('memory_capacity', 50)
            self._agentic_memory = AgenticMemory(capacity=memory_capacity)
            
            # Learning 모듈 초기화
            learning_rate = agentic_config.get('learning_rate', 0.1)
            self._agentic_learning = AgenticLearning(learning_rate=learning_rate)
            
            # Tools 모듈 초기화
            self._agentic_tools = AgenticTools()
            
            logger.info(f"✅ Agentic AI features initialized for {self.name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Agentic AI features: {e}")
            self._agentic_enabled = False
    
    async def initialize(self) -> bool:
        """에이전트 초기화"""
        try:
            # MessageBus 시작
            await self.message_bus.start()
            
            # 에이전트 간 통신을 위한 토픽 구독
            await self._subscribe_to_agent_communication()
            
            # 하위 클래스의 초기화 로직 호출
            if hasattr(self, '_custom_initialize'):
                await self._custom_initialize()
            
            self.initialized = True
            logger.info(f"✅ Agent {self.name} initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize agent {self.name}: {e}")
            return False
    
    async def _subscribe_to_agent_communication(self):
        """에이전트 간 통신을 위한 토픽 구독"""
        # 자신에게 오는 직접 메시지 구독
        await self.message_bus.subscribe(
            f"agent.{self.id}",
            self._handle_direct_message
        )
        
        # 브로드캐스트 메시지 구독
        await self.message_bus.subscribe(
            "agent.broadcast",
            self._handle_broadcast_message
        )
        
        # 협업 요청 구독
        await self.message_bus.subscribe(
            "agent.collaboration",
            self._handle_collaboration_request
        )
    
    async def _handle_direct_message(self, message: Message):
        """직접 메시지 처리"""
        logger.info(f"📨 {self.name} received direct message from {message.sender}: {message.data}")
        
        # 메시지 타입에 따른 처리
        if isinstance(message.data, dict):
            msg_type = message.data.get('type')
            
            if msg_type == 'request':
                # 다른 에이전트의 요청 처리
                response = await self._handle_agent_request(message.data)
                await self.send_message_to_agent(
                    message.sender,
                    {'type': 'response', 'data': response}
                )
            elif msg_type == 'collaboration':
                # 협업 요청 처리
                await self._handle_collaboration(message.data)
    
    async def _handle_broadcast_message(self, message: Message):
        """브로드캐스트 메시지 처리"""
        logger.debug(f"📢 {self.name} received broadcast from {message.sender}")
    
    async def _handle_collaboration_request(self, message: Message):
        """협업 요청 처리"""
        logger.info(f"🤝 {self.name} received collaboration request from {message.sender}")
        
        # 협업 가능 여부 확인 및 응답
        if self._can_collaborate(message.data):
            await self.send_message_to_agent(
                message.sender,
                {'type': 'collaboration_accept', 'agent_id': self.id}
            )
    
    async def _handle_agent_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """다른 에이전트의 요청 처리"""
        query = request_data.get('query', '')
        context = request_data.get('context', {})
        
        # 요청 처리
        result = await self.process(query, context)
        
        return {
            'success': result.type == AgentResponseType.SUCCESS,
            'data': result.content
        }
    
    def _can_collaborate(self, collaboration_data: Dict[str, Any]) -> bool:
        """협업 가능 여부 확인"""
        # 기본적으로 모든 협업 허용 (하위 클래스에서 오버라이드 가능)
        return True
    
    async def send_message_to_agent(self, target_agent_id: str, data: Any):
        """특정 에이전트에게 메시지 전송"""
        message = Message(
            topic=f"agent.{target_agent_id}",
            data=data,
            sender=self.id
        )
        await self.message_bus.publish(message)
        logger.debug(f"📤 {self.name} sent message to {target_agent_id}")
    
    async def broadcast_message(self, data: Any):
        """모든 에이전트에게 브로드캐스트"""
        message = Message(
            topic="agent.broadcast",
            data=data,
            sender=self.id
        )
        await self.message_bus.publish(message)
        logger.debug(f"📢 {self.name} broadcasted message")
    
    async def request_collaboration(self, task: str, requirements: Dict[str, Any]):
        """다른 에이전트들에게 협업 요청"""
        message = Message(
            topic="agent.collaboration",
            data={
                'task': task,
                'requirements': requirements,
                'requester': self.id
            },
            sender=self.id
        )
        await self.message_bus.publish(message)
        logger.info(f"🤝 {self.name} requested collaboration for task: {task}")
    
    async def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """
        쿼리 처리 - Agentic AI 사이클 자동 적용
        
        이 메서드는 Framework 레벨에서 Think-Plan-Act-Reflect 사이클을 관리합니다.
        하위 클래스는 _process_core_logic만 구현하면 됩니다.
        """
        if not self.initialized:
            await self.initialize()
        
        try:
            # Agentic AI가 활성화되어 있으면 Think-Plan-Act-Reflect 사이클 실행
            if self._agentic_enabled and self._agentic_core:
                return await self._process_with_agentic(query, context)
            else:
                # 기본 처리 (Agentic AI 없이)
                return await self._process_basic(query, context)
                
        except Exception as e:
            logger.error(f"Error processing query in {self.name}: {e}")
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": str(e)},
                message=f"Error: {str(e)}"
            )
    
    async def _process_with_agentic(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """Agentic AI 사이클을 통한 처리"""
        logger.info(f"🧠 {self.name} processing with Agentic AI cycle")
        
        # 1️⃣ THINK - 쿼리 이해 및 분석
        thought = await self._agentic_core.think(query, context)
        logger.debug(f"💭 Thought confidence: {thought.confidence}")
        
        # 2️⃣ MEMORY RECALL - 관련 경험 회상
        memories = self._agentic_memory.recall(query, limit=3)
        if memories:
            logger.debug(f"📚 Recalled {len(memories)} relevant memories")
        
        # 3️⃣ PLAN - 실행 계획 수립
        plan = await self._agentic_core.plan(thought, memories)
        logger.debug(f"📋 Created plan with {len(plan.actions)} actions")
        
        # 4️⃣ REASONING - 추론 체인 실행
        reasoning_result = await self._agentic_reasoning.reason(
            query=query,
            context=context,
            thought=thought
        )
        
        # 5️⃣ ACT - 핵심 비즈니스 로직 실행 (하위 클래스 구현)
        core_result = await self._process_core_logic(query, context)
        
        # 6️⃣ REFLECT - 결과 평가 및 학습
        reflection = await self._agentic_core.reflect(
            thought=thought,
            plan=plan,
            result=core_result,
            reasoning=reasoning_result
        )
        
        # 7️⃣ MEMORY STORAGE - 경험 저장
        self._agentic_memory.add(
            content={
                'query': query,
                'result': core_result,
                'confidence': thought.confidence,
                'timestamp': datetime.now()
            },
            importance=MemoryImportance.HIGH if reflection.success else MemoryImportance.NORMAL
        )
        
        # 8️⃣ LEARNING - 피드백 기반 학습
        self._agentic_learning.record_feedback(
            query=query,
            result=core_result,
            feedback_type=FeedbackType.POSITIVE if reflection.success else FeedbackType.NEGATIVE,
            confidence=thought.confidence
        )
        
        # 결과 반환 (Agentic 메타데이터 포함)
        return AgentResponse(
            type=AgentResponseType.SUCCESS if reflection.success else AgentResponseType.ERROR,
            content=core_result,
            message=self._format_agentic_response(core_result, thought, reflection),
            metadata={
                'agentic': {
                    'thought_confidence': thought.confidence,
                    'plan_actions': len(plan.actions),
                    'reflection_success': reflection.success,
                    'memory_count': len(self._agentic_memory.short_term.memories),
                    'reasoning_type': reasoning_result.reasoning_type.value
                }
            }
        )
    
    async def _process_basic(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """기본 처리 (Agentic AI 없이)"""
        logger.info(f"⚡ {self.name} processing in basic mode")
        
        # 핵심 비즈니스 로직만 실행
        result = await self._process_core_logic(query, context)
        
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content=result,
            message="처리가 완료되었습니다."
        )
    
    @abstractmethod
    async def _process_core_logic(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        핵심 비즈니스 로직 구현 (하위 클래스에서 반드시 구현)
        
        이 메서드는 에이전트의 실제 작업을 수행합니다.
        Agentic AI 기능은 Framework에서 자동으로 처리됩니다.
        """
        raise NotImplementedError("Subclasses must implement _process_core_logic")
    
    def _format_agentic_response(self, result: Dict[str, Any], thought: ThoughtProcess, reflection: Reflection) -> str:
        """Agentic 응답 포맷팅"""
        confidence_str = f"(신뢰도: {thought.confidence:.2f})" if thought else ""
        success_str = "✅" if reflection.success else "⚠️"
        
        return f"{success_str} 처리 완료 {confidence_str}"
    
    async def cleanup(self):
        """에이전트 정리"""
        try:
            # MessageBus에서 구독 해제
            await self.message_bus.unsubscribe_all(self.id)
            
            # Agentic 모듈 정리
            if self._agentic_memory:
                self._agentic_memory.clear()
            
            logger.info(f"🧹 Agent {self.name} cleaned up")
            
        except Exception as e:
            logger.error(f"Error cleaning up agent {self.name}: {e}")