"""ToolUseMixin — 도구 등록 + Tool Use Loop.

agent.py에서 분리. 사용하는 인스턴스 변수:
  self._tools: List[Dict]
  self._tool_executors: Dict[str, Any]
  self._tool_metrics: Dict[str, Dict]
  self._llm: LLMClient (lazy)
  self.initialized: bool
  self.logger: Logger
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any, Optional, List, TYPE_CHECKING


class ToolUseMixin:
    """도구 등록 및 Tool Use Loop 기능."""

    def _init_tool_use(self):
        """__init__에서 호출. 도구 관련 인스턴스 변수 초기화."""
        self._tools: List[Dict] = []
        self._tool_executors: Dict[str, Any] = {}
        self._tool_metrics: Dict[str, Dict] = {}

    def register_tool(self, name: str, description: str, executor, parameters: Dict = None):
        """Register a tool that this agent can use autonomously.

        Args:
            name: Tool name (unique)
            description: What the tool does (LLM reads this)
            executor: Async or sync callable
            parameters: {param_name: {"type": "string", "description": "..."}}
        """
        self._tools = [t for t in self._tools if t["name"] != name]
        self._tools.append({
            "name": name,
            "description": description,
            "parameters": parameters or {},
        })
        self._tool_executors[name] = executor
        self.logger.debug(f"Tool registered: {name} ({len(self._tools)} total)")

    def register_tool_object(self, tool) -> None:
        """Register a Tool dataclass or @tool_decorator result.

        agentic/tools.py의 Tool 객체를 직접 등록. Tool의 category, ToolParameter
        정보가 보존되어 LLM에게 더 정확한 도구 정보를 제공합니다.

        Args:
            tool: Tool dataclass instance (from agentic/tools.py or @tool_decorator)

        Example:
            from logosai.agentic.tools import Tool, ToolParameter, ToolCategory, tool_decorator

            # 방법 1: Tool 직접 생성
            tool = Tool(name="search", description="웹 검색",
                        category=ToolCategory.WEB_ACCESS, function=search_func,
                        parameters=[ToolParameter("query", "str", "검색어")])
            agent.register_tool_object(tool)

            # 방법 2: @tool_decorator
            @tool_decorator("calc", "계산기", ToolCategory.CALCULATION)
            async def calculator(expression: str) -> str: ...
            agent.register_tool_object(calculator)
        """
        # Tool의 parameters를 run_with_tools가 사용하는 dict 형식으로 변환
        params_dict = {}
        if hasattr(tool, 'parameters') and tool.parameters:
            for p in tool.parameters:
                params_dict[p.name] = {
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                }

        # 카테고리 정보 보존
        category = ""
        if hasattr(tool, 'category'):
            category = tool.category.value if hasattr(tool.category, 'value') else str(tool.category)

        self._tools = [t for t in self._tools if t["name"] != tool.name]
        self._tools.append({
            "name": tool.name,
            "description": tool.description,
            "parameters": params_dict,
            "category": category,
        })
        self._tool_executors[tool.name] = tool.function
        self.logger.debug(f"Tool object registered: {tool.name} (category={category}, {len(self._tools)} total)")

    def register_builtin_tools(self):
        """Register all built-in tools (calculator, datetime, text)."""
        try:
            from ..tools import BUILTIN_TOOLS, BUILTIN_EXECUTORS
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
        """
        from ..agent_types import AgentResponse, AgentResponseType

        if not self.initialized:
            await self.initialize()

        # Ensure LLM
        llm = getattr(self, '_llm', None)
        if not llm:
            try:
                from ..utils.llm_client import LLMClient
                from ..config.llm_defaults import get_default_provider, get_default_model
                llm = LLMClient(provider=get_default_provider(), model=get_default_model())
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
        from ..utils.context_manager import ContextManager
        ctx_mgr = ContextManager(max_tokens=getattr(llm, 'max_tokens', 4000) or 4000)

        # Tool use loop
        response = None
        for iteration in range(max_iterations):
            messages = ctx_mgr.fit_messages(messages)

            try:
                response = await asyncio.wait_for(
                    llm.invoke_with_tools(messages, tools=tools),
                    timeout=15,
                )
            except (asyncio.TimeoutError, Exception) as e:
                self.logger.warning(f"Tool loop LLM call failed (iter {iteration}): {e}")
                break

            if not response.has_tool_calls:
                return AgentResponse(
                    type=AgentResponseType.SUCCESS,
                    content={"answer": response.content, "iterations": iteration + 1},
                    message="Tool use completed",
                )

            for tc in response.tool_calls:
                executor = tool_executors.get(tc.name)
                if not executor:
                    messages.append({"role": "assistant", "content": f"[Tool call: {tc.name}({tc.args})]"})
                    messages.append({"role": "user", "content": f"[Tool error: '{tc.name}' is not available]"})
                    self.logger.warning(f"Tool '{tc.name}' not found in executors")
                    continue

                if tc.name not in self._tool_metrics:
                    self._tool_metrics[tc.name] = {"calls": 0, "successes": 0, "failures": 0}
                self._tool_metrics[tc.name]["calls"] += 1

                try:
                    tool_result = await asyncio.wait_for(
                        executor(**tc.args) if asyncio.iscoroutinefunction(executor) else asyncio.to_thread(executor, **tc.args),
                        timeout=10,
                    )
                    tool_result_str = str(tool_result)

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

                messages.append({"role": "assistant", "content": f"[Tool call: {tc.name}({tc.args})]"})
                messages.append({"role": "user", "content": f"[Tool result: {tc.name}] {tool_result_str}"})

        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": response.content if response else "도구 실행 결과를 종합할 수 없습니다.", "iterations": max_iterations},
            message=f"Max iterations ({max_iterations}) reached",
        )
