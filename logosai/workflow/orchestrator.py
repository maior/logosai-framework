"""
LogosAI 워크플로우 오케스트레이터 (Workflow Orchestrator)

워크플로우 계획을 실행하고 에이전트 간 결과를 조율합니다.
순차/병렬/하이브리드 실행 전략을 지원합니다.
"""

import asyncio
import json
import time
from typing import Dict, Any, Optional, List, Callable, Awaitable
from loguru import logger

from .models import (
    WorkflowPlan, WorkflowResult, ExecutionResult,
    ExecutionStrategy, TaskInfo, TaskStatus
)


class WorkflowOrchestrator:
    """
    워크플로우 실행 오케스트레이터

    워크플로우 계획에 따라 에이전트를 실행하고 결과를 통합합니다.
    """

    def __init__(
        self,
        agent_executor: Optional[Callable[[str, str, Dict[str, Any]], Awaitable[Any]]] = None,
        max_concurrent: int = 5,
        default_timeout: float = 120.0
    ):
        """
        초기화

        Args:
            agent_executor: 에이전트 실행 함수
                (agent_id, query, context) -> AgentResponse
            max_concurrent: 최대 동시 실행 수
            default_timeout: 기본 타임아웃 (초)
        """
        self.agent_executor = agent_executor
        self.max_concurrent = max_concurrent
        self.default_timeout = default_timeout

        # 실행 중인 태스크 결과 저장
        self._task_results: Dict[str, ExecutionResult] = {}

    def set_agent_executor(
        self,
        executor: Callable[[str, str, Dict[str, Any]], Awaitable[Any]]
    ):
        """에이전트 실행 함수 설정"""
        self.agent_executor = executor

    async def execute(
        self,
        plan: WorkflowPlan,
        initial_context: Optional[Dict[str, Any]] = None
    ) -> WorkflowResult:
        """
        워크플로우 계획 실행

        Args:
            plan: 실행할 워크플로우 계획
            initial_context: 초기 컨텍스트

        Returns:
            WorkflowResult: 실행 결과
        """
        if not self.agent_executor:
            raise RuntimeError("agent_executor가 설정되지 않았습니다")

        start_time = time.time()
        self._task_results.clear()

        logger.info(
            f"워크플로우 실행 시작: plan_id={plan.plan_id}, "
            f"tasks={plan.task_count}, "
            f"strategy={plan.execution_strategy.value}"
        )

        try:
            # 실행은 logosai.orchestration 엔진에 맡긴다 (레벨 = stage)
            await self._run_on_engine(plan, initial_context)

            # 결과 집계
            result = self._aggregate_results(plan, start_time)

            logger.info(
                f"워크플로우 실행 완료: "
                f"success={result.success}, "
                f"completed={result.completed_tasks}/{result.total_tasks}, "
                f"time={result.total_execution_time:.2f}s"
            )

            return result

        except Exception as e:
            logger.error(f"워크플로우 실행 중 오류: {e}")
            return WorkflowResult(
                plan_id=plan.plan_id,
                original_query=plan.original_query,
                success=False,
                task_results=list(self._task_results.values()),
                total_execution_time=time.time() - start_time,
                strategy_used=plan.execution_strategy,
                error_summary=str(e)
            )

    async def _run_on_engine(
        self,
        plan: WorkflowPlan,
        initial_context: Optional[Dict[str, Any]]
    ):
        """레벨 하나를 stage 하나로 바꿔 logosai.orchestration 엔진으로 실행한다.

        왜: 이 클래스는 자기 실행 루프를 갖고 있었고, 의존 태스크의 agent_query 가
        None 이면(LLM 분해기가 "앞 결과를 쓰라"는 뜻으로 null 을 낸다) 그대로
        실행기에 넘겨 순차 2단계가 실패했다. 운영 엔진은 앞 결과를 다음 쿼리에
        싣는다 — 실행부를 그 하나로 모은다 (2026-10-04, orchestrator-unify).

        acp_server 계약은 그대로다: 실행기는 dependency_results 를 받고, 결과는
        _to_execution_result 의 기존 판정 규칙으로 ExecutionResult 가 된다.
        """
        from logosai.orchestration import (
            AgentTask, ExecutionEngine, ExecutionPlan, ExecutionStage,
        )

        tasks = {t.task_id: t for t in plan.tasks}
        levels = plan.execution_order or self._fallback_levels(plan)
        base = dict(initial_context or {})

        stages = []
        for level in levels:
            agents = [
                AgentTask(
                    agent_id=tasks[tid].agent_id,
                    sub_query=(self._as_query_text(tasks[tid].agent_query)
                               or tasks[tid].description or plan.original_query),
                    task_id=tid,
                    timeout_ms=int((tasks[tid].timeout or self.default_timeout) * 1000),
                    max_retries=tasks[tid].max_retries,
                )
                for tid in level if tid in tasks
            ]
            if agents:
                stages.append(ExecutionStage(
                    stage_id=len(stages) + 1,
                    execution_type="parallel" if len(agents) > 1 else "sequential",
                    agents=agents,
                ))

        async def executor(agent_id: str, query: str, context: Dict[str, Any]):
            task = tasks.get((context or {}).get("task_id"))
            merged = {**base, **(context or {})}
            if task is None:  # 방어 — 엔진이 task_id 를 잃으면 의존 결과 없이 실행
                return await self.agent_executor(agent_id, query, merged)
            task.status = TaskStatus.RUNNING
            started = time.time()
            result = await self.agent_executor(
                agent_id, query, self._build_task_context(task, merged))
            self._task_results[task.task_id] = self._to_execution_result(
                task, result, time.time() - started)
            return result

        strategy = plan.execution_strategy.value
        engine_result = await ExecutionEngine(agent_executor=executor).execute(
            ExecutionPlan(
                query=plan.original_query,
                workflow_strategy=strategy if strategy in ("sequential", "parallel", "hybrid") else "hybrid",
                stages=stages,
                plan_id=plan.plan_id,
            ),
            base,
        )

        # 실행기가 결과를 내지 못한 태스크(예외·시간 초과)는 엔진의 기록으로 채운다.
        # stage 의 결과 순서는 그 stage 의 에이전트 순서와 같다.
        by_stage = {st.stage_id: st for st in engine_result.stages}
        for stage in stages:
            ran = by_stage.get(stage.stage_id)
            for agent_task, agent_result in zip(stage.agents, ran.results if ran else []):
                if agent_task.task_id in self._task_results:
                    continue
                task = tasks[agent_task.task_id]
                task.status = TaskStatus.FAILED
                task.error = agent_result.error or "결과 없음"
                self._task_results[task.task_id] = ExecutionResult(
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    success=False,
                    result=None,
                    result_type="error",
                    execution_time=(agent_result.execution_time_ms or 0) / 1000,
                    error=task.error,
                )

        # 집계 순서는 완료 순서가 아니라 계획 순서
        ordered = [tid for level in levels for tid in level if tid in self._task_results]
        self._task_results = {tid: self._task_results[tid] for tid in ordered}

    @staticmethod
    def _as_query_text(value: Any) -> str:
        """LLM 분해기의 agent_query 를 실행기가 받을 문자열로.

        문자열로 시켜도 객체가 온다 — 실측 `{'text': 'hello world'}`,
        `{'text_upper': 'hello world'}` (능력 이름을 키로 쓴다). 그대로 넘기면
        실행기가 `query.split` 에서 죽는다. 값이 문자열 하나뿐인 dict 는 그 값,
        그 외 객체는 JSON — 정보를 버리지 않는다. 빈 값은 "" (호출자가 대체).
        """
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict) and len(value) == 1:
            (only,) = value.values()
            if isinstance(only, str):
                return only
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _fallback_levels(plan: WorkflowPlan) -> List[List[str]]:
        """execution_order 가 비었을 때 — 순차는 한 줄씩, 그 외는 한 묶음."""
        ids = [t.task_id for t in plan.tasks]
        if plan.execution_strategy == ExecutionStrategy.SEQUENTIAL:
            return [[tid] for tid in ids]
        return [ids] if ids else []

    def _to_execution_result(
        self,
        task: TaskInfo,
        result: Any,
        execution_time: float
    ) -> ExecutionResult:
        """실행기 응답 → ExecutionResult. 판정 규칙은 기존 그대로다 (acp_server 계약)."""
        if hasattr(result, 'type') and hasattr(result, 'content'):
            # AgentResponse 객체
            success = self._is_success_response(result)
            content = result.content
            result_type = result.type.value if hasattr(result.type, 'value') else str(result.type)
            metadata = result.metadata if hasattr(result, 'metadata') else {}
        elif isinstance(result, dict):
            # 딕셔너리 응답
            success = result.get('success', True)
            content = result.get('content', result.get('result', result))
            result_type = result.get('type', 'success')
            metadata = result.get('metadata', {})
        else:
            # 기타 응답
            success = True
            content = result
            result_type = 'success'
            metadata = {}

        task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        task.result = content
        task.execution_time = execution_time

        logger.info(
            f"태스크 실행 완료: task_id={task.task_id}, "
            f"success={success}, time={execution_time:.2f}s"
        )

        return ExecutionResult(
            task_id=task.task_id,
            agent_id=task.agent_id,
            success=success,
            result=content,
            result_type=result_type,
            execution_time=execution_time,
            metadata=metadata
        )

    async def _execute_task(
        self,
        task: TaskInfo,
        context: Dict[str, Any]
    ) -> ExecutionResult:
        """
        단일 태스크 실행

        Args:
            task: 실행할 태스크
            context: 컨텍스트 (의존성 결과 포함)

        Returns:
            ExecutionResult: 실행 결과
        """
        start_time = time.time()
        task.status = TaskStatus.RUNNING

        logger.info(
            f"태스크 실행 시작: task_id={task.task_id}, "
            f"agent={task.agent_id}"
        )

        try:
            # 타임아웃 설정
            timeout = task.timeout or self.default_timeout

            # 에이전트 실행
            result = await asyncio.wait_for(
                self.agent_executor(task.agent_id, task.agent_query, context),
                timeout=timeout
            )

            execution_time = time.time() - start_time

            return self._to_execution_result(task, result, execution_time)

        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            task.status = TaskStatus.FAILED
            task.error = f"타임아웃 ({task.timeout}s)"
            task.execution_time = execution_time

            logger.warning(
                f"태스크 타임아웃: task_id={task.task_id}, "
                f"timeout={task.timeout}s"
            )

            return ExecutionResult(
                task_id=task.task_id,
                agent_id=task.agent_id,
                success=False,
                result=None,
                result_type="error",
                execution_time=execution_time,
                error=f"Timeout after {task.timeout}s"
            )

        except Exception as e:
            execution_time = time.time() - start_time
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.execution_time = execution_time

            logger.error(
                f"태스크 실행 실패: task_id={task.task_id}, "
                f"error={e}"
            )

            # 재시도 로직
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                logger.info(
                    f"태스크 재시도: task_id={task.task_id}, "
                    f"attempt={task.retry_count}/{task.max_retries}"
                )
                return await self._execute_task(task, context)

            return ExecutionResult(
                task_id=task.task_id,
                agent_id=task.agent_id,
                success=False,
                result=None,
                result_type="error",
                execution_time=execution_time,
                error=str(e)
            )

    def _is_success_response(self, result: Any) -> bool:
        """AgentResponse 성공 여부 확인"""
        if not hasattr(result, 'type'):
            return True

        type_value = result.type.value if hasattr(result.type, 'value') else str(result.type)

        # 성공 타입들
        success_types = {'success', 'data', 'chart', 'table', 'text', 'html'}
        return type_value.lower() in success_types

    def _build_task_context(
        self,
        task: TaskInfo,
        base_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        태스크 실행 컨텍스트 생성

        의존성 태스크의 결과를 컨텍스트에 포함시킵니다.
        """
        context = base_context.copy()

        # 의존성 결과 추가
        dependency_results = {}
        for dep_id in task.depends_on:
            if dep_id in self._task_results:
                dep_result = self._task_results[dep_id]
                if dep_result.success:
                    dependency_results[dep_id] = dep_result.result

        if dependency_results:
            context['dependency_results'] = dependency_results

            # 쿼리 확장: 의존성 결과를 참조할 수 있도록
            context['previous_results'] = dependency_results

        return context

    def _aggregate_results(
        self,
        plan: WorkflowPlan,
        start_time: float
    ) -> WorkflowResult:
        """
        실행 결과 집계

        모든 태스크 결과를 통합하여 최종 결과를 생성합니다.
        """
        results = list(self._task_results.values())

        completed = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        skipped = plan.task_count - len(results)

        # 최종 결과 생성
        final_result = self._create_final_result(results)

        # 전체 성공 여부
        # 모든 태스크 성공 또는 필수 태스크만 성공했으면 성공
        success = failed == 0 and skipped == 0

        # 오류 요약
        error_summary = None
        if failed > 0:
            errors = [r.error for r in results if not r.success and r.error]
            error_summary = "; ".join(errors[:3])  # 최대 3개만

        return WorkflowResult(
            plan_id=plan.plan_id,
            original_query=plan.original_query,
            success=success,
            task_results=results,
            final_result=final_result,
            total_execution_time=time.time() - start_time,
            strategy_used=plan.execution_strategy,
            error_summary=error_summary,
            completed_tasks=completed,
            failed_tasks=failed,
            skipped_tasks=skipped
        )

    def _create_final_result(
        self,
        results: List[ExecutionResult]
    ) -> Any:
        """
        최종 결과 생성

        여러 태스크 결과를 하나의 통합 결과로 만듭니다.
        """
        if not results:
            return None

        successful_results = [r for r in results if r.success]

        if len(successful_results) == 0:
            return None

        if len(successful_results) == 1:
            return successful_results[0].result

        # 다중 결과 통합
        combined = {
            "task_count": len(successful_results),
            "results": []
        }

        for result in successful_results:
            combined["results"].append({
                "task_id": result.task_id,
                "agent_id": result.agent_id,
                "result": result.result
            })

        return combined

    async def execute_single_task(
        self,
        agent_id: str,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """
        단일 태스크 직접 실행 (워크플로우 없이)

        Args:
            agent_id: 에이전트 ID
            query: 쿼리
            context: 컨텍스트

        Returns:
            ExecutionResult: 실행 결과
        """
        task = TaskInfo(
            description="Direct execution",
            agent_id=agent_id,
            agent_query=query,
            timeout=self.default_timeout
        )

        return await self._execute_task(task, context or {})


class WorkflowEngine:
    """
    통합 워크플로우 엔진

    QueryDecomposer, WorkflowPlanner, WorkflowOrchestrator를 통합하여
    단일 인터페이스로 복합 쿼리 처리를 제공합니다.
    """

    def __init__(
        self,
        agent_executor: Optional[Callable[[str, str, Dict[str, Any]], Awaitable[Any]]] = None,
        llm=None
    ):
        """
        초기화

        Args:
            agent_executor: 에이전트 실행 함수
            llm: LLM 인스턴스 (QueryDecomposer용)
        """
        from .query_decomposer import QueryDecomposer
        from .workflow_planner import WorkflowPlanner

        self.decomposer = QueryDecomposer(llm=llm)
        self.planner = WorkflowPlanner()
        self.orchestrator = WorkflowOrchestrator(agent_executor=agent_executor)

        self._initialized = False

    def set_agent_executor(
        self,
        executor: Callable[[str, str, Dict[str, Any]], Awaitable[Any]]
    ):
        """에이전트 실행 함수 설정"""
        self.orchestrator.set_agent_executor(executor)

    async def initialize(self):
        """엔진 초기화"""
        if self._initialized:
            return

        await self.decomposer.initialize()
        self._initialized = True
        logger.info("WorkflowEngine 초기화 완료")

    async def process(
        self,
        query: str,
        available_agents: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> WorkflowResult:
        """
        쿼리 처리

        1. 쿼리 분해
        2. 워크플로우 계획 생성
        3. 워크플로우 실행

        Args:
            query: 사용자 쿼리
            available_agents: 사용 가능한 에이전트 목록
            context: 초기 컨텍스트

        Returns:
            WorkflowResult: 처리 결과
        """
        if not self._initialized:
            await self.initialize()

        logger.info(f"WorkflowEngine 처리 시작: {query[:100]}...")

        # 1. 쿼리 분해
        decomposition = await self.decomposer.decompose(query, available_agents)

        # 2. 단순 쿼리인 경우 빈 결과 반환 (기존 로직 사용하도록)
        if not decomposition.is_complex:
            logger.info("단순 쿼리 - 기존 에이전트 선택 로직 사용")
            return WorkflowResult(
                plan_id="",
                original_query=query,
                success=True,
                task_results=[],
                final_result=None,
                total_execution_time=decomposition.analysis_time,
                strategy_used=ExecutionStrategy.SEQUENTIAL,
                completed_tasks=0,
                failed_tasks=0,
                skipped_tasks=0
            )

        # 3. 워크플로우 계획 생성
        plan = self.planner.create_plan(decomposition)

        # 4. 계획 검증
        if not self.planner.validate_plan(plan):
            logger.warning("워크플로우 계획 검증 실패")

        # 5. 워크플로우 실행
        result = await self.orchestrator.execute(plan, context)

        return result

    async def analyze_query(
        self,
        query: str,
        available_agents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        쿼리 분석만 수행 (실행 없이)

        Args:
            query: 분석할 쿼리
            available_agents: 사용 가능한 에이전트 목록

        Returns:
            분석 결과 딕셔너리
        """
        if not self._initialized:
            await self.initialize()

        decomposition = await self.decomposer.decompose(query, available_agents)

        if decomposition.is_complex:
            plan = self.planner.create_plan(decomposition)
            return {
                "decomposition": decomposition.to_dict(),
                "plan": plan.to_dict()
            }
        else:
            return {
                "decomposition": decomposition.to_dict(),
                "plan": None
            }
