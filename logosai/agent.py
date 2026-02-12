"""
LogosAI 에이전트 구현

이 모듈은 LogosAI 에이전트의 기본 클래스와 유틸리티 함수를 제공합니다.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Union, List, Tuple
from .agent_types import AgentType, AgentResponse, AgentResponseType
from .config import AgentConfig
from langchain_openai import ChatOpenAI
from loguru import logger
from .agent_self_assessment import AgentSelfAssessment, SelfAssessmentResult
from .dialogue_protocol import SimpleDialogueProtocol, DialogueCapability, DialogueMessage, DialogueTurn

# 쿼리 최적화 시스템은 나중에 import (순환 참조 방지)
optimize_query_for_agent = None
check_agent_suitability = None
OptimizerAgentType = None

def _lazy_import_query_optimizer():
    """쿼리 최적화 모듈을 필요할 때 import"""
    global optimize_query_for_agent, check_agent_suitability, OptimizerAgentType
    if optimize_query_for_agent is None:
        try:
            from .query_optimizer import optimize_query_for_agent as _optimize, check_agent_suitability as _check, AgentType as _AgentType
            optimize_query_for_agent = _optimize
            check_agent_suitability = _check
            OptimizerAgentType = _AgentType
        except ImportError:
            logger.warning("쿼리 최적화 시스템을 로드할 수 없습니다")

# 로깅 설정
logger = logging.getLogger(__name__)

class LogosAIAgent:
    """LogosAI 에이전트 기본 클래스 - 조건부 Agentic AI 지원"""
    
    def __init__(self, config: AgentConfig):
        """에이전트 초기화
        
        Args:
            config: 에이전트 설정
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.initialized = False
        
        # 에이전트 ID와 이름 설정
        self.id = getattr(config, 'agent_id', self.__class__.__name__)
        self.name = getattr(config, 'name', self.__class__.__name__)
        
        # Agentic AI 기능 활성화 여부 확인
        self._agentic_enabled = self._should_enable_agentic()
        
        # Agentic AI 모듈 초기화 (조건부)
        self._agentic_core = None
        self._agentic_reasoning = None
        self._agentic_memory = None
        self._agentic_learning = None
        self._agentic_tools = None
        
        if self._agentic_enabled:
            self._init_agentic_features()
        
        # 자기평가 시스템 초기화
        self._self_assessment = None
        self._init_self_assessment()
        
        # 대화 프로토콜 초기화
        self._dialogue_protocol = None
        self._init_dialogue_protocol()
    
    def _should_enable_agentic(self) -> bool:
        """Agentic AI 기능 활성화 여부 결정"""
        if not hasattr(self.config, 'config') or not isinstance(self.config.config, dict):
            return False
        
        # 명시적 enable 플래그 확인
        if self.config.config.get('enable_agentic'):
            return True
        
        # agentic_config 존재 여부 확인
        if 'agentic_config' in self.config.config:
            return True
        
        return False
    
    def _init_agentic_features(self):
        """Agentic AI 기능 초기화"""
        try:
            # Agentic 모듈들을 동적으로 import
            from .agentic import (
                AgenticCore,
                AgenticReasoning,
                AgenticTools,
                AgenticMemory,
                AgenticLearning
            )
            
            agentic_config = self.config.config.get('agentic_config', {})
            
            # Core 모듈 초기화
            self._agentic_core = AgenticCore(
                agent_name=self.name,
                config=agentic_config
            )
            
            # Reasoning 모듈 초기화 (reasoning_type이 있을 때만)
            if agentic_config.get('reasoning_type'):
                self._agentic_reasoning = AgenticReasoning()
            
            # Memory 모듈 초기화 (memory_capacity > 0일 때만)
            memory_capacity = agentic_config.get('memory_capacity', 0)
            if memory_capacity > 0:
                self._agentic_memory = AgenticMemory(capacity=memory_capacity)
            
            # Learning 모듈 초기화 (learning_rate > 0일 때만)
            learning_rate = agentic_config.get('learning_rate', 0)
            if learning_rate > 0:
                self._agentic_learning = AgenticLearning(learning_rate=learning_rate)
            
            # Tools 모듈 초기화 (tools_enabled일 때만)
            if agentic_config.get('tools_enabled'):
                self._agentic_tools = AgenticTools()
            
            logger.info(f"✅ Agentic AI features enabled for {self.name}")
            
        except ImportError as e:
            logger.warning(f"Agentic AI modules not available: {e}")
            self._agentic_enabled = False
        except Exception as e:
            logger.error(f"Failed to initialize agentic features: {e}")
            self._agentic_enabled = False
    
    async def initialize(self) -> bool:
        """에이전트 초기화
        
        Returns:
            bool: 초기화 성공 여부
        """
        self.initialized = True
        return True
    
    async def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """쿼리 처리

        Args:
            query: 처리할 쿼리
            context: 처리 컨텍스트

        Returns:
            AgentResponse: 처리 결과
        """
        if not self.initialized:
            await self.initialize()

        raise NotImplementedError("process 메서드를 구현해야 합니다.")

    async def process_stream(self, query: str, context: Optional[Dict[str, Any]] = None):
        """스트리밍 쿼리 처리 - AsyncGenerator로 중간 결과 반환

        Args:
            query: 처리할 쿼리
            context: 처리 컨텍스트

        Yields:
            Dict[str, Any]: 스트리밍 이벤트
                - type: 이벤트 타입 (start, progress, chunk, complete, error)
                - data: 이벤트 데이터
                - timestamp: 이벤트 시간

        Example:
            async for event in agent.process_stream("query"):
                if event["type"] == "chunk":
                    print(event["data"]["content"])
                elif event["type"] == "complete":
                    print("Done:", event["data"]["result"])
        """
        import time

        if not self.initialized:
            await self.initialize()

        # 스트리밍 시작 이벤트
        yield {
            "type": "start",
            "data": {
                "agent_id": self.id,
                "agent_name": self.name,
                "query": query
            },
            "timestamp": time.time()
        }

        try:
            # 진행 상황 이벤트
            yield {
                "type": "progress",
                "data": {
                    "stage": "processing",
                    "message": f"{self.name}이(가) 쿼리를 처리 중입니다..."
                },
                "timestamp": time.time()
            }

            # 실제 처리 실행 (하위 클래스에서 오버라이드 가능)
            result = await self.process(query, context)

            # 결과를 청크로 분할하여 전송 (긴 응답의 경우)
            if result.type == AgentResponseType.SUCCESS:
                content = result.content
                if isinstance(content, dict):
                    answer = content.get("answer", str(content))
                else:
                    answer = str(content)

                # 긴 응답을 청크로 분할
                chunk_size = 500  # 500자씩 분할
                if len(answer) > chunk_size:
                    for i in range(0, len(answer), chunk_size):
                        chunk = answer[i:i + chunk_size]
                        yield {
                            "type": "chunk",
                            "data": {
                                "content": chunk,
                                "index": i // chunk_size,
                                "is_last": i + chunk_size >= len(answer)
                            },
                            "timestamp": time.time()
                        }
                        await asyncio.sleep(0.01)  # 약간의 딜레이로 스트리밍 효과
                else:
                    yield {
                        "type": "chunk",
                        "data": {
                            "content": answer,
                            "index": 0,
                            "is_last": True
                        },
                        "timestamp": time.time()
                    }

            # 완료 이벤트
            yield {
                "type": "complete",
                "data": {
                    "result": result.content,
                    "response_type": result.type.value if hasattr(result.type, 'value') else str(result.type),
                    "message": result.message,
                    "metadata": result.metadata
                },
                "timestamp": time.time()
            }

        except NotImplementedError:
            # process()가 구현되지 않은 경우
            yield {
                "type": "error",
                "data": {
                    "error": "process 메서드가 구현되지 않았습니다",
                    "error_type": "NotImplementedError"
                },
                "timestamp": time.time()
            }
        except Exception as e:
            # 에러 이벤트
            yield {
                "type": "error",
                "data": {
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                "timestamp": time.time()
            }

    def _init_self_assessment(self):
        """자기평가 시스템 초기화"""
        try:
            # LLM 클라이언트 가져오기
            llm_client = getattr(self, 'llm_client', None)
            
            # AgentSelfAssessment 인스턴스 생성
            self._self_assessment = AgentSelfAssessment(
                agent_id=getattr(self.config, 'agent_id', self.__class__.__name__),
                agent_name=getattr(self.config, 'name', self.__class__.__name__),
                llm_client=llm_client
            )
            
            # 에이전트 능력 설정 (하위 클래스에서 오버라이드 가능)
            capabilities = self.get_capabilities()
            if capabilities:
                self._self_assessment.set_capabilities(capabilities)
                
            # 도메인 키워드 설정 (하위 클래스에서 오버라이드 가능)
            domain_keywords = self.get_domain_keywords()
            if domain_keywords:
                self._self_assessment.set_domain_keywords(domain_keywords)
                
        except Exception as e:
            logger.warning(f"자기평가 시스템 초기화 실패: {e}")
            self._self_assessment = None
    
    def get_capabilities(self) -> List[str]:
        """
        에이전트 능력 목록 반환
        하위 클래스에서 오버라이드하여 구체적인 능력을 정의
        """
        return []
    
    def get_domain_keywords(self) -> Dict[str, List[str]]:
        """
        도메인별 키워드 반환
        하위 클래스에서 오버라이드하여 구체적인 도메인 키워드를 정의
        """
        return {}
    
    def _init_dialogue_protocol(self):
        """대화 프로토콜 초기화"""
        try:
            # 대화 프로토콜 인스턴스 생성
            self._dialogue_protocol = SimpleDialogueProtocol(
                agent_id=self.id,
                agent_name=self.name,
                auto_participate=True  # 기본적으로 모든 대화에 참여
            )
            
            # 대화 프로토콜에 실제 처리 메서드 연결
            self._dialogue_protocol.on_dialogue_invite = self._on_dialogue_invite
            self._dialogue_protocol.on_dialogue_message = self._on_dialogue_message
            self._dialogue_protocol.generate_dialogue_response = self._generate_dialogue_response
            
            # 대화 능력 설정
            self._dialogue_protocol.dialogue_capability = self.get_dialogue_capability()
            
            logger.info(f"대화 프로토콜 초기화 완료: {self.name}")
            
        except Exception as e:
            logger.warning(f"대화 프로토콜 초기화 실패: {e}")
            self._dialogue_protocol = None
    
    def get_dialogue_capability(self) -> DialogueCapability:
        """
        에이전트의 대화 능력 정의
        하위 클래스에서 오버라이드하여 구체적인 능력을 정의
        """
        return DialogueCapability(
            can_ask_questions=True,
            can_make_proposals=True,
            can_negotiate=True,
            can_brainstorm=True,
            can_clarify=True,
            dialogue_style="collaborative"
        )
    
    async def _on_dialogue_invite(self, session_id: str, topic: str,
                                 participants: List[str], context: Dict[str, Any]) -> bool:
        """
        대화 초대 처리
        하위 클래스에서 오버라이드하여 선택적 참여 로직 구현 가능
        """
        # 기본적으로 자신의 전문 분야와 관련있으면 참여
        can_handle, confidence, _ = await self.can_handle(topic, context)
        
        if confidence > 0.5:
            logger.info(f"✅ {self.name}이(가) 대화 참여 결정: {topic} (신뢰도: {confidence:.2f})")
            return True
        else:
            logger.info(f"❌ {self.name}이(가) 대화 참여 거절: {topic} (신뢰도: {confidence:.2f})")
            return False
    
    async def _on_dialogue_message(self, session_id: str, message: DialogueMessage):
        """
        대화 메시지 수신 처리
        하위 클래스에서 오버라이드하여 구체적인 반응 구현
        """
        logger.debug(f"💬 [{self.name}] 메시지 수신: [{message.speaker}] {message.content[:50]}...")
    
    async def _generate_dialogue_response(self, session_id: str,
                                        context: List[DialogueMessage]) -> Optional[DialogueMessage]:
        """
        대화 응답 생성
        하위 클래스에서 오버라이드하여 지능적인 응답 생성
        """
        if not context:
            return None
        
        last_message = context[-1]
        
        # 자신에게 온 질문에 대한 응답
        if last_message.turn_type == DialogueTurn.QUESTION:
            if f"@{self.id}" in last_message.content or last_message.metadata.get("target_agent") == self.id:
                # 질문 내용 추출
                question = last_message.content.replace(f"@{self.id}", "").strip()
                
                try:
                    # 에이전트의 process 메서드를 사용하여 답변 생성
                    response = await self.process(question, {"dialogue_context": context})
                    
                    if response.type == AgentResponseType.SUCCESS:
                        answer_content = response.content
                        if isinstance(answer_content, dict):
                            answer_content = answer_content.get("message", str(answer_content))
                        
                        return DialogueMessage(
                            speaker=self.id,
                            turn_type=DialogueTurn.ANSWER,
                            content=str(answer_content),
                            in_reply_to=last_message.message_id
                        )
                except Exception as e:
                    logger.error(f"대화 응답 생성 중 오류: {e}")
                    return DialogueMessage(
                        speaker=self.id,
                        turn_type=DialogueTurn.ANSWER,
                        content=f"죄송합니다. 답변 생성 중 오류가 발생했습니다: {str(e)}",
                        in_reply_to=last_message.message_id
                    )
        
        return None
    
    async def can_handle(self, query: str, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, float, str]:
        """
        쿼리 처리 가능 여부 평가
        
        Args:
            query: 사용자 쿼리
            context: 추가 컨텍스트
            
        Returns:
            (처리 가능 여부, 신뢰도 0-1, 이유)
        """
        if self._self_assessment is None:
            # 자기평가 시스템이 없으면 기본값 반환
            return True, 0.5, "자기평가 시스템 비활성화"
        
        try:
            # 자기평가 수행
            assessment_result = await self._self_assessment.assess_request_compatibility(query, context)
            
            # 결과 변환
            can_handle = assessment_result.can_handle
            confidence = assessment_result.confidence_score
            
            # 이유 구성
            reasons = assessment_result.reasoning
            if assessment_result.capability_level.value:
                reasons.insert(0, f"능력 수준: {assessment_result.capability_level.value}")
            reason = " | ".join(reasons[:3])  # 상위 3개 이유만
            
            return can_handle, confidence, reason
            
        except Exception as e:
            logger.error(f"자기평가 중 오류 발생: {e}")
            return True, 0.5, f"평가 오류: {str(e)}"
    
    async def process_with_optimization(
        self, 
        query: str, 
        context: Optional[Dict[str, Any]] = None,
        agent_type_override: Optional[str] = None
    ) -> AgentResponse:
        """
        쿼리 최적화를 포함한 처리
        
        이 메서드는 다음 단계를 수행합니다:
        1. 에이전트 적합성 판단
        2. 쿼리 최적화 (에이전트 타입별)
        3. 최적화된 쿼리로 처리 실행
        
        Args:
            query: 원본 쿼리
            context: 처리 컨텍스트
            agent_type_override: 에이전트 타입 오버라이드 (선택사항)
            
        Returns:
            AgentResponse: 처리 결과 (최적화 정보 포함)
        """
        if not self.initialized:
            await self.initialize()
        
        # 1. 쿼리 최적화 시스템 사용 가능 여부 확인
        _lazy_import_query_optimizer()
        if optimize_query_for_agent is None:
            logger.warning("쿼리 최적화 시스템을 사용할 수 없어 원본 쿼리로 처리합니다")
            return await self.process(query, context)
        
        try:
            # 2. 에이전트 타입 결정
            agent_type = agent_type_override or self._get_agent_type_for_optimization()
            
            # 3. 쿼리 최적화 실행
            optimization_result = await optimize_query_for_agent(
                query=query,
                agent_type=agent_type,
                agent_id=getattr(self.config, 'agent_id', None),
                context=context
            )
            
            # 4. 적합성 체크
            if not optimization_result.is_suitable:
                logger.warning(
                    f"에이전트 타입 '{agent_type}'에 적합하지 않은 쿼리입니다. "
                    f"적합성 점수: {optimization_result.suitability_score:.2f}"
                )
                # 적합하지 않아도 처리는 계속 진행
            else:
                logger.info(
                    f"쿼리 최적화 완료 - 적합성: {optimization_result.suitability_score:.2f}, "
                    f"최적화: {optimization_result.optimization_reason}"
                )
            
            # 5. 최적화된 쿼리로 처리
            optimized_query = optimization_result.optimized_query
            
            # 컨텍스트에 최적화 정보 추가
            enhanced_context = context.copy() if context else {}
            enhanced_context.update({
                'query_optimization': {
                    'original_query': query,
                    'optimized_query': optimized_query,
                    'optimized_query_en': optimization_result.optimized_query_en,
                    'suitability_score': optimization_result.suitability_score,
                    'is_suitable': optimization_result.is_suitable,
                    'optimization_reason': optimization_result.optimization_reason,
                    'agent_type': agent_type
                }
            })
            
            # 6. 실제 처리 실행
            response = await self.process(optimized_query, enhanced_context)
            
            # 7. 응답에 최적화 정보 추가
            if response.metadata is None:
                response.metadata = {}
            response.metadata['query_optimization'] = enhanced_context['query_optimization']
            
            return response
            
        except Exception as e:
            logger.error(f"쿼리 최적화 처리 중 오류 발생: {e}")
            # 오류 발생 시 원본 쿼리로 폴백
            return await self.process(query, context)
    
    def _get_agent_type_for_optimization(self) -> str:
        """최적화를 위한 에이전트 타입 반환"""
        # config에서 agent_type을 가져오고 최적화 시스템 타입으로 매핑
        if hasattr(self.config, 'agent_type'):
            agent_type_str = str(self.config.agent_type.value).lower()
            
            # 타입 매핑
            type_mapping = {
                'document_processing': 'rag',
                'text_search': 'search',
                'data_analysis': 'analysis',
                'code_generation': 'coding',
                'math_calculation': 'math',
                'weather_info': 'weather',
                'calculation': 'calculator',
                'web_search': 'internet',
                'rag': 'rag',
                'search': 'search',
                'analysis': 'analysis',
                'coding': 'coding',
                'math': 'math',
                'document': 'document',
                'weather': 'weather',
                'calculator': 'calculator',
                'internet': 'internet'
            }
            
            return type_mapping.get(agent_type_str, 'general')
        
        # 클래스 이름에서 추론
        class_name = self.__class__.__name__.lower()
        if 'rag' in class_name or 'document' in class_name:
            return 'rag'
        elif 'search' in class_name:
            return 'search'
        elif 'analysis' in class_name or 'analyze' in class_name:
            return 'analysis'
        elif 'code' in class_name or 'coding' in class_name:
            return 'coding'
        elif 'math' in class_name or 'calc' in class_name:
            return 'math'
        elif 'weather' in class_name:
            return 'weather'
        elif 'internet' in class_name or 'web' in class_name:
            return 'internet'
        else:
            return 'general'
    
    async def check_query_suitability(self, query: str) -> Dict[str, Any]:
        """
        쿼리가 이 에이전트에 적합한지 확인
        
        Args:
            query: 확인할 쿼리
            
        Returns:
            Dict[str, Any]: 적합성 정보
        """
        _lazy_import_query_optimizer()
        if check_agent_suitability is None:
            return {
                'is_suitable': True,
                'suitability_score': 0.5,
                'reason': '쿼리 최적화 시스템을 사용할 수 없음'
            }
        
        try:
            agent_type = self._get_agent_type_for_optimization()
            is_suitable, score = await check_agent_suitability(query, agent_type)
            
            return {
                'is_suitable': is_suitable,
                'suitability_score': score,
                'agent_type': agent_type,
                'reason': f'적합성 점수 기반 판단: {score:.2f}'
            }
        except Exception as e:
            logger.error(f"적합성 체크 중 오류: {e}")
            return {
                'is_suitable': True,
                'suitability_score': 0.5,
                'reason': f'적합성 체크 실패: {str(e)}'
            }
    
    async def process_with_fallback(self, request: Any) -> AgentResponse:
        """
        에이전트 처리 메서드 (에러 발생 시 라우팅 지원)
        
        이 메서드는 process 메서드를 호출하고, 오류 발생 시
        AgentRouter를 사용하여 다른 적절한 에이전트로 라우팅을 시도합니다.
        
        Args:
            request: 처리할 요청 (문자열 또는 딕셔너리)
            
        Returns:
            처리 결과
        """
        try:
            # agent_router 모듈 임포트 시도
            try:
                from .agent_router import process_with_fallback
                # AgentRouter 사용하여 처리
                return await process_with_fallback(self, request)
            except ImportError:
                # AgentRouter를 사용할 수 없는 경우 직접 처리
                return await self.process(request)
        except Exception as e:
            # 최종 에러 처리
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={
                    "answer": f"처리 중 오류: {str(e)}",
                    "error": str(e)
                },
                message=f"처리 중 오류가 발생했습니다: {str(e)}",
                metadata={"error_type": type(e).__name__}
            )
    
    def get_info(self) -> Dict[str, Any]:
        """에이전트 정보 반환
        
        Returns:
            Dict[str, Any]: 에이전트 정보
        """
        return {
            "name": self.config.name,
            "type": self.config.agent_type.value,
            "description": self.config.description,
            "capabilities": self.get_capabilities(),
            "initialized": self.initialized
        }
    
    def get_capabilities(self) -> Dict[str, Any]:
        """에이전트 기능 반환
        
        Returns:
            Dict[str, Any]: 에이전트 기능 목록
        """
        return {}

class AgentTemplate:
    """에이전트 템플릿"""
    def __init__(self, config: AgentConfig):
        self.config = config
        self.session = None
        self.llm = None
        self.chain = None
        
    @classmethod
    def create_default(cls) -> 'AgentTemplate':
        """기본 설정으로 에이전트 생성"""
        config = AgentConfig(
            name="Default Agent",
            agent_type=AgentType.UNKNOWN,
            description="기본 에이전트"
        )
        return cls(config)
        
    async def initialize(self) -> None:
        """에이전트 초기화"""
        # session은 None으로 설정하여 _process_logic이 호출되도록 합니다
        self.session = None
        
        self.llm = ChatOpenAI(
            model_name="gpt-4",
            temperature=0.3
        )
        # 체인 생성
        self.chain = self._create_classification_chain()
        
        logger.info("Agent has been successfully initialized.")
    
    async def process(self, input_data: Any) -> AgentResponse:
        """입력 데이터 처리"""
        raise NotImplementedError("이 메서드는 하위 클래스에서 구현해야 합니다.")

def create_agent(agent_type: Union[AgentType, str], config: Optional[AgentConfig] = None) -> LogosAIAgent:
    """에이전트 생성
    
    Args:
        agent_type: 생성할 에이전트 유형
        config: 에이전트 설정
        
    Returns:
        LogosAIAgent: 생성된 에이전트
        
    Raises:
        ValueError: 지원하지 않는 에이전트 유형
    """
    if isinstance(agent_type, str):
        agent_type = AgentType.from_string(agent_type)
    
    if config is None:
        config = AgentConfig(
            name=f"{agent_type.value}_agent",
            agent_type=agent_type,
            description=f"{agent_type.value} 에이전트"
        )
    
    # 에이전트 유형에 따라 적절한 클래스 반환
    if agent_type == AgentType.LLM:
        from .agents.llm import LLMAgent
        return LLMAgent(config)
    elif agent_type == AgentType.SEARCH:
        from .agents.search import SearchAgent
        return SearchAgent(config)
    else:
        raise ValueError(f"지원하지 않는 에이전트 유형: {agent_type}") 