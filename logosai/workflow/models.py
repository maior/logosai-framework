"""
LogosAI 워크플로우 엔진 데이터 모델

복합 쿼리 처리를 위한 멀티에이전트 워크플로우 데이터 구조 정의
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
from enum import Enum
from datetime import datetime
import uuid


class ExecutionStrategy(Enum):
    """실행 전략"""
    SEQUENTIAL = "sequential"      # 순차 실행
    PARALLEL = "parallel"          # 병렬 실행
    HYBRID = "hybrid"              # 혼합 (의존성 기반)


class TaskStatus(Enum):
    """태스크 상태"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class QueryComplexity(Enum):
    """쿼리 복잡도"""
    SIMPLE = "simple"              # 단일 에이전트로 처리 가능
    MODERATE = "moderate"          # 2-3개 태스크
    COMPLEX = "complex"            # 4개 이상 태스크


@dataclass
class TaskInfo:
    """개별 태스크 정보"""
    task_id: str = ""
    description: str = ""                    # 태스크 설명 (LLM 분석 결과)
    agent_id: str = ""                       # 실행할 에이전트 ID
    agent_query: str = ""                    # 에이전트에 전달할 쿼리
    depends_on: List[str] = field(default_factory=list)  # 의존 태스크 ID
    priority: int = 0                        # 우선순위 (높을수록 먼저)
    estimated_time: float = 30.0             # 예상 실행 시간 (초)
    timeout: float = 120.0                   # 타임아웃 (초)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    retry_count: int = 0
    max_retries: int = 2

    def __post_init__(self):
        if not self.task_id:
            self.task_id = f"task_{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "agent_id": self.agent_id,
            "agent_query": self.agent_query,
            "depends_on": self.depends_on,
            "priority": self.priority,
            "estimated_time": self.estimated_time,
            "timeout": self.timeout,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskInfo':
        """딕셔너리에서 생성"""
        status = data.get("status", "pending")
        if isinstance(status, str):
            status = TaskStatus(status)

        return cls(
            task_id=data.get("task_id", ""),
            description=data.get("description", ""),
            agent_id=data.get("agent_id", ""),
            agent_query=data.get("agent_query", ""),
            depends_on=data.get("depends_on", []),
            priority=data.get("priority", 0),
            estimated_time=data.get("estimated_time", 30.0),
            timeout=data.get("timeout", 120.0),
            status=status,
            result=data.get("result"),
            error=data.get("error"),
            execution_time=data.get("execution_time", 0.0)
        )


@dataclass
class DecompositionResult:
    """쿼리 분해 결과"""
    original_query: str = ""
    is_complex: bool = False                    # 복합 쿼리 여부
    complexity: QueryComplexity = QueryComplexity.SIMPLE
    complexity_score: float = 0.0               # 복잡도 점수 (0.0 ~ 1.0)
    tasks: List[TaskInfo] = field(default_factory=list)  # 분해된 태스크 목록
    reasoning: str = ""                         # LLM의 분석 이유
    suggested_strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL
    analysis_time: float = 0.0
    error: Optional[str] = None

    @property
    def task_count(self) -> int:
        return len(self.tasks)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "original_query": self.original_query,
            "is_complex": self.is_complex,
            "complexity": self.complexity.value,
            "complexity_score": self.complexity_score,
            "tasks": [t.to_dict() for t in self.tasks],
            "reasoning": self.reasoning,
            "suggested_strategy": self.suggested_strategy.value,
            "analysis_time": self.analysis_time,
            "task_count": self.task_count,
            "error": self.error
        }


@dataclass
class WorkflowPlan:
    """워크플로우 실행 계획"""
    plan_id: str = ""
    original_query: str = ""
    tasks: List[TaskInfo] = field(default_factory=list)
    execution_strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL
    execution_order: List[List[str]] = field(default_factory=list)  # 실행 순서 (단계별 그룹)
    estimated_total_time: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = f"plan_{uuid.uuid4().hex[:8]}"

    @property
    def total_steps(self) -> int:
        """총 실행 단계 수"""
        return len(self.execution_order)

    @property
    def task_count(self) -> int:
        """총 태스크 수"""
        return len(self.tasks)

    def get_task_by_id(self, task_id: str) -> Optional[TaskInfo]:
        """태스크 ID로 검색"""
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "plan_id": self.plan_id,
            "original_query": self.original_query,
            "tasks": [t.to_dict() for t in self.tasks],
            "execution_strategy": self.execution_strategy.value,
            "execution_order": self.execution_order,
            "estimated_total_time": self.estimated_total_time,
            "created_at": self.created_at.isoformat(),
            "total_steps": self.total_steps,
            "task_count": self.task_count
        }


@dataclass
class ExecutionResult:
    """개별 태스크 실행 결과"""
    task_id: str = ""
    agent_id: str = ""
    success: bool = False
    result: Any = None
    result_type: str = ""                    # AgentResponseType
    execution_time: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "success": self.success,
            "result": self.result,
            "result_type": self.result_type,
            "execution_time": self.execution_time,
            "error": self.error,
            "metadata": self.metadata
        }


@dataclass
class WorkflowResult:
    """워크플로우 전체 실행 결과"""
    plan_id: str = ""
    original_query: str = ""
    success: bool = False
    task_results: List[ExecutionResult] = field(default_factory=list)
    final_result: Any = None                   # 통합된 최종 결과
    total_execution_time: float = 0.0
    strategy_used: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL
    error_summary: Optional[str] = None
    completed_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0

    @property
    def total_tasks(self) -> int:
        return len(self.task_results)

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.completed_tasks / self.total_tasks

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "plan_id": self.plan_id,
            "original_query": self.original_query,
            "success": self.success,
            "task_results": [r.to_dict() for r in self.task_results],
            "final_result": self.final_result,
            "total_execution_time": self.total_execution_time,
            "strategy_used": self.strategy_used.value,
            "error_summary": self.error_summary,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "skipped_tasks": self.skipped_tasks,
            "total_tasks": self.total_tasks,
            "success_rate": self.success_rate
        }

    def get_task_result(self, task_id: str) -> Optional[ExecutionResult]:
        """태스크 ID로 결과 검색"""
        for result in self.task_results:
            if result.task_id == task_id:
                return result
        return None
