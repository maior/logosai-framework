"""
Workflow Orchestrator

Main entry point for the orchestration system. Coordinates all components
to execute user queries through intelligent multi-agent workflows.

Pipeline:
1. Query → QueryPlanner (Flash-Lite) → ExecutionPlan
2. ExecutionPlan → PlanValidator → Validated Plan
3. Validated Plan → ExecutionEngine → Stage Results
4. Stage Results → ResultAggregator → Final Output

All with real-time progress streaming to frontend.

정본 이전 (2026-10-05, orchestrator-unify P3): ontology/orchestrator/workflow_orchestrator.py
에서 옮겼다. 조직별 오케스트레이터는 _make_planner 를 재정의해 자기 플래너를 쓴다 —
Logos 운영 인스턴스가 ontology.orchestrator.WorkflowOrchestrator 다. 옮기기 전후
동작이 같음은 ontology 의 tests/test_orchestrator_characterization.py 가 확인한다.

구 logosai.workflow.WorkflowOrchestrator 와는 다른 클래스다.
"""

import asyncio
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from .models import (
    ExecutionPlan,
    WorkflowResult,
    ProgressEvent,
    ProgressEventType,
)
from .agent_registry import AgentRegistry, get_registry
from .planner import LLMInvoke, QueryPlanner
from .plan_validator import PlanValidator
from .data_transformer import DataTransformer
from .execution_engine import ExecutionEngine, AgentExecutor
from .result_aggregator import ResultAggregator
from .progress_streamer import ProgressStreamer
from .exceptions import OrchestratorError, PlanValidationError

logger = logging.getLogger(__name__)


class WorkflowOrchestrator:
    """
    Main orchestration coordinator.

    Provides a high-level API for executing user queries through
    intelligent multi-agent workflows.

    Example (simple):
        orchestrator = WorkflowOrchestrator(agent_executor=my_executor)
        result = await orchestrator.run("Compare today's weather in Seoul and Busan")
        print(result.final_output)

    Example (with streaming):
        orchestrator = WorkflowOrchestrator(agent_executor=my_executor)

        async for event in orchestrator.run_streaming("query"):
            print(f"{event.type}: {event.message}")
            if event.type == "workflow_complete":
                print(f"Result: {event.data}")
    """

    def __init__(
        self,
        agent_executor: Optional[AgentExecutor] = None,
        registry: Optional[AgentRegistry] = None,
        enable_validation: bool = True,
        enable_streaming: bool = True,
        llm_invoke: Optional[LLMInvoke] = None,
    ):
        """
        Initialize Workflow Orchestrator.

        Args:
            agent_executor: Function to execute agents
            registry: Agent registry (uses default if not provided)
            enable_validation: Whether to validate plans before execution
            enable_streaming: Whether to emit progress events
            llm_invoke: 플래너가 쓸 LLM (async prompt -> str). 없으면 LLMClient
        """
        self.registry = registry or get_registry()
        self.enable_validation = enable_validation
        self.enable_streaming = enable_streaming

        # Initialize components (will be fully initialized in run())
        self._agent_executor = agent_executor
        self._llm_invoke = llm_invoke
        self._planner: Optional[QueryPlanner] = None
        self._validator: Optional[PlanValidator] = None
        self._transformer: Optional[DataTransformer] = None
        self._engine: Optional[ExecutionEngine] = None
        self._aggregator: Optional[ResultAggregator] = None

    def _init_components(self, streamer: Optional[ProgressStreamer]) -> None:
        """Initialize all components with shared streamer"""
        self._planner = self._make_planner(streamer)

        # 산출물 관문에 플래너의 LLM 을 빌려준다. 없으면 관문은 침묵한다
        # (관문 때문에 별도 LLM 배선을 만들지 않는다 — 실패 지점이 늘어난다).
        async def _validator_llm(prompt: str) -> str:
            return await self._planner._call_llm(prompt)

        self._validator = PlanValidator(
            registry=self.registry,
            streamer=streamer,
            llm_invoke=_validator_llm,
        )

        self._transformer = DataTransformer(
            registry=self.registry,
            streamer=streamer,
        )

        self._engine = ExecutionEngine(
            agent_executor=self._agent_executor,
            registry=self.registry,
            transformer=self._transformer,
            streamer=streamer,
        )

        self._aggregator = ResultAggregator(
            streamer=streamer,
        )

    def _make_planner(self, streamer: Optional[ProgressStreamer]) -> QueryPlanner:
        """플래너 생성 훅 — 조직별 오케스트레이터가 자기 플래너로 바꾼다."""
        return QueryPlanner(registry=self.registry, streamer=streamer, llm_invoke=self._llm_invoke)

    async def run(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> WorkflowResult:
        """
        Execute a query and return the result.

        Args:
            query: User query to process
            context: Optional execution context

        Returns:
            WorkflowResult with final output and all intermediate results
        """
        workflow_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        # Create streamer (without listeners, just for internal tracking)
        streamer = ProgressStreamer(
            workflow_id=workflow_id,
            include_debug=False,
        ) if self.enable_streaming else None

        # Initialize components
        self._init_components(streamer)

        logger.info(f"[Orchestrator] Starting workflow {workflow_id}: {query[:50]}...")

        try:
            # Step 1: Create execution plan
            plan = await self._planner.create_plan(query, context)

            # Step 2: Validate plan
            if self.enable_validation:
                validation_result = await self._validator.validate(plan)
                if not validation_result.is_valid:
                    raise PlanValidationError(
                        message="Plan validation failed",
                        validation_errors=validation_result.errors,
                    )

            # Step 3: Execute plan
            result = await self._engine.execute(plan, context)

            # Log completion
            total_time = (time.time() - start_time) * 1000
            logger.info(
                f"[Orchestrator] Workflow {workflow_id} completed in {total_time:.0f}ms"
            )

            return result

        except Exception as e:
            logger.error(f"[Orchestrator] Workflow {workflow_id} failed: {e}")
            raise

        finally:
            # Cleanup
            if streamer:
                await streamer.close()

    async def run_streaming(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """
        Execute a query with real-time progress streaming.

        Yields progress events that can be sent to frontend.

        Args:
            query: User query to process
            context: Optional execution context

        Yields:
            ProgressEvent for each stage of execution
        """
        workflow_id = str(uuid.uuid4())[:8]

        # Create streamer with buffer
        streamer = ProgressStreamer(
            workflow_id=workflow_id,
            buffer_size=200,
            include_debug=False,
        )

        # Initialize components
        self._init_components(streamer)

        # Create task to run workflow
        result_holder = {"result": None, "error": None, "plan": None}

        async def run_workflow():
            try:
                plan = await self._planner.create_plan(query, context)
                result_holder["plan"] = plan

                if self.enable_validation:
                    validation_result = await self._validator.validate(plan)
                    if not validation_result.is_valid:
                        raise PlanValidationError(
                            message="Plan validation failed",
                            validation_errors=validation_result.errors,
                        )

                result = await self._engine.execute(plan, context)
                result_holder["result"] = result

                # Store success feedback to HybridAgentSelector for learning
                await self._store_feedback_for_plan(query, plan, success=True)

            except Exception as e:
                result_holder["error"] = e
                # Store failure feedback if plan was created
                if result_holder.get("plan"):
                    await self._store_feedback_for_plan(query, result_holder["plan"], success=False)
                raise

        # Start workflow in background
        workflow_task = asyncio.create_task(run_workflow())

        # Stream events as they come
        try:
            # 생산자(run_workflow)가 살아 있는 동안은 스트림을 연다 — 계획 수립이 0.5s 를
            # 넘겨도 끊기지 않고, 계획 단계에서 죽으면 태스크가 끝나 스트림도 끝난다.
            async for event in streamer.events(keep_alive=lambda: not workflow_task.done()):
                yield event

                # Check if this is the final event (WORKFLOW_COMPLETE or WORKFLOW_ERROR)
                if event.type in (ProgressEventType.WORKFLOW_COMPLETE, ProgressEventType.WORKFLOW_ERROR):
                    break

            # Wait for workflow to complete (if not already done)
            if not workflow_task.done():
                await workflow_task

        except asyncio.CancelledError:
            workflow_task.cancel()
            raise

        finally:
            await streamer.close()

        # Raise any errors from workflow
        if result_holder["error"]:
            raise result_holder["error"]

    async def run_sse(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Execute with Server-Sent Events format output.

        Use with FastAPI StreamingResponse:
            return StreamingResponse(
                orchestrator.run_sse(query),
                media_type="text/event-stream"
            )
        """
        async for event in self.run_streaming(query, context):
            yield event.to_sse()

    async def run_json(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Execute with newline-delimited JSON output.
        """
        async for event in self.run_streaming(query, context):
            yield event.to_json() + "\n"

    async def create_plan_only(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        """
        Create execution plan without running it.

        Useful for previewing what would be executed.
        """
        # Create temporary streamer
        streamer = ProgressStreamer() if self.enable_streaming else None
        self._init_components(streamer)

        try:
            plan = await self._planner.create_plan(query, context)

            if self.enable_validation:
                validation_result = await self._validator.validate(plan)
                if not validation_result.is_valid:
                    plan.validation_errors = validation_result.errors

            return plan

        finally:
            if streamer:
                await streamer.close()

    def set_agent_executor(self, executor: AgentExecutor) -> None:
        """Set the agent executor function"""
        self._agent_executor = executor

    def get_registry(self) -> AgentRegistry:
        """Get the agent registry"""
        return self.registry

    async def _store_feedback_for_plan(
        self,
        query: str,
        plan: ExecutionPlan,
        success: bool,
    ) -> None:
        """
        Store feedback for all agents in the execution plan.

        This enables the GNN+RL system to learn from execution outcomes.

        Args:
            query: Original user query
            plan: Execution plan that was run
            success: Whether the execution was successful
        """
        if not self._planner:
            return

        try:
            # Extract all unique agents from the plan
            agents_used = set()
            for stage in plan.stages:
                for agent in stage.agents:
                    agents_used.add(agent.agent_id)

            # Store feedback for the primary agent (first stage, first agent)
            if plan.stages and plan.stages[0].agents:
                primary_agent = plan.stages[0].agents[0].agent_id
                await self._planner.store_execution_feedback(
                    query=query,
                    agent_id=primary_agent,
                    success=success,
                )
                logger.debug(
                    f"[Orchestrator] Stored feedback for primary agent: {primary_agent} "
                    f"({'success' if success else 'failure'})"
                )
        except Exception as e:
            logger.warning(f"[Orchestrator] Failed to store feedback: {e}")


# Factory functions

def create_orchestrator(
    agent_executor: Optional[AgentExecutor] = None,
    registry: Optional[AgentRegistry] = None,
) -> WorkflowOrchestrator:
    """Create a WorkflowOrchestrator with default configuration"""
    return WorkflowOrchestrator(
        agent_executor=agent_executor,
        registry=registry,
    )


async def quick_run(
    query: str,
    agent_executor: AgentExecutor,
    context: Optional[Dict[str, Any]] = None,
) -> WorkflowResult:
    """Quick helper to run a query with minimal setup"""
    orchestrator = WorkflowOrchestrator(agent_executor=agent_executor)
    return await orchestrator.run(query, context)


# Convenience for sync usage
def run_sync(
    query: str,
    agent_executor: AgentExecutor,
    context: Optional[Dict[str, Any]] = None,
) -> WorkflowResult:
    """Synchronous wrapper for quick_run"""
    return asyncio.run(quick_run(query, agent_executor, context))
