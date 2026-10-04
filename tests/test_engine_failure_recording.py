"""엔진이 에이전트 실패를 실패로 기록한다 — 판정은 정본(agent_outcome.failure_reason).

지금까지 엔진은 실행기가 예외만 던지지 않으면 결과 내용과 무관하게
AgentResult.success=True 를 박았다. logos_api 실행기는 실패하면
`{"success": False, "error": ...}` 를 돌려주고, ACP 안의 실패(response_type ERROR,
실측: file_agent "Access denied")는 `{"success": True, "data": {...ERROR...}}` 로
감싼다 — 둘 다 성공으로 기록됐다.

고치는 것은 '무엇을 기록하는가'이지 '무엇을 하는가'가 아니다. 실측이 두 번 확인했다
(2026-10-04, logos_api OrchestratorService 무수정 E2E):
  · 결말까지 실패로 바꾸면 logos_api 재시도 루프가 같은 에이전트를 3번 부른다
    (계획 1→3회, 8.8s→18.9s).
  · 실패 출력을 핸드오프에서 빼면 하류가 지어낸다 — 없는 파일 요약 요청에 요약
    에이전트가 "접근이 거부되었습니다" 대신 AI 모델 일반론을 만들어 냈다.
그래서 기록(AgentResult·이벤트 상태·통계)만 정직하게 하고, 핸드오프와 결말은 그대로다.
"""
import pytest

from logosai.orchestration import AgentTask, ExecutionEngine, ExecutionPlan, ExecutionStage

# logos_api `_execute_agent_via_acp` 가 실제로 돌려주는 모양들
LOGOS_API_FAILURE = {"success": False, "error": "Agent 'x' is not running on ACP server"}
ACP_ERROR_WRAPPED = {"success": True, "data": {
    "result": {"error": "Access denied: /nonexistent/path"}, "response_type": "ERROR",
    "message": "Access denied", "metadata": {}}}
ACP_SUCCESS_WRAPPED = {"success": True, "data": {
    "result": {"answer": "5"}, "response_type": "SUCCESS", "message": "", "metadata": {}}}


class StreamerRecorder:
    """ProgressStreamer 대역 — agent_complete 호출만 기록한다."""

    def __init__(self):
        self.completes = []

    async def agent_complete(self, **kwargs):
        self.completes.append(kwargs)

    def __getattr__(self, name):
        async def noop(*a, **k):
            return None
        return noop


def _single(agent_ids, kind="parallel"):
    return ExecutionPlan(query="원 질문", workflow_strategy=kind, stages=[
        ExecutionStage(stage_id=1, execution_type=kind,
                       agents=[AgentTask(agent_id=a, sub_query=f"{a} 해") for a in agent_ids])])


async def _run(outputs, plan, streamer=None):
    calls = []

    async def executor(agent_id, query, context):
        calls.append({"agent": agent_id, "query": query, "context": dict(context or {})})
        return outputs[agent_id]

    result = await ExecutionEngine(agent_executor=executor, streamer=streamer).execute(plan)
    return result, calls


@pytest.mark.parametrize("output,expected_reason", [
    (LOGOS_API_FAILURE, "not running"),
    (ACP_ERROR_WRAPPED, "Access denied"),
])
async def test_failure_shapes_are_recorded_as_failure(output, expected_reason):
    streamer = StreamerRecorder()
    result, calls = await _run({"a_agent": output}, _single(["a_agent"]), streamer)

    (agent_result,) = result.stages[0].results
    assert agent_result.success is False
    assert expected_reason in (agent_result.error or "")
    (event,) = streamer.completes
    assert event["success"] is False and expected_reason in (event.get("error") or "")
    assert len(calls) == 1, "돌려준 실패에 재시도를 하면 안 된다 (호출 수 불변)"


@pytest.mark.parametrize("output", [
    ACP_SUCCESS_WRAPPED,
    {"success": True, "result": {"answer": "ok"}},
    "평범한 문자열 답",
    {"answer": ""},               # 근거 없음 → 성공 (정본: 지어내지 않는다)
    {"success": False},           # 정본은 error 값 없는 success=False 를 실패로 보지 않는다
])
async def test_success_shapes_stay_success(output):
    """대조군 — 오탐은 멀쩡한 결과를 핸드오프에서 빼는 반대 방향 사고다."""
    streamer = StreamerRecorder()
    result, _ = await _run({"a_agent": output}, _single(["a_agent"]), streamer)

    assert result.stages[0].results[0].success is True
    assert streamer.completes[0]["success"] is True


async def test_returned_failure_content_still_reaches_the_next_stage():
    """하류는 실패 사실을 알아야 지어내지 않는다 — 실패 출력을 핸드오프에서 빼지 않는다.

    뺐을 때 실측: 요약 에이전트가 입력 없이 지시문만 받고 무관한 요약을 지어냈다.
    실패를 '실패로서' 알리는 핸드오프는 하류 답이 바뀌는 별개 변경이라 측정 후에 한다.
    """
    outputs = {"ok_agent": {"success": True, "result": {"answer": "OK-DATA-31"}},
               "bad_agent": ACP_ERROR_WRAPPED,
               "next_agent": {"success": True, "result": {"answer": "done"}}}
    plan = ExecutionPlan(query="원 질문", workflow_strategy="hybrid", stages=[
        ExecutionStage(stage_id=1, execution_type="parallel", agents=[
            AgentTask(agent_id="ok_agent", sub_query="하나"),
            AgentTask(agent_id="bad_agent", sub_query="둘")]),
        ExecutionStage(stage_id=2, execution_type="sequential", depends_on=[1], agents=[
            AgentTask(agent_id="next_agent", sub_query="합쳐라")]),
    ])

    result, calls = await _run(outputs, plan)

    nxt = next(c for c in calls if c["agent"] == "next_agent")
    assert "OK-DATA-31" in nxt["query"]
    assert "Access denied" in nxt["query"], "실패 내용이 하류에 전달되지 않았다 — 하류가 지어낸다"
    # 기록은 정직하다
    assert result.failed_agents == 1 and result.successful_agents == 2


async def test_successful_stage_still_injects_its_result():
    """대조군 — 빈 블록 제거가 정상 핸드오프까지 지우지 않는다."""
    outputs = {"ok_agent": {"success": True, "result": {"answer": "OK-DATA-31"}},
               "next_agent": {"success": True, "result": {"answer": "done"}}}
    plan = ExecutionPlan(query="원 질문", workflow_strategy="sequential", stages=[
        ExecutionStage(stage_id=1, execution_type="sequential",
                       agents=[AgentTask(agent_id="ok_agent", sub_query="하나")]),
        ExecutionStage(stage_id=2, execution_type="sequential", depends_on=[1],
                       agents=[AgentTask(agent_id="next_agent", sub_query="합쳐라")]),
    ])

    _, calls = await _run(outputs, plan)

    nxt = next(c for c in calls if c["agent"] == "next_agent")
    assert "OK-DATA-31" in nxt["query"] and "합쳐라" in nxt["query"]


# ── 화면 계약: 돌려준 실패는 agent_complete 로 (종류 유지), 예외는 agent_error ──
#
# logos_web streaming.ts 는 agent_complete/agent_completed 만 처리하고 agent_error 는
# 처리하지 않는다. logos_api 도 결과 목록을 agent_complete 에서만 모은다. 돌려준
# 실패를 agent_error 로 바꾸면 카드가 '실행 중'에서 멈추고 출력이 결과에서 빠진다.
# 그래서 종류는 유지하고 status/error 만 바로잡는다 (기록만 고친다).

async def _events_for(executor):
    from logosai.orchestration import ProgressEventType, ProgressStreamer

    streamer = ProgressStreamer()
    events = []
    streamer.on_event(events.append)
    plan = _single(["a_agent"], kind="sequential")
    plan.stages[0].agents[0].max_retries = 0
    await ExecutionEngine(agent_executor=executor, streamer=streamer).execute(plan)
    return [e for e in events if e.agent_id == "a_agent" and e.type in (
        ProgressEventType.AGENT_COMPLETE, ProgressEventType.AGENT_ERROR)]


async def test_returned_failure_keeps_agent_complete_event_with_failed_status():
    from logosai.orchestration import AgentStatus, ProgressEventType

    async def executor(agent_id, query, context):
        return ACP_ERROR_WRAPPED

    (event,) = await _events_for(executor)
    assert event.type == ProgressEventType.AGENT_COMPLETE, "돌려준 실패의 이벤트 종류가 바뀌었다 — 화면이 멈춘다"
    assert event.status == AgentStatus.FAILED
    assert "Access denied" in (event.error or "")
    assert event.data.get("full_result") == ACP_ERROR_WRAPPED  # logos_api 결과 수집이 그대로


async def test_exception_failure_still_emits_agent_error():
    """대조군 — 예외 경로는 원래대로 agent_error 다 (이번 변경 범위 밖)."""
    from logosai.orchestration import ProgressEventType

    async def executor(agent_id, query, context):
        raise RuntimeError("boom")

    events = await _events_for(executor)
    assert events and events[-1].type == ProgressEventType.AGENT_ERROR


async def test_success_event_is_unchanged():
    """대조군 — 성공은 agent_complete + COMPLETED."""
    from logosai.orchestration import AgentStatus, ProgressEventType

    async def executor(agent_id, query, context):
        return ACP_SUCCESS_WRAPPED

    (event,) = await _events_for(executor)
    assert event.type == ProgressEventType.AGENT_COMPLETE and event.status == AgentStatus.COMPLETED


# ── 결말 보존: 돌려준 실패는 워크플로우의 결말을 바꾸지 않는다 ─────────────
#
# 실측(2026-10-04, logos_api OrchestratorService 무수정 E2E): 에이전트 하나짜리 계획이
# 실패를 돌려주자 워크플로우가 실패로 판정돼 workflow_error 가 나갔고, logos_api 재시도
# 루프가 같은 에이전트를 3번 불렀다 (계획 1→3회, 8.8s→18.9s). logos_api 는 이 에이전트를
# 실패 목록에 넣지 않으므로(실행기는 성공으로 봄) 재계획이 같은 선택을 반복한다.
# 기록과 핸드오프만 고치고 결말은 이전과 같게 둔다 — 재시도 조건 불변 원칙.

async def _workflow_events(executor, agents=("a_agent",)):
    from logosai.orchestration import ProgressStreamer

    streamer = ProgressStreamer()
    events = []
    streamer.on_event(events.append)
    plan = _single(list(agents), kind="sequential")
    for t in plan.stages[0].agents:
        t.max_retries = 0
    result = await ExecutionEngine(agent_executor=executor, streamer=streamer).execute(plan)
    return result, [e.type.value for e in events]


async def test_returned_failure_does_not_fail_the_workflow():
    async def executor(agent_id, query, context):
        return ACP_ERROR_WRAPPED

    result, types = await _workflow_events(executor)

    assert result.success is True, "돌려준 실패가 워크플로우를 실패시켜 logos_api 재시도를 부른다"
    assert "workflow_complete" in types and "workflow_error" not in types
    assert "stage_error" not in types
    assert "Access denied" in str(result.final_output), "사용자에게 보이던 에이전트 출력이 사라졌다"
    # 기록은 정직하다
    assert result.stages[0].results[0].success is False and result.failed_agents == 1


async def test_raised_failure_still_fails_the_workflow():
    """대조군 — 예외로 난 실패의 결말은 원래대로다."""
    async def executor(agent_id, query, context):
        raise RuntimeError("boom")

    result, types = await _workflow_events(executor)

    assert result.success is False and "workflow_error" in types
