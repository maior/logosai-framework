"""
LogosAI Agent Implementation

This module provides the base classes and utility functions for LogosAI agents.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any, Optional, Union, List, Tuple, TYPE_CHECKING
from .agent_types import AgentType, AgentResponse, AgentResponseType
from .config import AgentConfig
from loguru import logger

if TYPE_CHECKING:
    from .collaboration import CollaborationService, CollaborationResult, AgentCapability

# Optional LLM dependency
try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None

from .agent_self_assessment import AgentSelfAssessment, SelfAssessmentResult
from .dialogue_protocol import SimpleDialogueProtocol, DialogueCapability, DialogueMessage, DialogueTurn

# Query optimization system is imported later (to avoid circular references)
optimize_query_for_agent = None
check_agent_suitability = None
OptimizerAgentType = None

def _lazy_import_query_optimizer():
    """Import query optimization module when needed"""
    global optimize_query_for_agent, check_agent_suitability, OptimizerAgentType
    if optimize_query_for_agent is None:
        try:
            from .query_optimizer import optimize_query_for_agent as _optimize, check_agent_suitability as _check, AgentType as _AgentType
            optimize_query_for_agent = _optimize
            check_agent_suitability = _check
            OptimizerAgentType = _AgentType
        except ImportError:
            logger.warning("Failed to load query optimization system")

# Logging setup
logger = logging.getLogger(__name__)

class LogosAIAgent:
    """LogosAI Agent Base Class - Conditional Agentic AI Support"""

    def __init__(self, config: AgentConfig):
        """Initialize agent

        Args:
            config: Agent configuration
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.initialized = False

        # Set agent ID and name
        self.id = getattr(config, 'agent_id', self.__class__.__name__)
        self.name = getattr(config, 'name', self.__class__.__name__)

        # Check if Agentic AI features should be enabled
        self._agentic_enabled = self._should_enable_agentic()

        # Initialize Agentic AI modules (conditional)
        self._agentic_core = None
        self._agentic_reasoning = None
        self._agentic_memory = None
        self._agentic_learning = None
        self._agentic_tools = None

        if self._agentic_enabled:
            self._init_agentic_features()

        # Initialize self-assessment system
        self._self_assessment = None
        self._init_self_assessment()

        # Initialize dialogue protocol
        self._dialogue_protocol = None
        self._init_dialogue_protocol()

        # Inter-agent collaboration service (injected by ACP server at runtime)
        self._collaboration_service: Optional[CollaborationService] = None
    
    def _should_enable_agentic(self) -> bool:
        """Determine whether to enable Agentic AI features"""
        if not hasattr(self.config, 'config') or not isinstance(self.config.config, dict):
            return False

        # Check explicit enable flag
        if self.config.config.get('enable_agentic'):
            return True

        # Check if agentic_config exists
        if 'agentic_config' in self.config.config:
            return True

        return False

    def _init_agentic_features(self):
        """Initialize Agentic AI features"""
        try:
            # Dynamically import Agentic modules
            from .agentic import (
                AgenticCore,
                AgenticReasoning,
                AgenticTools,
                AgenticMemory,
                AgenticLearning
            )

            agentic_config = self.config.config.get('agentic_config', {})

            # Initialize Core module
            self._agentic_core = AgenticCore(
                agent_name=self.name,
                config=agentic_config
            )

            # Initialize Reasoning module (only if reasoning_type exists)
            if agentic_config.get('reasoning_type'):
                self._agentic_reasoning = AgenticReasoning()

            # Initialize Memory module (only if memory_capacity > 0)
            memory_capacity = agentic_config.get('memory_capacity', 0)
            if memory_capacity > 0:
                self._agentic_memory = AgenticMemory(capacity=memory_capacity)

            # Initialize Learning module (only if learning_rate > 0)
            learning_rate = agentic_config.get('learning_rate', 0)
            if learning_rate > 0:
                self._agentic_learning = AgenticLearning(learning_rate=learning_rate)

            # Initialize Tools module (only if tools_enabled)
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
        """Initialize agent

        Returns:
            bool: Whether initialization was successful
        """
        self.initialized = True
        return True

    async def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """Process query

        Args:
            query: Query to process
            context: Processing context

        Returns:
            AgentResponse: Processing result
        """
        if not self.initialized:
            await self.initialize()

        raise NotImplementedError("process method must be implemented.")

    async def process_stream(self, query: str, context: Optional[Dict[str, Any]] = None):
        """Streaming query processing - Returns intermediate results via AsyncGenerator

        Args:
            query: Query to process
            context: Processing context

        Yields:
            Dict[str, Any]: Streaming event
                - type: Event type (start, progress, chunk, complete, error)
                - data: Event data
                - timestamp: Event timestamp

        Example:
            async for event in agent.process_stream("query"):
                if event["type"] == "chunk":
                    logger.info(event["data"]["content"])
                elif event["type"] == "complete":
                    logger.info("Done:", event["data"]["result"])
        """
        import time

        if not self.initialized:
            await self.initialize()

        # Streaming start event
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
            # Progress event
            yield {
                "type": "progress",
                "data": {
                    "stage": "processing",
                    "message": f"{self.name} is processing the query..."
                },
                "timestamp": time.time()
            }

            # Execute actual processing (can be overridden in subclasses)
            result = await self.process(query, context)

            # Split result into chunks for transmission (for long responses)
            if result.type == AgentResponseType.SUCCESS:
                content = result.content
                if isinstance(content, dict):
                    answer = content.get("answer", str(content))
                else:
                    answer = str(content)

                # Split long responses into chunks
                chunk_size = 500  # Split into 500 character chunks
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
                        await asyncio.sleep(0.01)  # Slight delay for streaming effect
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

            # Complete event
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
            # If process() is not implemented
            yield {
                "type": "error",
                "data": {
                    "error": "process method is not implemented",
                    "error_type": "NotImplementedError"
                },
                "timestamp": time.time()
            }
        except Exception as e:
            # Error event
            yield {
                "type": "error",
                "data": {
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                "timestamp": time.time()
            }

    def _init_self_assessment(self):
        """Initialize self-assessment system"""
        try:
            # Get LLM client
            llm_client = getattr(self, 'llm_client', None)

            # Create AgentSelfAssessment instance
            self._self_assessment = AgentSelfAssessment(
                agent_id=getattr(self.config, 'agent_id', self.__class__.__name__),
                agent_name=getattr(self.config, 'name', self.__class__.__name__),
                llm_client=llm_client
            )

            # Set agent capabilities (can be overridden in subclasses)
            capabilities = self.get_capabilities()
            if capabilities:
                self._self_assessment.set_capabilities(capabilities)

            # Set domain keywords (can be overridden in subclasses)
            domain_keywords = self.get_domain_keywords()
            if domain_keywords:
                self._self_assessment.set_domain_keywords(domain_keywords)

        except Exception as e:
            logger.warning(f"Failed to initialize self-assessment system: {e}")
            self._self_assessment = None

    def get_capabilities(self) -> List[str]:
        """
        Return list of agent capabilities
        Override in subclasses to define specific capabilities
        """
        return []

    def get_domain_keywords(self) -> Dict[str, List[str]]:
        """
        Return domain-specific keywords
        Override in subclasses to define specific domain keywords
        """
        return {}
    
    def _init_dialogue_protocol(self):
        """Initialize dialogue protocol"""
        try:
            # Create dialogue protocol instance
            self._dialogue_protocol = SimpleDialogueProtocol(
                agent_id=self.id,
                agent_name=self.name,
                auto_participate=True  # Participate in all dialogues by default
            )

            # Connect actual processing methods to dialogue protocol
            self._dialogue_protocol.on_dialogue_invite = self._on_dialogue_invite
            self._dialogue_protocol.on_dialogue_message = self._on_dialogue_message
            self._dialogue_protocol.generate_dialogue_response = self._generate_dialogue_response

            # Set dialogue capabilities
            self._dialogue_protocol.dialogue_capability = self.get_dialogue_capability()

            logger.info(f"Dialogue protocol initialized: {self.name}")

        except Exception as e:
            logger.warning(f"Failed to initialize dialogue protocol: {e}")
            self._dialogue_protocol = None

    # ─── Agent Collaboration ────────────────────────

    def set_collaboration_service(self, service: CollaborationService) -> None:
        """
        Inject collaboration service — called by ACP server when loading agent.

        Args:
            service: CollaborationService implementation
        """
        self._collaboration_service = service

    @property
    def can_collaborate(self) -> bool:
        """Whether collaboration is possible"""
        return self._collaboration_service is not None

    async def invoke_agent(
        self,
        capability: str,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> CollaborationResult:
        """
        Call another agent to perform collaboration.

        Usage example:
            result = await self.invoke_agent(
                capability="document_processing",
                query="Analyze this PDF: https://example.com/doc.pdf"
            )
            if result.status == CollaborationStatus.COMPLETED:
                pdf_content = result.data

        Args:
            capability: Required capability (e.g., "translation", "document_processing")
            query: Query to process
            context: Additional context
            timeout: Timeout (seconds). Auto-decremented timeout if None

        Returns:
            CollaborationResult
        """
        if self._collaboration_service is None:
            from .collaboration import CollaborationResult, CollaborationStatus
            return CollaborationResult(
                request_id="no-service",
                status=CollaborationStatus.FAILED,
                error="No collaboration service available. Agent not running in ACP context.",
            )

        # Extract parent request info from context (for chain calls)
        parent_request = None
        if context and "_collaboration" in context:
            from .collaboration import CollaborationRequest
            collab_info = context["_collaboration"]
            parent_request = CollaborationRequest(
                request_id=collab_info.get("request_id", ""),
                caller_id=collab_info.get("caller_id", ""),
                depth=collab_info.get("depth", 0),
                call_chain=collab_info.get("call_chain", []),
                timeout=collab_info.get("timeout", 30.0),
            )

        return await self._collaboration_service.invoke(
            caller=self,
            capability=capability,
            query=query,
            context=context,
            timeout=timeout,
            parent_request=parent_request,
        )

    async def discover_agents(
        self, capability: str
    ) -> List[AgentCapability]:
        """
        Query list of agents with specific capability.

        Args:
            capability: Required capability

        Returns:
            List of matched agents. Empty list if service not connected.
        """
        if self._collaboration_service is None:
            return []
        return await self._collaboration_service.discover_agents(
            capability=capability, exclude_ids=[self.id]
        )

    def get_dialogue_capability(self) -> DialogueCapability:
        """
        Define agent's dialogue capabilities
        Override in subclasses to define specific capabilities
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
        Handle dialogue invitation
        Can be overridden in subclasses to implement selective participation logic
        """
        # By default, participate if related to area of expertise
        can_handle, confidence, _ = await self.can_handle(topic, context)

        if confidence > 0.5:
            logger.info(f"✅ {self.name} decided to participate in dialogue: {topic} (confidence: {confidence:.2f})")
            return True
        else:
            logger.info(f"❌ {self.name} declined dialogue participation: {topic} (confidence: {confidence:.2f})")
            return False

    async def _on_dialogue_message(self, session_id: str, message: DialogueMessage):
        """
        Handle received dialogue message
        Override in subclasses to implement specific reactions
        """
        logger.debug(f"💬 [{self.name}] Message received: [{message.speaker}] {message.content[:50]}...")

    async def _generate_dialogue_response(self, session_id: str,
                                        context: List[DialogueMessage]) -> Optional[DialogueMessage]:
        """
        Generate dialogue response
        Override in subclasses to generate intelligent responses
        """
        if not context:
            return None

        last_message = context[-1]

        # Respond to questions directed at this agent
        if last_message.turn_type == DialogueTurn.QUESTION:
            if f"@{self.id}" in last_message.content or last_message.metadata.get("target_agent") == self.id:
                # Extract question content
                question = last_message.content.replace(f"@{self.id}", "").strip()

                try:
                    # Generate answer using agent's process method
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
                    logger.error(f"Error generating dialogue response: {e}")
                    return DialogueMessage(
                        speaker=self.id,
                        turn_type=DialogueTurn.ANSWER,
                        content=f"Sorry, an error occurred while generating the response: {str(e)}",
                        in_reply_to=last_message.message_id
                    )

        return None
    
    async def can_handle(self, query: str, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, float, str]:
        """
        Evaluate whether query can be handled

        Args:
            query: User query
            context: Additional context

        Returns:
            (can_handle, confidence 0-1, reason)
        """
        if self._self_assessment is None:
            # Return default values if self-assessment system is not available
            return True, 0.5, "Self-assessment system disabled"

        try:
            # Perform self-assessment
            assessment_result = await self._self_assessment.assess_request_compatibility(query, context)

            # Convert results
            can_handle = assessment_result.can_handle
            confidence = assessment_result.confidence_score

            # Construct reason
            reasons = assessment_result.reasoning
            if assessment_result.capability_level.value:
                reasons.insert(0, f"Capability level: {assessment_result.capability_level.value}")
            reason = " | ".join(reasons[:3])  # Top 3 reasons only

            return can_handle, confidence, reason

        except Exception as e:
            logger.error(f"Error during self-assessment: {e}")
            return True, 0.5, f"Assessment error: {str(e)}"
    
    async def process_with_optimization(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        agent_type_override: Optional[str] = None
    ) -> AgentResponse:
        """
        Processing with query optimization

        This method performs the following steps:
        1. Determine agent suitability
        2. Query optimization (by agent type)
        3. Execute processing with optimized query

        Args:
            query: Original query
            context: Processing context
            agent_type_override: Agent type override (optional)

        Returns:
            AgentResponse: Processing result (includes optimization info)
        """
        if not self.initialized:
            await self.initialize()

        # 1. Check if query optimization system is available
        _lazy_import_query_optimizer()
        if optimize_query_for_agent is None:
            logger.warning("Query optimization system unavailable, processing with original query")
            return await self.process(query, context)

        try:
            # 2. Determine agent type
            agent_type = agent_type_override or self._get_agent_type_for_optimization()

            # 3. Execute query optimization
            optimization_result = await optimize_query_for_agent(
                query=query,
                agent_type=agent_type,
                agent_id=getattr(self.config, 'agent_id', None),
                context=context
            )

            # 4. Check suitability
            if not optimization_result.is_suitable:
                logger.warning(
                    f"Query not suitable for agent type '{agent_type}'. "
                    f"Suitability score: {optimization_result.suitability_score:.2f}"
                )
                # Continue processing even if not suitable
            else:
                logger.info(
                    f"Query optimization complete - suitability: {optimization_result.suitability_score:.2f}, "
                    f"optimization: {optimization_result.optimization_reason}"
                )

            # 5. Process with optimized query
            optimized_query = optimization_result.optimized_query

            # Add optimization info to context
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

            # 6. Execute actual processing
            response = await self.process(optimized_query, enhanced_context)

            # 7. Add optimization info to response
            if response.metadata is None:
                response.metadata = {}
            response.metadata['query_optimization'] = enhanced_context['query_optimization']

            return response

        except Exception as e:
            logger.error(f"Error during query optimization processing: {e}")
            # Fallback to original query on error
            return await self.process(query, context)
    
    def _get_agent_type_for_optimization(self) -> str:
        """Return agent type for optimization"""
        # Get agent_type from config and map to optimization system type
        if hasattr(self.config, 'agent_type'):
            agent_type_str = str(self.config.agent_type.value).lower()

            # Type mapping
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

        # Infer from class name
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
        Check if query is suitable for this agent

        Args:
            query: Query to check

        Returns:
            Dict[str, Any]: Suitability information
        """
        _lazy_import_query_optimizer()
        if check_agent_suitability is None:
            return {
                'is_suitable': True,
                'suitability_score': 0.5,
                'reason': 'Query optimization system unavailable'
            }

        try:
            agent_type = self._get_agent_type_for_optimization()
            is_suitable, score = await check_agent_suitability(query, agent_type)

            return {
                'is_suitable': is_suitable,
                'suitability_score': score,
                'agent_type': agent_type,
                'reason': f'Suitability score-based decision: {score:.2f}'
            }
        except Exception as e:
            logger.error(f"Error during suitability check: {e}")
            return {
                'is_suitable': True,
                'suitability_score': 0.5,
                'reason': f'Suitability check failed: {str(e)}'
            }
    
    async def process_with_fallback(self, request: Any) -> AgentResponse:
        """
        Agent processing method (with routing support on error)

        This method calls the process method, and on error
        attempts to route to another appropriate agent using AgentRouter.

        Args:
            request: Request to process (string or dictionary)

        Returns:
            Processing result
        """
        try:
            # Attempt to import agent_router module
            try:
                from .agent_router import process_with_fallback
                # Process using AgentRouter
                return await process_with_fallback(self, request)
            except ImportError:
                # Process directly if AgentRouter is unavailable
                return await self.process(request)
        except Exception as e:
            # Final error handling
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={
                    "answer": f"Processing error: {str(e)}",
                    "error": str(e)
                },
                message=f"An error occurred during processing: {str(e)}",
                metadata={"error_type": type(e).__name__}
            )

    def get_info(self) -> Dict[str, Any]:
        """Return agent information

        Returns:
            Dict[str, Any]: Agent information
        """
        return {
            "name": self.config.name,
            "type": self.config.agent_type.value,
            "description": self.config.description,
            "capabilities": self.get_capabilities(),
            "initialized": self.initialized
        }

    def get_capabilities(self) -> Dict[str, Any]:
        """Return agent capabilities

        Returns:
            Dict[str, Any]: List of agent capabilities
        """
        return {}

class AgentTemplate:
    """Agent Template"""
    def __init__(self, config: AgentConfig):
        self.config = config
        self.session = None
        self.llm = None
        self.chain = None

    @classmethod
    def create_default(cls) -> 'AgentTemplate':
        """Create agent with default configuration"""
        config = AgentConfig(
            name="Default Agent",
            agent_type=AgentType.UNKNOWN,
            description="Default agent"
        )
        return cls(config)

    async def initialize(self) -> None:
        """Initialize agent"""
        # Set session to None so that _process_logic is called
        self.session = None

        self.llm = ChatOpenAI(
            model_name="gpt-4",
            temperature=0.3
        )
        # Create chain
        self.chain = self._create_classification_chain()

        logger.info("Agent has been successfully initialized.")

    async def process(self, input_data: Any) -> AgentResponse:
        """Process input data"""
        raise NotImplementedError("This method must be implemented in subclasses.")

def create_agent(agent_type: Union[AgentType, str], config: Optional[AgentConfig] = None) -> LogosAIAgent:
    """Create agent

    Args:
        agent_type: Type of agent to create
        config: Agent configuration

    Returns:
        LogosAIAgent: Created agent

    Raises:
        ValueError: Unsupported agent type
    """
    if isinstance(agent_type, str):
        agent_type = AgentType.from_string(agent_type)

    if config is None:
        config = AgentConfig(
            name=f"{agent_type.value}_agent",
            agent_type=agent_type,
            description=f"{agent_type.value} agent"
        )

    # Return appropriate class based on agent type
    if agent_type == AgentType.LLM:
        from .agents.llm import LLMAgent
        return LLMAgent(config)
    elif agent_type == AgentType.SEARCH:
        from .agents.search import SearchAgent
        return SearchAgent(config)
    else:
        raise ValueError(f"Unsupported agent type: {agent_type}") 