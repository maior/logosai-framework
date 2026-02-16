"""
LLM Workflow Orchestrator - LLM 기반 워크플로우 생성 및 실행

=============================================================================
아키텍처:
=============================================================================

  User Query
       ↓
  ┌────────────────────────────────────────────────────────────────────────┐
  │                    LLM Workflow Orchestrator                           │
  │                                                                        │
  │  1. Query Analysis ──────→ 의도 파악, 복잡도 분석                       │
  │       ↓                                                                │
  │  2. Agent Selection ─────→ 적합한 에이전트 선택 (도메인/능력 매칭)       │
  │       ↓                                                                │
  │  3. Workflow Planning ───→ 실행 계획 수립 (병렬/순차/하이브리드)         │
  │       ↓                                                                │
  │  4. Execution Strategy ──→ 의존성 기반 실행 순서 결정                   │
  │       ↓                                                                │
  │  5. Merge Strategy ──────→ 결과 통합 전략 정의                          │
  │                                                                        │
  └────────────────────────────────────────────────────────────────────────┘
       ↓
  WorkflowPlan {
      agents: [...],
      execution_mode: "parallel" | "sequential" | "hybrid",
      steps: [...],
      merge_strategy: {...}
  }

=============================================================================
핵심 기능:
=============================================================================

1. **지능형 쿼리 분석**
   - LLM이 사용자 의도를 깊이 이해
   - 복잡도 판단 (단순/중간/복잡)
   - 필요한 정보 유형 식별

2. **동적 에이전트 선택**
   - 에이전트 capabilities 분석
   - 쿼리-에이전트 매칭 스코어링
   - 최적 에이전트 조합 결정

3. **스마트 실행 계획**
   - 의존성 그래프 구축
   - 병렬 실행 가능 태스크 그룹화
   - 예상 실행 시간 추정

4. **결과 통합 전략**
   - 쿼리 유형별 통합 방식 결정
   - 정보 우선순위 지정
   - 충돌 해결 규칙

의존성:
- langchain_google_genai (Gemini 2.5 Flash)
- pydantic (데이터 검증)
- logosai.workflow.models (기본 데이터 모델)
"""

import json
import time
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import uuid

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from loguru import logger

from .models import (
    ExecutionStrategy,
    TaskStatus,
    QueryComplexity,
    TaskInfo,
    DecompositionResult,
    WorkflowPlan,
    ExecutionResult,
    WorkflowResult
)


# ============================================================================
# 추가 데이터 모델
# ============================================================================

class MergeStrategy(str, Enum):
    """결과 통합 전략"""
    CONCATENATE = "concatenate"        # 순차 연결
    SYNTHESIZE = "synthesize"          # LLM 기반 통합
    TABULAR = "tabular"                # 표 형식 비교
    HIERARCHICAL = "hierarchical"      # 계층적 구조화
    PRIORITY_BASED = "priority_based"  # 우선순위 기반


class QueryIntent(str, Enum):
    """쿼리 의도 유형"""
    INFORMATION = "information"        # 정보 조회
    COMPARISON = "comparison"          # 비교 분석
    RECOMMENDATION = "recommendation"  # 추천
    CALCULATION = "calculation"        # 계산
    SYNTHESIS = "synthesis"            # 종합 분석
    CREATION = "creation"              # 생성/작성


@dataclass
class AgentCapability:
    """에이전트 능력 정보"""
    agent_id: str
    name: str
    description: str
    domains: List[str]           # 도메인 목록
    capabilities: List[str]      # 능력 목록
    estimated_latency: float = 5.0  # 예상 응답 시간 (초)
    reliability_score: float = 0.9  # 신뢰도 (0-1)


@dataclass
class AgentAssignment:
    """에이전트 태스크 할당"""
    agent_id: str
    agent_name: str
    task_description: str        # 이 에이전트가 수행할 태스크 설명
    agent_query: str             # 에이전트에 전달할 실제 쿼리
    priority: int                # 우선순위 (1이 가장 높음)
    depends_on: List[str] = field(default_factory=list)  # 의존 에이전트 ID
    expected_output_type: str = "text"  # 예상 출력 유형
    confidence: float = 0.8      # 할당 신뢰도

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "task_description": self.task_description,
            "agent_query": self.agent_query,
            "priority": self.priority,
            "depends_on": self.depends_on,
            "expected_output_type": self.expected_output_type,
            "confidence": self.confidence
        }


@dataclass
class MergeConfig:
    """결과 통합 설정"""
    strategy: MergeStrategy = MergeStrategy.SYNTHESIZE
    priority_order: List[str] = field(default_factory=list)  # 에이전트 ID 순서
    conflict_resolution: str = "latest"  # latest, merge, prioritized
    output_format: str = "markdown"      # markdown, json, html
    include_sources: bool = True         # 출처 포함 여부
    max_length: int = 5000              # 최대 출력 길이

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "priority_order": self.priority_order,
            "conflict_resolution": self.conflict_resolution,
            "output_format": self.output_format,
            "include_sources": self.include_sources,
            "max_length": self.max_length
        }


@dataclass
class LLMWorkflowPlan:
    """LLM이 생성한 워크플로우 계획"""
    plan_id: str = ""
    original_query: str = ""

    # 쿼리 분석 결과
    query_intent: QueryIntent = QueryIntent.INFORMATION
    complexity: QueryComplexity = QueryComplexity.SIMPLE
    complexity_score: float = 0.0
    key_entities: List[str] = field(default_factory=list)

    # 에이전트 할당
    agent_assignments: List[AgentAssignment] = field(default_factory=list)

    # 실행 계획
    execution_strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL
    execution_steps: List[List[str]] = field(default_factory=list)  # 단계별 에이전트 ID
    estimated_total_time: float = 0.0

    # 결과 통합
    merge_config: MergeConfig = field(default_factory=MergeConfig)

    # 메타데이터
    reasoning: str = ""           # LLM의 계획 수립 이유
    analysis_time: float = 0.0    # 분석 소요 시간
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = f"llm_plan_{uuid.uuid4().hex[:8]}"

    @property
    def total_agents(self) -> int:
        return len(self.agent_assignments)

    @property
    def is_parallel(self) -> bool:
        return self.execution_strategy in [ExecutionStrategy.PARALLEL, ExecutionStrategy.HYBRID]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "original_query": self.original_query,
            "query_analysis": {
                "intent": self.query_intent.value,
                "complexity": self.complexity.value,
                "complexity_score": self.complexity_score,
                "key_entities": self.key_entities
            },
            "agent_assignments": [a.to_dict() for a in self.agent_assignments],
            "execution": {
                "strategy": self.execution_strategy.value,
                "steps": self.execution_steps,
                "estimated_total_time": self.estimated_total_time
            },
            "merge_config": self.merge_config.to_dict(),
            "reasoning": self.reasoning,
            "analysis_time": self.analysis_time,
            "created_at": self.created_at.isoformat(),
            "total_agents": self.total_agents
        }


# ============================================================================
# LLM Workflow Orchestrator
# ============================================================================

class LLMWorkflowOrchestrator:
    """
    LLM 기반 워크플로우 오케스트레이터

    사용자 쿼리를 분석하여:
    1. 필요한 에이전트 선택
    2. 실행 계획 수립 (병렬/순차)
    3. 결과 통합 전략 결정

    모든 결정은 LLM이 에이전트 정보를 분석하여 자동으로 수행합니다.
    """

    def __init__(self, model: str = "gemini-2.5-flash-lite"):
        """
        Args:
            model: 사용할 LLM 모델 (기본: Gemini 2.5 Flash Lite)
        """
        self.model_name = model
        self.llm = None
        self._initialized = False
        self._stats = {
            "total_plans": 0,
            "parallel_plans": 0,
            "sequential_plans": 0,
            "hybrid_plans": 0,
            "avg_analysis_time": 0.0
        }

    async def initialize(self):
        """오케스트레이터 초기화"""
        if self._initialized:
            return

        try:
            self.llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                temperature=0.2,  # 결정적인 출력을 위해 낮은 temperature
                convert_system_message_to_human=True
            )
            self._initialized = True
            logger.info(f"✅ LLMWorkflowOrchestrator 초기화 완료 ({self.model_name})")
        except Exception as e:
            logger.error(f"❌ 초기화 실패: {e}")
            raise

    def _build_agent_context(self, available_agents: List[Dict[str, Any]]) -> str:
        """
        에이전트 정보를 LLM 컨텍스트로 변환
        """
        if not available_agents:
            return "등록된 에이전트가 없습니다."

        context_parts = []
        for idx, agent in enumerate(available_agents, 1):
            agent_id = agent.get("agent_id", "unknown")
            name = agent.get("name", "")
            description = agent.get("description", "")
            capabilities = agent.get("capabilities", [])

            cap_list = []
            for cap in capabilities[:5]:
                cap_name = cap.get("name", "")
                cap_desc = cap.get("description", "")
                if cap_name:
                    cap_list.append(f"    - {cap_name}: {cap_desc}")

            cap_text = "\n".join(cap_list) if cap_list else "    - (능력 정보 없음)"

            context_parts.append(f"""
에이전트 {idx}: {agent_id}
  이름: {name}
  설명: {description}
  능력:
{cap_text}
""")

        return "\n".join(context_parts)

    def _create_orchestration_prompt(self, available_agents: List[Dict[str, Any]]) -> str:
        """
        LLM에게 워크플로우 계획을 요청하는 프롬프트 생성
        """
        agent_context = self._build_agent_context(available_agents)
        agent_ids = [a.get("agent_id", "") for a in available_agents]

        template = f"""당신은 사용자 쿼리를 분석하여 최적의 워크플로우를 설계하는 AI 오케스트레이터입니다.

# 역할
주어진 사용자 쿼리를 분석하고, 등록된 에이전트들을 활용하여:
1. 쿼리의 의도와 복잡도 파악
2. 필요한 에이전트 선택 및 태스크 할당
3. 실행 전략 결정 (병렬/순차/하이브리드)
4. 결과 통합 방식 결정

# 등록된 에이전트 목록
{agent_context}

# 실행 전략 가이드
- **sequential**: 한 에이전트의 결과가 다음 에이전트의 입력으로 필요한 경우
- **parallel**: 각 에이전트가 독립적으로 작업 가능한 경우 (더 빠름)
- **hybrid**: 일부는 병렬, 일부는 순차 (의존성이 혼합된 경우)

# 통합 전략 가이드
- **synthesize**: LLM이 결과를 종합하여 새로운 답변 생성 (추천)
- **concatenate**: 결과를 순서대로 연결
- **tabular**: 표 형식으로 비교 (비교 분석에 적합)
- **hierarchical**: 계층적 구조화 (복잡한 분석에 적합)
- **priority_based**: 우선순위 높은 결과 중심

# 사용자 쿼리
{{query}}

# 응답 형식 (JSON)
반드시 아래 JSON 형식으로만 응답하세요:
{{{{
    "query_analysis": {{{{
        "intent": "information | comparison | recommendation | calculation | synthesis | creation",
        "complexity": "simple | moderate | complex",
        "complexity_score": 0.0-1.0,
        "key_entities": ["핵심 엔티티1", "핵심 엔티티2"]
    }}}},
    "agent_assignments": [
        {{{{
            "agent_id": "에이전트ID",
            "task_description": "이 에이전트가 수행할 구체적인 작업",
            "agent_query": "에이전트에 전달할 실제 쿼리 (사용자 쿼리에서 이 에이전트가 처리할 부분)",
            "priority": 1-10 (낮을수록 먼저 실행),
            "depends_on": ["의존 에이전트 ID"] 또는 [],
            "expected_output_type": "text | data | chart | analysis",
            "confidence": 0.0-1.0
        }}}}
    ],
    "execution": {{{{
        "strategy": "sequential | parallel | hybrid",
        "steps": [
            ["step1에서 병렬 실행할 에이전트 ID들"],
            ["step2에서 병렬 실행할 에이전트 ID들"]
        ],
        "estimated_total_time": 예상 총 시간(초)
    }}}},
    "merge_config": {{{{
        "strategy": "synthesize | concatenate | tabular | hierarchical | priority_based",
        "priority_order": ["우선순위 순 에이전트 ID"],
        "output_format": "markdown | json | html",
        "include_sources": true | false
    }}}},
    "reasoning": "이 워크플로우를 선택한 이유를 상세히 설명"
}}}}

# 주의사항
1. 단순한 쿼리(계산, 단일 정보 조회)는 에이전트 1개만 선택
2. 복잡한 쿼리(비교, 종합 분석)는 여러 에이전트 활용
3. 의존성이 없는 태스크는 병렬 실행으로 설계
4. agent_query는 사용자 쿼리에서 해당 에이전트가 처리할 부분만 추출
5. 사용 가능한 agent_id: {', '.join(agent_ids)}
"""
        return template

    async def create_workflow_plan(
        self,
        query: str,
        available_agents: List[Dict[str, Any]]
    ) -> LLMWorkflowPlan:
        """
        사용자 쿼리와 에이전트 정보를 분석하여 워크플로우 계획 생성

        Args:
            query: 사용자 쿼리
            available_agents: 사용 가능한 에이전트 목록

        Returns:
            LLMWorkflowPlan: 생성된 워크플로우 계획
        """
        if not self._initialized:
            await self.initialize()

        start_time = time.time()

        try:
            # 프롬프트 생성
            prompt_template = self._create_orchestration_prompt(available_agents)
            chain = ChatPromptTemplate.from_template(prompt_template) | self.llm

            # LLM 호출
            result = await chain.ainvoke({"query": query})

            # 응답 파싱
            content = result.content if hasattr(result, 'content') else str(result)
            plan = self._parse_llm_response(query, content)
            plan.analysis_time = time.time() - start_time

            # 통계 업데이트
            self._update_stats(plan)

            logger.info(
                f"✅ 워크플로우 계획 생성 완료: "
                f"{plan.total_agents}개 에이전트, "
                f"{plan.execution_strategy.value} 실행, "
                f"{plan.analysis_time:.2f}s"
            )

            return plan

        except Exception as e:
            logger.error(f"❌ 워크플로우 계획 생성 실패: {e}")
            # 기본 fallback 계획 반환
            return self._create_fallback_plan(query, available_agents, str(e))

    def _parse_llm_response(self, query: str, content: str) -> LLMWorkflowPlan:
        """
        LLM 응답을 LLMWorkflowPlan으로 파싱
        """
        # JSON 추출
        content_clean = content.strip()
        if content_clean.startswith("```json"):
            content_clean = content_clean[7:]
        if content_clean.startswith("```"):
            content_clean = content_clean[3:]
        if content_clean.endswith("```"):
            content_clean = content_clean[:-3]
        content_clean = content_clean.strip()

        try:
            data = json.loads(content_clean)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 파싱 실패: {e}")
            raise ValueError(f"LLM 응답 파싱 실패: {e}")

        # 쿼리 분석 파싱
        query_analysis = data.get("query_analysis", {})

        intent_str = query_analysis.get("intent", "information")
        try:
            intent = QueryIntent(intent_str)
        except ValueError:
            intent = QueryIntent.INFORMATION

        complexity_str = query_analysis.get("complexity", "simple")
        try:
            complexity = QueryComplexity(complexity_str)
        except ValueError:
            complexity = QueryComplexity.SIMPLE

        # 에이전트 할당 파싱
        agent_assignments = []
        for assignment in data.get("agent_assignments", []):
            agent_assignments.append(AgentAssignment(
                agent_id=assignment.get("agent_id", ""),
                agent_name=assignment.get("agent_id", "").replace("_", " ").title(),
                task_description=assignment.get("task_description", ""),
                agent_query=assignment.get("agent_query", query),
                priority=assignment.get("priority", 5),
                depends_on=assignment.get("depends_on", []),
                expected_output_type=assignment.get("expected_output_type", "text"),
                confidence=assignment.get("confidence", 0.8)
            ))

        # 실행 전략 파싱
        execution = data.get("execution", {})
        strategy_str = execution.get("strategy", "sequential")
        try:
            execution_strategy = ExecutionStrategy(strategy_str)
        except ValueError:
            execution_strategy = ExecutionStrategy.SEQUENTIAL

        # 통합 설정 파싱
        merge_data = data.get("merge_config", {})
        merge_strategy_str = merge_data.get("strategy", "synthesize")
        try:
            merge_strategy = MergeStrategy(merge_strategy_str)
        except ValueError:
            merge_strategy = MergeStrategy.SYNTHESIZE

        merge_config = MergeConfig(
            strategy=merge_strategy,
            priority_order=merge_data.get("priority_order", []),
            output_format=merge_data.get("output_format", "markdown"),
            include_sources=merge_data.get("include_sources", True)
        )

        return LLMWorkflowPlan(
            original_query=query,
            query_intent=intent,
            complexity=complexity,
            complexity_score=query_analysis.get("complexity_score", 0.5),
            key_entities=query_analysis.get("key_entities", []),
            agent_assignments=agent_assignments,
            execution_strategy=execution_strategy,
            execution_steps=execution.get("steps", []),
            estimated_total_time=execution.get("estimated_total_time", 30.0),
            merge_config=merge_config,
            reasoning=data.get("reasoning", "")
        )

    def _create_fallback_plan(
        self,
        query: str,
        available_agents: List[Dict[str, Any]],
        error: str
    ) -> LLMWorkflowPlan:
        """
        LLM 실패 시 기본 fallback 계획 생성
        """
        # 가장 일반적인 에이전트 선택
        fallback_agent = "llm_search_agent"
        for agent in available_agents:
            agent_id = agent.get("agent_id", "")
            if "search" in agent_id.lower() or "general" in agent_id.lower():
                fallback_agent = agent_id
                break

        return LLMWorkflowPlan(
            original_query=query,
            query_intent=QueryIntent.INFORMATION,
            complexity=QueryComplexity.SIMPLE,
            complexity_score=0.3,
            agent_assignments=[
                AgentAssignment(
                    agent_id=fallback_agent,
                    agent_name="Fallback Agent",
                    task_description="기본 쿼리 처리",
                    agent_query=query,
                    priority=1,
                    confidence=0.5
                )
            ],
            execution_strategy=ExecutionStrategy.SEQUENTIAL,
            execution_steps=[[fallback_agent]],
            estimated_total_time=30.0,
            merge_config=MergeConfig(strategy=MergeStrategy.CONCATENATE),
            reasoning=f"LLM 분석 실패로 인한 기본 계획: {error}"
        )

    def _update_stats(self, plan: LLMWorkflowPlan):
        """통계 업데이트"""
        self._stats["total_plans"] += 1

        if plan.execution_strategy == ExecutionStrategy.PARALLEL:
            self._stats["parallel_plans"] += 1
        elif plan.execution_strategy == ExecutionStrategy.SEQUENTIAL:
            self._stats["sequential_plans"] += 1
        else:
            self._stats["hybrid_plans"] += 1

        # 이동 평균 업데이트
        n = self._stats["total_plans"]
        old_avg = self._stats["avg_analysis_time"]
        self._stats["avg_analysis_time"] = old_avg + (plan.analysis_time - old_avg) / n

    def get_stats(self) -> Dict[str, Any]:
        """오케스트레이터 통계 반환"""
        return self._stats.copy()

    async def analyze_query_complexity(self, query: str) -> Dict[str, Any]:
        """
        쿼리 복잡도만 빠르게 분석 (에이전트 선택 전 사전 분석용)
        """
        if not self._initialized:
            await self.initialize()

        prompt = f"""다음 쿼리의 복잡도를 분석하세요.

쿼리: {query}

JSON 형식으로 응답:
{{
    "intent": "information | comparison | recommendation | calculation | synthesis | creation",
    "complexity": "simple | moderate | complex",
    "complexity_score": 0.0-1.0,
    "requires_multiple_agents": true | false,
    "reasoning": "판단 이유"
}}
"""
        try:
            chain = ChatPromptTemplate.from_template(prompt) | self.llm
            result = await chain.ainvoke({})
            content = result.content if hasattr(result, 'content') else str(result)

            # JSON 파싱
            content_clean = content.strip()
            if content_clean.startswith("```"):
                content_clean = content_clean.split("```")[1]
                if content_clean.startswith("json"):
                    content_clean = content_clean[4:]
            content_clean = content_clean.strip()

            return json.loads(content_clean)

        except Exception as e:
            logger.warning(f"복잡도 분석 실패: {e}")
            return {
                "intent": "information",
                "complexity": "simple",
                "complexity_score": 0.3,
                "requires_multiple_agents": False,
                "reasoning": "분석 실패 - 기본값 사용"
            }


# ============================================================================
# 워크플로우 실행기 (Executor)
# ============================================================================

class WorkflowExecutor:
    """
    LLMWorkflowPlan을 실제로 실행하는 클래스

    기능:
    - 병렬/순차 실행 관리
    - 의존성 해결
    - 결과 통합
    """

    def __init__(self, agent_registry: Dict[str, Any] = None):
        """
        Args:
            agent_registry: agent_id -> agent_instance 매핑
        """
        self.agent_registry = agent_registry or {}

    def register_agent(self, agent_id: str, agent_instance: Any):
        """에이전트 등록"""
        self.agent_registry[agent_id] = agent_instance

    async def execute_plan(
        self,
        plan: LLMWorkflowPlan,
        agent_executor: callable = None
    ) -> WorkflowResult:
        """
        워크플로우 계획 실행

        Args:
            plan: 실행할 워크플로우 계획
            agent_executor: 에이전트 실행 함수 (async def executor(agent_id, query) -> result)

        Returns:
            WorkflowResult: 실행 결과
        """
        start_time = time.time()
        task_results = []
        completed = 0
        failed = 0

        try:
            if plan.execution_strategy == ExecutionStrategy.PARALLEL:
                task_results = await self._execute_parallel(plan, agent_executor)
            elif plan.execution_strategy == ExecutionStrategy.SEQUENTIAL:
                task_results = await self._execute_sequential(plan, agent_executor)
            else:
                task_results = await self._execute_hybrid(plan, agent_executor)

            # 결과 집계
            for result in task_results:
                if result.success:
                    completed += 1
                else:
                    failed += 1

            # 결과 통합
            final_result = await self._merge_results(plan, task_results)

            return WorkflowResult(
                plan_id=plan.plan_id,
                original_query=plan.original_query,
                success=failed == 0,
                task_results=task_results,
                final_result=final_result,
                total_execution_time=time.time() - start_time,
                strategy_used=plan.execution_strategy,
                completed_tasks=completed,
                failed_tasks=failed
            )

        except Exception as e:
            logger.error(f"워크플로우 실행 오류: {e}")
            return WorkflowResult(
                plan_id=plan.plan_id,
                original_query=plan.original_query,
                success=False,
                task_results=task_results,
                total_execution_time=time.time() - start_time,
                strategy_used=plan.execution_strategy,
                error_summary=str(e),
                completed_tasks=completed,
                failed_tasks=failed + 1
            )

    async def _execute_parallel(
        self,
        plan: LLMWorkflowPlan,
        agent_executor: callable
    ) -> List[ExecutionResult]:
        """병렬 실행"""
        if not agent_executor:
            logger.warning("에이전트 실행기가 없습니다.")
            return []

        tasks = []
        for assignment in plan.agent_assignments:
            tasks.append(self._execute_single_agent(assignment, agent_executor))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        execution_results = []
        for i, result in enumerate(results):
            assignment = plan.agent_assignments[i]
            if isinstance(result, Exception):
                execution_results.append(ExecutionResult(
                    task_id=f"task_{i}",
                    agent_id=assignment.agent_id,
                    success=False,
                    error=str(result)
                ))
            else:
                execution_results.append(result)

        return execution_results

    async def _execute_sequential(
        self,
        plan: LLMWorkflowPlan,
        agent_executor: callable
    ) -> List[ExecutionResult]:
        """순차 실행"""
        if not agent_executor:
            return []

        results = []
        previous_result = None

        # priority 순으로 정렬
        sorted_assignments = sorted(
            plan.agent_assignments,
            key=lambda x: x.priority
        )

        for assignment in sorted_assignments:
            result = await self._execute_single_agent(
                assignment,
                agent_executor,
                context=previous_result
            )
            results.append(result)
            if result.success:
                previous_result = result.result

        return results

    async def _execute_hybrid(
        self,
        plan: LLMWorkflowPlan,
        agent_executor: callable
    ) -> List[ExecutionResult]:
        """하이브리드 실행 (단계별 병렬)"""
        if not agent_executor:
            return []

        all_results = []
        step_results = {}

        for step_idx, step_agent_ids in enumerate(plan.execution_steps):
            # 이 단계에서 실행할 에이전트들
            step_assignments = [
                a for a in plan.agent_assignments
                if a.agent_id in step_agent_ids
            ]

            # 의존성 확인 및 컨텍스트 구성
            tasks = []
            for assignment in step_assignments:
                context = None
                if assignment.depends_on:
                    context = {
                        dep_id: step_results.get(dep_id)
                        for dep_id in assignment.depends_on
                        if dep_id in step_results
                    }
                tasks.append(
                    self._execute_single_agent(assignment, agent_executor, context)
                )

            # 이 단계 병렬 실행
            step_results_list = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(step_results_list):
                assignment = step_assignments[i]
                if isinstance(result, Exception):
                    exec_result = ExecutionResult(
                        task_id=f"task_step{step_idx}_{i}",
                        agent_id=assignment.agent_id,
                        success=False,
                        error=str(result)
                    )
                else:
                    exec_result = result
                    step_results[assignment.agent_id] = result.result

                all_results.append(exec_result)

        return all_results

    async def _execute_single_agent(
        self,
        assignment: AgentAssignment,
        agent_executor: callable,
        context: Any = None
    ) -> ExecutionResult:
        """단일 에이전트 실행"""
        start_time = time.time()

        try:
            result = await agent_executor(
                assignment.agent_id,
                assignment.agent_query,
                context
            )

            return ExecutionResult(
                task_id=f"task_{assignment.agent_id}",
                agent_id=assignment.agent_id,
                success=True,
                result=result,
                execution_time=time.time() - start_time
            )

        except Exception as e:
            return ExecutionResult(
                task_id=f"task_{assignment.agent_id}",
                agent_id=assignment.agent_id,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time
            )

    async def _merge_results(
        self,
        plan: LLMWorkflowPlan,
        results: List[ExecutionResult]
    ) -> Any:
        """결과 통합"""
        merge_config = plan.merge_config
        successful_results = [r for r in results if r.success]

        if not successful_results:
            return {"error": "모든 에이전트 실행 실패"}

        if merge_config.strategy == MergeStrategy.CONCATENATE:
            return self._merge_concatenate(successful_results, merge_config)
        elif merge_config.strategy == MergeStrategy.TABULAR:
            return self._merge_tabular(successful_results, merge_config)
        elif merge_config.strategy == MergeStrategy.HIERARCHICAL:
            return self._merge_hierarchical(successful_results, merge_config)
        elif merge_config.strategy == MergeStrategy.PRIORITY_BASED:
            return self._merge_priority_based(successful_results, merge_config)
        else:
            # SYNTHESIZE - 기본적으로 연결 후 LLM 통합 필요 (추후 구현)
            return self._merge_concatenate(successful_results, merge_config)

    def _merge_concatenate(
        self,
        results: List[ExecutionResult],
        config: MergeConfig
    ) -> str:
        """순차 연결 통합"""
        output_parts = []

        for result in results:
            if config.include_sources:
                output_parts.append(f"## {result.agent_id}\n\n{result.result}")
            else:
                output_parts.append(str(result.result))

        return "\n\n---\n\n".join(output_parts)

    def _merge_tabular(
        self,
        results: List[ExecutionResult],
        config: MergeConfig
    ) -> str:
        """표 형식 통합"""
        headers = ["에이전트", "결과"]
        rows = []

        for result in results:
            result_str = str(result.result)[:200]  # 200자 제한
            rows.append(f"| {result.agent_id} | {result_str} |")

        table = f"| {' | '.join(headers)} |\n| --- | --- |\n"
        table += "\n".join(rows)

        return table

    def _merge_hierarchical(
        self,
        results: List[ExecutionResult],
        config: MergeConfig
    ) -> Dict[str, Any]:
        """계층적 구조 통합"""
        return {
            "summary": "종합 결과",
            "sections": [
                {
                    "agent": r.agent_id,
                    "result": r.result,
                    "execution_time": r.execution_time
                }
                for r in results
            ]
        }

    def _merge_priority_based(
        self,
        results: List[ExecutionResult],
        config: MergeConfig
    ) -> Any:
        """우선순위 기반 통합"""
        if config.priority_order:
            # 우선순위 순으로 정렬
            priority_map = {
                agent_id: idx
                for idx, agent_id in enumerate(config.priority_order)
            }
            sorted_results = sorted(
                results,
                key=lambda r: priority_map.get(r.agent_id, 999)
            )
            # 가장 높은 우선순위 결과 반환
            return sorted_results[0].result if sorted_results else None
        else:
            return results[0].result if results else None


# ============================================================================
# 테스트 및 사용 예시
# ============================================================================

async def test_llm_orchestrator():
    """LLM Workflow Orchestrator 테스트"""
    logger.info("=" * 70)
    logger.info("🧠 LLM Workflow Orchestrator 테스트")
    logger.info("=" * 70)

    # 테스트 에이전트 목록
    test_agents = [
        {
            "agent_id": "calculator_agent",
            "name": "Calculator",
            "description": "수학 계산 및 연산 수행",
            "capabilities": [
                {"name": "arithmetic", "description": "기본 산술 연산"},
                {"name": "statistics", "description": "통계 계산"}
            ]
        },
        {
            "agent_id": "weather_agent",
            "name": "Weather",
            "description": "날씨 정보 조회 및 예보 제공",
            "capabilities": [
                {"name": "current_weather", "description": "현재 날씨 조회"},
                {"name": "forecast", "description": "일기 예보"}
            ]
        },
        {
            "agent_id": "internet_agent",
            "name": "Internet Search",
            "description": "인터넷 검색 및 정보 조사",
            "capabilities": [
                {"name": "web_search", "description": "웹 검색"},
                {"name": "news_search", "description": "뉴스 검색"}
            ]
        },
        {
            "agent_id": "analysis_agent",
            "name": "Analysis",
            "description": "데이터 분석 및 비교 검토",
            "capabilities": [
                {"name": "comparison", "description": "비교 분석"},
                {"name": "trend_analysis", "description": "트렌드 분석"}
            ]
        },
        {
            "agent_id": "samsung_gateway",
            "name": "Samsung Gateway",
            "description": "Samsung 반도체 관련 분석 및 대시보드",
            "capabilities": [
                {"name": "yield_analysis", "description": "수율 분석"},
                {"name": "market_analysis", "description": "시장 분석"}
            ]
        },
        {
            "agent_id": "restaurant_finder_agent",
            "name": "Restaurant Finder",
            "description": "맛집 검색 및 추천",
            "capabilities": [
                {"name": "search_nearby", "description": "주변 맛집 검색"},
                {"name": "recommendation", "description": "맛집 추천"}
            ]
        }
    ]

    # 오케스트레이터 초기화
    orchestrator = LLMWorkflowOrchestrator()
    await orchestrator.initialize()

    # 테스트 쿼리들
    test_queries = [
        "98-1 계산해줘",
        "삼성전자와 SK하이닉스의 반도체 시장 점유율을 비교 분석하고 투자 의견을 제시해줘",
        "제주도 3박4일 여행 계획 세워줘. 맛집, 관광지, 날씨 정보 포함해서",
        "오늘 서울 날씨 어때?",
    ]

    logger.info("\n📋 워크플로우 계획 생성 테스트")
    logger.info("-" * 70)

    for query in test_queries:
        logger.info(f"\n🔍 Query: {query[:50]}...")
        logger.info("-" * 50)

        plan = await orchestrator.create_workflow_plan(query, test_agents)

        logger.info(f"   📊 복잡도: {plan.complexity.value} ({plan.complexity_score:.2f})")
        logger.info(f"   🎯 의도: {plan.query_intent.value}")
        logger.info(f"   ⚡ 실행 전략: {plan.execution_strategy.value}")
        logger.info(f"   🤖 에이전트 수: {plan.total_agents}")

        if plan.agent_assignments:
            logger.info(f"   📋 할당된 에이전트:")
            for assignment in plan.agent_assignments:
                logger.info(f"      - {assignment.agent_id}: {assignment.task_description[:40]}...")

        logger.info(f"   🔗 통합 전략: {plan.merge_config.strategy.value}")
        logger.info(f"   ⏱️ 분석 시간: {plan.analysis_time:.2f}s")
        logger.info(f"   💬 Reasoning: {plan.reasoning[:80]}...")

    # 통계 출력
    logger.info("\n" + "=" * 70)
    logger.info("📊 오케스트레이터 통계")
    logger.info("-" * 70)
    stats = orchestrator.get_stats()
    for key, value in stats.items():
        logger.info(f"   {key}: {value}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_llm_orchestrator())
