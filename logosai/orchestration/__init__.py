"""워크플로 실행부 — 계획(ExecutionPlan)을 받아 에이전트를 단계별로 실행한다.

계획은 stage 목록이다. stage 안의 에이전트는 병렬로(`execution_type="parallel"`),
stage 사이는 순서대로 돈다. 앞 stage 의 결과는 다음 stage 의 쿼리와 문맥
(`original_query`, `previous_results`)에 실린다. 싱글·순차·병렬·하이브리드가
전부 이 하나의 모양으로 표현된다.

정본 이전 (2026-10-04): 이 코드는 ontology/orchestrator 에 있었고 운영(logos_api)이
그것을 썼다. SDK 에는 별도 엔진(logosai.workflow)이 있었는데 운영에서 고친
핸드오프가 넘어오지 않아 순차 2단계가 실패했다. 실행부를 여기 하나로 모으고
ontology.orchestrator 의 옛 경로는 이 모듈들의 별칭으로 남겼다.

계획을 '세우는' 쪽(QueryPlanner — 지식 그래프·선택기에 의존)은 아직
ontology 에 있다. 이 패키지는 ontology 를 import 하지 않는다.
"""

from .models import (
    AgentSchema,
    AgentRegistryEntry,
    AgentTask,
    ExecutionStage,
    ExecutionPlan,
    AgentResult,
    StageResult,
    WorkflowResult,
    ProgressEvent,
    ProgressEventType,
    AgentStatus,
)
from .exceptions import (
    OrchestratorError,
    PlanValidationError,
    ExecutionError,
    TransformationError,
    AgentNotFoundError,
    CircularDependencyError,
    SchemaCompatibilityError,
)
from .agent_registry import AgentRegistry, get_registry
from .progress_streamer import ProgressStreamer
from .plan_validator import PlanValidator
from .data_transformer import DataTransformer
from .execution_engine import ExecutionEngine
from .result_aggregator import ResultAggregator
from .planner import QueryPlanner
from .workflow_orchestrator import WorkflowOrchestrator

__all__ = [
    "AgentSchema", "AgentRegistryEntry", "AgentTask", "ExecutionStage", "ExecutionPlan",
    "AgentResult", "StageResult", "WorkflowResult", "ProgressEvent", "ProgressEventType",
    "AgentStatus",
    "OrchestratorError", "PlanValidationError", "ExecutionError", "TransformationError",
    "AgentNotFoundError", "CircularDependencyError", "SchemaCompatibilityError",
    "AgentRegistry", "get_registry", "ProgressStreamer", "PlanValidator",
    "DataTransformer", "ExecutionEngine", "ResultAggregator", "QueryPlanner", "WorkflowOrchestrator",
]
