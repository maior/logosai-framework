"""
Execution Engine

Executes the validated plan with support for sequential, parallel,
and hybrid execution strategies.

Features:
- Stage-based execution (sequential within stage, parallel across agents)
- Automatic retry with exponential backoff
- Data transformation between agents
- Real-time progress streaming
- Graceful error handling
"""

import asyncio
import html as _html_mod
import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import (
    AgentTask,
    AgentResult,
    AgentStatus,
    ExecutionPlan,
    ExecutionStage,
    StageResult,
    WorkflowResult,
)
from .agent_registry import AgentRegistry, get_registry
from .data_transformer import DataTransformer
from .progress_streamer import ProgressStreamer
from .exceptions import (
    ExecutionError,
    AgentExecutionError,
    AgentTimeoutError,
)

logger = logging.getLogger(__name__)


# Type for agent executor function
AgentExecutor = Callable[[str, str, Optional[Dict[str, Any]]], Any]


class ExecutionEngine:
    """
    Executes validated execution plans with parallel/sequential support.

    Handles:
    - Sequential stage execution (stages run one after another)
    - Parallel/sequential agent execution within stages
    - Data transformation between agents
    - Retry logic for failed agents
    - Progress streaming for frontend visualization

    Example:
        engine = ExecutionEngine(agent_executor=my_executor)
        result = await engine.execute(plan)
    """

    DEFAULT_TIMEOUT_MS = 120000  # 120 seconds (2 minutes) for LLM-heavy agents
    MAX_RETRIES = 2
    RETRY_BASE_DELAY = 1.0  # seconds

    def __init__(
        self,
        agent_executor: Optional[AgentExecutor] = None,
        registry: Optional[AgentRegistry] = None,
        transformer: Optional[DataTransformer] = None,
        streamer: Optional[ProgressStreamer] = None,
    ):
        """
        Initialize Execution Engine.

        Args:
            agent_executor: Function to execute agents (agent_id, sub_query, context) -> result
            registry: Agent registry
            transformer: Data transformer for agent I/O
            streamer: Progress streamer for real-time updates
        """
        self.agent_executor = agent_executor or self._default_executor
        self.registry = registry or get_registry()
        self.transformer = transformer or DataTransformer(registry=self.registry)
        self.streamer = streamer

        # Execution state
        self._stage_results: Dict[int, StageResult] = {}
        self._agent_results: Dict[str, AgentResult] = {}

    async def execute(
        self,
        plan: ExecutionPlan,
        context: Optional[Dict[str, Any]] = None,
    ) -> WorkflowResult:
        """
        Execute the given plan.

        Args:
            plan: Validated execution plan
            context: Optional execution context

        Returns:
            WorkflowResult with all stage and agent results
        """
        workflow_id = plan.plan_id or str(uuid.uuid4())[:8]
        start_time = time.time()
        # 원 사용자 쿼리 보존 — stage sub_query 재작성으로 소실되는 수치/조건을
        # 에이전트가 context.original_query 로 복원할 수 있게 전달
        self._current_user_query = plan.query or ""

        logger.info(
            f"[ExecutionEngine] Starting workflow {workflow_id}: "
            f"{plan.get_stage_count()} stages, {plan.get_total_agents()} agents"
        )

        # Initialize result tracking
        self._stage_results = {}
        self._agent_results = {}

        # Emit workflow start
        if self.streamer:
            await self.streamer.workflow_start(plan.query)

        try:
            # Execute stages sequentially
            all_stage_results: List[StageResult] = []
            current_output: Any = None

            for stage in plan.stages:
                stage_result = await self._execute_stage(
                    stage=stage,
                    previous_output=current_output,
                    context=context,
                )

                all_stage_results.append(stage_result)
                self._stage_results[stage.stage_id] = stage_result

                # Update current output for next stage
                current_output = stage_result.aggregated_output

                # Stop on stage failure if critical
                if not stage_result.success:
                    logger.warning(
                        f"[ExecutionEngine] Stage {stage.stage_id} failed, "
                        f"continuing with partial results"
                    )

            # Calculate statistics
            total_time_ms = (time.time() - start_time) * 1000
            total_agents = sum(len(sr.results) for sr in all_stage_results)
            successful_agents = sum(
                len(sr.get_successful_results()) for sr in all_stage_results
            )
            failed_agents = total_agents - successful_agents

            # Build final output
            final_output = self._build_final_output(
                all_stage_results, plan.final_aggregation
            )

            # Determine overall success
            success = failed_agents == 0 or (
                successful_agents > 0 and final_output is not None
            )

            result = WorkflowResult(
                success=success,
                workflow_id=workflow_id,
                query=plan.query,
                stages=all_stage_results,
                final_output=final_output,
                start_time=datetime.now(),
                total_time_ms=total_time_ms,
                plan=plan,
                total_agents_executed=total_agents,
                successful_agents=successful_agents,
                failed_agents=failed_agents,
            )

            # Emit workflow complete
            if self.streamer:
                await self.streamer.workflow_complete(
                    success=success,
                    final_output=final_output,
                )

            logger.info(
                f"[ExecutionEngine] Workflow {workflow_id} completed in "
                f"{total_time_ms:.0f}ms: {successful_agents}/{total_agents} agents succeeded"
            )

            return result

        except Exception as e:
            logger.error(f"[ExecutionEngine] Workflow failed: {e}")

            # Emit workflow error
            if self.streamer:
                await self.streamer.workflow_complete(
                    success=False,
                    error=str(e),
                )

            raise ExecutionError(
                message=f"Workflow execution failed: {e}",
            )

    async def _execute_stage(
        self,
        stage: ExecutionStage,
        previous_output: Any,
        context: Optional[Dict[str, Any]],
    ) -> StageResult:
        """Execute a single stage"""
        stage_start = time.time()

        # Emit stage start
        agent_ids = [a.agent_id for a in stage.agents]
        if self.streamer:
            await self.streamer.stage_start(
                stage_id=stage.stage_id,
                execution_type=stage.execution_type,
                agent_ids=agent_ids,
            )

        logger.info(
            f"[ExecutionEngine] Stage {stage.stage_id} ({stage.execution_type}): "
            f"{len(stage.agents)} agents"
        )

        try:
            if stage.execution_type == "parallel":
                results = await self._execute_parallel(
                    stage=stage,
                    previous_output=previous_output,
                    context=context,
                )
            else:
                results = await self._execute_sequential(
                    stage=stage,
                    previous_output=previous_output,
                    context=context,
                )

            # Aggregate stage results
            stage_time = (time.time() - stage_start) * 1000
            success = all(r.success for r in results)

            # Create aggregated output for next stage
            if success:
                if len(results) == 1:
                    aggregated = results[0].data
                else:
                    aggregated = [r.data for r in results]
            else:
                # Include successful results even if some failed
                aggregated = [r.data for r in results if r.success]

            stage_result = StageResult(
                stage_id=stage.stage_id,
                execution_type=stage.execution_type,
                success=success,
                results=results,
                total_time_ms=stage_time,
                aggregated_output=aggregated,
            )

            # Emit stage complete
            if self.streamer:
                await self.streamer.stage_complete(
                    stage_id=stage.stage_id,
                    success=success,
                    results_count=len(results),
                )

            return stage_result

        except Exception as e:
            logger.error(f"[ExecutionEngine] Stage {stage.stage_id} failed: {e}")

            stage_time = (time.time() - stage_start) * 1000
            return StageResult(
                stage_id=stage.stage_id,
                execution_type=stage.execution_type,
                success=False,
                results=[],
                total_time_ms=stage_time,
            )

    async def _execute_parallel(
        self,
        stage: ExecutionStage,
        previous_output: Any,
        context: Optional[Dict[str, Any]],
    ) -> List[AgentResult]:
        """Execute agents in parallel"""
        tasks = []

        occurrences = self._occurrences(stage.agents)
        for agent_task, occurrence in zip(stage.agents, occurrences):
            task = asyncio.create_task(
                self._execute_agent(
                    agent_task=agent_task,
                    stage_id=stage.stage_id,
                    previous_output=previous_output,
                    context=context,
                    occurrence=occurrence,
                )
            )
            tasks.append(task)

        # Wait for all tasks
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        agent_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Task raised exception
                agent_task = stage.agents[i]
                agent_results.append(
                    AgentResult(
                        agent_id=agent_task.agent_id,
                        stage_id=stage.stage_id,
                        success=False,
                        error=str(result),
                    )
                )
            else:
                agent_results.append(result)

        return agent_results

    async def _execute_sequential(
        self,
        stage: ExecutionStage,
        previous_output: Any,
        context: Optional[Dict[str, Any]],
    ) -> List[AgentResult]:
        """Execute agents sequentially, passing output to next"""
        results = []
        current_input = previous_output

        occurrences = self._occurrences(stage.agents)
        for agent_task, occurrence in zip(stage.agents, occurrences):
            result = await self._execute_agent(
                agent_task=agent_task,
                stage_id=stage.stage_id,
                previous_output=current_input,
                context=context,
                occurrence=occurrence,
            )
            results.append(result)

            # Pass output to next agent (for sequential chains)
            if result.success:
                current_input = result.data
            else:
                # Continue with None if agent failed
                current_input = None

        return results

    @staticmethod
    def _occurrences(agents: List[AgentTask]) -> List[int]:
        """stage 안에서 같은 agent_id 가 몇 번째 등장인지 (정의 순서, 0부터)."""
        seen: Dict[str, int] = {}
        out: List[int] = []
        for task in agents:
            n = seen.get(task.agent_id, 0)
            out.append(n)
            seen[task.agent_id] = n + 1
        return out

    @staticmethod
    def _result_key(stage_id: int, agent_id: str, occurrence: int = 0) -> str:
        """결과 저장 키 — 같은 stage 의 동일 agent_id 중복을 구분한다.

        2026-08-10 C1 실측: stage1 이 `weather_agent×3 + currency` 병렬이었는데
        키가 `stage_1.weather_agent` 하나뿐이라 **서울·부산이 제주에 덮여** 사라졌다.
        `_call_agent` 가 이 dict 로 `previous_results`(구조화 채널)를 만들므로
        하류 에이전트는 3개 도시 중 1개만 구조화로 보고, 나머지는 2000자 절단
        산문에서 재파싱해야 했다.

        첫 등장은 접미사 없음 — 기존 키(`stage_{id}.{agent_id}`)와 `get_agent_result`
        조회가 그대로 유효하다.
        """
        base = f"stage_{stage_id}.{agent_id}"
        return base if occurrence <= 0 else f"{base}#{occurrence + 1}"

    async def _execute_agent(
        self,
        agent_task: AgentTask,
        stage_id: int,
        previous_output: Any,
        context: Optional[Dict[str, Any]],
        occurrence: int = 0,
    ) -> AgentResult:
        """Execute a single agent with retry logic"""
        agent_id = agent_task.agent_id
        result_key = self._result_key(stage_id, agent_id, occurrence)
        sub_query = agent_task.sub_query
        timeout_ms = agent_task.timeout_ms or self.DEFAULT_TIMEOUT_MS
        max_retries = agent_task.max_retries

        # Emit agent start
        agent_entry = self.registry.get_agent_safe(agent_id)
        display_name = agent_entry.display_name if agent_entry else agent_id

        if self.streamer:
            await self.streamer.agent_queued(
                agent_id=agent_id,
                stage_id=stage_id,
                sub_query=sub_query,
                display_name=display_name,
            )

        # Prepare input data
        input_data = previous_output
        if agent_task.input_from and previous_output is not None:
            # Transform data if needed
            for input_ref in agent_task.input_from:
                if "." in input_ref:
                    source_agent = input_ref.split(".")[-1]
                    input_data = await self.transformer.transform(
                        source_agent=source_agent,
                        target_agent=agent_id,
                        data=previous_output,
                    )
                    break

        # Execute with retry
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                if self.streamer:
                    await self.streamer.agent_start(
                        agent_id=agent_id,
                        stage_id=stage_id,
                        sub_query=sub_query,
                        display_name=display_name,
                    )

                start_time = time.time()

                # Execute with timeout
                result = await asyncio.wait_for(
                    self._call_agent(agent_id, sub_query, input_data, context),
                    timeout=timeout_ms / 1000,
                )

                execution_time = (time.time() - start_time) * 1000

                # Create success result
                agent_result = AgentResult(
                    agent_id=agent_id,
                    stage_id=stage_id,
                    success=True,
                    data=result,
                    execution_time_ms=execution_time,
                    retry_count=attempt,
                )

                # Store result
                self._agent_results[result_key] = agent_result

                # Emit agent complete
                if self.streamer:
                    result_preview = str(result)[:100] if result else None
                    await self.streamer.agent_complete(
                        agent_id=agent_id,
                        stage_id=stage_id,
                        success=True,
                        result_preview=result_preview,
                        full_result=result,  # Pass full result as well
                    )

                return agent_result

            except asyncio.TimeoutError:
                last_error = f"Timeout after {timeout_ms}ms"
                logger.warning(
                    f"[ExecutionEngine] Agent {agent_id} timeout (attempt {attempt + 1})"
                )

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"[ExecutionEngine] Agent {agent_id} failed (attempt {attempt + 1}): {e}"
                )

            # Retry with delay
            if attempt < max_retries:
                delay = self.RETRY_BASE_DELAY * (2 ** attempt)

                if self.streamer:
                    await self.streamer.agent_retry(
                        agent_id=agent_id,
                        stage_id=stage_id,
                        retry_count=attempt + 1,
                        reason=last_error,
                    )

                await asyncio.sleep(delay)

        # All retries failed
        agent_result = AgentResult(
            agent_id=agent_id,
            stage_id=stage_id,
            success=False,
            error=last_error,
            retry_count=max_retries,
        )

        self._agent_results[result_key] = agent_result

        # Emit agent error
        if self.streamer:
            await self.streamer.agent_complete(
                agent_id=agent_id,
                stage_id=stage_id,
                success=False,
                error=last_error,
            )

        return agent_result

    async def _call_agent(
        self,
        agent_id: str,
        sub_query: str,
        input_data: Any,
        context: Optional[Dict[str, Any]],
    ) -> Any:
        """Call the actual agent executor"""
        # Build execution context
        exec_context = context.copy() if context else {}
        exec_context["input_data"] = input_data
        exec_context.setdefault("original_query", getattr(self, "_current_user_query", ""))

        # 전 스테이지 구조화 핸드오프 (Agentic Upgrade Phase 2) — 직전 스테이지의
        # 2000자 절단 문자열만으로는 하류 에이전트가 상류 원문을 못 본다 (실측:
        # viz 가 internet 결과 접근 불가). 성공한 모든 이전 결과를 무절단으로 탑재
        # — 에이전트는 logosai HandoffEnvelope(get_handoff)로 표준 소비한다.
        prior = {
            key.split(".", 1)[1]: ar.data
            for key, ar in getattr(self, "_agent_results", {}).items()
            if ar.success and ar.data is not None
        }
        if prior:
            try:
                from logosai.utils.safe_json import json_safe
                prior = json_safe(prior)  # NaN/Inf → null (HTTP JSON 직렬화 안전)
            except ImportError:
                pass
            exec_context.setdefault("previous_results", prior)

        # 🔥 Include the previous stage result in sub_query so the agent can utilize it
        enriched_query = self._enrich_query_with_input(sub_query, input_data, agent_id)

        # Call executor
        result = await self.agent_executor(agent_id, enriched_query, exec_context)

        return result

    @staticmethod
    def _looks_like_html_page(text: str) -> bool:
        """표시용 full-HTML(문서/스타일 블록 시작)인지 보수적으로 감지.

        인라인 태그가 섞인 markdown 을 오탐하지 않도록 문서 시작 마커만 본다.
        """
        lowered = text.lstrip()[:100].lower()
        return lowered.startswith(("<!doctype", "<html", "<style"))

    @staticmethod
    def _html_to_text(text: str) -> str:
        """full-HTML answer 를 핸드오프용 순수 텍스트로 변환.

        script/style 본문 제거 → 블록 태그를 개행으로 → 나머지 태그 제거 →
        엔티티 복원 → 공백 정리. (표시 경로는 건드리지 않음 — 핸드오프 전용)
        """
        cleaned = re.sub(r"<(script|style)\b[\s\S]*?</\1\s*>", " ", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"</(div|p|li|tr|h[1-6])\s*>|<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = _html_mod.unescape(cleaned)
        lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in cleaned.splitlines()]
        return "\n".join(ln for ln in lines if ln)

    def _extract_core_result(self, data: Any, depth: int = 0) -> str:
        """
        Recursively extract core result (answer, result, content) from nested data.

        Args:
            data: Data to extract from
            depth: Recursion depth (to prevent infinite recursion)

        Returns:
            Core result string or empty string
        """
        if depth > 5:  # Prevent infinite recursion
            return ""

        if data is None:
            return ""

        if isinstance(data, str):
            # 상류(DataTransformer 등)가 stage 결과를 JSON '문자열'로 직렬화해
            # 전달하는 실경로(2026-07-07 프로브 실측) — JSON 이면 파싱해 핵심만
            # 압축 추출. 비JSON 텍스트는 기존대로 그대로 반환.
            stripped = data.strip()
            if stripped[:1] in ("[", "{"):
                try:
                    parsed = json.loads(stripped)
                    extracted = self._extract_core_result(parsed, depth + 1)
                    if extracted:
                        return extracted
                except (ValueError, TypeError):
                    pass
            # full-HTML answer(예: scheduler 프리미엄 뷰)는 표시용 — 핸드오프
            # 데이터로는 태그를 걷어낸 텍스트가 맞다 (D3 실측: HTML 이 다음
            # stage 입력과 최종 join 을 오염). 인라인 태그 섞인 markdown 은
            # 건드리지 않도록 문서 시작 마커로만 보수적으로 감지.
            if self._looks_like_html_page(stripped):
                return self._html_to_text(stripped)
            return data

        if isinstance(data, (int, float, bool)):
            return str(data)

        if isinstance(data, dict):
            # 1. Check for direct answer field
            # (str 이어도 재귀 — str 분기의 HTML→텍스트 등 정규화를 통과시킴)
            if "answer" in data:
                return self._extract_core_result(data["answer"], depth + 1)

            # 2. Check for result field (may be nested)
            if "result" in data:
                result = data["result"]
                if isinstance(result, str):
                    return result
                extracted = self._extract_core_result(result, depth + 1)
                if extracted:
                    return extracted

            # 3. Check for content field
            if "content" in data:
                content = data["content"]
                if isinstance(content, str):
                    return content
                return self._extract_core_result(content, depth + 1)

            # 4. Check for data field (may be nested)
            if "data" in data:
                inner_data = data["data"]
                extracted = self._extract_core_result(inner_data, depth + 1)
                if extracted:
                    return extracted

            # 5. Check for text field
            if "text" in data:
                text = data["text"]
                if isinstance(text, str):
                    return text

            # 6. Fall back to full JSON conversion
            try:
                return json.dumps(data, ensure_ascii=False, indent=2)
            except:
                return str(data)

        if isinstance(data, list):
            if len(data) == 1:
                return self._extract_core_result(data[0], depth + 1)
            # 병렬 stage 결과 리스트 (2026-07-07): 각 항목의 핵심(answer/result/
            # content)만 추출해 [결과 N] 라벨로 압축. 통 JSON 직렬화는 metadata·
            # source_info 가 _enrich_query_with_input 의 2000자 예산을 잠식해
            # 뒷 병렬 결과가 잘리는 문제가 있었다(하이브리드 실측).
            parts = []
            for i, item in enumerate(data):
                core = self._extract_core_result(item, depth + 1)
                if core and core.strip():
                    parts.append(f"[결과 {i + 1}]\n{core.strip()}")
            if parts:
                return "\n\n".join(parts)
            # 아무 항목도 핵심 추출 실패 → 기존 JSON fallback 유지
            try:
                return json.dumps(data, ensure_ascii=False, indent=2)
            except:
                return str(data)

        return str(data)

    def _enrich_query_with_input(
        self,
        sub_query: str,
        input_data: Any,
        agent_id: str,
    ) -> str:
        """
        Integrate the previous stage result into sub_query.

        Converts an abstract sub_query (e.g. "deliver the calculation result")
        into a concrete query containing the actual data.
        """
        if input_data is None:
            return sub_query

        # Extract core result from input_data
        input_str = self._extract_core_result(input_data)

        if not input_str:
            return sub_query

        # Truncate if too long
        max_input_len = 2000
        if len(input_str) > max_input_len:
            input_str = input_str[:max_input_len] + "... (truncated)"

        # Build enriched query
        enriched_query = f"""[이전 단계 결과]
{input_str}

[요청]
{sub_query}

위의 이전 단계 결과를 활용하여 요청에 응답해주세요."""

        logger.info(
            f"[ExecutionEngine] Enriched query (v2-compact) for {agent_id}: "
            f"input_data length={len(input_str)}, original query='{sub_query[:50]}...'"
        )

        return enriched_query

    def _build_final_output(
        self,
        stage_results: List[StageResult],
        aggregation: Dict[str, Any],
    ) -> Any:
        """Build final output from all stage results"""
        if not stage_results:
            return None

        # Get last stage's output
        last_stage = stage_results[-1]

        if not last_stage.results:
            return None

        aggregation_type = aggregation.get("type", "combine")

        if aggregation_type == "single":
            # Return single result (usually visualization)
            if last_stage.results:
                return last_stage.results[-1].data
            return None

        elif aggregation_type == "combine":
            # Combine all results
            all_data = []
            for stage in stage_results:
                for result in stage.results:
                    if result.success and result.data:
                        all_data.append({
                            "agent_id": result.agent_id,
                            "stage_id": result.stage_id,
                            "data": result.data,
                        })
            return all_data

        elif aggregation_type == "last":
            # Return only last result
            return last_stage.aggregated_output

        else:
            # Default: return aggregated from last stage
            return last_stage.aggregated_output

    async def _default_executor(
        self,
        agent_id: str,
        sub_query: str,
        context: Optional[Dict[str, Any]],
    ) -> Any:
        """Default agent executor (for testing)"""
        logger.warning(
            f"[ExecutionEngine] Using default executor for {agent_id}. "
            f"Provide a real executor for production use."
        )

        # Simulate execution
        await asyncio.sleep(0.5)

        return {
            "agent_id": agent_id,
            "query": sub_query,
            "result": f"Mock result from {agent_id}",
            "timestamp": datetime.now().isoformat(),
        }

    def get_agent_result(self, stage_id: int, agent_id: str) -> Optional[AgentResult]:
        """Get result for specific agent"""
        key = f"stage_{stage_id}.{agent_id}"
        return self._agent_results.get(key)

    def get_stage_result(self, stage_id: int) -> Optional[StageResult]:
        """Get result for specific stage"""
        return self._stage_results.get(stage_id)


# Factory function
def create_execution_engine(
    agent_executor: Optional[AgentExecutor] = None,
    registry: Optional[AgentRegistry] = None,
    streamer: Optional[ProgressStreamer] = None,
) -> ExecutionEngine:
    """Create an ExecutionEngine instance with default configuration"""
    return ExecutionEngine(
        agent_executor=agent_executor,
        registry=registry,
        streamer=streamer,
    )
