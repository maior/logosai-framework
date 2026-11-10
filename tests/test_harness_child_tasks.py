"""하네스 자식 태스크 계수 — LOGOSAI_HARNESS_CHILD_TASKS.

실측으로 확인한 구멍 둘을 막는다:
  1. 기존(messages) 경로의 LLM 호출이 자식 태스크 안에서 일어나면 세지지 않았다.
     상한 3 에 `asyncio.wait_for(one(), 5)` 10회, `gather` 10개가 전부 돌았다 —
     계수가 ContextVar 정수라 자식은 사본을 올리고 부모는 영영 모른다.
  2. `run_with_tools` · `react` 가 LLM 호출을 `except Exception` 으로 감싸서,
     예산 초과가 삼켜지고 정상처럼 보이는 답이 나갔다.

기본은 observe — 세기만 하고 막지 않는다. 그래서 부정 단언("안 막혔다")마다
대조군("실제로 셌다")을 붙였다.

네트워크 없음: 제공자 호출은 전부 가짜. 이벤트는 emit_harness_block 을 가로챈다.
"""
import asyncio
from types import SimpleNamespace

import pytest

from logosai import AgentConfig, LogosAIAgent
from logosai import observability as obs
from logosai.agent_types import AgentResponse
from logosai.utils import guardrails as gr
from logosai.utils.llm_client import LLMClient, LLMResponse

MSG = [{"role": "user", "content": "q"}]


def _cfg(name):
    return AgentConfig(name=name, agent_type="custom", description="probe")


def _resp(tokens=(0, 0)):
    raw = SimpleNamespace(usage=SimpleNamespace(
        prompt_tokens=tokens[0], completion_tokens=tokens[1]))
    return LLMResponse(content="x", provider="google", model="probe", raw_response=raw)


class _FakeLimiter:
    async def acquire(self):
        pass


@pytest.fixture
def env(monkeypatch):
    """가짜 제공자 + 이벤트 수집 + 전역 가드레일 격리."""
    for k in ("LOGOSAI_HARNESS_NEW_PATHS", "LOGOSAI_HARNESS_CHILD_TASKS",
              "LOGOSAI_HARNESS", "LOGOSAI_HARNESS_MAX_TOKENS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LOGOSAI_HARNESS_MAX_CALLS", "3")
    monkeypatch.setenv("LOGOSAI_HARNESS_TIMEOUT", "30")

    st = SimpleNamespace(tools=0, plain=0, events=[], tokens=(0, 0))

    async def fake_tools(self, messages, tools, **kw):
        st.tools += 1
        return _resp(st.tokens)

    async def fake_plain(self, messages, **kw):
        st.plain += 1
        return _resp(st.tokens)

    async def noop_init(self):
        self._initialized = True

    monkeypatch.setattr(LLMClient, "_dispatch_with_tools", fake_tools)
    monkeypatch.setattr(LLMClient, "_call_google", fake_plain)
    monkeypatch.setattr(LLMClient, "initialize", noop_init)
    monkeypatch.setattr(LLMClient, "_metrics_callback", None)
    limiter = _FakeLimiter()
    counter = gr.RequestCallCounter(max_calls=10_000)
    monkeypatch.setattr(gr, "get_rate_limiter", lambda: limiter)
    monkeypatch.setattr(gr, "get_request_counter", lambda: counter)
    monkeypatch.setattr(
        obs, "emit_harness_block",
        lambda kind, agent_id, detail, payload=None:
            st.events.append((kind, agent_id, detail, dict(payload or {}))))
    return st


def _llm():
    return LLMClient(provider="google", model="probe")


def _kinds(st, kind):
    return [e for e in st.events if e[0] == kind]


def _one(llm):
    return llm.invoke_messages(MSG, _max_retries=0)


async def _children(llm, n, shape):
    """자식 태스크에서 기존 경로 호출 n 번 — react.py 와 gather 두 모양."""
    if shape == "wait_for":
        for _ in range(n):
            await asyncio.wait_for(_one(llm), 5)
    else:
        await asyncio.gather(*[_one(llm) for _ in range(n)])


def _agent(body, seen):
    """body(llm) 를 돌리고 마지막 사용량을 seen 에 남기는 하네스 에이전트."""
    class Probe(LogosAIAgent):
        async def process(self, query, context=None):
            try:
                await body(_llm())
            finally:
                seen.update(gr.execution_usage())
            return "done"
    return Probe(_cfg("childprobe"))


SHAPES = ["wait_for", "gather"]


# ── observe (기본) ───────────────────────────────────────────────────────

@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("mode", [None, "observe", "enforc"])  # 오타는 observe
async def test_observe_child_calls_all_run_and_would_block_once(env, monkeypatch, shape, mode):
    if mode:
        monkeypatch.setenv("LOGOSAI_HARNESS_CHILD_TASKS", mode)
    seen = {}
    r = await _agent(lambda llm: _children(llm, 10, shape), seen).process("q")
    assert r == "done"                       # 막히지 않았다
    assert env.plain == 10
    # 대조군: 안 막힌 것이 '안 셌기 때문'이 아니다.
    assert seen["child_calls"] == 10
    assert seen["calls"] == 0                # 소유 태스크 계수는 건드리지 않았다
    assert seen["would_block"] == ["calls"]
    wb = _kinds(env, "would_block")
    assert len(wb) == 1                      # 실행당 종류별 1회
    assert wb[0][3] == {"path": "child_task", "budget_kind": "calls",
                        "max_calls": 3, "max_tokens": 200000, "mode": "observe"}
    assert _kinds(env, "budget_exceeded") == []


async def test_observe_under_cap_is_silent(env):
    seen = {}
    r = await _agent(lambda llm: _children(llm, 3, "wait_for"), seen).process("q")
    assert r == "done"
    assert seen["child_calls"] == 3          # 대조군: 세고는 있다
    assert env.events == []


# ── enforce ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("shape", SHAPES)
async def test_enforce_child_calls_blocked_at_cap(env, monkeypatch, shape):
    monkeypatch.setenv("LOGOSAI_HARNESS_CHILD_TASKS", "enforce")
    seen = {}
    r = await _agent(lambda llm: _children(llm, 10, shape), seen).process("q")
    assert env.plain == 3                    # 4번째는 제공자에 닿지 못했다
    assert "harness budget" in str(r.message)
    assert "LLM call budget exceeded: 4/3" in str(r.message)
    be = _kinds(env, "budget_exceeded")
    assert len(be) == 1 and be[0][3]["budget_kind"] == "calls"
    assert _kinds(env, "would_block") == []


async def test_enforce_owner_call_sees_child_calls(env, monkeypatch):
    """자식 2 + 소유 1 = 3, 그다음 소유 호출이 넘긴다 — 어느 태스크든 넘기는 쪽이 막힌다."""
    monkeypatch.setenv("LOGOSAI_HARNESS_CHILD_TASKS", "enforce")

    async def body(llm):
        await _children(llm, 2, "wait_for")
        for _ in range(10):
            await _one(llm)

    r = await _agent(body, {}).process("q")
    assert env.plain == 3
    assert "LLM call budget exceeded: 4/3" in str(r.message)


# ── off ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("shape", SHAPES)
async def test_off_child_calls_not_accumulated(env, monkeypatch, shape):
    monkeypatch.setenv("LOGOSAI_HARNESS_CHILD_TASKS", "off")
    seen = {}

    async def body(llm):
        await _children(llm, 10, shape)
        await _one(llm)                      # 대조군: 예산 자체는 살아 있다

    assert await _agent(body, seen).process("q") == "done"
    assert env.plain == 11
    assert (seen["child_calls"], seen["child_tokens"]) == (0, 0)
    assert seen["calls"] == 1
    assert env.events == []


# ── 소유 태스크: 세 모드에서 같은 자리 ───────────────────────────────────

@pytest.mark.parametrize("mode,child_first", [
    (None, 0), ("observe", 0), ("enforce", 0), ("off", 0),
    ("observe", 5),      # 자식 5회가 앞서도 소유 태스크 상한은 그대로
    ("off", 5),
])
async def test_owner_cap_trips_at_same_call_number(env, monkeypatch, mode, child_first):
    if mode:
        monkeypatch.setenv("LOGOSAI_HARNESS_CHILD_TASKS", mode)
    seen = {}

    async def body(llm):
        await _children(llm, child_first, "wait_for")
        for _ in range(10):
            await _one(llm)

    r = await _agent(body, seen).process("q")
    assert env.plain == child_first + 3      # 4번째에서 정확히 — 이전과 같은 자리
    assert "LLM call budget exceeded: 4/3" in str(r.message)
    assert len(_kinds(env, "budget_exceeded")) == 1
    assert seen["calls"] == 4
    assert seen["child_calls"] == (child_first if mode == "observe" else 0)


def test_no_running_loop_behaves_like_owner(env, monkeypatch):
    """루프 밖(동기 호출)에서도 죽지 않고 예전 자리에서 걸린다."""
    monkeypatch.setenv("LOGOSAI_HARNESS_CHILD_TASKS", "enforce")
    tok = gr.begin_execution_budget(3, None)
    try:
        for _ in range(3):
            gr.precheck_llm_call()
        with pytest.raises(gr.HarnessBudgetExceeded, match="LLM call budget exceeded: 4/3"):
            gr.precheck_llm_call()
        assert gr.execution_usage()["child_calls"] == 0
    finally:
        gr.reset_execution_budget(tok)


async def test_no_budget_is_a_noop(env):
    async def one():
        gr.precheck_llm_call()
        gr.record_llm_tokens(10, 10)
    await asyncio.gather(*[one() for _ in range(10)])
    u = gr.execution_usage()
    assert (u["calls"], u["child_calls"], u["child_tokens"]) == (0, 0, 0)
    assert env.events == [] and gr.budget_active() is False


# ── 토큰 상한 ────────────────────────────────────────────────────────────

def _token_env(env, monkeypatch):
    monkeypatch.setenv("LOGOSAI_HARNESS_MAX_CALLS", "0")       # 호출 상한 없음
    monkeypatch.setenv("LOGOSAI_HARNESS_MAX_TOKENS", "1000")
    env.tokens = (400, 200)


async def test_observe_token_cap_via_child_tasks(env, monkeypatch):
    _token_env(env, monkeypatch)
    seen = {}
    assert await _agent(lambda llm: _children(llm, 5, "wait_for"), seen).process("q") == "done"
    assert env.plain == 5
    assert seen["child_tokens"] == 3000 and seen["tokens"] == 0
    assert seen["would_block"] == ["tokens"]
    wb = _kinds(env, "would_block")
    assert len(wb) == 1
    assert wb[0][3]["path"] == "child_task" and wb[0][3]["budget_kind"] == "tokens"
    assert wb[0][3]["max_tokens"] == 1000


async def test_enforce_token_cap_via_child_tasks(env, monkeypatch):
    _token_env(env, monkeypatch)
    monkeypatch.setenv("LOGOSAI_HARNESS_CHILD_TASKS", "enforce")
    r = await _agent(lambda llm: _children(llm, 5, "wait_for"), {}).process("q")
    assert env.plain == 2                    # 600 → 1200 ≥ 1000, 세 번째에서 차단
    assert "token budget exceeded: 1200/1000" in str(r.message)
    assert _kinds(env, "budget_exceeded")[0][3]["budget_kind"] == "tokens"


async def test_off_token_cap_via_child_tasks(env, monkeypatch):
    _token_env(env, monkeypatch)
    monkeypatch.setenv("LOGOSAI_HARNESS_CHILD_TASKS", "off")
    seen = {}
    assert await _agent(lambda llm: _children(llm, 5, "wait_for"), seen).process("q") == "done"
    assert env.plain == 5 and seen["child_tokens"] == 0 and env.events == []


# ── 섞인 계수: 소유 + 자식 + 도구 ────────────────────────────────────────

def _mixed(child_tail):
    async def body(llm):
        await _one(llm)                                   # 소유 1
        await _children(llm, 1, "wait_for")               # 자식 1
        await llm.invoke_with_tools(MSG, tools=[])        # 도구 1 (observe: 따로 센다)
        await _children(llm, child_tail, "wait_for")
    return body


async def test_observe_mixed_owner_child_tool(env):
    seen = {}
    assert await _agent(_mixed(1), seen).process("q") == "done"
    assert (seen["calls"], seen["child_calls"], seen["tool_calls"]) == (1, 2, 1)
    wb = _kinds(env, "would_block")
    assert len(wb) == 1 and wb[0][3]["budget_kind"] == "calls"
    assert wb[0][3]["path"] == "child_task"


async def test_observe_mixed_exactly_at_cap_is_silent(env):
    seen = {}
    assert await _agent(_mixed(0), seen).process("q") == "done"
    assert (seen["calls"], seen["child_calls"], seen["tool_calls"]) == (1, 1, 1)  # 대조군
    assert env.events == []


async def test_observe_owner_call_notices_combined_overrun(env):
    """자식 2 + 소유 2 (상한 3): 넘기는 호출이 소유 태스크여도 관측돼야 한다."""
    seen = {}

    async def body(llm):
        await _children(llm, 2, "gather")
        await _one(llm)
        await _one(llm)

    assert await _agent(body, seen).process("q") == "done"
    assert (seen["calls"], seen["child_calls"]) == (2, 2)
    wb = _kinds(env, "would_block")
    assert len(wb) == 1 and wb[0][3]["path"] == "child_task"


async def test_enforce_mixed_tool_observe_calls_do_not_eat_the_cap(env, monkeypatch):
    """도구 경로가 observe 면 도구 호출은 상한을 갉아먹지 않는다(기존 규칙 그대로)."""
    monkeypatch.setenv("LOGOSAI_HARNESS_CHILD_TASKS", "enforce")
    r = await _agent(_mixed(5), {}).process("q")
    assert (env.plain, env.tools) == (3, 1)  # 소유 1 + 자식 2 = 3, 그다음 자식에서 차단
    assert "LLM call budget exceeded: 4/3" in str(r.message)
    assert len(_kinds(env, "budget_exceeded")) == 1


# ── 스트림(observe 로 연 예산) 안의 자식 태스크 ──────────────────────────

async def test_stream_observe_counts_child_task_calls(env):
    usage = {}

    class Chatty(LogosAIAgent):
        async def process(self, query, context=None):
            return "ok"

        async def process_stream(self, query, context=None):
            llm = _llm()
            for i in range(6):
                await asyncio.wait_for(_one(llm), 5)
                usage.update(gr.execution_usage())
                yield i

    out = [x async for x in Chatty(_cfg("chatty")).process_stream("q")]
    assert out == [0, 1, 2, 3, 4, 5]         # observe 는 끊지 않는다
    assert usage["child_calls"] == 6         # 대조군
    wb = _kinds(env, "would_block")
    assert len(wb) == 1 and wb[0][3]["budget_kind"] == "calls"


# ── span metadata ────────────────────────────────────────────────────────

async def test_span_end_carries_harness_usage(env, monkeypatch):
    ended = []

    class FakeSpan:
        def end(self, **kw):
            ended.append(kw)

    monkeypatch.setenv("LOGOSAI_AUTO_OBSERVE", "true")
    monkeypatch.setattr(obs, "start_agent_span", lambda *a, **k: FakeSpan())
    monkeypatch.setattr(obs, "emit_agent_execution", lambda *a, **k: None)

    async def body(llm):
        await _children(llm, 2, "wait_for")
        await _one(llm)

    assert await _agent(body, {}).process("q") == "done"
    assert len(ended) == 1
    hu = ended[0]["metadata"]["harness_usage"]
    assert (hu["calls"], hu["child_calls"]) == (1, 2)


# ── 믹스인: 예산 초과를 삼키지 않는다 ────────────────────────────────────

class _StubLLM:
    max_tokens = 4000

    def __init__(self, exc):
        self.exc, self.n = exc, 0

    async def invoke_with_tools(self, messages, tools=None, **kw):
        self.n += 1
        raise self.exc

    async def invoke_messages(self, messages, **kw):
        self.n += 1
        raise self.exc


def _mixin_agent(method, exc):
    async def tool(**kw):
        return "ok"

    class M(LogosAIAgent):
        async def process(self, query, context=None):
            if method == "run_with_tools":
                return await self.run_with_tools(query, [{"name": "t"}], {"t": tool})
            if method == "react_tools":
                return await self.react(query, [{"name": "t"}], {"t": tool})
            return await self.react(query)

        async def recall_as_context(self, query="", top_k=3):
            return ""

    a = M(_cfg("mixin"))
    a.initialized = True
    a._llm = _StubLLM(exc)
    return a


MIXIN_METHODS = ["run_with_tools", "react_tools", "react_plain"]


@pytest.mark.parametrize("method", MIXIN_METHODS)
async def test_mixin_budget_exceeded_propagates(env, method):
    a = _mixin_agent(method, gr.HarnessBudgetExceeded("LLM call budget exceeded: 4/3"))
    r = await a.process("q")
    assert isinstance(r, AgentResponse)
    assert "harness budget" in str(r.message)
    assert "LLM call budget exceeded: 4/3" in str(r.message)
    assert len(_kinds(env, "budget_exceeded")) == 1
    assert a._llm.n == 1


@pytest.mark.parametrize("method", MIXIN_METHODS)
async def test_mixin_ordinary_exception_still_handled_as_before(env, method):
    a = _mixin_agent(method, RuntimeError("provider 500"))
    r = await a.process("q")
    assert a._llm.n == 1                     # 대조군: 호출까지는 갔다
    assert "harness budget" not in str(r.message)
    assert "reached" in str(r.message)       # 예전처럼 루프를 끝내고 정상 응답 모양
    assert env.events == []


async def test_react_real_budget_overrun_reaches_process_result(env):
    """소유 3회 뒤 react 의 첫 LLM 호출(4번째)이 넘긴다 — 조용히 '답'이 나가면 안 된다."""
    class R(LogosAIAgent):
        async def process(self, query, context=None):
            for _ in range(3):
                await _one(self._llm)
            return await self.react(query)

        async def recall_as_context(self, query="", top_k=3):
            return ""

    a = R(_cfg("reactreal"))
    a.initialized = True
    a._llm = _llm()
    r = await a.process("q")
    assert env.plain == 3
    assert "LLM call budget exceeded: 4/3" in str(r.message)
    assert len(_kinds(env, "budget_exceeded")) == 1


@pytest.mark.parametrize("exc,budget", [
    (gr.HarnessBudgetExceeded("LLM call budget exceeded: 4/3"), True),
    (RuntimeError("planner down"), False),
])
async def test_plan_does_not_swallow_budget_exceeded(env, monkeypatch, exc, budget):
    from logosai.agentic import planner

    async def boom(query, llm=None):
        raise exc
    monkeypatch.setattr(planner, "plan_goal", boom)

    class P(LogosAIAgent):
        async def process(self, query, context=None):
            return await self.plan(query)

        async def react(self, *a, **k):
            return "react-fallback"

    a = P(_cfg("plan"))
    a.initialized = True
    r = await a.process("q")
    if budget:
        assert "harness budget" in str(r.message)
    else:
        assert r == "react-fallback"         # 예전처럼 react 로 내려간다
