"""P0-2 확장 — 하네스 LLM 호출/비용 상한 (2026-07-06).

표준 준비도 진단 G2 완전 밀봉: 타임아웃에 더해 base process() 실행당
LLM 호출 수·토큰(비용) 상한을 기본 적용. 폭주 에이전트가 무한 LLM 호출로
비용을 태우지 않게 한다. 계약:
  - per-execution 격리(ContextVar) — 동시 실행이 서로 카운터를 오염하지 않음.
  - 호출 상한 초과 → HarnessBudgetExceeded, 하네스가 graceful AgentResponse.error 로.
  - 토큰 상한 누적 초과 → 다음 호출 precheck 에서 차단.
  - 예산 미활성(하네스 off / caps None) → precheck/record no-op(비하네스 경로 불변).
  - reset 로 실행 간 카운터 격리.
  - opt-out: _harness=False / env LOGOSAI_HARNESS=off → 예산 미적용.

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가
    **0건을 수집**했고, 회귀가 자동으로 잡히지 않았다.
  - 직접 실행: python tests/test_harness_budget.py  → 마지막 줄 `RESULT: GREEN`

import 시점에 프로세스 전역(os.environ·모듈 속성)을 건드리지 않는다. 이 테스트는
진짜 하네스 차단을 일으키고 차단은 Pulse 로 런타임 이벤트를 발행하므로
(observability.emit_harness_block) 전송은 반드시 막아야 하는데, 그 차단도
`_setup` 이 monkeypatch 로 세웠다가 되돌린다. 2026-08-09: import 시점에 세운
`LOGOS_PULSE_DISABLED=1` 이 프로세스에 남아 test_pulse_client_{spool,visibility}
8건을 조용히 죽였다 (파일 단독 실행 때는 통과해서 오래 안 보였다).
"""
import asyncio
import inspect
import os
import sys

# pytest_generate_tests / 스크립트 러너가 함께 쓰는 매개변수 표 (이 파일엔 없음).
_PARAMS = {}

_ENV_CLEARED = (
    "LOGOSAI_AUTO_OBSERVE", "LOGOSAI_HARNESS",
    # opt-in 이 켜진 환경에서 돌아도 테스트가 운영 관측 DB 로 쏘지 않게 한다.
    "LOGOSAI_PULSE_ALLOW_IN_TESTS",
)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _setup(mp):
    """테스트 하나의 환경. `mp` = pytest monkeypatch 또는 `_ScriptPatch` — 끝나면 전부 되돌려진다."""
    for k in _ENV_CLEARED:
        mp.delenv(k, raising=False)
    mp.setenv("LOGOS_PULSE_DISABLED", "1")
    mp.setenv("LOGOSAI_HARNESS_TIMEOUT", "5")       # 타임아웃은 넉넉히
    mp.setenv("LOGOSAI_HARNESS_MAX_CALLS", "3")     # 테스트용 낮은 상한
    mp.setenv("LOGOSAI_HARNESS_MAX_TOKENS", "100")

    import logosai.observability as obs
    from logosai.utils import pulse_client

    assert pulse_client._sending_blocked(), "Pulse 전송이 막혀 있지 않다 — 테스트가 관측 DB 를 오염시킨다"
    # 루프 밖에서 부른 배경 전송은 차단 판정 전에 스풀로 간다(pulse_client._fire_and_forget).
    # 스풀은 나중에 진짜 프로세스가 재전송하므로, 테스트가 거기에 쓰지 못하게 막는다.
    mp.setattr(pulse_client, "_spool_append", lambda *a, **k: None)

    # 관측 emit/span 은 무해화(예산만 검증)
    mp.setattr(obs, "emit_agent_execution", lambda *a, **k: None)
    mp.setattr(
        obs, "start_agent_span",
        lambda agent_id, query, harness_meta=None:
            type("S", (), {"end": lambda self, *a, **k: None})())


def _teardown():
    pass


def _gr():
    from logosai.utils import guardrails
    return guardrails


def _burst_agent():
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse
    gr = _gr()

    class BurstAgent(SimpleAgent):
        async def process(self, query, context=None):
            for _ in range(10):            # 상한(3) 훨씬 초과하는 LLM 호출 시뮬
                gr.precheck_llm_call()
            return AgentResponse.success(content={"answer": "done"})

    return BurstAgent()


def _light_agent():
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse
    gr = _gr()

    class LightAgent(SimpleAgent):
        async def process(self, query, context=None):
            gr.precheck_llm_call()
            gr.record_llm_tokens(10, 10)
            return AgentResponse.success(content={"answer": "ok:" + query})

    return LightAgent()


def _answer(res):
    return getattr(res, "content", {}).get("answer")


# ── 프리미티브 ──

def test_b1_no_active_budget_is_noop():
    """B-1 예산 미활성 → precheck/record no-op"""
    # 원래 검사는 `t(name, True)` — 예외가 안 나면 통과라는 뜻이었으나 단언이 없었다.
    gr = _gr()
    raised = None
    try:
        gr.precheck_llm_call()            # caps None → raise 안 함
        gr.record_llm_tokens(9999, 9999)
        gr.precheck_llm_call()            # 예산 없이 쌓인 토큰이 다음 호출을 막지도 않는다
    except gr.HarnessBudgetExceeded as e:
        raised = e
    assert raised is None, f"예산이 없는데 차단됐다: {raised}"


def test_b2_call_cap_exceeded_raises():
    """B-2 호출 상한 초과 → HarnessBudgetExceeded"""
    gr = _gr()
    tok = gr.begin_execution_budget(max_calls=3, max_tokens=None)
    allowed, raised = 0, False
    try:
        for _ in range(3):
            gr.precheck_llm_call()  # 1,2,3 OK
            allowed += 1
        gr.precheck_llm_call()      # 4번째 → 초과
    except gr.HarnessBudgetExceeded:
        raised = True
    finally:
        gr.reset_execution_budget(tok)
    assert allowed == 3, f"상한 3 인데 {allowed}번째에서 이미 막혔다"
    assert raised, "4번째 호출이 막히지 않았다"


def test_b3_token_cap_blocks_next_precheck():
    """B-3 토큰 상한 누적 초과 → 다음 precheck 차단"""
    gr = _gr()
    tok = gr.begin_execution_budget(max_calls=None, max_tokens=100)
    raised = False
    try:
        gr.precheck_llm_call()           # 1번째 OK (누적 0)
        gr.record_llm_tokens(80, 40)     # 누적 120 >= 100
        try:
            gr.precheck_llm_call()       # 다음 호출 차단
        except gr.HarnessBudgetExceeded:
            raised = True
    finally:
        gr.reset_execution_budget(tok)
    assert raised


def test_b4_reset_isolates_counters():
    """B-4 reset 후 카운터 격리(0부터)"""
    gr = _gr()
    tok = gr.begin_execution_budget(max_calls=2, max_tokens=None)
    try:
        gr.precheck_llm_call()
    finally:
        gr.reset_execution_budget(tok)
    # reset 후 새 예산 → 카운터 0 부터
    tok2 = gr.begin_execution_budget(max_calls=2, max_tokens=None)
    ok = True
    try:
        gr.precheck_llm_call()
        gr.precheck_llm_call()
    except gr.HarnessBudgetExceeded:
        ok = False
    finally:
        gr.reset_execution_budget(tok2)
    assert ok, "이전 실행의 호출 수가 새 예산으로 넘어왔다"


# ── 통합: process() ──

def test_b5_process_over_call_cap_returns_graceful_error():
    """B-5 호출 상한 초과 시 graceful AgentResponse.error"""
    from logosai.agent_types import AgentResponseType
    res = run(_burst_agent().process("x"))
    assert getattr(res, "type", None) == AgentResponseType.ERROR


def test_b6_process_within_caps_completes():
    """B-6 상한 이내 → 정상 완료"""
    assert _answer(run(_light_agent().process("hi"))) == "ok:hi"


def test_b7_harness_false_disables_budget():
    """B-7 _harness=False → 예산 미적용(완료)"""
    burst = _burst_agent()
    burst._harness = False
    assert _answer(run(burst.process("y"))) == "done"


# ══ pytest 배선 ═══════════════════════════════════════════════════════════

if "pytest" in sys.modules:
    import pytest

    @pytest.fixture(autouse=True)
    def _harness_env(monkeypatch):
        _setup(monkeypatch)
        yield
        _teardown()


def pytest_generate_tests(metafunc):
    for key, values in _PARAMS.items():
        if key in metafunc.fixturenames:
            metafunc.parametrize(key, values, ids=[repr(v) for v in values])


# ══ 스크립트 모드 러너 ═════════════════════════════════════════════════════
# pytest 없이도 돈다. 검사 목록을 따로 두지 않고 이 모듈의 `test_*` 를 정의
# 순서대로 찾아 부르므로, 테스트를 추가하고 여기에 빠뜨리는 일이 생길 수 없다.

class _ScriptPatch:
    """pytest monkeypatch 의 최소 대역 — 세운 것을 `undo()` 로 전부 되돌린다."""

    def __init__(self):
        self._undo = []

    def setenv(self, key, value):
        self._remember_env(key)
        os.environ[key] = str(value)

    def delenv(self, key, raising=True):
        if key not in os.environ:
            if raising:
                raise KeyError(key)
            return
        self._remember_env(key)
        del os.environ[key]

    def setattr(self, obj, name, value):
        old = getattr(obj, name)
        self._undo.append(lambda: setattr(obj, name, old))
        setattr(obj, name, value)

    def _remember_env(self, key):
        old = os.environ.get(key)

        def restore():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

        self._undo.append(restore)

    def undo(self):
        while self._undo:
            self._undo.pop()()


def _script_cases():
    """(라벨, 함수, kwargs) — 라벨은 docstring 첫 줄, 매개변수화된 것은 값마다 편다."""
    for name, fn in list(globals().items()):
        if not name.startswith("test_") or not inspect.isfunction(fn):
            continue
        label = (fn.__doc__ or name).strip().splitlines()[0]
        key = next((p for p in inspect.signature(fn).parameters if p in _PARAMS), None)
        if key is None:
            yield label, fn, {}
        else:
            for value in _PARAMS[key]:
                yield label.format(**{key: value}), fn, {key: value}


def _run_script_case(fn, kwargs):
    mp = _ScriptPatch()
    try:
        _setup(mp)
        if "monkeypatch" in inspect.signature(fn).parameters:
            kwargs = dict(kwargs, monkeypatch=mp)
        result = fn(**kwargs)
        if inspect.iscoroutine(result):
            asyncio.run(result)
        return True
    except AssertionError:
        return False
    finally:
        _teardown()
        mp.undo()


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    fails = []
    for label, fn, kwargs in _script_cases():
        ok = _run_script_case(fn, kwargs)
        print(("PASS " if ok else "FAIL ") + label)
        if not ok:
            fails.append(label)
    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
