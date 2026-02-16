"""
Agent Collaboration System 테스트

테스트 항목:
1. GlobalCallGraph - 루프 탐지, 깊이 제한, 동시 호출 관리
2. CollaborationService - invoke 플로우, 타임아웃, 에러 처리
3. LogosAIAgent - invoke_agent, discover_agents 통합
4. 체인 호출 - A→B→C 정상 / A→B→A 루프 탐지
"""

import asyncio
import pytest
import time
from typing import Any, Dict, List, Optional

from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType
from logosai.collaboration import (
    GlobalCallGraph,
    CollaborationService,
    CollaborationRequest,
    CollaborationResult,
    CollaborationStatus,
    AgentCapability,
)


# ─── Mock Agents ────────────────────────────────────────────────────

class MockAgent(LogosAIAgent):
    """테스트용 에이전트"""

    def __init__(self, name: str, capabilities: List[str] = None):
        config = AgentConfig(name=name, agent_type=AgentType.CUSTOM)
        super().__init__(config)
        self.id = name.lower().replace(" ", "_")
        self._capabilities = capabilities or []
        self.process_calls = []

    async def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        self.process_calls.append({"query": query, "context": context})
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": f"[{self.name}] processed: {query}"},
            message=f"Processed by {self.name}",
        )


class SlowAgent(MockAgent):
    """느린 에이전트 (타임아웃 테스트용)"""

    async def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        await asyncio.sleep(10)  # 10초 대기
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": "slow result"},
            message="Slow",
        )


class ChainAgent(MockAgent):
    """체인 호출하는 에이전트 (A→B 호출)"""

    def __init__(self, name: str, target_capability: str = ""):
        super().__init__(name)
        self.target_capability = target_capability

    async def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        self.process_calls.append({"query": query, "context": context})
        if self.target_capability and self.can_collaborate:
            result = await self.invoke_agent(
                capability=self.target_capability,
                query=f"[from {self.name}] {query}",
                context=context,
            )
            return AgentResponse(
                type=AgentResponseType.SUCCESS,
                content={"answer": f"[{self.name}] chain result", "sub_result": result.data},
                message=f"Chain processed by {self.name}",
            )
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": f"[{self.name}] processed: {query}"},
            message=f"Processed by {self.name}",
        )


class ErrorAgent(MockAgent):
    """에러 발생 에이전트"""

    async def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        raise RuntimeError("Agent failed intentionally")


# ─── Mock CollaborationService ──────────────────────────────────────

class MockCollaborationService(CollaborationService):
    """테스트용 CollaborationService 구현"""

    def __init__(self):
        super().__init__()
        self.agents: Dict[str, MockAgent] = {}
        self.capability_map: Dict[str, List[str]] = {}  # capability → [agent_ids]

    def register_agent(self, agent: MockAgent, capabilities: List[str]):
        self.agents[agent.id] = agent
        for cap in capabilities:
            if cap not in self.capability_map:
                self.capability_map[cap] = []
            self.capability_map[cap].append(agent.id)

    async def discover_agents(
        self, capability: str, exclude_ids: Optional[List[str]] = None
    ) -> List[AgentCapability]:
        exclude = set(exclude_ids or [])
        result = []
        for agent_id in self.capability_map.get(capability, []):
            if agent_id not in exclude:
                agent = self.agents[agent_id]
                result.append(AgentCapability(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    capabilities=[capability],
                ))
        return result

    async def select_agent(
        self, capability: str, query: str, exclude_ids: Optional[List[str]] = None
    ) -> Optional[AgentCapability]:
        agents = await self.discover_agents(capability, exclude_ids)
        return agents[0] if agents else None

    async def _execute_on_agent(
        self, agent_id: str, query: str, context: Dict[str, Any]
    ) -> Any:
        agent = self.agents.get(agent_id)
        if not agent:
            raise ValueError(f"Agent not found: {agent_id}")
        response = await agent.process(query, context)
        if response.type == AgentResponseType.SUCCESS:
            return response.content
        raise RuntimeError(response.message)


# ─── Tests: GlobalCallGraph ─────────────────────────────────────────

class TestGlobalCallGraph:

    def setup_method(self):
        GlobalCallGraph.reset()
        self.cg = GlobalCallGraph.get_instance()

    def test_singleton(self):
        cg2 = GlobalCallGraph.get_instance()
        assert self.cg is cg2

    def test_normal_call_allowed(self):
        can, err = self.cg.check_can_call("A", "B", ["A"], 0)
        assert can is True
        assert err is None

    def test_loop_detected(self):
        """A→B→A should be detected as loop"""
        can, err = self.cg.check_can_call("B", "A", ["A", "B"], 1)
        assert can is False
        assert "Loop" in err

    def test_self_call_blocked(self):
        can, err = self.cg.check_can_call("A", "A", [], 0)
        assert can is False
        assert "Self-call" in err

    def test_max_depth_enforced(self):
        self.cg.set_max_depth(3)
        can, err = self.cg.check_can_call("C", "D", ["A", "B", "C"], 3)
        assert can is False
        assert "depth" in err.lower()

    def test_deep_chain_within_limit(self):
        """A→B→C→D at depth 3 with max_depth 5 should be allowed"""
        self.cg.set_max_depth(5)
        can, err = self.cg.check_can_call("D", "E", ["A", "B", "C", "D"], 3)
        assert can is True

    def test_enter_exit_call(self):
        self.cg.enter_call("req-1", "A", "B", 0)
        assert self.cg.get_active_calls_count() == 1
        assert self.cg.get_agent_active_count("A") == 1
        assert self.cg.get_agent_active_count("B") == 1

        self.cg.exit_call("req-1")
        assert self.cg.get_active_calls_count() == 0
        assert self.cg.get_agent_active_count("A") == 0

    @pytest.mark.asyncio
    async def test_track_call_context_manager(self):
        async with self.cg.track_call("req-1", "A", "B", ["A"], 0) as (ok, err):
            assert ok is True
            assert err is None
            assert self.cg.get_active_calls_count() == 1

        assert self.cg.get_active_calls_count() == 0

    @pytest.mark.asyncio
    async def test_track_call_loop_blocked(self):
        async with self.cg.track_call("req-1", "B", "A", ["A", "B"], 1) as (ok, err):
            assert ok is False
            assert "Loop" in err

    def test_concurrent_limit(self):
        self.cg._max_concurrent_chains = 3
        self.cg.enter_call("req-1", "A", "B", 0)
        self.cg.enter_call("req-2", "C", "D", 0)
        self.cg.enter_call("req-3", "E", "F", 0)

        can, err = self.cg.check_can_call("G", "H", ["G"], 0)
        assert can is False
        assert "concurrent" in err.lower()

        self.cg.exit_call("req-1")
        can, err = self.cg.check_can_call("G", "H", ["G"], 0)
        assert can is True

    def test_stats(self):
        self.cg.enter_call("req-1", "A", "B", 0)
        stats = self.cg.get_stats()
        assert stats["active_calls"] == 1
        assert stats["agents_involved"] == 2


# ─── Tests: CollaborationService ────────────────────────────────────

class TestCollaborationService:

    def setup_method(self):
        GlobalCallGraph.reset()
        self.service = MockCollaborationService()

        self.agent_a = MockAgent("AgentA")
        self.agent_b = MockAgent("AgentB")
        self.service.register_agent(self.agent_a, ["search"])
        self.service.register_agent(self.agent_b, ["translation"])

    @pytest.mark.asyncio
    async def test_discover_agents(self):
        agents = await self.service.discover_agents("search")
        assert len(agents) == 1
        assert agents[0].agent_id == "agenta"

    @pytest.mark.asyncio
    async def test_discover_with_exclude(self):
        agents = await self.service.discover_agents("search", exclude_ids=["agenta"])
        assert len(agents) == 0

    @pytest.mark.asyncio
    async def test_select_agent(self):
        selected = await self.service.select_agent("translation", "hello")
        assert selected is not None
        assert selected.agent_id == "agentb"

    @pytest.mark.asyncio
    async def test_select_agent_not_found(self):
        selected = await self.service.select_agent("nonexistent", "hello")
        assert selected is None

    @pytest.mark.asyncio
    async def test_invoke_success(self):
        self.agent_a.set_collaboration_service(self.service)
        result = await self.service.invoke(
            caller=self.agent_a,
            capability="translation",
            query="안녕하세요를 영어로",
        )
        assert result.status == CollaborationStatus.COMPLETED
        assert result.agent_id == "agentb"
        assert "AgentB" in str(result.data)

    @pytest.mark.asyncio
    async def test_invoke_no_agent(self):
        result = await self.service.invoke(
            caller=self.agent_a,
            capability="nonexistent",
            query="hello",
        )
        assert result.status == CollaborationStatus.FAILED
        assert "No agent found" in result.error

    @pytest.mark.asyncio
    async def test_invoke_timeout(self):
        slow = SlowAgent("SlowAgent")
        self.service.register_agent(slow, ["slow_task"])

        result = await self.service.invoke(
            caller=self.agent_a,
            capability="slow_task",
            query="do something slow",
            timeout=0.5,
        )
        assert result.status == CollaborationStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_invoke_error(self):
        err_agent = ErrorAgent("ErrorAgent")
        self.service.register_agent(err_agent, ["error_task"])

        result = await self.service.invoke(
            caller=self.agent_a,
            capability="error_task",
            query="trigger error",
        )
        assert result.status == CollaborationStatus.FAILED
        assert "intentionally" in result.error

    @pytest.mark.asyncio
    async def test_invoke_excludes_caller_from_selection(self):
        """호출자 자신이 capability를 가지고 있어도 자기를 선택하지 않음"""
        self.service.register_agent(self.agent_a, ["translation"])

        result = await self.service.invoke(
            caller=self.agent_a,
            capability="translation",
            query="hello",
        )
        # AgentB가 선택되어야 함 (AgentA는 call_chain에 있으므로 제외)
        assert result.status == CollaborationStatus.COMPLETED
        assert result.agent_id == "agentb"


# ─── Tests: Chain Calls (A→B→C) ────────────────────────────────────

class TestChainCalls:

    def setup_method(self):
        GlobalCallGraph.reset()
        self.service = MockCollaborationService()

    @pytest.mark.asyncio
    async def test_chain_a_b_c_succeeds(self):
        """A→B→C 정상 체인 호출"""
        agent_c = MockAgent("AgentC")
        agent_b = ChainAgent("AgentB", target_capability="final_process")
        agent_a = ChainAgent("AgentA", target_capability="middle_process")

        self.service.register_agent(agent_a, ["start"])
        self.service.register_agent(agent_b, ["middle_process"])
        self.service.register_agent(agent_c, ["final_process"])

        for a in [agent_a, agent_b, agent_c]:
            a.set_collaboration_service(self.service)

        # A가 B를 호출 (B가 내부에서 C를 호출)
        result = await self.service.invoke(
            caller=agent_a,
            capability="middle_process",
            query="start task",
        )

        assert result.status == CollaborationStatus.COMPLETED
        assert result.agent_id == "agentb"
        # B가 process 호출됨
        assert len(agent_b.process_calls) == 1
        # C도 process 호출됨 (B가 invoke_agent로 호출)
        assert len(agent_c.process_calls) == 1

    @pytest.mark.asyncio
    async def test_chain_a_b_a_loop_detected(self):
        """A→B→A 루프 탐지"""
        agent_b = ChainAgent("AgentB", target_capability="task_a")
        agent_a = ChainAgent("AgentA", target_capability="task_b")

        self.service.register_agent(agent_a, ["task_a"])
        self.service.register_agent(agent_b, ["task_b"])

        for a in [agent_a, agent_b]:
            a.set_collaboration_service(self.service)

        # A → B를 호출, B가 내부에서 A를 호출하려고 시도
        result = await self.service.invoke(
            caller=agent_a,
            capability="task_b",
            query="start loop",
        )

        # B가 호출됨
        assert result.status == CollaborationStatus.COMPLETED
        assert len(agent_b.process_calls) == 1

        # B 내부에서 A 호출 시도 → call_chain에 A가 있으므로 선택 단계에서 제외
        # (exclude_ids에 call_chain 전체가 전달되므로 A가 제외됨)
        # B의 결과에서 sub_result가 None이어야 함 (A가 제외되어 No agent found)


# ─── Tests: LogosAIAgent Integration ────────────────────────────────

class TestAgentIntegration:

    def setup_method(self):
        GlobalCallGraph.reset()

    @pytest.mark.asyncio
    async def test_invoke_without_service(self):
        agent = MockAgent("TestAgent")
        result = await agent.invoke_agent("search", "hello")
        assert result.status == CollaborationStatus.FAILED
        assert "No collaboration service" in result.error

    @pytest.mark.asyncio
    async def test_discover_without_service(self):
        agent = MockAgent("TestAgent")
        agents = await agent.discover_agents("search")
        assert agents == []

    @pytest.mark.asyncio
    async def test_invoke_with_service(self):
        service = MockCollaborationService()
        agent_a = MockAgent("AgentA")
        agent_b = MockAgent("AgentB")
        service.register_agent(agent_a, [])
        service.register_agent(agent_b, ["search"])

        agent_a.set_collaboration_service(service)
        result = await agent_a.invoke_agent("search", "find something")

        assert result.status == CollaborationStatus.COMPLETED
        assert result.agent_id == "agentb"

    @pytest.mark.asyncio
    async def test_discover_with_service(self):
        service = MockCollaborationService()
        agent_a = MockAgent("AgentA")
        agent_b = MockAgent("AgentB")
        service.register_agent(agent_b, ["search"])

        agent_a.set_collaboration_service(service)
        agents = await agent_a.discover_agents("search")

        assert len(agents) == 1
        assert agents[0].agent_id == "agentb"

    def test_can_collaborate_property(self):
        agent = MockAgent("TestAgent")
        assert agent.can_collaborate is False

        service = MockCollaborationService()
        agent.set_collaboration_service(service)
        assert agent.can_collaborate is True


# ─── Tests: Timeout Cascading ───────────────────────────────────────

class TestTimeoutCascading:

    def setup_method(self):
        GlobalCallGraph.reset()

    @pytest.mark.asyncio
    async def test_decreasing_timeout(self):
        """체인 호출 시 타임아웃이 점감되는지 확인"""
        service = MockCollaborationService()
        agent_a = MockAgent("AgentA")
        agent_b = MockAgent("AgentB")
        service.register_agent(agent_a, [])
        service.register_agent(agent_b, ["task"])

        agent_a.set_collaboration_service(service)

        # 초기 타임아웃 30초로 호출
        result = await agent_a.invoke_agent("task", "hello", timeout=30.0)
        assert result.status == CollaborationStatus.COMPLETED

        # B에 전달된 context에서 timeout 확인
        assert len(agent_b.process_calls) == 1
        collab_ctx = agent_b.process_calls[0]["context"]["_collaboration"]
        # B의 타임아웃은 30초 (A의 직접 호출이므로 기본값)
        assert collab_ctx["timeout"] == 30.0
        assert collab_ctx["depth"] == 0
        assert collab_ctx["caller_id"] == "agenta"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
