"""PlanningMixin — Goal Decomposition (Plan → Execute).

agent.py에서 분리. 의존:
  ReActMixin.react()
  ToolUseMixin._tools, _tool_executors
  self._llm / self.llm_client
  self.initialized, self.logger
"""

from __future__ import annotations

import asyncio
from typing import Dict, Any, Optional, List


class PlanningMixin:
    """Goal 분해 + 실행 — plan(), plan_stream()."""

    async def plan(
        self,
        query: str,
        tools: List[Dict] = None,
        tool_executors: Dict[str, Any] = None,
        system_prompt: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> 'AgentResponse':
        """Decompose a complex query into sub-goals and execute each.

        For simple queries: runs as single step (no overhead).
        For complex queries: breaks into sub-goals with dependencies,
        executes in order, combines results.
        """
        from ..agent_types import AgentResponse, AgentResponseType
        from ..agentic.planner import plan_goal, execute_goal_tree

        if not self.initialized:
            await self.initialize()

        llm = getattr(self, '_llm', None) or getattr(self, 'llm_client', None)

        try:
            tree = await plan_goal(query, llm=llm)
        except Exception as e:
            self.logger.warning(f"Plan failed, falling back to react: {e}")
            return await self.react(query, tools, tool_executors, system_prompt, context=context)

        num_goals = len(tree.root.sub_goals)
        self.logger.info(f"Plan: {num_goals} goals for '{query[:40]}'")

        if num_goals <= 1:
            return await self.react(query, tools, tool_executors, system_prompt, context=context)

        _tools = tools or self._tools
        _executors = tool_executors or self._tool_executors

        async def goal_executor(title, goal_context=None):
            ctx_str = ""
            if goal_context:
                ctx_str = "\n".join([f"- {v[:100]}" for v in goal_context.values() if v])
            sub_prompt = title
            if ctx_str:
                sub_prompt = f"{title}\n\nContext from previous steps:\n{ctx_str}"
            result = await self.react(
                sub_prompt,
                tools=_tools if _tools else None,
                tool_executors=_executors if _executors else None,
                system_prompt=system_prompt,
                max_steps=3,
            )
            return result.content.get("answer", str(result.content)) if isinstance(result.content, dict) else str(result.content)

        await execute_goal_tree(tree, executor=goal_executor)

        results = tree.get_completed_results()
        combined = "\n\n".join([
            f"**{tree.get(gid).title}**:\n{result}"
            for gid, result in results.items()
            if gid != "root"
        ])

        if num_goals >= 3 and llm:
            try:
                synth = await asyncio.wait_for(llm.invoke(
                    f"아래 단계별 결과를 종합하여 사용자의 원래 질문에 대한 최종 답변을 작성하세요.\n\n"
                    f"원래 질문: {query}\n\n단계별 결과:\n{combined[:3000]}\n\n"
                    f"종합적이고 정리된 최종 답변을 작성하세요."
                ), timeout=15)
                final = synth.content if hasattr(synth, 'content') else str(synth)
            except Exception:
                final = combined
        else:
            final = combined

        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={
                "answer": final,
                "goals": num_goals,
                "progress": f"{tree.progress:.0%}",
                "tree": tree.root.to_dict(),
            },
            message=f"Plan completed ({num_goals} goals)",
        )

    async def plan_stream(
        self,
        query: str,
        tools: List[Dict] = None,
        tool_executors: Dict[str, Any] = None,
        system_prompt: str = "",
        context: Optional[Dict[str, Any]] = None,
    ):
        """Plan with real-time progress streaming.

        Yields SSE events as each sub-goal executes.
        """
        from ..agent_types import AgentResponse, AgentResponseType
        from ..agentic.planner import plan_goal, execute_goal_tree_stream
        import time as _time

        if not self.initialized:
            await self.initialize()

        llm = getattr(self, '_llm', None) or getattr(self, 'llm_client', None)

        try:
            tree = await plan_goal(query, llm=llm)
        except Exception as e:
            yield {"type": "error", "data": {"error": f"Plan failed: {e}"}, "timestamp": _time.time()}
            return

        num_goals = len(tree.root.sub_goals)

        yield {
            "type": "plan_created",
            "data": {"goals": num_goals, "tree": tree.root.to_dict(), "query": query[:100]},
            "timestamp": _time.time(),
        }

        if num_goals <= 1:
            yield {"type": "goal_started", "data": {"goal_id": "g1", "title": query[:60], "progress": "0%"}, "timestamp": _time.time()}
            result = await self.react(query, tools, tool_executors, system_prompt, context=context)
            answer = result.content.get("answer", "") if isinstance(result.content, dict) else str(result.content)
            yield {"type": "goal_completed", "data": {"goal_id": "g1", "title": query[:60], "result": answer[:200], "progress": "100%"}, "timestamp": _time.time()}
            yield {"type": "plan_completed", "data": {"answer": answer, "goals": 1}, "timestamp": _time.time()}
            return

        _tools = tools or self._tools
        _executors = tool_executors or self._tool_executors

        async def goal_executor(title, goal_context=None):
            ctx_str = ""
            if goal_context:
                ctx_str = "\n".join([f"- {v[:100]}" for v in goal_context.values() if v])
            sub_prompt = title
            if ctx_str:
                sub_prompt = f"{title}\n\nContext from previous steps:\n{ctx_str}"
            result = await self.react(
                sub_prompt,
                tools=_tools if _tools else None,
                tool_executors=_executors if _executors else None,
                system_prompt=system_prompt,
                max_steps=3,
            )
            return result.content.get("answer", str(result.content)) if isinstance(result.content, dict) else str(result.content)

        async for event in execute_goal_tree_stream(tree, executor=goal_executor):
            yield {"type": event["event"], "data": event["data"], "timestamp": _time.time()}

        results = tree.get_completed_results()
        combined = "\n\n".join([
            f"**{tree.get(gid).title}**:\n{result}"
            for gid, result in results.items() if gid != "root"
        ])

        if num_goals >= 3 and llm:
            try:
                synth = await asyncio.wait_for(llm.invoke(
                    f"아래 단계별 결과를 종합하여 원래 질문에 대한 최종 답변을 작성하세요.\n\n"
                    f"질문: {query}\n\n결과:\n{combined[:3000]}\n\n종합 답변 작성."
                ), timeout=15)
                final = synth.content if hasattr(synth, 'content') else str(synth)
            except Exception:
                final = combined
        else:
            final = combined

        yield {
            "type": "plan_completed",
            "data": {"answer": final, "goals": num_goals, "progress": f"{tree.progress:.0%}"},
            "timestamp": _time.time(),
        }
