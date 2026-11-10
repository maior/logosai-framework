"""P0-1 관측 자동 배선 테스트 (2026-07-06).

표준 준비도 진단 G3: base process() 가 관측 신호를 자동 emit 해야 "그냥 만들면
Pulse 에 뜬다"는 표준 default 경험이 성립. 계약:
  - 서브클래스가 정의한 process 는 자동으로 관측 래핑된다 (_logos_observed).
  - enabled + standalone → execution emit + span 시작. process 결과 불변.
  - opt-out: env LOGOSAI_AUTO_OBSERVE=false 또는 agent._auto_observe=False → emit 없음.
  - fire-and-forget: emit 이 raise 해도 process 는 정상 반환.
  - 부모 trace 존재(ACP 내부) → execution 이중 emit 안 함 (ACP 소유). span 은 중첩.
  - 이중 서브클래싱 → 이중 래핑/이중 emit 없음.

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가
    **0건을 수집**했고, 회귀가 자동으로 잡히지 않았다.
  - 직접 실행: python tests/test_auto_observability.py  → 마지막 줄 `RESULT: GREEN`

import 시점에 프로세스 전역(os.environ·모듈 속성)을 건드리지 않는다. emit/span 은
레코더로 바꿔 관찰하고, 진짜 전송(부모 TraceSpan 등)은 `_setup` 이 막는다 —
둘 다 monkeypatch 라 테스트가 끝나면 되돌려진다.
"""
import asyncio
import inspect
import os
import sys

# emit / span 레코더 — `_setup` 이 매 테스트마다 초기화한다.
_REC = {"exec": [], "span": 0, "raise": False}

# pytest_generate_tests / 스크립트 러너가 함께 쓰는 매개변수 표 (이 파일엔 없음).
_PARAMS = {}

_ENV_CLEARED = (
    "LOGOSAI_AUTO_OBSERVE",  # 기본 on
    "LOGOSAI_HARNESS", "LOGOSAI_HARNESS_TIMEOUT",
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

    import logosai.observability as obs
    from logosai.utils import pulse_client

    assert pulse_client._sending_blocked(), "Pulse 전송이 막혀 있지 않다 — 테스트가 관측 DB 를 오염시킨다"
    # 루프 밖에서 부른 배경 전송은 차단 판정 전에 스풀로 간다(pulse_client._fire_and_forget).
    # 스풀은 나중에 진짜 프로세스가 재전송하므로, 테스트가 거기에 쓰지 못하게 막는다.
    mp.setattr(pulse_client, "_spool_append", lambda *a, **k: None)

    _REC.update({"exec": [], "span": 0, "raise": False})

    def fake_emit(agent_id, query, success, duration_ms, output="", error=None):
        if _REC["raise"]:
            raise RuntimeError("pulse down")
        _REC["exec"].append({"agent_id": agent_id, "success": success})

    class _FakeSpan:
        def end(self, *a, **k):
            pass

    def fake_span(agent_id, query, harness_meta=None):
        _REC["span"] += 1
        return _FakeSpan()

    mp.setattr(obs, "emit_agent_execution", fake_emit)
    mp.setattr(obs, "start_agent_span", fake_span)


def _teardown():
    pass


def _my_agent_cls():
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse

    class MyAgent(SimpleAgent):
        async def process(self, query, context=None):
            return AgentResponse.success(content={"answer": "ok:" + query})

    return MyAgent


def _fail_agent():
    from logosai.simple_agent import SimpleAgent

    class FailAgent(SimpleAgent):
        async def process(self, query, context=None):
            raise ValueError("boom")

    return FailAgent()


def _answer(res):
    return res.content.get("answer") if hasattr(res, "content") else None


# ── 래핑 여부 ──

def test_o1_subclass_process_is_auto_wrapped():
    """O-1 서브클래스 process 자동 래핑"""
    MyAgent = _my_agent_cls()
    assert getattr(MyAgent.__dict__.get("process"), "_logos_observed", False) is True


# ── enabled + standalone ──

def test_o2_process_result_unchanged():
    """O-2 process 결과 불변"""
    assert _answer(run(_my_agent_cls()().process("hi"))) == "ok:hi"


def test_o3_standalone_emits_one_successful_execution():
    """O-3 standalone → execution emit"""
    run(_my_agent_cls()().process("hi"))
    assert len(_REC["exec"]) == 1, f"execution emit {len(_REC['exec'])}건 (1건이어야 한다)"
    assert _REC["exec"][0]["success"] is True


def test_o4_span_started():
    """O-4 span 시작됨"""
    run(_my_agent_cls()().process("hi"))
    assert _REC["span"] >= 1


# ── opt-out ──

def test_o5_env_false_suppresses_emit(monkeypatch):
    """O-5 env false → emit 없음"""
    monkeypatch.setenv("LOGOSAI_AUTO_OBSERVE", "false")
    res = run(_my_agent_cls()().process("x"))
    assert len(_REC["exec"]) == 0
    assert _answer(res) == "ok:x"   # 대조군: process 는 실제로 돌았다


def test_o6_agent_attr_false_suppresses_emit():
    """O-6 _auto_observe=False → emit 없음"""
    a = _my_agent_cls()()
    a._auto_observe = False
    res = run(a.process("y"))
    assert len(_REC["exec"]) == 0
    assert _answer(res) == "ok:y"   # 대조군: process 는 실제로 돌았다


# ── fire-and-forget: emit raise 해도 process 정상 ──

def test_o7_emit_failure_does_not_break_process():
    """O-7 emit 실패해도 process 정상 반환"""
    _REC["raise"] = True
    res = run(_my_agent_cls()().process("z"))
    assert hasattr(res, "content") and res.content.get("answer") == "ok:z"


# ── 실패 케이스: process 예외 → success False emit + 예외 전파 ──

def test_o8_process_exception_propagates():
    """O-8 process 예외 전파 유지"""
    raised = False
    try:
        run(_fail_agent().process("q"))
    except ValueError:
        raised = True
    assert raised


def test_o9_failure_is_emitted_as_unsuccessful_execution():
    """O-9 실패도 execution emit(success False)"""
    try:
        run(_fail_agent().process("q"))
    except ValueError:
        pass
    assert len(_REC["exec"]) == 1, f"execution emit {len(_REC['exec'])}건 (1건이어야 한다)"
    assert _REC["exec"][0]["success"] is False


# ── 부모 trace 존재 → execution 이중 emit 안 함 ──

def test_o10_parent_trace_suppresses_execution_emit():
    """O-10 부모 trace 있으면 execution emit 생략(ACP 소유)"""
    from logosai.utils.trace_span import TraceSpan
    a = _my_agent_cls()()
    parent = TraceSpan.start(name="test.parent", agent_id="acp")
    try:
        res = run(a.process("nested"))
    finally:
        parent.end()
    assert len(_REC["exec"]) == 0
    assert _answer(res) == "ok:nested"   # 대조군: process 는 실제로 돌았다


# ── 이중 서브클래싱 → 이중 emit 없음 ──

def test_o11_inherited_subclass_emits_once():
    """O-11 상속 서브클래스 이중 emit 없음"""
    MyAgent = _my_agent_cls()

    class ChildAgent(MyAgent):  # process 재정의 안 함 → 상속(이미 래핑됨)
        pass

    run(ChildAgent().process("c"))
    assert len(_REC["exec"]) == 1


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
