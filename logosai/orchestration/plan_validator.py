"""
Plan Validator

Validates execution plans before execution to catch errors early.

Validation Checks:
1. Agent existence - All agents exist in registry
2. Dependency validation - input_from references are valid
3. Circular dependency check - No A→B→A cycles
4. Schema compatibility - Output types match input types
5. First stage validation - First stage has no input_from
"""

import json
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from .models import ExecutionPlan, ExecutionStage, AgentTask
from .agent_registry import AgentRegistry, get_registry
from .progress_streamer import ProgressStreamer
from .exceptions import (
    PlanValidationError,
    AgentNotFoundError,
    CircularDependencyError,
    SchemaCompatibilityError,
)

logger = logging.getLogger(__name__)

# 산출물 관문 (2026-08-11) — 판정은 LLM 이 한다.
#
# 첫 판은 "쿼리에 등장하는 고유 태그의 주인이 계획에 없으면 누락"이었다.
# 실제 레지스트리(106 에이전트)로 돌리니 **정상 계획조차** 막혔다:
#   "…도시별 여행 추천 한 줄을 붙여서 엑셀 표로…"
#     → restaurant_finder_agent 누락 (태그 '여행')  ← 오탐
# '여행 추천 한 줄'은 맛집 검색 요구가 아니다. 문자열은 문맥을 못 본다 —
# 이 프로젝트가 키워드 매칭을 금지하는 이유 그대로다.
#
# 패턴은 `enforce_exclusion_gate` 를 따른다: 좁은 단일 질문 · 주입된 llm_invoke ·
# fail-open. 질문을 **산출물 한정**으로 좁혀 관문이 넘보는 범위를 줄인다.

_ARTIFACT_PROMPT = """사용자 요청이 **명시적으로 요구한 최종 산출물(파일·문서)**이 있는지,
그리고 현재 계획이 그것을 만들 수 있는지 판단하세요.

사용자 요청: {query}

현재 계획에 포함된 에이전트:
{planned}

사용 가능한 에이전트:
{available}

판단 규칙:
- 사용자가 **직접 말한** 산출물만 본다. 추측해서 만들지 않는다.
- 계획의 에이전트 중 하나가 그 산출물을 만들 수 있으면 missing_agent 는 null 이다.
- 산출물 요구가 없으면 artifact 를 "none" 으로 둔다.

JSON 만 출력하세요:
{{"artifact": "요구된 산출물 또는 none", "missing_agent": "agent_id 또는 null"}}"""


async def check_artifact_capability(
    query: str,
    planned: Set[str],
    agents_info: Dict[str, str],
    llm_invoke=None,
) -> List[str]:
    """명시된 산출물을 낼 수 있는 에이전트가 계획에 있는가 (LLM 판정).

    Args:
        agents_info: {agent_id: description}

    Returns:
        오류 메시지 목록. 판정 불가·실패는 **빈 목록**(fail-open) — 관문 장애가
        서비스 장애가 되면 안 된다.
    """
    if not query or not agents_info or llm_invoke is None:
        return []
    try:
        prompt = _ARTIFACT_PROMPT.format(
            query=query,
            planned="\n".join(f"- {a}: {agents_info.get(a, '')[:80]}"
                               for a in sorted(planned)) or "- (없음)",
            available="\n".join(f"- {a}: {d[:80]}"
                                 for a, d in sorted(agents_info.items())),
        )
        raw = str(await llm_invoke(prompt))
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return []
        data = json.loads(m.group(0))
    except Exception as e:  # noqa: BLE001 — fail-open
        logger.warning(f"[ArtifactGate] 판정 실패: {e}")
        return []

    artifact = str(data.get("artifact") or "").strip()
    missing = data.get("missing_agent")
    if not artifact or artifact.lower() in ("none", "null", "없음"):
        return []
    if not missing or not isinstance(missing, str):
        return []
    if missing in planned:          # 자기모순 — 이미 계획에 있다
        return []
    if missing not in agents_info:  # 환각 — 없는 에이전트는 요구할 수 없다
        logger.warning(f"[ArtifactGate] 존재하지 않는 에이전트 지목: {missing}")
        return []
    return [f"산출물 누락: '{artifact}' 를 요구했으나 이를 만들 수 있는 "
            f"{missing} 가 계획에 없습니다"]


class PlanValidator:
    """
    Validates execution plans before they are executed.

    Performs comprehensive validation including:
    - Agent existence checks
    - Dependency graph validation
    - Circular dependency detection
    - Schema compatibility verification
    - First stage validation

    Example:
        validator = PlanValidator()
        result = await validator.validate(plan)
        if not result.is_valid:
            print(f"Validation errors: {result.errors}")
    """

    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        streamer: Optional[ProgressStreamer] = None,
        llm_invoke=None,
    ):
        """
        Initialize Plan Validator.

        Args:
            registry: Agent registry for agent existence checks
            streamer: Progress streamer for status updates
        """
        self.registry = registry or get_registry()
        self.streamer = streamer
        # 산출물 관문용. 없으면 관문은 침묵한다 (문자열 매칭으로 되돌아가지 않는다).
        self.llm_invoke = llm_invoke

    async def validate(self, plan: ExecutionPlan) -> "ValidationResult":
        """
        Validate the execution plan.

        Args:
            plan: Execution plan to validate

        Returns:
            ValidationResult with is_valid flag and any errors
        """
        errors: List[str] = []
        warnings: List[str] = []

        # Emit validation start
        if self.streamer:
            await self.streamer.validation_start()

        try:
            # 1. Basic structure validation
            structure_errors = self._validate_structure(plan)
            errors.extend(structure_errors)

            # 2. Agent existence validation
            agent_errors = self._validate_agents_exist(plan)
            errors.extend(agent_errors)

            # 3. First stage validation
            first_stage_errors = self._validate_first_stage(plan)
            errors.extend(first_stage_errors)

            # 4. Dependency validation
            dependency_errors = self._validate_dependencies(plan)
            errors.extend(dependency_errors)

            # 5. Circular dependency check
            circular_errors = self._check_circular_dependencies(plan)
            errors.extend(circular_errors)

            # 6. Schema compatibility check
            schema_errors = self._validate_schema_compatibility(plan)
            errors.extend(schema_errors)

            # 7. 산출물 관문 (2026-08-11) — 명시된 산출물을 만들 에이전트가 있는가.
            #    errors 로 올려 상위의 기존 재계획 루프(MAX_ATTEMPTS)를 태운다.
            #    실측: 게이트 전 40% → 후 100% (같은 쿼리 5회).
            errors.extend(await self._validate_artifact(plan))

            # 8. Additional warnings (non-blocking)
            warnings = self._generate_warnings(plan)

            # Build result
            result = ValidationResult(
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                plan=plan,
            )

            # Update plan validation status
            plan.is_validated = result.is_valid
            plan.validation_errors = errors

            # Emit validation result
            if self.streamer:
                if result.is_valid:
                    # 판정(경고 포함)을 넘긴다 — 종전엔 통과 시 경고가 통째로 유실
                    await self.streamer.validation_complete(result)
                else:
                    await self.streamer.validation_error(errors)

            if errors:
                logger.warning(
                    f"[PlanValidator] Validation failed with {len(errors)} errors"
                )
                for err in errors:
                    logger.warning(f"  - {err}")
            else:
                logger.info("[PlanValidator] Validation passed")

            return result

        except Exception as e:
            logger.error(f"[PlanValidator] Validation exception: {e}")
            if self.streamer:
                await self.streamer.validation_error([str(e)])
            raise

    async def _validate_artifact(self, plan: ExecutionPlan) -> List[str]:
        """산출물 관문 배선. llm_invoke 가 주입되지 않으면 침묵한다."""
        if self.llm_invoke is None:
            return []
        try:
            agents_info: Dict[str, str] = {}
            for entry in (self.registry.list_agents() or []):
                aid = getattr(entry, "agent_id", None)
                if aid:
                    agents_info[aid] = str(getattr(entry, "description", "") or "")
            planned = {t.agent_id for st in plan.stages for t in (st.agents or [])}
            return await check_artifact_capability(
                plan.query or "", planned, agents_info, self.llm_invoke)
        except Exception as e:  # noqa: BLE001 — 관문 장애가 검증을 죽이면 안 된다
            logger.warning(f"[PlanValidator] 산출물 관문 건너뜀: {e}")
            return []

    def _validate_structure(self, plan: ExecutionPlan) -> List[str]:
        """Validate basic plan structure"""
        errors = []

        if not plan.query:
            errors.append("Plan has no query")

        if not plan.stages:
            errors.append("Plan has no stages")

        if plan.workflow_strategy not in ["sequential", "parallel", "hybrid"]:
            errors.append(
                f"Invalid workflow strategy: {plan.workflow_strategy}. "
                f"Must be one of: sequential, parallel, hybrid"
            )

        for stage in plan.stages:
            if not stage.agents:
                errors.append(f"Stage {stage.stage_id} has no agents")

            if stage.execution_type not in ["sequential", "parallel"]:
                errors.append(
                    f"Stage {stage.stage_id} has invalid execution_type: "
                    f"{stage.execution_type}. Must be: sequential or parallel"
                )

            for agent in stage.agents:
                if not agent.agent_id:
                    errors.append(
                        f"Stage {stage.stage_id} has agent without agent_id"
                    )
                if not agent.sub_query:
                    errors.append(
                        f"Stage {stage.stage_id} agent {agent.agent_id} has no sub_query"
                    )

        return errors

    def _validate_agents_exist(self, plan: ExecutionPlan) -> List[str]:
        """Check all agents exist in registry"""
        errors = []

        for stage in plan.stages:
            for agent in stage.agents:
                if not self.registry.has_agent(agent.agent_id):
                    available = self.registry.get_agent_ids()
                    errors.append(
                        f"Agent '{agent.agent_id}' not found in registry. "
                        f"Available agents: {', '.join(available)}"
                    )

        return errors

    def _validate_first_stage(self, plan: ExecutionPlan) -> List[str]:
        """Validate first stage has no input dependencies"""
        errors = []

        if plan.stages:
            first_stage = plan.stages[0]
            for agent in first_stage.agents:
                if agent.input_from:
                    errors.append(
                        f"First stage agent '{agent.agent_id}' has input_from "
                        f"dependency: {agent.input_from}. First stage should "
                        f"not have input dependencies."
                    )

        return errors

    def _validate_dependencies(self, plan: ExecutionPlan) -> List[str]:
        """Validate all input_from references are valid"""
        errors = []

        # Build a map of all available outputs
        available_outputs: Set[str] = set()
        stage_map: Dict[int, List[str]] = {}

        for stage in plan.stages:
            stage_outputs = []
            for agent in stage.agents:
                output_ref = f"stage_{stage.stage_id}.{agent.agent_id}"
                available_outputs.add(output_ref)
                stage_outputs.append(output_ref)
            stage_map[stage.stage_id] = stage_outputs

        # Check dependencies
        for stage in plan.stages:
            for agent in stage.agents:
                if agent.input_from:
                    for input_ref in agent.input_from:
                        # Parse input reference
                        if input_ref.startswith("stage_"):
                            # Full reference: stage_1.internet_agent
                            if input_ref not in available_outputs:
                                # Check if it's a stage-only reference
                                parts = input_ref.split(".")
                                if len(parts) == 1:
                                    # Just stage reference
                                    stage_num = int(parts[0].replace("stage_", ""))
                                    if stage_num >= stage.stage_id:
                                        errors.append(
                                            f"Agent '{agent.agent_id}' in stage "
                                            f"{stage.stage_id} references future "
                                            f"stage: {input_ref}"
                                        )
                                else:
                                    errors.append(
                                        f"Agent '{agent.agent_id}' references "
                                        f"invalid output: {input_ref}"
                                    )
                        elif input_ref == "final":
                            # Reference to final output - valid
                            pass
                        else:
                            errors.append(
                                f"Agent '{agent.agent_id}' has invalid "
                                f"input_from format: {input_ref}"
                            )

        return errors

    def _check_circular_dependencies(self, plan: ExecutionPlan) -> List[str]:
        """Detect circular dependencies using DFS"""
        errors = []

        # Build dependency graph
        graph: Dict[str, List[str]] = {}

        for stage in plan.stages:
            for agent in stage.agents:
                node = f"stage_{stage.stage_id}.{agent.agent_id}"
                graph[node] = []

                if agent.input_from:
                    for input_ref in agent.input_from:
                        if input_ref and input_ref != "final":
                            graph[node].append(input_ref)

        # DFS to detect cycles
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        path: List[str] = []

        def dfs(node: str) -> Optional[List[str]]:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    cycle = dfs(neighbor)
                    if cycle:
                        return cycle
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    return path[cycle_start:] + [neighbor]

            path.pop()
            rec_stack.remove(node)
            return None

        for node in graph:
            if node not in visited:
                cycle = dfs(node)
                if cycle:
                    errors.append(
                        f"Circular dependency detected: {' → '.join(cycle)}"
                    )
                    break

        return errors

    def _validate_schema_compatibility(self, plan: ExecutionPlan) -> List[str]:
        """Check that agent output schemas are compatible with input schemas"""
        errors = []

        for i, stage in enumerate(plan.stages):
            for agent in stage.agents:
                if agent.input_from:
                    target_agent = self.registry.get_agent_safe(agent.agent_id)
                    if not target_agent:
                        continue  # Already caught by existence check

                    for input_ref in agent.input_from:
                        if not input_ref or input_ref == "final":
                            continue

                        # Parse source agent from reference
                        parts = input_ref.split(".")
                        if len(parts) == 2:
                            source_agent_id = parts[1]
                            source_agent = self.registry.get_agent_safe(source_agent_id)

                            if source_agent:
                                if not self.registry.get_schema_compatibility(
                                    source_agent_id, agent.agent_id
                                ):
                                    errors.append(
                                        f"Schema incompatibility: {source_agent_id} "
                                        f"outputs '{source_agent.schema.output_type}' but "
                                        f"{agent.agent_id} expects "
                                        f"'{target_agent.schema.input_type}'"
                                    )

        return errors

    def _generate_warnings(self, plan: ExecutionPlan) -> List[str]:
        """Generate non-blocking warnings"""
        warnings = []

        # Check for potentially slow operations
        total_agents = plan.get_total_agents()
        if total_agents > 5:
            warnings.append(
                f"Plan has {total_agents} agents. Consider optimizing for performance."
            )

        # Check for sequential stages that could be parallel
        for stage in plan.stages:
            if stage.execution_type == "sequential" and len(stage.agents) > 1:
                # Check if agents are independent
                has_internal_deps = False
                for agent in stage.agents:
                    if agent.input_from:
                        for ref in agent.input_from:
                            if f"stage_{stage.stage_id}." in ref:
                                has_internal_deps = True
                                break

                if not has_internal_deps:
                    warnings.append(
                        f"Stage {stage.stage_id} has {len(stage.agents)} sequential "
                        f"agents with no internal dependencies. "
                        f"Consider using parallel execution."
                    )

        # Check for empty final_aggregation
        if not plan.final_aggregation:
            warnings.append(
                "Plan has no final_aggregation strategy. "
                "Results will be combined by default."
            )

        return warnings

    def validate_sync(self, plan: ExecutionPlan) -> "ValidationResult":
        """Synchronous validation (for use without asyncio)"""
        import asyncio
        return asyncio.run(self.validate(plan))


class ValidationResult:
    """Result of plan validation"""

    def __init__(
        self,
        is_valid: bool,
        errors: List[str],
        warnings: List[str],
        plan: ExecutionPlan,
    ):
        self.is_valid = is_valid
        self.errors = errors
        self.warnings = warnings
        self.plan = plan

    def to_dict(self) -> Dict:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }

    def raise_if_invalid(self):
        """Raise PlanValidationError if validation failed"""
        if not self.is_valid:
            raise PlanValidationError(
                message=f"Plan validation failed with {len(self.errors)} errors",
                validation_errors=self.errors,
            )


# Factory function
def create_plan_validator(
    registry: Optional[AgentRegistry] = None,
    streamer: Optional[ProgressStreamer] = None,
) -> PlanValidator:
    """Create a PlanValidator instance with default configuration"""
    return PlanValidator(registry=registry, streamer=streamer)
