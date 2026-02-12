"""
LogosAI 워크플로우 플래너 (Workflow Planner)

분해된 태스크를 실행 가능한 워크플로우 계획으로 변환합니다.
의존성 분석, 실행 순서 결정, 병렬화 최적화를 수행합니다.
"""

from typing import List, Dict, Any, Optional, Set
from collections import defaultdict
from loguru import logger

from .models import (
    DecompositionResult, TaskInfo, WorkflowPlan,
    ExecutionStrategy, TaskStatus
)


class WorkflowPlanner:
    """
    워크플로우 계획 생성기

    분해된 태스크를 분석하여 최적의 실행 계획을 생성합니다.
    - 의존성 그래프 생성
    - 위상 정렬로 실행 순서 결정
    - 병렬 실행 가능 그룹 식별
    """

    def __init__(self):
        """초기화"""
        pass

    def create_plan(self, decomposition: DecompositionResult) -> WorkflowPlan:
        """
        분해 결과를 워크플로우 계획으로 변환

        Args:
            decomposition: 쿼리 분해 결과

        Returns:
            WorkflowPlan: 실행 계획
        """
        if not decomposition.tasks:
            logger.warning("태스크 없음 - 빈 워크플로우 계획 생성")
            return WorkflowPlan(
                original_query=decomposition.original_query,
                tasks=[],
                execution_strategy=ExecutionStrategy.SEQUENTIAL,
                execution_order=[],
                estimated_total_time=0.0
            )

        try:
            # 1. 의존성 그래프 생성
            dependency_graph = self._build_dependency_graph(decomposition.tasks)

            # 2. 순환 참조 검사
            if self._has_cycle(dependency_graph, decomposition.tasks):
                logger.warning("순환 참조 감지 - 의존성 제거 후 순차 실행")
                return self._create_sequential_plan(decomposition)

            # 3. 위상 정렬 + 레벨별 그룹화
            execution_order = self._topological_sort_with_levels(
                decomposition.tasks,
                dependency_graph
            )

            # 4. 실행 전략 결정
            strategy = self._determine_strategy(
                decomposition.suggested_strategy,
                execution_order
            )

            # 5. 예상 시간 계산
            estimated_time = self._calculate_estimated_time(
                decomposition.tasks,
                execution_order,
                strategy
            )

            plan = WorkflowPlan(
                original_query=decomposition.original_query,
                tasks=decomposition.tasks,
                execution_strategy=strategy,
                execution_order=execution_order,
                estimated_total_time=estimated_time
            )

            logger.info(
                f"워크플로우 계획 생성 완료: "
                f"tasks={len(plan.tasks)}, "
                f"steps={plan.total_steps}, "
                f"strategy={strategy.value}, "
                f"estimated_time={estimated_time:.1f}s"
            )

            return plan

        except Exception as e:
            logger.error(f"워크플로우 계획 생성 실패: {e}")
            # 오류 시 순차 실행 폴백
            return self._create_sequential_plan(decomposition)

    def _build_dependency_graph(
        self,
        tasks: List[TaskInfo]
    ) -> Dict[str, Set[str]]:
        """
        의존성 그래프 생성

        Returns:
            Dict[task_id, Set[depends_on_task_ids]]
        """
        graph = defaultdict(set)
        task_ids = {task.task_id for task in tasks}

        for task in tasks:
            # 유효한 의존성만 포함
            valid_deps = {
                dep for dep in task.depends_on
                if dep in task_ids
            }
            graph[task.task_id] = valid_deps

        return dict(graph)

    def _has_cycle(
        self,
        graph: Dict[str, Set[str]],
        tasks: List[TaskInfo]
    ) -> bool:
        """순환 참조 검사 (DFS)"""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {task.task_id: WHITE for task in tasks}

        def dfs(node: str) -> bool:
            color[node] = GRAY
            for neighbor in graph.get(node, set()):
                if color.get(neighbor, WHITE) == GRAY:
                    return True  # 순환 발견
                if color.get(neighbor, WHITE) == WHITE:
                    if dfs(neighbor):
                        return True
            color[node] = BLACK
            return False

        for task in tasks:
            if color[task.task_id] == WHITE:
                if dfs(task.task_id):
                    return True

        return False

    def _topological_sort_with_levels(
        self,
        tasks: List[TaskInfo],
        graph: Dict[str, Set[str]]
    ) -> List[List[str]]:
        """
        위상 정렬 + 레벨별 그룹화

        같은 레벨의 태스크는 병렬 실행 가능

        Returns:
            List[List[task_id]] - 레벨별 태스크 ID 그룹
        """
        task_ids = {task.task_id for task in tasks}

        # 진입 차수 계산
        in_degree = {tid: 0 for tid in task_ids}
        for task_id in task_ids:
            for dep in graph.get(task_id, set()):
                if dep in in_degree:
                    in_degree[task_id] += 1

        # 레벨별 그룹화
        levels = []
        remaining = set(task_ids)

        while remaining:
            # 현재 레벨: 의존성이 모두 해결된 태스크
            current_level = [
                tid for tid in remaining
                if in_degree.get(tid, 0) == 0
            ]

            if not current_level:
                # 모든 태스크에 의존성이 있으면 (순환 가능성)
                # 우선순위가 높은 것부터 처리
                remaining_tasks = [
                    t for t in tasks if t.task_id in remaining
                ]
                remaining_tasks.sort(key=lambda t: -t.priority)
                current_level = [remaining_tasks[0].task_id]

            # 우선순위로 정렬
            task_map = {t.task_id: t for t in tasks}
            current_level.sort(
                key=lambda tid: -task_map.get(tid, TaskInfo()).priority
            )

            levels.append(current_level)

            # 진입 차수 업데이트
            for task_id in current_level:
                remaining.discard(task_id)
                # 이 태스크에 의존하는 다른 태스크들의 진입 차수 감소
                for other_id in remaining:
                    if task_id in graph.get(other_id, set()):
                        in_degree[other_id] -= 1

        return levels

    def _determine_strategy(
        self,
        suggested: ExecutionStrategy,
        execution_order: List[List[str]]
    ) -> ExecutionStrategy:
        """실행 전략 결정"""

        # 단일 레벨이면 순차/병렬 중 선택
        if len(execution_order) == 1:
            if len(execution_order[0]) == 1:
                return ExecutionStrategy.SEQUENTIAL
            else:
                return ExecutionStrategy.PARALLEL

        # 모든 레벨이 단일 태스크면 순차
        if all(len(level) == 1 for level in execution_order):
            return ExecutionStrategy.SEQUENTIAL

        # 병렬 가능한 레벨이 있으면 하이브리드
        has_parallel = any(len(level) > 1 for level in execution_order)
        if has_parallel:
            return ExecutionStrategy.HYBRID

        return suggested

    def _calculate_estimated_time(
        self,
        tasks: List[TaskInfo],
        execution_order: List[List[str]],
        strategy: ExecutionStrategy
    ) -> float:
        """예상 총 실행 시간 계산"""

        task_map = {t.task_id: t for t in tasks}
        total_time = 0.0

        for level in execution_order:
            level_tasks = [task_map.get(tid) for tid in level if tid in task_map]

            if strategy == ExecutionStrategy.SEQUENTIAL:
                # 순차: 모든 태스크 시간 합산
                total_time += sum(t.estimated_time for t in level_tasks if t)
            else:
                # 병렬/하이브리드: 가장 긴 태스크 시간
                if level_tasks:
                    total_time += max(t.estimated_time for t in level_tasks if t)

        return total_time

    def _create_sequential_plan(
        self,
        decomposition: DecompositionResult
    ) -> WorkflowPlan:
        """순차 실행 계획 생성 (폴백용)"""

        # 우선순위로 정렬
        sorted_tasks = sorted(
            decomposition.tasks,
            key=lambda t: -t.priority
        )

        # 각 태스크를 별도 레벨로
        execution_order = [[task.task_id] for task in sorted_tasks]

        # 총 시간 계산
        total_time = sum(t.estimated_time for t in sorted_tasks)

        return WorkflowPlan(
            original_query=decomposition.original_query,
            tasks=sorted_tasks,
            execution_strategy=ExecutionStrategy.SEQUENTIAL,
            execution_order=execution_order,
            estimated_total_time=total_time
        )

    def optimize_plan(self, plan: WorkflowPlan) -> WorkflowPlan:
        """
        워크플로우 계획 최적화

        - 병렬화 가능한 태스크 그룹화
        - 불필요한 의존성 제거
        - 예상 시간 재계산
        """
        # 현재는 기본 계획 반환
        # 향후 고급 최적화 로직 추가 가능
        return plan

    def validate_plan(self, plan: WorkflowPlan) -> bool:
        """워크플로우 계획 유효성 검사"""

        if not plan.tasks:
            return True  # 빈 계획도 유효

        task_ids = {t.task_id for t in plan.tasks}

        # 1. execution_order의 모든 태스크가 tasks에 있는지
        for level in plan.execution_order:
            for task_id in level:
                if task_id not in task_ids:
                    logger.error(f"execution_order에 없는 태스크: {task_id}")
                    return False

        # 2. 모든 태스크가 execution_order에 있는지
        order_ids = {tid for level in plan.execution_order for tid in level}
        for task_id in task_ids:
            if task_id not in order_ids:
                logger.error(f"execution_order에 누락된 태스크: {task_id}")
                return False

        # 3. 의존성이 실행 순서상 먼저 오는지
        executed = set()
        for level in plan.execution_order:
            for task_id in level:
                task = plan.get_task_by_id(task_id)
                if task:
                    for dep in task.depends_on:
                        if dep not in executed and dep in task_ids:
                            logger.error(
                                f"의존성 순서 오류: {task_id}가 {dep}보다 먼저 실행"
                            )
                            return False
            executed.update(level)

        return True
