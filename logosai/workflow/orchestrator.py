"""
LogosAI 워크플로우 오케스트레이터 (Workflow Orchestrator)

워크플로우 계획을 실행하고 에이전트 간 결과를 조율합니다.
순차/병렬/하이브리드 실행 전략을 지원합니다.
"""

import asyncio
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
            # 실행 전략에 따라 처리
            if plan.execution_strategy == ExecutionStrategy.SEQUENTIAL:
                await self._execute_sequential(plan, initial_context)
            elif plan.execution_strategy == ExecutionStrategy.PARALLEL:
                await self._execute_parallel(plan, initial_context)
            else:  # HYBRID
                await self._execute_hybrid(plan, initial_context)

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

    async def _execute_sequential(
        self,
        plan: WorkflowPlan,
        initial_context: Optional[Dict[str, Any]]
    ):
        """순차 실행"""
        context = initial_context or {}

        for level in plan.execution_order:
            for task_id in level:
                task = plan.get_task_by_id(task_id)
                if not task:
                    continue

                # 의존성 결과 주입
                task_context = self._build_task_context(task, context)

                # 태스크 실행
                result = await self._execute_task(task, task_context)
                self._task_results[task_id] = result

                # 결과를 컨텍스트에 추가
                if result.success:
                    context[task_id] = result.result

    async def _execute_parallel(
        self,
        plan: WorkflowPlan,
        initial_context: Optional[Dict[str, Any]]
    ):
        """병렬 실행 (모든 태스크)"""
        context = initial_context or {}

        tasks_to_execute = [
            self._execute_task(task, self._build_task_context(task, context))
            for task in plan.tasks
        ]

        # 동시 실행 제한 적용
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def limited_execute(coro, task_id):
            async with semaphore:
                return task_id, await coro

        results = await asyncio.gather(
            *[
                limited_execute(coro, plan.tasks[i].task_id)
                for i, coro in enumerate(tasks_to_execute)
            ],
            return_exceptions=True
        )

        # 결과 저장
        for item in results:
            if isinstance(item, Exception):
                logger.error(f"병렬 실행 중 예외: {item}")
                continue
            task_id, result = item
            self._task_results[task_id] = result

    async def _execute_hybrid(
        self,
        plan: WorkflowPlan,
        initial_context: Optional[Dict[str, Any]]
    ):
        """하이브리드 실행 (레벨 단위 병렬)"""
        context = initial_context or {}

        for level in plan.execution_order:
            if len(level) == 1:
                # 단일 태스크 - 순차 실행
                task_id = level[0]
                task = plan.get_task_by_id(task_id)
                if task:
                    task_context = self._build_task_context(task, context)
                    result = await self._execute_task(task, task_context)
                    self._task_results[task_id] = result
                    if result.success:
                        context[task_id] = result.result
            else:
                # 다중 태스크 - 병렬 실행
                semaphore = asyncio.Semaphore(self.max_concurrent)

                async def execute_with_semaphore(t: TaskInfo):
                    async with semaphore:
                        tc = self._build_task_context(t, context)
                        return t.task_id, await self._execute_task(t, tc)

                tasks = [
                    plan.get_task_by_id(tid)
                    for tid in level
                ]
                tasks = [t for t in tasks if t is not None]

                results = await asyncio.gather(
                    *[execute_with_semaphore(t) for t in tasks],
                    return_exceptions=True
                )

                # 결과 저장 및 컨텍스트 업데이트
                for item in results:
                    if isinstance(item, Exception):
                        logger.error(f"하이브리드 실행 중 예외: {item}")
                        continue
                    task_id, result = item
                    self._task_results[task_id] = result
                    if result.success:
                        context[task_id] = result.result

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

            # AgentResponse 처리
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
