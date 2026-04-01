"""
LogosAI Agent Implementation

This module provides the base classes and utility functions for LogosAI agents.
"""

from __future__ import annotations

import asyncio
import logging
import os
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

        # Agent registry for direct agent-to-agent calls (injected by ACP server)
        # Usage: result = await self.call_agent("internet_agent", "search query")
        self._agent_registry: Optional[Dict[str, 'LogosAIAgent']] = None

        # Tool registry — agents can register tools for autonomous use
        self._tools: List[Dict] = []
        self._tool_executors: Dict[str, Any] = {}

        # Memory store — persistent agent memory (PostgreSQL)
        self._memory_store = None

        # Tool usage metrics
        self._tool_metrics: Dict[str, Dict] = {}  # tool_name → {calls, successes, failures}
    
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

    # ═══════════════════════════════════════════
    # Tool Registration
    # ═══════════════════════════════════════════

    def register_tool(self, name: str, description: str, executor, parameters: Dict = None):
        """Register a tool that this agent can use autonomously.

        Args:
            name: Tool name (unique)
            description: What the tool does (LLM reads this)
            executor: Async or sync callable
            parameters: {param_name: {"type": "string", "description": "..."}}

        Example:
            agent.register_tool(
                "search", "Search the web for information",
                my_search_func,
                {"query": {"type": "string", "description": "Search query"}}
            )
        """
        # Remove existing tool with same name
        self._tools = [t for t in self._tools if t["name"] != name]
        self._tools.append({
            "name": name,
            "description": description,
            "parameters": parameters or {},
        })
        self._tool_executors[name] = executor
        self.logger.debug(f"Tool registered: {name} ({len(self._tools)} total)")

    def register_builtin_tools(self):
        """Register all built-in tools (calculator, datetime, text)."""
        try:
            from .tools import BUILTIN_TOOLS, BUILTIN_EXECUTORS
            for tool in BUILTIN_TOOLS:
                self._tools = [t for t in self._tools if t["name"] != tool["name"]]
                self._tools.append(tool)
            self._tool_executors.update(BUILTIN_EXECUTORS)
            self.logger.debug(f"Built-in tools registered: {[t['name'] for t in BUILTIN_TOOLS]}")
        except ImportError:
            self.logger.debug("Built-in tools not available")

    @property
    def has_tools(self) -> bool:
        return bool(self._tools)

    @property
    def tool_metrics(self) -> Dict[str, Dict]:
        """Get tool usage metrics: {tool_name: {calls, successes, failures}}."""
        return self._tool_metrics

    # ═══════════════════════════════════════════
    # Persistent Memory
    # ═══════════════════════════════════════════

    async def _ensure_memory(self):
        """Lazy-initialize memory store."""
        if self._memory_store is None:
            try:
                from .storage.agent_memory_store import AgentMemoryStore
                self._memory_store = AgentMemoryStore.get()
                await self._memory_store.initialize()
            except Exception as e:
                self.logger.debug(f"Memory store unavailable: {e}")

    async def memorize(self, key: str, content: str, importance: float = -1, tags: List[str] = None):
        """Store a memory for this agent.

        If importance is not provided (-1), LLM auto-evaluates it.

        Example:
            await self.memorize("gmail_tip", "Add &fs=1 to Gmail compose URL", tags=["gmail"])
            # → LLM auto-evaluates importance (e.g., 0.85)
        """
        await self._ensure_memory()
        if not self._memory_store:
            return

        # Auto-evaluate importance if not provided
        if importance < 0:
            importance = await self._evaluate_memory_importance(key, content)

        await self._memory_store.store(self.id, key, content, importance=importance, tags=tags)

    async def _evaluate_memory_importance(self, key: str, content: str) -> float:
        """LLM auto-evaluates memory importance (0.0 - 1.0)."""
        try:
            llm = getattr(self, '_llm', None) or getattr(self, 'llm_client', None)
            if not llm:
                return 0.5

            import re
            resp = await asyncio.wait_for(llm.invoke(
                f"Rate the importance of this information for an AI agent on a scale of 0.0 to 1.0.\n\n"
                f"Key: {key}\nContent: {content}\n\n"
                f"Criteria:\n"
                f"- 0.9-1.0: Critical (user preferences, recurring errors, key facts)\n"
                f"- 0.7-0.8: Important (useful patterns, domain knowledge)\n"
                f"- 0.4-0.6: Moderate (general information)\n"
                f"- 0.1-0.3: Low (trivial, temporary)\n\n"
                f"Return ONLY a number between 0.0 and 1.0."
            ), timeout=5)
            text = resp.content if hasattr(resp, 'content') else str(resp)
            match = re.search(r'(\d+\.?\d*)', text.strip())
            if match:
                return max(0.0, min(1.0, float(match.group(1))))
        except Exception:
            pass
        return 0.5  # Default fallback

    async def recall(self, query: str = "", tags: List[str] = None, top_k: int = 5) -> List[Dict]:
        """Recall relevant memories for this agent.

        Returns list of {key, content, importance, ...}
        """
        await self._ensure_memory()
        if self._memory_store:
            return await self._memory_store.recall(self.id, query=query, tags=tags, top_k=top_k)
        return []

    async def recall_as_context(self, query: str = "", top_k: int = 3) -> str:
        """Recall memories and format as LLM context string.

        Returns empty string if no relevant memories found.
        Used internally by react()/run_with_tools() for auto-injection.
        """
        memories = await self.recall(query, top_k=top_k)
        if not memories:
            return ""
        lines = [f"- {m['key']}: {m['content']}" for m in memories]
        return "Relevant memories from past interactions:\n" + "\n".join(lines)

    async def forget(self, key: str):
        """Delete a specific memory."""
        await self._ensure_memory()
        if self._memory_store:
            await self._memory_store.forget(self.id, key)

    # ═══════════════════════════════════════════
    # Tool Use Loop (Agentic AI)
    # ═══════════════════════════════════════════

    async def run_with_tools(
        self,
        query: str,
        tools: List[Dict],
        tool_executors: Dict[str, Any],
        system_prompt: str = "",
        max_iterations: int = 5,
        context: Optional[Dict[str, Any]] = None,
    ) -> 'AgentResponse':
        """Run agent with tool use loop.

        LLM decides which tools to use, executes them, observes results,
        and repeats until it has enough information to answer.

        Args:
            query: User query
            tools: Tool definitions for LLM [{name, description, parameters}]
            tool_executors: Mapping of tool name → async callable
            system_prompt: System instruction for LLM
            max_iterations: Maximum tool call rounds (safety limit)
            context: Additional context

        Returns:
            AgentResponse with final answer (after tool use)

        Example:
            tools = [{"name": "calculator", "description": "...", "parameters": {...}}]
            executors = {"calculator": async_calc_func}
            result = await agent.run_with_tools("325/60은?", tools, executors)
        """
        from .agent_types import AgentResponse, AgentResponseType

        if not self.initialized:
            await self.initialize()

        # Ensure LLM
        llm = getattr(self, '_llm', None)
        if not llm:
            try:
                from .utils.llm_client import LLMClient
                llm = LLMClient(provider="google", model="gemini-2.5-flash-lite")
                await llm.initialize()
                self._llm = llm
            except Exception as e:
                return AgentResponse(
                    type=AgentResponseType.ERROR,
                    content={"answer": f"LLM 초기화 실패: {e}"},
                    message=str(e),
                )

        # Auto-inject relevant memories
        memory_context = await self.recall_as_context(query, top_k=3)

        # Build messages
        messages = []
        sys_content = system_prompt or ""
        if memory_context:
            sys_content += f"\n\n{memory_context}"
        if sys_content:
            messages.append({"role": "system", "content": sys_content})
        messages.append({"role": "user", "content": query})

        # Context window management
        from .utils.context_manager import ContextManager
        ctx_mgr = ContextManager(max_tokens=getattr(llm, 'max_tokens', 4000) or 4000)

        # Tool use loop
        for iteration in range(max_iterations):
            # Auto-prune if context grows too large
            messages = ctx_mgr.fit_messages(messages)

            try:
                response = await asyncio.wait_for(
                    llm.invoke_with_tools(messages, tools=tools),
                    timeout=15,
                )
            except (asyncio.TimeoutError, Exception) as e:
                self.logger.warning(f"Tool loop LLM call failed (iter {iteration}): {e}")
                break

            # If no tool calls, we have the final answer
            if not response.has_tool_calls:
                return AgentResponse(
                    type=AgentResponseType.SUCCESS,
                    content={"answer": response.content, "iterations": iteration + 1},
                    message="Tool use completed",
                )

            # Execute tool calls
            for tc in response.tool_calls:
                executor = tool_executors.get(tc.name)
                if not executor:
                    # Unknown tool — tell LLM
                    messages.append({"role": "assistant", "content": f"[Tool call: {tc.name}({tc.args})]"})
                    messages.append({"role": "user", "content": f"[Tool error: '{tc.name}' is not available]"})
                    self.logger.warning(f"Tool '{tc.name}' not found in executors")
                    continue

                # Track metrics
                if tc.name not in self._tool_metrics:
                    self._tool_metrics[tc.name] = {"calls": 0, "successes": 0, "failures": 0}
                self._tool_metrics[tc.name]["calls"] += 1

                try:
                    tool_result = await asyncio.wait_for(
                        executor(**tc.args) if asyncio.iscoroutinefunction(executor) else asyncio.to_thread(executor, **tc.args),
                        timeout=10,
                    )
                    tool_result_str = str(tool_result)

                    # Validate result — empty/error detection
                    is_valid = bool(tool_result_str) and len(tool_result_str) > 1 and "Error:" not in tool_result_str
                    if is_valid:
                        self._tool_metrics[tc.name]["successes"] += 1
                        self.logger.info(f"  Tool [{tc.name}]: {tool_result_str[:80]}")
                    else:
                        self._tool_metrics[tc.name]["failures"] += 1
                        self.logger.warning(f"  Tool [{tc.name}] invalid result: {tool_result_str[:80]}")
                        tool_result_str = f"[Tool returned invalid result: {tool_result_str[:100]}. Try a different approach.]"

                except Exception as e:
                    self._tool_metrics[tc.name]["failures"] += 1
                    tool_result_str = f"[Tool error: {e}. Try a different approach or answer without this tool.]"
                    self.logger.warning(f"  Tool [{tc.name}] failed: {e}")

                # Inject tool result back into conversation
                messages.append({"role": "assistant", "content": f"[Tool call: {tc.name}({tc.args})]"})
                messages.append({"role": "user", "content": f"[Tool result: {tc.name}] {tool_result_str}"})

        # Max iterations reached — return whatever we have
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": response.content if response else "도구 실행 결과를 종합할 수 없습니다.", "iterations": max_iterations},
            message=f"Max iterations ({max_iterations}) reached",
        )

    # ═══════════════════════════════════════════
    # ReAct Loop (Think → Act → Observe)
    # ═══════════════════════════════════════════

    async def react(
        self,
        query: str,
        tools: List[Dict] = None,
        tool_executors: Dict[str, Any] = None,
        system_prompt: str = "",
        max_steps: int = 5,
        context: Optional[Dict[str, Any]] = None,
    ) -> 'AgentResponse':
        """ReAct loop: Reasoning + Acting with explicit thought/observation steps.

        Each step:
          1. THINK: LLM reasons about what to do next (visible thought)
          2. ACT: Execute a tool or generate final answer
          3. OBSERVE: Evaluate tool result, decide if more steps needed

        Args:
            query: User query
            tools: Tool definitions (optional — works without tools too)
            tool_executors: Tool name → async callable
            system_prompt: System instruction
            max_steps: Maximum reasoning steps
            context: Additional context

        Returns:
            AgentResponse with final answer + reasoning trace

        Example:
            result = await agent.react(
                "서울~부산 거리 구해서 시속100km로 걸리는 시간 계산해줘",
                tools=BUILTIN_TOOLS, tool_executors=BUILTIN_EXECUTORS,
            )
        """
        from .agent_types import AgentResponse, AgentResponseType

        if not self.initialized:
            await self.initialize()

        llm = getattr(self, '_llm', None)
        if not llm:
            try:
                from .utils.llm_client import LLMClient
                llm = LLMClient(provider="google", model="gemini-2.5-flash-lite")
                await llm.initialize()
                self._llm = llm
            except Exception as e:
                return AgentResponse(
                    type=AgentResponseType.ERROR,
                    content={"answer": f"LLM 초기화 실패: {e}"},
                    message=str(e),
                )

        # Auto-inject relevant memories into context
        memory_context = await self.recall_as_context(query, top_k=3)

        # Build ReAct system prompt
        react_system = system_prompt or "당신은 문제를 단계적으로 해결하는 AI 에이전트입니다."
        if memory_context:
            react_system += f"\n\n{memory_context}\n"
        react_system += """

You must follow the ReAct pattern strictly:

1. **Thought**: Analyze what you know and what you need to find out. Write your reasoning.
2. **Action**: If you need more information, call a tool. If you have enough info, provide the final answer.
3. **Observation**: After receiving tool results, analyze them and decide next step.

Format your response EXACTLY like this:

Thought: [your reasoning about what to do next]
Action: [tool_call OR final_answer]

When you have the final answer, respond with:
Thought: [summary of reasoning]
Final Answer: [your complete answer to the user]

Always think step by step. Never skip the Thought step."""

        messages = [{"role": "system", "content": react_system}]
        messages.append({"role": "user", "content": query})

        trace = []  # Reasoning trace for transparency
        tools = tools or []
        tool_executors = tool_executors or {}

        for step in range(max_steps):
            try:
                # THINK + ACT: LLM generates thought and decides action
                if tools and tool_executors:
                    response = await asyncio.wait_for(
                        llm.invoke_with_tools(messages, tools=tools), timeout=15
                    )
                else:
                    response = await asyncio.wait_for(
                        llm.invoke_messages(messages), timeout=15
                    )
            except (asyncio.TimeoutError, Exception) as e:
                self.logger.warning(f"ReAct step {step} failed: {e}")
                break

            content = response.content or ""

            # Parse thought from content
            thought = ""
            if "Thought:" in content:
                thought = content.split("Thought:")[-1].split("Action:")[0].split("Final Answer:")[0].strip()

            # Check for final answer
            if "Final Answer:" in content:
                final = content.split("Final Answer:")[-1].strip()
                trace.append({"step": step + 1, "type": "final", "thought": thought, "answer": final})
                return AgentResponse(
                    type=AgentResponseType.SUCCESS,
                    content={"answer": final, "steps": len(trace), "trace": trace},
                    message="ReAct completed",
                )

            # Check for tool calls (from function calling)
            if response.has_tool_calls:
                for tc in response.tool_calls:
                    trace.append({"step": step + 1, "type": "tool_call", "thought": thought, "tool": tc.name, "args": tc.args})

                    executor = tool_executors.get(tc.name)
                    if executor:
                        try:
                            result = await asyncio.wait_for(
                                executor(**tc.args) if asyncio.iscoroutinefunction(executor)
                                else asyncio.to_thread(executor, **tc.args),
                                timeout=10,
                            )
                            result_str = str(result)
                        except Exception as e:
                            result_str = f"Error: {e}"
                    else:
                        result_str = f"Tool '{tc.name}' not available"

                    trace.append({"step": step + 1, "type": "observation", "tool": tc.name, "result": result_str[:300]})
                    self.logger.info(f"  ReAct [{step+1}] {tc.name} → {result_str[:60]}")

                    # OBSERVE: inject result back
                    messages.append({"role": "assistant", "content": f"Thought: {thought}\nAction: {tc.name}({tc.args})"})
                    messages.append({"role": "user", "content": f"Observation: {result_str}"})
                continue

            # No tool call and no "Final Answer" — treat content as final
            if content.strip():
                trace.append({"step": step + 1, "type": "final", "thought": thought, "answer": content})
                # Clean up — remove ReAct markers
                clean = content
                for marker in ["Thought:", "Action:", "Observation:"]:
                    if marker in clean:
                        clean = clean.split("Final Answer:")[-1] if "Final Answer:" in clean else clean
                return AgentResponse(
                    type=AgentResponseType.SUCCESS,
                    content={"answer": clean.strip(), "steps": len(trace), "trace": trace},
                    message="ReAct completed",
                )

        # Max steps reached
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": content if content else "추론 단계를 초과했습니다.", "steps": len(trace), "trace": trace},
            message=f"ReAct max steps ({max_steps}) reached",
        )

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

    # ═══════════════════════════════════════════
    # Agent-to-Agent Communication (ACP built-in)
    # ═══════════════════════════════════════════

    async def call_agent(
        self,
        agent_id: str,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call another agent by ID. Built into the framework — no imports needed.

        Usage:
            result = await self.call_agent("internet_agent", "오늘 서울 날씨")
            if result["success"]:
                answer = result["answer"]

        Args:
            agent_id: Target agent ID (e.g., 'internet_agent', 'calculator_agent')
            query: Query string to send
            context: Optional context dict

        Returns:
            {"success": bool, "answer": str, "agent_id": str}
        """
        if self._agent_registry is None:
            self.logger.warning(f"call_agent: no registry available (not running in ACP context)")
            return {"success": False, "answer": "에이전트 간 통신이 설정되지 않았습니다. ACP 서버에서 실행해주세요."}

        target = self._agent_registry.get(agent_id)
        if target is None:
            available = list(self._agent_registry.keys())
            self.logger.warning(f"call_agent: '{agent_id}' not found. Available: {available}")
            return {"success": False, "answer": f"에이전트 '{agent_id}'를 찾을 수 없습니다."}

        try:
            caller_id = getattr(self, 'id', self.__class__.__name__)
            self.logger.info(f"call_agent: {caller_id} → {agent_id}: {query[:50]}")

            result = await target.process(query, context or {})

            # Normalize response
            if hasattr(result, 'content'):
                answer = result.content.get("answer", "") if isinstance(result.content, dict) else str(result.content)
                return {"success": True, "answer": answer, "agent_id": agent_id}
            elif isinstance(result, dict):
                return {"success": True, "agent_id": agent_id, **result}
            else:
                return {"success": True, "answer": str(result), "agent_id": agent_id}

        except Exception as e:
            self.logger.error(f"call_agent to {agent_id} failed: {e}")
            return {"success": False, "answer": f"에이전트 호출 실패: {e}", "agent_id": agent_id}

    def available_agents(self) -> List[str]:
        """List available agent IDs that can be called via call_agent().

        Usage:
            agents = self.available_agents()
            # ['internet_agent', 'calculator_agent', 'llm_search_agent', ...]
        """
        if self._agent_registry is None:
            return []
        return list(self._agent_registry.keys())

    # ═══════════════════════════════════════════
    # Dynamic Sub-Agent + Team Delegation
    # ═══════════════════════════════════════════

    def spawn_agent(
        self,
        name: str,
        description: str,
        handler,
        tools: List[Dict] = None,
        tool_executors: Dict = None,
    ) -> 'LogosAIAgent':
        """Create a specialized sub-agent at runtime.

        The spawned agent inherits this agent's LLM and registry.
        No server restart needed — lives in memory.

        Args:
            name: Agent name
            description: What this agent does
            handler: async function(query, context) → AgentResponse
            tools: Optional tool definitions
            tool_executors: Optional tool executors

        Returns:
            New agent instance (also registered in agent_registry)

        Example:
            translator = self.spawn_agent(
                "translator", "Translates text",
                handler=my_translate_func,
            )
            result = await self.call_agent("translator", "Translate to English: 안녕")
        """
        from .simple_agent import SimpleAgent
        from .agent_types import AgentResponse, AgentResponseType

        parent = self

        class SpawnedAgent(SimpleAgent):
            agent_name = name
            agent_description = description

            async def handle(self_inner, query, context=None):
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(query, context)
                else:
                    result = handler(query, context)
                if isinstance(result, AgentResponse):
                    return result
                return AgentResponse.success(content={"answer": str(result)})

        agent = SpawnedAgent()
        # Inherit parent's LLM and registry
        agent._llm = getattr(parent, '_llm', None)
        agent.llm_client = getattr(parent, 'llm_client', getattr(parent, '_llm', None))
        agent._agent_registry = parent._agent_registry

        # Register tools
        if tools and tool_executors:
            for t in tools:
                agent._tools.append(t)
            agent._tool_executors.update(tool_executors)
        elif parent.has_tools:
            agent._tools = parent._tools.copy()
            agent._tool_executors = parent._tool_executors.copy()

        # Register in agent registry so other agents can call it
        agent_id = name.lower().replace(" ", "_")
        if parent._agent_registry is not None:
            parent._agent_registry[agent_id] = agent

        self.logger.info(f"Spawned sub-agent: {name} (id={agent_id})")
        return agent

    async def delegate(
        self,
        tasks: List[Dict[str, str]],
        parallel: bool = True,
    ) -> List[Dict[str, Any]]:
        """Delegate multiple tasks to different agents and collect results.

        Args:
            tasks: List of {"agent_id": "...", "query": "..."}
            parallel: Run tasks in parallel (True) or sequential (False)

        Returns:
            List of {"agent_id": str, "success": bool, "answer": str}

        Example:
            results = await self.delegate([
                {"agent_id": "internet_agent", "query": "Tesla stock price"},
                {"agent_id": "internet_agent", "query": "Apple stock price"},
            ], parallel=True)
        """
        if parallel:
            coros = [
                self.call_agent(t["agent_id"], t["query"], t.get("context"))
                for t in tasks
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)
            return [
                r if isinstance(r, dict) else {"success": False, "answer": str(r), "agent_id": tasks[i].get("agent_id", "")}
                for i, r in enumerate(results)
            ]
        else:
            results = []
            for t in tasks:
                r = await self.call_agent(t["agent_id"], t["query"], t.get("context"))
                results.append(r)
            return results

    # ═══════════════════════════════════════════
    # L3: Real-time Collaboration
    # ═══════════════════════════════════════════

    async def ask_opinion(
        self,
        agent_id: str,
        question: str,
        my_analysis: Optional[Dict[str, Any]] = None,
    ):
        """Ask another agent for their opinion on your analysis.

        Unlike call_agent() which just sends data and gets results,
        ask_opinion() shares your reasoning and asks for judgment.

        Usage:
            opinion = await self.ask_opinion(
                "analysis_agent",
                "이 데이터에서 3월 급등 패턴이 보이는데 계절적 요인일까?",
                my_analysis={"pattern": "3월마다 급등", "confidence": 0.6}
            )
            if opinion.agrees:
                proceed_with_analysis()
            else:
                reconsider(opinion.reasoning, opinion.suggestion)

        Returns:
            Opinion(agrees, confidence, reasoning, suggestion)
        """
        from .agent_types import Opinion

        if self._agent_registry is None:
            return Opinion(agent_id=agent_id, agrees=True, confidence=0.0,
                           reasoning="ACP 미연결 — 의견 교환 불가")

        target = self._agent_registry.get(agent_id)
        if not target:
            return Opinion(agent_id=agent_id, agrees=True, confidence=0.0,
                           reasoning=f"에이전트 '{agent_id}' 없음")

        caller_id = getattr(self, 'id', self.__class__.__name__)
        self.logger.info(f"ask_opinion: {caller_id} → {agent_id}: {question[:50]}")

        try:
            # L3 context: opinion request with caller's analysis
            context = {
                "_l3_type": "ask_opinion",
                "_caller_id": caller_id,
                "_caller_analysis": my_analysis or {},
                "_question": question,
            }
            result = await target.process(question, context)

            # Parse opinion from result
            if hasattr(result, 'content') and isinstance(result.content, dict):
                content = result.content
            elif isinstance(result, dict):
                content = result
            else:
                content = {"answer": str(result)}

            return Opinion(
                agent_id=agent_id,
                agrees=content.get("agrees", True),
                confidence=content.get("confidence", 0.5),
                reasoning=content.get("reasoning", content.get("answer", "")),
                suggestion=content.get("suggestion", ""),
            )
        except Exception as e:
            self.logger.warning(f"ask_opinion failed: {e}")
            return Opinion(agent_id=agent_id, agrees=True, confidence=0.0,
                           reasoning=f"의견 교환 실패: {e}")

    async def share_finding(
        self,
        finding: Dict[str, Any],
        relevant_agents: Optional[List[str]] = None,
    ):
        """Broadcast a finding to relevant agents during work.

        Unlike call_agent(), this is informational — you're not asking for
        a result, you're sharing something you discovered.

        Usage:
            await self.share_finding(
                {"type": "data_anomaly", "detail": "2026-03 매출 데이터 누락"},
                relevant_agents=["analysis_agent", "report_agent"]
            )

        Returns:
            List[Acknowledgment]
        """
        from .agent_types import Acknowledgment

        if self._agent_registry is None:
            return []

        caller_id = getattr(self, 'id', self.__class__.__name__)
        targets = relevant_agents or list(self._agent_registry.keys())
        results = []

        for aid in targets:
            if aid == caller_id:
                continue
            target = self._agent_registry.get(aid)
            if not target:
                continue

            try:
                context = {
                    "_l3_type": "share_finding",
                    "_caller_id": caller_id,
                    "_finding": finding,
                }
                # Non-blocking: don't wait for full processing
                if hasattr(target, '_on_finding'):
                    will_act = await target._on_finding(finding, caller_id)
                    results.append(Acknowledgment(agent_id=aid, received=True, will_act=will_act))
                else:
                    results.append(Acknowledgment(agent_id=aid, received=True, will_act=False))
            except Exception:
                results.append(Acknowledgment(agent_id=aid, received=False, will_act=False))

        self.logger.info(f"share_finding: {caller_id} → {len(results)} agents, "
                         f"will_act: {sum(1 for r in results if r.will_act)}")
        return results

    async def request_help(
        self,
        agent_id: str,
        task: str,
        reason: str,
    ):
        """Request help from another agent, explaining why you need it.

        Unlike call_agent() which is a command, request_help() is a
        request — the other agent can decline if it can't help.

        Usage:
            help = await self.request_help(
                "internet_agent",
                task="작년 3월 서울 날씨 데이터",
                reason="분석 중 계절 패턴 비교 필요, 내가 접근 못하는 데이터"
            )
            if help.available:
                use_data(help.result)
            else:
                find_alternative(help.reason)

        Returns:
            HelpResult(available, result, reason)
        """
        from .agent_types import HelpResult

        if self._agent_registry is None:
            return HelpResult(agent_id=agent_id, available=False,
                              reason="ACP 미연결")

        target = self._agent_registry.get(agent_id)
        if not target:
            return HelpResult(agent_id=agent_id, available=False,
                              reason=f"에이전트 '{agent_id}' 없음")

        caller_id = getattr(self, 'id', self.__class__.__name__)
        self.logger.info(f"request_help: {caller_id} → {agent_id}: {task[:50]} (reason: {reason[:50]})")

        try:
            context = {
                "_l3_type": "request_help",
                "_caller_id": caller_id,
                "_task": task,
                "_reason": reason,
            }
            result = await target.process(task, context)

            if hasattr(result, 'content') and isinstance(result.content, dict):
                answer = result.content.get("answer", "")
            elif isinstance(result, dict):
                answer = result.get("answer", str(result))
            else:
                answer = str(result)

            return HelpResult(
                agent_id=agent_id,
                available=True,
                result=answer,
            )
        except Exception as e:
            return HelpResult(agent_id=agent_id, available=False,
                              reason=f"도움 요청 실패: {e}")

    # ═══════════════════════════════════════════
    # L4: Learning Sharing
    # ═══════════════════════════════════════════
    # L5: Self-Evaluation (opt-in)
    # ═══════════════════════════════════════════

    async def self_evaluate(self, query: str, response: 'AgentResponse',
                            context: Optional[Dict[str, Any]] = None) -> float:
        """Evaluate the quality of own response before returning to user.

        Returns quality score (0.0 - 1.0). Higher = better.
        -1.0 = evaluation not available or disabled.

        **Opt-in**: Only runs when LOGOSAI_SELF_EVAL=true env is set.
        **Non-blocking fallback**: Returns -1.0 on any error (never blocks response).

        Usage by subclasses:
            result = await self.process(query, context)
            score = await self.self_evaluate(query, result, context)
            if score >= 0 and score < 0.3:
                result = await self.process(query, context)  # retry
        """
        if not os.environ.get("LOGOSAI_SELF_EVAL"):
            return -1.0

        try:
            # Get answer text from response
            answer = ""
            if hasattr(response, 'content') and isinstance(response.content, dict):
                answer = str(response.content.get("answer", "")).strip()
            if not answer and hasattr(response, 'content') and not isinstance(response.content, dict):
                answer = str(response.content)[:500].strip()

            if not answer or len(answer) < 10:
                return -1.0  # Too short to evaluate

            # Use LLM for quality assessment
            llm = None
            if hasattr(self, '_llm') and self._llm:
                llm = self._llm
            else:
                try:
                    from logosai.utils.llm_client import LLMClient
                    llm = LLMClient(provider="google", model="gemini-2.5-flash-lite")
                    await llm.initialize()
                except Exception:
                    return -1.0

            import asyncio as _aio
            eval_prompt = (
                f"Rate the quality of this AI agent response on a scale of 0.0 to 1.0.\n\n"
                f"User query: {query[:200]}\n"
                f"Agent response: {answer[:500]}\n\n"
                f"Criteria:\n"
                f"- Relevance: Does it answer the question? (0.3 weight)\n"
                f"- Completeness: Is the answer thorough? (0.3 weight)\n"
                f"- Accuracy: Does it seem factually correct? (0.2 weight)\n"
                f"- Clarity: Is it easy to understand? (0.2 weight)\n\n"
                f"Return ONLY a number between 0.0 and 1.0, nothing else."
            )

            resp = await _aio.wait_for(llm.invoke(eval_prompt), timeout=5)
            score_text = resp.content if hasattr(resp, 'content') else str(resp)

            # Extract float from response
            import re
            match = re.search(r'(\d+\.?\d*)', score_text.strip())
            if match:
                score = float(match.group(1))
                score = max(0.0, min(1.0, score))
                self.logger.info(f"Self-eval [{self.id}]: {score:.2f} for '{query[:40]}...'")
                return score

        except Exception as e:
            self.logger.debug(f"Self-eval failed (non-fatal): {e}")

        return -1.0

    # ═══════════════════════════════════════════

    async def share_learning(self, pattern: str, solution: str,
                             confidence: float = 0.8, tags: List[str] = None):
        """Share something you learned so other agents can benefit.

        Usage:
            await self.share_learning(
                pattern="Gmail compose overlay 모드에서 JS selector 실패",
                solution="compose URL에 &fs=1 추가하면 전체 화면으로 열림",
                confidence=0.9,
                tags=["gmail", "chrome"],
            )
        """
        from .agent_types import Learning

        caller_id = getattr(self, 'id', self.__class__.__name__)
        learning = Learning(
            source_agent=caller_id,
            pattern=pattern,
            solution=solution,
            confidence=confidence,
            tags=tags or [],
        )

        # Store via ACP's LearningStore if available
        if hasattr(self, '_acp_server') and self._acp_server:
            store = getattr(self._acp_server, 'learning_store', None)
            if store:
                store.add(learning)
                self.logger.info(f"share_learning: {caller_id} → {pattern[:50]}")
                return

        # Fallback: store in instance (not shared, but at least not lost)
        if not hasattr(self, '_local_learnings'):
            self._local_learnings = []
        self._local_learnings.append(learning)
        self.logger.info(f"share_learning (local): {caller_id} → {pattern[:50]}")

    async def get_learnings(self, tags: List[str] = None,
                            source_agent: str = None):
        """Get learnings shared by other agents.

        Usage:
            learnings = await self.get_learnings(tags=["gmail"])
            for l in learnings:
                print(f"{l.source_agent}: {l.pattern} → {l.solution}")
        """
        # Try ACP's LearningStore first
        if hasattr(self, '_acp_server') and self._acp_server:
            store = getattr(self._acp_server, 'learning_store', None)
            if store:
                return store.query(tags=tags, source_agent=source_agent)

        # Fallback: local learnings
        learnings = getattr(self, '_local_learnings', [])
        if tags:
            learnings = [l for l in learnings if any(t in l.tags for t in tags)]
        if source_agent:
            learnings = [l for l in learnings if l.source_agent == source_agent]
        return learnings

    # Optional hook for receiving findings from other agents
    async def _on_finding(self, finding: Dict[str, Any], from_agent: str) -> bool:
        """Override to react to findings shared by other agents.

        Returns True if this agent will act on the finding.
        """
        return False

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