"""MultiAgentMixin — 에이전트 간 통신, 위임, 동적 생성.

agent.py에서 분리. 사용하는 인스턴스 변수:
  self._agent_registry: Dict[str, LogosAIAgent] (ACP 서버가 주입)
  self.logger: Logger
  self.id: str
  self._tools, self._tool_executors: ToolUseMixin에서
"""

from __future__ import annotations

import asyncio
from typing import Dict, Any, Optional, List


class MultiAgentMixin:
    """에이전트 간 호출, 위임, 동적 생성."""

    def _init_multi_agent(self):
        """__init__에서 호출. 멀티에이전트 관련 인스턴스 변수 초기화."""
        self._agent_registry = None

    async def call_agent(
        self,
        agent_id: str,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call another agent by ID.

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

            _span = None
            try:
                from logosai.utils.trace_span import TraceSpan
                _span = TraceSpan.start(
                    name=f"call_agent({agent_id})",
                    agent_id=agent_id,
                    input_text=query[:200],
                )
            except Exception:
                pass

            result = await target.process(query, context or {})

            if hasattr(result, 'content'):
                answer = result.content.get("answer", "") if isinstance(result.content, dict) else str(result.content)
                if _span: _span.end(success=True, output=answer[:200])
                return {"success": True, "answer": answer, "agent_id": agent_id}
            elif isinstance(result, dict):
                if _span: _span.end(success=True, output=str(result.get("answer", ""))[:200])
                return {"success": True, "agent_id": agent_id, **result}
            else:
                if _span: _span.end(success=True, output=str(result)[:200])
                return {"success": True, "answer": str(result), "agent_id": agent_id}

        except Exception as e:
            self.logger.error(f"call_agent to {agent_id} failed: {e}")
            if _span: _span.end(success=False, output=str(e)[:200])
            return {"success": False, "answer": f"에이전트 호출 실패: {e}", "agent_id": agent_id}

    def available_agents(self) -> List[str]:
        """List available agent IDs that can be called via call_agent()."""
        if self._agent_registry is None:
            return []
        return list(self._agent_registry.keys())

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
        """
        from ..simple_agent import SimpleAgent
        from ..agent_types import AgentResponse, AgentResponseType

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
        agent._llm = getattr(parent, '_llm', None)
        agent.llm_client = getattr(parent, 'llm_client', getattr(parent, '_llm', None))
        agent._agent_registry = parent._agent_registry

        if tools and tool_executors:
            for t in tools:
                agent._tools.append(t)
            agent._tool_executors.update(tool_executors)
        elif parent.has_tools:
            agent._tools = parent._tools.copy()
            agent._tool_executors = parent._tool_executors.copy()

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
        """Delegate multiple tasks to different agents and collect results."""
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
