"""P0-2 하네스 기본 적용 — 타임아웃 테스트 (2026-07-06).

표준 준비도 진단 G2: 안전이 default. base process() 에 실행 타임아웃을 기본으로
걸어, 폭주 에이전트가 무한정 매달리지 않게 한다. 계약:
  - 기본 타임아웃(default) 초과 시 process 가 매달리지 않고 AgentResponse.error 반환.
  - 정상(빠른) process 는 영향 없음.
  - opt-out: agent._harness=False 또는 env LOGOSAI_HARNESS=off → 타임아웃 미적용.
  - env LOGOSAI_HARNESS_TIMEOUT 로 초 조정.
  - 타임아웃도 관측(success=False)으로 기록.
  - 관측·하네스 공존.

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가
    **0건을 수집**했고, 회귀가 자동으로 잡히지 않았다.
  - 직접 실행: python tests/test_harness_timeout.py  → 마지막 줄 `RESULT: GREEN`

import 시점에 프로세스 전역(os.environ·모듈 속성)을 건드리지 않는다. 이 테스트는
진짜 하네스 차단을 일으키고 차단은 Pulse 로 런타임 이벤트를 발행하므로
(observability.emit_harness_block) 전송은 반드시 막아야 하는데, 그 차단도
`_setup` 이 monkeypatch 로 세웠다가 되돌린다 — 예전처럼 import 시점에
`LOGOS_PULSE_DISABLED=1` 을 세우면 다른 파일의 전송 경로 테스트를 조용히 죽인다
(2026-08-09 사고).
"""
import asyncio
import inspect
import os
import sys
import time

# 타임아웃 관측 레코더 — `_setup` 이 매 테스트마다 비운다.
_REC = {"exec": []}

# pytest_generate_tests / 스크립트 러너가 함께 쓰는 매개변수 표 (이 파일엔 없음).
_PARAMS = {}

_ENV_CLEARED = (
    "LOGOSAI_AUTO_OBSERVE", "LOGOSAI_HARNESS",
    "LOGOSAI_HARNESS_MAX_CALLS", "LOGOSAI_HARNESS_MAX_TOKENS",
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
    mp.setenv("LOGOSAI_HARNESS_TIMEOUT", "0.15")  # 테스트용 짧은 기본

    import logosai.observability as obs
    from logosai.utils import pulse_client

    assert pulse_client._sending_blocked(), "Pulse 전송이 막혀 있지 않다 — 테스트가 관측 DB 를 오염시킨다"
    # 루프 밖에서 부른 배경 전송은 차단 판정 전에 스풀로 간다(pulse_client._fire_and_forget).
    # 스풀은 나중에 진짜 프로세스가 재전송하므로, 테스트가 거기에 쓰지 못하게 막는다.
    mp.setattr(pulse_client, "_spool_append", lambda *a, **k: None)

    # 관측 emit 은 레코더로 (하네스와 무관하게 관측 검증)
    _REC["exec"].clear()
    mp.setattr(
        obs, "emit_agent_execution",
        lambda agent_id, query, success, duration_ms, output="", error=None:
            _REC["exec"].append({"success": success}))
    mp.setattr(
        obs, "start_agent_span",
        lambda agent_id, query, harness_meta=None:
            type("S", (), {"end": lambda self, *a, **k: None})())


def _teardown():
    pass


def _slow_agent():
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse

    class SlowAgent(SimpleAgent):
        async def process(self, query, context=None):
            await asyncio.sleep(1.0)  # 기본 타임아웃(0.15s) 초과
            return AgentResponse.success(content={"answer": "late"})

    return SlowAgent()


def _fast_agent():
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse

    class FastAgent(SimpleAgent):
        async def process(self, query, context=None):
            return AgentResponse.success(content={"answer": "quick:" + query})

    return FastAgent()


def _answer(res):
    return getattr(res, "content", {}).get("answer")


# ── 타임아웃 발동: 매달리지 않고 error 반환 ──

def test_h1_timeout_does_not_hang():
    """H-1 타임아웃 초과 시 매달리지 않음(<0.5s)"""
    slow = _slow_agent()
    t0 = time.monotonic()
    run(slow.process("x"))
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5, f"1.0초짜리 process 가 0.15초 한도에서 {elapsed:.2f}s 걸렸다"


def test_h2_timeout_returns_agent_response_error():
    """H-2 AgentResponse.error 반환"""
    from logosai.agent_types import AgentResponseType
    res = run(_slow_agent().process("x"))
    assert getattr(res, "type", None) == AgentResponseType.ERROR


# ── 정상 process 영향 없음 ──

def test_h3_fast_process_unaffected():
    """H-3 빠른 process 정상"""
    res = run(_fast_agent().process("hi"))
    assert _answer(res) == "quick:hi"


# ── opt-out ──

def test_h4_harness_false_disables_timeout():
    """H-4 _harness=False → 타임아웃 미적용(완료)"""
    slow = _slow_agent()
    slow._harness = False
    assert _answer(run(slow.process("y"))) == "late"


def test_h5_env_harness_off_disables_timeout(monkeypatch):
    """H-5 env HARNESS=off → 타임아웃 미적용"""
    monkeypatch.setenv("LOGOSAI_HARNESS", "off")
    assert _answer(run(_slow_agent().process("z"))) == "late"


# ── env 타임아웃 조정: 크게 하면 완료 ──

def test_h6_env_timeout_raised_lets_slow_process_finish(monkeypatch):
    """H-6 env TIMEOUT 상향 → 완료"""
    monkeypatch.setenv("LOGOSAI_HARNESS_TIMEOUT", "2.0")
    assert _answer(run(_slow_agent().process("w"))) == "late"


# ── 타임아웃도 관측 success=False ──

def test_h7_timeout_is_observed_as_failure():
    """H-7 타임아웃도 관측(success False)"""
    run(_slow_agent().process("obs"))
    assert len(_REC["exec"]) == 1, f"execution emit {len(_REC['exec'])}건 (1건이어야 한다)"
    assert _REC["exec"][0]["success"] is False


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
