"""계획 수립 — 사용자 쿼리를 stage 계획(ExecutionPlan)으로 바꾼다.

메커니즘만 담는다: 계획 흐름, 응답 파싱, 실행 계획 구성, 계획 비평, gap 백필·정규화,
단계 병합. 특정 조직의 에이전트 지식(라우팅 규칙, 예시, 배제 표식, 키워드)은 없다.

조직별 플래너는 이 클래스를 상속해 훅을 재정의한다:
  _build_planning_prompt  계획 프롬프트            (기본: 등록된 에이전트로 만든 일반 프롬프트)
  _call_llm               LLM 호출                 (기본: 주입한 llm_invoke, 없으면 LLMClient)
  _recommend              선택기 힌트              (기본: 없음)
  _apply_exclusion_gate   에이전트 배제 규칙 집행   (기본: 없음)
  _explicit_gap           코드 수준 gap 안전망      (기본: 없음)
Logos 운영 플래너가 그 예다: ontology.orchestrator.query_planner.QueryPlanner.

정본 이전 (2026-10-04, orchestrator-unify P2): 이 흐름은 ontology/orchestrator/
query_planner.py 에 있었다. 동작을 바꾸지 않고 옮겼다 — ontology 의 황금 기록 테스트가
LLM 에 보내는 프롬프트 전부와 최종 계획이 이전과 바이트 단위로 같음을 확인한다.
"""

import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .agent_registry import AgentRegistry, get_registry
from .exceptions import PlanningError
from .models import AgentTask, ExecutionPlan, ExecutionStage
from .progress_streamer import ProgressStreamer

logger = logging.getLogger(__name__)

LLMInvoke = Callable[[str], Awaitable[str]]


async def critique_plan(
    query: str,
    plan_data: Dict[str, Any],
    agent_descriptions: Dict[str, str],
    llm_invoke,
) -> tuple:
    """Plan Critique 관문 (Agentic Upgrade Phase 5, 2026-07-15).

    멀티스테이지 계획을 좁은 판정 1콜로 검증 — 배제 관문 패턴의 일반화.
    실측 근거: 직접 데이터 차트 요청에 불필요한 analysis 가 삽입돼 그 단계가
    데이터를 오염시킨 사례 (2026-07-14). 프롬프트 규칙만으로는 flash-lite 가
    무시하므로 코드 레벨 관문으로 집행한다.

    안전핀(과교정 방지): ① 단일 에이전트 계획은 발동 안 함(콜 0)
    ② 마지막(최종 표현) 스테이지는 제거 금지 ③ 제거로 계획이 비면 원본 유지
    ④ LLM 에러/비JSON → fail-open (계획을 막지 않는다)

    Returns:
        (plan_data, verdict) — verdict={"unnecessary_agents": [...],
        "broken_chain": bool, "reason": str} 또는 {} (미발동/실패).
        broken_chain 에 대한 재계획 판단은 호출측(create_plan) 몫.
    """
    stages = plan_data.get("stages") or []
    total_agents = sum(len(st.get("agents", [])) for st in stages)
    if total_agents < 2:
        return plan_data, {}

    lines = []
    for i, st in enumerate(stages):
        for ag in st.get("agents", []):
            aid = ag.get("agent_id", "")
            desc = (agent_descriptions.get(aid) or "")[:80]
            lines.append(f"{i + 1}단계 {aid}: {ag.get('sub_query', '')} (역할: {desc})")
    prompt = (
        "다음은 사용자 요청을 처리하기 위한 멀티스테이지 실행 계획이다.\n\n"
        f"[사용자 요청]\n{query[:800]}\n\n"
        "[계획]\n" + "\n".join(lines) + "\n\n"
        "두 가지만 판정하라:\n"
        "1. unnecessary_agents: 없어도 요청이 충족되는 스테이지의 에이전트 목록 "
        "(예1: 사용자가 데이터를 이미 제공했는데 별도 조회 단계가 있음. "
        "예2: 단순 계산·인사처럼 담당 에이전트가 자체 처리 가능한 요청에 웹 검색 단계가 있음. "
        "예3: 요청과 무관한 작업의 스테이지). "
        "확실한 경우에만 넣고, 애매하면 빈 목록.\n"
        "2. broken_chain: 어떤 스테이지가 앞 단계 산출물로는 입력을 얻을 수 없어 "
        "실행 불가능한가. 확실한 경우에만 true.\n\n"
        'JSON 만 반환: {"unnecessary_agents": [], "broken_chain": false, "reason": "한 줄"}'
    )
    try:
        answer = str(await llm_invoke(prompt))
        s, e = answer.find("{"), answer.rfind("}") + 1
        verdict = json.loads(answer[s:e]) if s >= 0 and e > s else None
        if not isinstance(verdict, dict):
            raise ValueError(f"비 JSON 응답: {answer[:120]}")
    except Exception as ex:  # 관문 실패는 계획을 막지 않는다 (fail-open)
        logger.warning(f"[PlanCritique] 판정 실패 (fail-open): {ex}")
        return plan_data, {}

    unnecessary = [str(a) for a in (verdict.get("unnecessary_agents") or [])]
    if unnecessary and len(unnecessary) * 2 > total_agents:
        # 과반 지목 = 판정 자체를 불신 (계획 대부분이 불필요하다는 판정은
        # 판정 오류일 가능성이 더 높다) → 원본 유지
        logger.warning(f"[PlanCritique] 과반 지목({unnecessary}) → 판정 불신, 원계획 유지")
        unnecessary = []
    if unnecessary:
        # 마지막 스테이지(최종 표현 담당)는 제거 금지 — 결정적 가드
        last_stage_agents = {a.get("agent_id") for a in stages[-1].get("agents", [])}
        removable = [a for a in unnecessary if a not in last_stage_agents]
        skipped = set(unnecessary) - set(removable)
        if skipped:
            logger.info(f"[PlanCritique] 마지막 스테이지 에이전트 제거 거부: {sorted(skipped)}")
        if removable:
            new_stages = []
            for st in stages:
                kept = [a for a in st.get("agents", []) if a.get("agent_id") not in removable]
                if kept:
                    new_stages.append({**st, "agents": kept})
            if new_stages:  # 전부 제거되면 원본 유지 (fail-open)
                plan_data["stages"] = new_stages
                logger.info(
                    f"[PlanCritique] 불필요 스테이지 제거: {removable} "
                    f"(사유: {verdict.get('reason', '')[:80]})")
            else:
                logger.warning(f"[PlanCritique] 과잉 제거({removable}) → 원계획 유지")

    if verdict.get("broken_chain"):
        logger.info(f"[PlanCritique] 입력 사슬 단절 판정: {verdict.get('reason', '')[:80]}")
    return plan_data, verdict


def backfill_gap_for_empty_plan(query: str, plan_data: Dict[str, Any]) -> Dict[str, Any]:
    """빈 stages + capability_gap 미선언 → gap 백필 (2026-07-11).

    LLM 이 '처리할 에이전트가 없다'는 판단을 gap 필드 대신 **빈 계획**으로만
    표현하는 케이스 (라이브 실측: 점자 쿼리 PLAN=[] gap=None → Validator 가
    빈 계획을 거부하며 재시도 3회 낭비 후 사과 답변). 무능력의 유일한 정직한
    출구는 capability_gap 이므로 코드가 백필한다 — schema 강제 부재 교훈의 구현.
    """
    stages = plan_data.get("stages") or []
    existing = plan_data.get("capability_gap")
    if stages or (isinstance(existing, dict) and existing.get("detected")):
        return plan_data
    plan_data["capability_gap"] = {
        "detected": True,
        "missing_capabilities": ["unhandled_by_registered_agents"],
        "required_resources": [],
        "suggested_agent_description": query,
        "reason": "플래너가 처리 가능한 에이전트를 찾지 못해 빈 계획 반환 (gap 백필)",
    }
    return plan_data


def normalize_capability_gap(cap_gap: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Ensure a capability_gap dict carries a clean list ``required_resources``.

    ``required_resources`` are resource tags the new agent will need at runtime
    (e.g. ``desktop:kakaotalk``, ``region:kr``, ``api:mastodon``). logos_api uses
    them for affinity-based placement onto the right ACP node. Missing or
    malformed values normalize to an empty list. ``None`` passes through.
    """
    if not isinstance(cap_gap, dict):
        return cap_gap
    raw = cap_gap.get("required_resources")
    if not isinstance(raw, list):
        raw = []
    cap_gap["required_resources"] = [str(x).strip() for x in raw if str(x).strip()]
    return cap_gap


def merge_independent_stages(stages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """LLM 이 만든 stages 에서 데이터 의존성 없는 1-agent stages 를 parallel 로 병합.

    flash-lite 의 흔한 실수 (독립적 multi-domain 쿼리를 1-agent-per-stage 로 분리) 의 backstop.

    Rules:
      - 인접한 stages 들이 모두 1 agent 이고 input_from 이 모두 null 이면 → 같은 parallel stage 로 병합
      - 데이터 의존성 (input_from 에 stage_X 참조) 있으면 그 자리에서 분리 유지
      - 이미 parallel 인 stage 는 건드리지 않음

    Args:
        stages: LLM 이 만든 raw stages list (각 dict: stage_id, execution_type, agents)

    Returns:
        Post-processed stages with stage_ids renumbered.
    """
    if not stages or len(stages) < 2:
        return stages

    def _is_independent_singleton(stage: Dict[str, Any]) -> bool:
        agents = stage.get("agents", [])
        if len(agents) != 1:
            return False
        input_from = agents[0].get("input_from")
        # input_from 이 None / [] / 빈 리스트 면 의존성 없음
        if input_from is None:
            return True
        if isinstance(input_from, list) and len(input_from) == 0:
            return True
        return False

    out: List[Dict[str, Any]] = []
    i = 0
    while i < len(stages):
        cur = stages[i]
        if _is_independent_singleton(cur):
            # 인접한 independent singletons 수집
            group_agents = list(cur.get("agents", []))
            j = i + 1
            while j < len(stages) and _is_independent_singleton(stages[j]):
                group_agents.extend(stages[j].get("agents", []))
                j += 1
            if len(group_agents) > 1:
                # 병합
                out.append({
                    "stage_id": len(out) + 1,
                    "execution_type": "parallel",
                    "agents": group_agents,
                })
                i = j
                continue
        # 그대로 추가 + stage_id 재번호
        new_stage = dict(cur)
        new_stage["stage_id"] = len(out) + 1
        out.append(new_stage)
        i += 1

    # 후속 stages 의 input_from 참조도 새 stage_id 로 매핑해야 하지만,
    # 현재 input_from 형식이 "stage_N.agent_id" 인데 stage 번호 변경이 일어남.
    # 안전성: ExecutionEngine 이 stage 번호 의존성보다는 stage 순서로 처리한다고 가정 (검증 필요).
    # 단, 1-agent → parallel 병합은 stage 1 에서 일어나므로 stage 1 이름은 유지됨.
    return out


_DEFAULT_PROMPT = """# 역할
당신은 사용자 요청을 처리할 실행 계획을 세우는 플래너입니다. 아래에 등록된 에이전트만
사용해 단계(stage) 계획을 JSON 으로 작성하세요.

# 사용 가능한 에이전트
{agents}
{hint}{history}
# 계획 원칙
1. 에이전트 하나로 충분하면 그 하나만 쓴다.
2. 서로 의존하지 않는 작업은 한 stage 안에 넣고 execution_type 을 "parallel" 로 한다.
3. 앞 단계 결과가 필요한 작업은 다음 stage 로 두고 input_from 에 앞 단계를 적는다
   (예: ["stage_1"]).
4. sub_query 는 그것만 읽어도 무엇을 할지 알 수 있는 자기완결적 문장으로 쓴다.
5. 사용자가 말한 조건(시간 범위, 대상, 형식)은 지우거나 좁히지 말고, 말하지 않은 조건은
   더하지 않는다.
6. 에이전트 설명을 근거로 고른다. 이름이 비슷해 보인다는 이유만으로 배정하지 않는다.
7. 등록된 에이전트로 처리할 수 없으면 capability_gap.detected 를 true 로 하고, 처리할 수
   없는 부분은 stages 에 넣지 않는다.

# 출력 형식
{{
  "workflow_strategy": "sequential" | "parallel" | "hybrid",
  "stages": [
    {{"stage_id": 1, "execution_type": "sequential" | "parallel",
      "agents": [{{"agent_id": "<agent_id>", "sub_query": "<자기완결적 지시>",
                  "input_from": null, "expected_output": "<기대 산출물>"}}]}}
  ],
  "capability_gap": null 또는 {{"detected": true, "missing_capabilities": ["<능력>"],
                                "required_resources": ["<자원 태그, 예: api:이름>"],
                                "suggested_agent_description": "<필요한 에이전트>",
                                "reason": "<이유>"}},
  "reasoning": "<한두 문장>",
  "final_aggregation": {{"type": "combine"}}
}}

# 사용자 요청
"{query}"

JSON 만 출력하세요.
"""


class QueryPlanner:
    """사용자 쿼리 → ExecutionPlan. 조직별 지식은 훅을 재정의해 넣는다."""

    MODEL = "default"
    #: 기본 LLM 경로의 출력 한도 — Logos 플래너와 같다. LLMClient 기본(2000)이면
    #: 다단계 계획 JSON 이 중간에 끊길 수 있다.
    MAX_TOKENS = 4096

    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        streamer: Optional[ProgressStreamer] = None,
        llm_invoke: Optional[LLMInvoke] = None,
    ):
        self.registry = registry or get_registry()
        self.streamer = streamer
        self._llm_invoke = llm_invoke
        self._llm_client = None

    async def create_plan(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        """
        Create execution plan for the given query.

        Args:
            query: User query to analyze
            context: Optional additional context

        Returns:
            ExecutionPlan with stages, agents, and aggregation strategy

        Raises:
            PlanningError: If planning fails
        """
        start_time = time.time()
        plan_id = str(uuid.uuid4())[:8]

        # Emit planning start event
        if self.streamer:
            await self.streamer.planning_start(query)

        try:
            # Phase 0: 선택기 힌트 (조직별 — 기본 없음)
            recommended_agent, hybrid_metadata = await self._recommend(query)

            # Build the prompt (with recommendation hint if available)
            prompt = self._build_planning_prompt(query, context, recommended_agent, hybrid_metadata)

            logger.info(f"[QueryPlanner] Calling {self.MODEL} for query: {query[:50]}...")
            response = await self._call_llm(prompt)

            # Parse response
            plan_data = self._parse_llm_response(response)

            # 에이전트 배제 규칙 집행 (조직별 — 기본 없음)
            plan_data = await self._apply_exclusion_gate(query, prompt, plan_data)

            # Plan Critique 관문 (Phase 5): 멀티스테이지 계획의 불필요 단계 제거 +
            # 입력 사슬 단절 시 1회 재계획. fail-open — 관문 실패는 계획을 막지 않는다.
            try:
                _descs2 = {
                    e.agent_id: (e.description or "")
                    for e in self.registry.get_available_agents()
                }

                async def _critique_llm(p: str) -> str:
                    return await self._call_llm(p)

                plan_data, _verdict = await critique_plan(
                    query, plan_data, _descs2, _critique_llm)
                if _verdict.get("broken_chain"):
                    retry_prompt2 = (
                        prompt
                        + "\n\n[제약] 직전 계획은 스테이지 간 입력 사슬이 끊겨 실행 불가 판정을 받았다"
                        + f" (사유: {str(_verdict.get('reason', ''))[:150]}).\n"
                        + "각 스테이지의 산출물이 다음 스테이지의 입력이 되도록 계획을 다시 구성하라."
                    )
                    logger.info("[QueryPlanner] 사슬 단절 → 재계획 1회")
                    _resp2 = await self._call_llm(retry_prompt2)
                    _replan = self._parse_llm_response(_resp2)
                    # 재계획이 유효할 때만 교체 (빈 재계획으로 원계획을 버리지 않는다)
                    if _replan.get("stages"):
                        plan_data = _replan
            except Exception as _ce:
                logger.warning(f"[QueryPlanner] PlanCritique 오류 (계획 계속): {_ce}")

            # 빈 계획 + gap 미선언 → gap 백필 (validator 재시도 낭비 방지)
            plan_data = backfill_gap_for_empty_plan(query, plan_data)

            # Build ExecutionPlan from parsed data
            plan = self._build_execution_plan(query, plan_data, plan_id)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[QueryPlanner] Plan created in {elapsed_ms:.0f}ms: "
                f"{plan.get_stage_count()} stages, {plan.get_total_agents()} agents"
            )

            # Emit planning complete event
            if self.streamer:
                await self.streamer.planning_complete(plan)

            return plan

        except Exception as e:
            logger.error(f"[QueryPlanner] Planning failed: {e}")
            if self.streamer:
                await self.streamer.planning_error(str(e))
            raise PlanningError(
                message=f"Failed to create execution plan: {e}",
                query=query,
            )

    # ── 훅 (조직별 플래너가 재정의) ─────────────────────────────────────

    async def _recommend(self, query: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """선택기 힌트 (agent_id, metadata). 기본: 없음."""
        return None, None

    async def _apply_exclusion_gate(
        self, query: str, prompt: str, plan_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """에이전트 배제 규칙 집행. 기본: 없음 (규칙은 조직의 관례다)."""
        return plan_data

    def _explicit_gap(self, query: str) -> Optional[Dict[str, Any]]:
        """LLM 이 gap 을 놓쳤을 때의 코드 수준 안전망. 기본: 없음."""
        return None

    async def _call_llm(self, prompt: str) -> str:
        """LLM 호출. 주입한 llm_invoke, 없으면 logosai LLMClient (비차단)."""
        if self._llm_invoke is not None:
            return await self._llm_invoke(prompt)
        if self._llm_client is None:
            from logosai.utils.llm_client import LLMClient
            self._llm_client = LLMClient()
            await self._llm_client.initialize()
        response = await self._llm_client.invoke(prompt, max_tokens=self.MAX_TOKENS)
        if (getattr(response, "metadata", None) or {}).get("truncated"):
            raise PlanningError(
                message=f"계획 응답이 출력 한도({self.MAX_TOKENS} 토큰)에서 잘렸다 — "
                        f"MAX_TOKENS 를 늘리거나 에이전트 수를 줄여라",
                llm_response=getattr(response, "content", "")[:500],
            )
        return getattr(response, "content", str(response))

    def _build_planning_prompt(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        recommended_agent: Optional[str] = None,
        hybrid_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """일반 계획 프롬프트 — 등록된 에이전트 정보만 쓴다."""
        hint = ""
        if recommended_agent:
            hint = (f"\n# 참고 힌트\n선택기가 `{recommended_agent}` 를 추천했다. 적합할 때만 "
                    f"참고하고, 맞지 않으면 무시한다.\n")
        history = ""
        if context and context.get("conversation_history"):
            history = f"\n# 이전 대화\n{context['conversation_history']}\n"
        return _DEFAULT_PROMPT.format(
            agents=self.registry.build_prompt_context(include_schema=True),
            hint=hint, history=history, query=query,
        )

    async def store_execution_feedback(
        self,
        query: str,
        agent_id: str,
        success: bool,
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """실행 결과를 선택기 학습에 넘긴다. 기본: 없음."""
        return None

    # ── 공용 메커니즘 ──────────────────────────────────────────────────

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """Parse the JSON response from LLM"""
        try:
            # Clean up response - extract JSON
            text = response.strip()

            # Remove markdown code blocks if present
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]

            if text.endswith("```"):
                text = text[:-3]

            text = text.strip()

            # Parse JSON
            return json.loads(text)

        except json.JSONDecodeError as e:
            logger.error(f"[QueryPlanner] Failed to parse JSON: {e}")
            logger.error(f"[QueryPlanner] Raw response: {response[:500]}...")
            raise PlanningError(
                message=f"Invalid JSON in LLM response: {e}",
                llm_response=response[:500],
            )

    def _build_execution_plan(
        self,
        query: str,
        plan_data: Dict[str, Any],
        plan_id: str,
    ) -> ExecutionPlan:
        """Build ExecutionPlan from parsed LLM response.

        Post-processing safety net (2026-05-09): merge_independent_stages 가
        flash-lite 의 흔한 실수 (의존성 없는 1-agent stages 의 sequential 분리) 를
        자동으로 parallel 로 병합. prompt 가 안 통할 때의 backstop.
        """

        raw_stages = plan_data.get("stages", [])
        merged_stages = merge_independent_stages(raw_stages)

        # workflow_strategy 도 함께 갱신 (병합 결과 반영)
        workflow_strategy = plan_data.get("workflow_strategy", "sequential")
        if len(merged_stages) != len(raw_stages):
            n_parallel = sum(1 for s in merged_stages if s.get("execution_type") == "parallel")
            n_seq = sum(1 for s in merged_stages if s.get("execution_type") != "parallel")
            workflow_strategy = (
                "parallel" if n_parallel > 0 and n_seq == 0
                else "hybrid" if n_parallel > 0 and n_seq > 0
                else "sequential"
            )
            logger.info(
                f"  Stage merger: {len(raw_stages)} → {len(merged_stages)} stages "
                f"(strategy: {plan_data.get('workflow_strategy')} → {workflow_strategy})"
            )
            plan_data["workflow_strategy"] = workflow_strategy

        stages = []
        for stage_data in merged_stages:
            agents = []
            for agent_data in stage_data.get("agents", []):
                agent = AgentTask(
                    agent_id=agent_data.get("agent_id"),
                    sub_query=agent_data.get("sub_query", query),
                    input_from=agent_data.get("input_from"),
                    output_to=agent_data.get("output_to"),
                    expected_output=agent_data.get("expected_output"),
                )
                agents.append(agent)

            stage = ExecutionStage(
                stage_id=stage_data.get("stage_id", len(stages) + 1),
                execution_type=stage_data.get("execution_type", "sequential"),
                agents=agents,
            )
            stages.append(stage)

        # capability_gap 결정 (LLM 응답 우선, 조직별 안전망으로 보강)
        capability_gap = plan_data.get("capability_gap")
        if not (isinstance(capability_gap, dict) and capability_gap.get("detected")):
            safety = self._explicit_gap(query)
            if safety:
                logger.info(
                    f"  Code safety net: 명시적 에이전트 생성 패턴 감지 → "
                    f"capability_gap 강제 trigger (LLM 누락 보강)"
                )
                capability_gap = safety
            else:
                capability_gap = None

        # P1.2: guarantee required_resources exists (list) for downstream
        # affinity placement by logos_api ForgeNegotiator → PlacementPlanner.
        capability_gap = normalize_capability_gap(capability_gap)

        plan = ExecutionPlan(
            query=query,
            workflow_strategy=plan_data.get("workflow_strategy", "sequential"),
            stages=stages,
            final_aggregation=plan_data.get("final_aggregation", {"type": "combine"}),
            reasoning=plan_data.get("reasoning", ""),
            plan_id=plan_id,
            capability_gap=capability_gap,
        )

        return plan

    async def validate_query(self, query: str) -> Dict[str, Any]:
        """
        Quick validation of query before full planning.

        Returns:
            Dict with validation results
        """
        # Check for empty query
        if not query or not query.strip():
            return {
                "valid": False,
                "error": "Empty query",
            }

        # Check for minimum length
        if len(query.strip()) < 2:
            return {
                "valid": False,
                "error": "Query too short",
            }

        # Check for available agents
        agents = self.registry.get_available_agents()
        if not agents:
            return {
                "valid": False,
                "error": "No agents available",
            }

        return {
            "valid": True,
            "available_agents": len(agents),
        }
