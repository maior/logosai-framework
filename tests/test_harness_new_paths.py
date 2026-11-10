"""하네스 신규 경로(tools · stream) 커버 — LOGOSAI_HARNESS_NEW_PATHS.

실측으로 확인한 구멍 둘을 막는다:
  1. `LLMClient.invoke_with_tools` 는 예산·레이트리밋·메트릭을 전부 건너뛰었다
     (상한 3 에 도구 호출 10회가 다 돌았다).
  2. `process_stream` 은 래핑되지 않았다 (타임아웃 2초에 4초 스트림이 끝까지 돌았다).

새 커버는 기본이 observe 다 — 세기만 하고 막지 않는다. 지금 되는 것이
이 변경 때문에 실패하기 시작하면 안 된다. 그래서 부정 단언("안 막혔다")마다
대조군("카운터는 실제로 올랐다")을 붙였다.

네트워크 없음: 제공자 호출은 전부 가짜. 이벤트는 emit_harness_block 을 가로챈다.
"""
import asyncio
import inspect
import time
from types import SimpleNamespace

import pytest

from logosai import AgentConfig, LogosAIAgent
from logosai import observability as obs
from logosai.utils import guardrails as gr
from logosai.utils.llm_client import LLMClient, LLMMessage, LLMResponse


def _cfg(name):
    return AgentConfig(name=name, agent_type="custom", description="probe")


def _resp(tokens=(0, 0)):
    raw = SimpleNamespace(usage=SimpleNamespace(
        prompt_tokens=tokens[0], completion_tokens=tokens[1]))
    return LLMResponse(content="x", provider="google", model="probe", raw_response=raw)


class _FakeLimiter:
    def __init__(self):
        self.acquired = 0

    async def acquire(self):
        self.acquired += 1


@pytest.fixture
def env(monkeypatch):
    """가짜 제공자 + 이벤트 수집 + 전역 가드레일 격리."""
    for k in ("LOGOSAI_HARNESS_NEW_PATHS", "LOGOSAI_HARNESS", "LOGOSAI_HARNESS_MAX_TOKENS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LOGOSAI_HARNESS_MAX_CALLS", "3")
    monkeypatch.setenv("LOGOSAI_HARNESS_TIMEOUT", "30")

    st = SimpleNamespace(tools=0, plain=0, events=[], tokens=(0, 0),
                         limiter=_FakeLimiter(),
                         counter=gr.RequestCallCounter(max_calls=10_000))

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
    # 전역 싱글턴(분당 30회·요청당 15회)이 테스트끼리 새지 않게 갈아 끼운다.
    monkeypatch.setattr(gr, "get_rate_limiter", lambda: st.limiter)
    monkeypatch.setattr(gr, "get_request_counter", lambda: st.counter)
    monkeypatch.setattr(
        obs, "emit_harness_block",
        lambda kind, agent_id, detail, payload=None:
            st.events.append((kind, agent_id, detail, dict(payload or {}))))
    return st


def _llm():
    return LLMClient(provider="google", model="probe")


def _kinds(st, kind):
    return [e for e in st.events if e[0] == kind]


def _tool_loop_agent(n, seen, wrap_wait_for=False):
    """도구 경로를 n 번 부르고 마지막 사용량을 seen 에 남기는 에이전트."""
    class ToolLoop(LogosAIAgent):
        async def process(self, query, context=None):
            llm = _llm()
            try:
                for _ in range(n):
                    coro = llm.invoke_with_tools([{"role": "user", "content": "q"}], tools=[])
                    # mixins/tool_use.py · react.py 가 실제로 이렇게 부른다.
                    await (asyncio.wait_for(coro, timeout=5) if wrap_wait_for else coro)
            finally:
                seen.update(gr.execution_usage())
            return "done"
    return ToolLoop(_cfg("toolloop"))


# ── tools: observe (기본) ────────────────────────────────────────────────

async def test_observe_default_tool_calls_run_and_would_block_once(env):
    seen = {}
    r = await _tool_loop_agent(10, seen).process("q")
    assert r == "done"                       # 막히지 않았다
    assert env.tools == 10
    # 대조군: 안 막힌 것이 '안 셌기 때문'이 아니다.
    assert seen["tool_calls"] == 10
    assert seen["calls"] == 0                # 메시지 경로 카운터는 건드리지 않았다
    assert seen["would_block"] == ["calls"]
    wb = _kinds(env, "would_block")
    assert len(wb) == 1                      # 실행당 종류별 1회
    assert wb[0][3] == {"path": "tools", "budget_kind": "calls",
                        "max_calls": 3, "max_tokens": 200000, "mode": "observe"}
    assert _kinds(env, "budget_exceeded") == []
    # observe 는 세기만 한다 — 전역 레이트리밋은 enforce 에서만.
    assert env.limiter.acquired == 0


async def test_observe_survives_wait_for_wrapped_calls(env):
    """자식 태스크는 ContextVar 사본을 받는다 — 거기서도 누적돼야 관측이 된다."""
    seen = {}
    await _tool_loop_agent(6, seen, wrap_wait_for=True).process("q")
    assert env.tools == 6
    assert seen["tool_calls"] == 6
    assert len(_kinds(env, "would_block")) == 1


@pytest.mark.parametrize("mode,tool_calls_first", [
    (None, 0),           # 기준선 — 도구 호출 없음
    ("observe", 5),      # 도구 5회가 앞서도
    ("off", 5),
])
async def test_messages_cap_trips_at_same_call_number(env, monkeypatch, mode, tool_calls_first):
    """observe/off 에서 도구 호출이 메시지 경로 상한을 갉아먹으면 안 된다."""
    if mode:
        monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", mode)

    class Mixed(LogosAIAgent):
        async def process(self, query, context=None):
            llm = _llm()
            for _ in range(tool_calls_first):
                await llm.invoke_with_tools([{"role": "user", "content": "q"}], tools=[])
            for _ in range(10):
                await llm.invoke_messages([{"role": "user", "content": "q"}], _max_retries=0)
            return "done"

    r = await Mixed(_cfg("mixed")).process("q")
    assert env.tools == tool_calls_first
    assert env.plain == 3                    # 4번째에서 정확히 걸린다 — 이전과 같은 자리
    assert "LLM call budget exceeded: 4/3" in str(r.message)
    assert len(_kinds(env, "budget_exceeded")) == 1


async def test_observe_notices_combined_overrun_on_messages_call(env):
    """도구 2 + 메시지 2 (상한 3): enforce 였다면 4번째에서 막혔다 → 관측돼야 한다."""
    seen = {}

    class Mixed(LogosAIAgent):
        async def process(self, query, context=None):
            llm = _llm()
            for _ in range(2):
                await llm.invoke_with_tools([{"role": "user", "content": "q"}], tools=[])
            for _ in range(2):
                await llm.invoke_messages([{"role": "user", "content": "q"}], _max_retries=0)
            seen.update(gr.execution_usage())
            return "done"

    assert await Mixed(_cfg("mixed2")).process("q") == "done"
    assert (seen["calls"], seen["tool_calls"]) == (2, 2)
    assert len(_kinds(env, "would_block")) == 1


async def test_messages_only_execution_emits_no_would_block(env):
    """도구 경로를 안 쓰는 실행은 이 변경을 전혀 느끼지 못한다."""
    seen = {}

    class Plain(LogosAIAgent):
        async def process(self, query, context=None):
            llm = _llm()
            for _ in range(3):
                await llm.invoke_messages([{"role": "user", "content": "q"}], _max_retries=0)
            seen.update(gr.execution_usage())
            return "done"

    assert await Plain(_cfg("plain")).process("q") == "done"
    assert seen["calls"] == 3                # 대조군: 세고는 있다
    assert env.events == []


# ── tools: enforce ───────────────────────────────────────────────────────

@pytest.mark.parametrize("wrap", [False, True])
async def test_enforce_tool_path_trips_at_call_four(env, monkeypatch, wrap):
    monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", "enforce")
    seen = {}
    r = await _tool_loop_agent(10, seen, wrap_wait_for=wrap).process("q")
    assert env.tools == 3                    # 4번째는 제공자에 닿지 못했다
    assert "harness budget" in str(r.message)
    assert "LLM call budget exceeded: 4/3" in str(r.message)
    be = _kinds(env, "budget_exceeded")
    assert len(be) == 1 and be[0][3]["budget_kind"] == "calls"
    assert _kinds(env, "would_block") == []
    # enforce 에서는 invoke_messages 와 같은 전역 가드레일도 지난다.
    assert env.limiter.acquired == 4
    assert env.counter.current_calls == 4


async def test_enforce_tool_and_messages_share_one_counter(env, monkeypatch):
    monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", "enforce")

    class Mixed(LogosAIAgent):
        async def process(self, query, context=None):
            llm = _llm()
            for _ in range(2):
                await llm.invoke_with_tools([{"role": "user", "content": "q"}], tools=[])
            for _ in range(10):
                await llm.invoke_messages([{"role": "user", "content": "q"}], _max_retries=0)
            return "done"

    r = await Mixed(_cfg("mixed3")).process("q")
    assert (env.tools, env.plain) == (2, 1)  # 2 + 1 = 3, 그다음에서 차단
    assert "LLM call budget exceeded: 4/3" in str(r.message)


async def test_enforce_fallback_is_not_double_counted(env, monkeypatch):
    """프롬프트 폴백은 내부에서 invoke_messages 를 부른다 — 한 호출이 두 번 세지면
    상한의 절반에서 잘린다(거짓 차단)."""
    monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", "enforce")
    seen = []

    async def via_fallback(self, messages, tools, **kw):
        fmt = [LLMMessage(**m) if isinstance(m, dict) else m for m in messages]
        return await self._call_with_tools_fallback(fmt, tools, _max_retries=0)

    monkeypatch.setattr(LLMClient, "_dispatch_with_tools", via_fallback)

    class Fb(LogosAIAgent):
        async def process(self, query, context=None):
            llm = _llm()
            for _ in range(10):
                await llm.invoke_with_tools([{"role": "user", "content": "q"}],
                                            tools=[{"name": "t"}])
                seen.append(gr.execution_usage()["calls"])
            return "done"

    r = await Fb(_cfg("fb")).process("q")
    assert seen == [1, 2, 3]                 # 2, 4, 6 이 아니다
    assert env.plain == 3
    assert "LLM call budget exceeded: 4/3" in str(r.message)


# ── tools: off ───────────────────────────────────────────────────────────

async def test_off_tool_path_not_counted_at_all(env, monkeypatch):
    monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", "off")
    calls = []
    monkeypatch.setattr(LLMClient, "_metrics_callback", lambda m: calls.append(m))
    seen = {}

    class Off(LogosAIAgent):
        async def process(self, query, context=None):
            llm = _llm()
            for _ in range(10):
                await llm.invoke_with_tools([{"role": "user", "content": "q"}], tools=[])
            gr.precheck_llm_call()           # 대조군: 예산 자체는 살아 있다
            seen.update(gr.execution_usage())
            return "done"

    assert await Off(_cfg("off")).process("q") == "done"
    assert env.tools == 10
    assert seen["tool_calls"] == 0 and seen["tool_tokens"] == 0
    assert seen["calls"] == 1
    assert env.events == [] and calls == [] and env.limiter.acquired == 0


# ── tools: 토큰 상한 ─────────────────────────────────────────────────────

async def test_observe_token_cap_would_block(env, monkeypatch):
    monkeypatch.setenv("LOGOSAI_HARNESS_MAX_CALLS", "0")       # 호출 상한 없음
    monkeypatch.setenv("LOGOSAI_HARNESS_MAX_TOKENS", "1000")
    env.tokens = (400, 200)
    seen = {}
    assert await _tool_loop_agent(5, seen).process("q") == "done"
    assert env.tools == 5
    assert seen["tool_tokens"] == 3000 and seen["tokens"] == 0
    assert seen["would_block"] == ["tokens"]
    wb = _kinds(env, "would_block")
    assert len(wb) == 1
    assert wb[0][3]["budget_kind"] == "tokens" and wb[0][3]["max_tokens"] == 1000


@pytest.mark.parametrize("wrap", [False, True])
async def test_enforce_token_cap_blocks(env, monkeypatch, wrap):
    monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", "enforce")
    monkeypatch.setenv("LOGOSAI_HARNESS_MAX_CALLS", "0")
    monkeypatch.setenv("LOGOSAI_HARNESS_MAX_TOKENS", "1000")
    env.tokens = (400, 200)
    r = await _tool_loop_agent(5, {}, wrap_wait_for=wrap).process("q")
    assert env.tools == 2                    # 600 → 1200 ≥ 1000, 세 번째에서 차단
    assert "token budget exceeded" in str(r.message)
    assert _kinds(env, "budget_exceeded")[0][3]["budget_kind"] == "tokens"


# ── tools: 메트릭 콜백 ───────────────────────────────────────────────────

async def test_tool_path_reports_metrics_callback(env, monkeypatch):
    got = []
    monkeypatch.setattr(LLMClient, "_metrics_callback", lambda m: got.append(m))
    env.tokens = (7, 5)
    await _llm().invoke_with_tools([{"role": "user", "content": "hello"}], tools=[])
    assert len(got) == 1
    assert (got[0]["input_tokens"], got[0]["output_tokens"]) == (7, 5)
    assert got[0]["success"] is True and got[0]["model"] == "probe"
    assert got[0]["prompt_preview"] == "hello"


async def test_guardrails_does_not_import_observability_at_import_time():
    src = inspect.getsource(gr)
    top = [l for l in src.splitlines()
           if l.startswith(("import ", "from ")) and "observability" in l]
    assert top == []
    assert "observability" in src            # 대조군: 지연 import 는 실제로 있다


async def test_would_block_emit_failure_never_raises(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("pulse down")
    monkeypatch.setattr(obs, "emit_harness_block", boom)
    seen = {}
    assert await _tool_loop_agent(5, seen).process("q") == "done"
    assert seen["would_block"] == ["calls"]  # 대조군: 발행 지점까지는 갔다


# ── stream ───────────────────────────────────────────────────────────────

def _slow_stream_agent(delay, closed):
    class Slow(LogosAIAgent):
        async def process(self, query, context=None):
            return "ok"

        async def process_stream(self, query, context=None):
            try:
                yield "first"
                await asyncio.sleep(delay)
                yield "late"
                yield "later"
            finally:
                closed.append(True)
    return Slow(_cfg("slow"))


async def _drain(agent):
    return [x async for x in agent.process_stream("q")]


async def test_stream_observe_keeps_yielding_past_timeout(env, monkeypatch):
    monkeypatch.setenv("LOGOSAI_HARNESS_TIMEOUT", "0.2")
    out = await _drain(_slow_stream_agent(0.5, []))
    assert out == ["first", "late", "later"]
    wb = _kinds(env, "would_block")
    assert len(wb) == 1                      # 시간이 지난 뒤 항목이 둘이어도 1회
    assert wb[0][3] == {"path": "stream", "budget_kind": "timeout",
                        "timeout_s": 0.2, "mode": "observe"}
    assert _kinds(env, "timeout") == []


async def test_stream_observe_within_timeout_is_silent(env):
    out = await _drain(_slow_stream_agent(0.01, []))
    assert out == ["first", "late", "later"]
    assert env.events == []


async def test_stream_enforce_cuts_at_timeout_with_error_event(env, monkeypatch):
    monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", "enforce")
    monkeypatch.setenv("LOGOSAI_HARNESS_TIMEOUT", "0.3")
    closed = []
    t0 = time.monotonic()
    agent = _slow_stream_agent(3.0, closed)
    out = await _drain(agent)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.5                     # 3초를 다 기다리지 않았다
    assert out[0] == "first"                 # 대조군: 한도 전 항목은 전달됐다
    assert out[-1] == {"type": "error", "data": {"error": (
        f"harness timeout: agent '{obs.harness_agent_id(agent)}' exceeded 0.3s budget")}}
    assert len(out) == 2
    assert closed == [True]                  # 안쪽 제너레이터를 닫았다
    to = _kinds(env, "timeout")
    assert len(to) == 1 and to[0][3]["path"] == "stream" and to[0][3]["timeout_s"] == 0.3


async def test_stream_enforce_does_not_mistake_inner_timeout_for_harness(env, monkeypatch):
    """스트림이 스스로 던진 TimeoutError 는 하네스 차단이 아니다."""
    monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", "enforce")

    class Own(LogosAIAgent):
        async def process(self, query, context=None):
            return "ok"

        async def process_stream(self, query, context=None):
            yield "a"
            raise TimeoutError("upstream socket")

    with pytest.raises(TimeoutError, match="upstream socket"):
        await _drain(Own(_cfg("own")))
    assert env.events == []


@pytest.mark.parametrize("knob", ["harness_off", "mode_off", "attr_false"])
async def test_stream_untouched_when_disabled(env, monkeypatch, knob):
    monkeypatch.setenv("LOGOSAI_HARNESS_TIMEOUT", "0.2")
    monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", "enforce")
    agent = _slow_stream_agent(0.5, [])
    if knob == "harness_off":
        monkeypatch.setenv("LOGOSAI_HARNESS", "off")
    elif knob == "mode_off":
        monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", "off")
    else:
        agent._harness = False
    # 대조군은 위 enforce 테스트 — 같은 스트림이 거기서는 잘린다.
    assert await _drain(agent) == ["first", "late", "later"]
    assert env.events == []


async def test_stream_wrapping_subclass_base_and_idempotent(env):
    class Own(LogosAIAgent):
        async def process(self, query, context=None):
            return "ok"

        async def process_stream(self, query, context=None):
            yield 1

    class Inherits(LogosAIAgent):
        async def process(self, query, context=None):
            return "ok"

    class Grand(Own):
        pass

    assert getattr(Own.__dict__["process_stream"], "_logos_stream_observed", False)
    assert getattr(LogosAIAgent.__dict__["process_stream"], "_logos_stream_observed", False)
    assert "process_stream" not in Inherits.__dict__        # 상속분은 다시 싸지 않는다
    assert Inherits.process_stream is LogosAIAgent.process_stream
    assert Grand.process_stream is Own.process_stream
    w = Own.__dict__["process_stream"]
    assert obs.observe_stream(w) is w                        # 이중 래핑 없음
    # 호출부가 async generator 인지 검사해도 깨지지 않는다.
    assert inspect.isasyncgenfunction(w)
    assert inspect.isasyncgenfunction(LogosAIAgent.process_stream)

    async def raw(self, query, context=None):
        yield 1
    assert obs.observe_stream(raw) is not raw                # 대조군: 처음엔 싼다


async def test_inherited_base_stream_is_harnessed(env, monkeypatch):
    monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", "enforce")
    monkeypatch.setenv("LOGOSAI_HARNESS_TIMEOUT", "0.3")

    class Sleepy(LogosAIAgent):
        async def initialize(self):
            self.initialized = True
            return True

        async def process(self, query, context=None):
            await asyncio.sleep(3)
            return "never"

    t0 = time.monotonic()
    out = await _drain(Sleepy(_cfg("sleepy")))
    assert time.monotonic() - t0 < 1.5
    assert out[0]["type"] == "start"         # 대조군: 기본 스트림이 실제로 돌았다
    assert out[-1]["type"] == "error"
    assert "harness timeout" in out[-1]["data"]["error"]


def _chatty_stream_agent(n, usage):
    class Chatty(LogosAIAgent):
        async def process(self, query, context=None):
            return "ok"

        async def process_stream(self, query, context=None):
            for i in range(n):
                gr.precheck_llm_call()       # invoke_messages 가 호출 전에 부르는 훅
                usage.append(gr.execution_usage()["calls"])
                yield i
    return Chatty(_cfg("chatty"))


async def test_stream_enforce_budget_ends_with_error_event(env, monkeypatch):
    monkeypatch.setenv("LOGOSAI_HARNESS_NEW_PATHS", "enforce")
    out = await _drain(_chatty_stream_agent(6, []))
    assert out[:3] == [0, 1, 2]
    assert len(out) == 4 and out[-1]["type"] == "error"
    assert out[-1]["data"]["error"].startswith("harness budget: agent '")
    assert "LLM call budget exceeded: 4/3" in out[-1]["data"]["error"]
    be = _kinds(env, "budget_exceeded")
    assert len(be) == 1 and be[0][3]["path"] == "stream"


async def test_stream_observe_budget_counts_but_never_raises(env):
    """observe 에서 스트림 안의 LLM 호출이 예외로 죽기 시작하면 안 된다."""
    usage, leaked = [], []
    agent = _chatty_stream_agent(6, usage)
    out = []
    async for x in agent.process_stream("q"):
        out.append(x)
        leaked.append(gr.budget_active())    # yield 사이에 소비자 컨텍스트로 새지 않는다
    assert out == [0, 1, 2, 3, 4, 5]
    assert usage == [1, 2, 3, 4, 5, 6]       # 대조군: yield 를 넘어 누적됐다
    assert leaked == [False] * 6
    assert gr.budget_active() is False
    wb = _kinds(env, "would_block")
    assert len(wb) == 1
    assert wb[0][3]["path"] == "stream" and wb[0][3]["budget_kind"] == "calls"


async def test_stream_nested_in_process_does_not_start_second_budget(env):
    seen = []

    class Nested(LogosAIAgent):
        async def process(self, query, context=None):
            gr.precheck_llm_call()
            gr.precheck_llm_call()
            async for _ in self.process_stream(query):
                pass
            seen.append(("after", gr.execution_usage()["calls"]))
            return "ok"

        async def process_stream(self, query, context=None):
            gr.precheck_llm_call()
            seen.append(("in", gr.execution_usage()["calls"]))
            yield 1

    assert await Nested(_cfg("nested")).process("q") == "ok"
    assert seen == [("in", 3), ("after", 3)]  # 0 에서 다시 시작하지 않았다
