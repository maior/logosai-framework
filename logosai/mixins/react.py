"""ReActMixin — ReAct Loop (Think → Act → Observe).

agent.py에서 분리. 사용하는 인스턴스 변수:
  self._llm: LLMClient (lazy)
  self.initialized: bool
  self.logger: Logger
의존: MemoryMixin.recall_as_context()
"""

from __future__ import annotations

import asyncio
from typing import Dict, Any, Optional, List


class ReActMixin:
    """ReAct 패턴 — Thought/Action/Observation 루프."""

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
          1. THINK: LLM reasons about what to do next
          2. ACT: Execute a tool or generate final answer
          3. OBSERVE: Evaluate tool result, decide if more steps needed
        """
        from ..agent_types import AgentResponse, AgentResponseType

        if not self.initialized:
            await self.initialize()

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

        memory_context = await self.recall_as_context(query, top_k=3)

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

        trace = []
        tools = tools or []
        tool_executors = tool_executors or {}
        content = ""

        for step in range(max_steps):
            try:
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

            thought = ""
            if "Thought:" in content:
                thought = content.split("Thought:")[-1].split("Action:")[0].split("Final Answer:")[0].strip()

            if "Final Answer:" in content:
                final = content.split("Final Answer:")[-1].strip()
                trace.append({"step": step + 1, "type": "final", "thought": thought, "answer": final})
                return AgentResponse(
                    type=AgentResponseType.SUCCESS,
                    content={"answer": final, "steps": len(trace), "trace": trace},
                    message="ReAct completed",
                )

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

                    messages.append({"role": "assistant", "content": f"Thought: {thought}\nAction: {tc.name}({tc.args})"})
                    messages.append({"role": "user", "content": f"Observation: {result_str}"})
                continue

            if content.strip():
                trace.append({"step": step + 1, "type": "final", "thought": thought, "answer": content})
                clean = content
                for marker in ["Thought:", "Action:", "Observation:"]:
                    if marker in clean:
                        clean = clean.split("Final Answer:")[-1] if "Final Answer:" in clean else clean
                return AgentResponse(
                    type=AgentResponseType.SUCCESS,
                    content={"answer": clean.strip(), "steps": len(trace), "trace": trace},
                    message="ReAct completed",
                )

        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": content if content else "추론 단계를 초과했습니다.", "steps": len(trace), "trace": trace},
            message=f"ReAct max steps ({max_steps}) reached",
        )
