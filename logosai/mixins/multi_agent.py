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
                    stage="a2a_call",
                    metadata={"caller_id": caller_id},
                )
            except Exception:
                pass

            import time as _tmod
            _conv_t0 = _tmod.time()

            def _log_conv(answer: str, status: str):
                try:
                    from logosai.utils.pulse_client import send_conversation_bg
                    from logosai.utils.trace_span import get_current_trace_id
                    send_conversation_bg(
                        trace_id=get_current_trace_id() or "",
                        caller=caller_id, callee=agent_id, channel="call_agent",
                        query=str(query), answer=str(answer), status=status,
                        duration_ms=(_tmod.time() - _conv_t0) * 1000, started_at=_conv_t0,
                    )
                except Exception:
                    pass

            try:
                result = await target.process(query, context or {})
            except asyncio.CancelledError:
                # wait_for 등에 의한 취소 — BaseException이라 아래 except에 안 잡힘.
                # 취소돼도 span/대화 기록은 남긴다 (관측 증발 방지).
                if _span: _span.end(success=False, output="cancelled (timeout)")
                _log_conv("", "cancelled")
                raise

            if hasattr(result, 'content'):
                if isinstance(result.content, dict):
                    answer = result.content.get("answer", "")
                    if _span: _span.end(success=True, output=str(answer)[:200])
                    _log_conv(str(answer), "success")
                    # content 전체 보존(협업: products/citations/breakdown/weights 등).
                    # 명시 키(success/agent_id/answer)를 마지막에 둬 하위호환·일관성 보장.
                    return {**result.content, "success": True, "agent_id": agent_id, "answer": answer}
                answer = str(result.content)
                if _span: _span.end(success=True, output=answer[:200])
                _log_conv(answer, "success")
                return {"success": True, "answer": answer, "agent_id": agent_id}
            elif isinstance(result, dict):
                if _span: _span.end(success=True, output=str(result.get("answer", ""))[:200])
                _log_conv(str(result.get("answer", "")), "success")
                return {"success": True, "agent_id": agent_id, **result}
            else:
                if _span: _span.end(success=True, output=str(result)[:200])
                return {"success": True, "answer": str(result), "agent_id": agent_id}

        except Exception as e:
            self.logger.error(f"call_agent to {agent_id} failed: {e}")
            if _span: _span.end(success=False, output=str(e)[:200])
            try:
                _log_conv(str(e), "error")
            except Exception:
                pass
            return {"success": False, "answer": f"에이전트 호출 실패: {e}", "agent_id": agent_id}

    def available_agents(self) -> List[str]:
        """List available agent IDs that can be called via call_agent()."""
        if self._agent_registry is None:
            return []
        return list(self._agent_registry.keys())

    async def request_upstream(
        self,
        agent_id: str,
        need: str,
        context: Optional[Dict[str, Any]] = None,
        max_depth: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """역방향 채널 — 상류 에이전트에 구조화 재요청 (Agentic Upgrade Phase 4).

        멀티스테이지 워크플로우에서 하류 에이전트가 받은 데이터로 작업이 불가할 때
        (예: 시각화할 수치 시리즈 없음) 조용히 포기하는 대신 상류에 "이런 형식으로
        다시" 를 요청한다. 재귀 상한(depth)으로 무한 왕복을 차단하고, 대용량
        previous_results 는 재전파하지 않는다.

        Returns:
            call_agent 결과 dict(success=True 일 때만), 그 외 None — 호출측이
            기존 폴백(passthrough 등)으로 진행한다.
        """
        ctx = dict(context or {})
        depth = 0
        try:
            depth = int(ctx.get("_upstream_depth") or 0)
        except (TypeError, ValueError):
            pass
        if depth >= max_depth:
            self.logger.info(
                f"request_upstream: depth {depth} ≥ {max_depth}, 재요청 생략 (재귀 상한)")
            return None
        ctx["_upstream_depth"] = depth + 1
        ctx.pop("previous_results", None)

        # SDK 를 상속하지 않는 "독립 구현" 에이전트도 unbound 호출로 쓸 수 있게
        # (요구 속성: _agent_registry, logger — viz 등 레거시 독립 에이전트 실측)
        call = getattr(self, "call_agent", None)
        if call is None:
            async def call(a, q, c):
                return await MultiAgentMixin.call_agent(self, a, q, c)
        result = await call(agent_id, need, ctx)
        if not (isinstance(result, dict) and result.get("success")):
            return None
        return result

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

    async def _delegate_span(self, n_tasks: int, parallel: bool):
        try:
            from logosai.utils.trace_span import TraceSpan
            return TraceSpan.start(
                name=f"delegate(x{n_tasks})",
                agent_id=getattr(self, 'id', self.__class__.__name__),
                stage="a2a_call",
                metadata={"parallel": parallel, "tasks": n_tasks},
            )
        except Exception:
            return None

    async def delegate(
        self,
        tasks: List[Dict[str, str]],
        parallel: bool = True,
    ) -> List[Dict[str, Any]]:
        """Delegate multiple tasks to different agents and collect results."""
        _span = await self._delegate_span(len(tasks), parallel)
        try:
            if parallel:
                coros = [
                    self.call_agent(t["agent_id"], t["query"], t.get("context"))
                    for t in tasks
                ]
                results = await asyncio.gather(*coros, return_exceptions=True)
                out = [
                    r if isinstance(r, dict) else {"success": False, "answer": str(r), "agent_id": tasks[i].get("agent_id", "")}
                    for i, r in enumerate(results)
                ]
            else:
                out = []
                for t in tasks:
                    r = await self.call_agent(t["agent_id"], t["query"], t.get("context"))
                    out.append(r)
            if _span:
                ok = sum(1 for r in out if isinstance(r, dict) and r.get("success"))
                _span.end(success=True, output=f"{ok}/{len(out)} success")
            return out
        except Exception as e:
            if _span:
                _span.end(success=False, output=str(e)[:200])
            raise
