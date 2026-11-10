"""하네스 에이전트별 재정의 훅 (2026-08-03).

왜 필요한가 — 30일 실측에서 한도에 근접한 상위 4개가 전부 데스크톱·문서 계열이다
(desktop_agent 101.8s = 한도의 84.8%, docx_generator 94.0s, file_agent 81.7s).
PowerPoint 를 몰고 Word 를 만드는 일은 **본성상 느리다.** 반면 calculator 는 1초에
끝나면서 같은 120초를 배정받는다. 성격이 다른 121개가 한 개의 전역 한도를 공유하는
것이 문제였고, 그래서 **에이전트별 재정의 계층**을 연다.

계약 (docs/tracks.md §1·§2 동결):

    agent._harness is False   → 미적용        (코드 opt-out 이 절대 우선)
    env LOGOSAI_HARNESS=off   → 미적용
    agent._harness 값          → 그 값         ← 코드가 왕
    ★ override resolver        → 그 값         ← 운영자 계층 (이번에 신설)
    env LOGOSAI_HARNESS_*     → 그 값
    기본값 120s / 25호출 / 200000토큰

`logosai` 는 저장소도 HTTP 도 모른다. 훅만 노출하고, 호스트(ACP)가 자기 저장소로
구현을 꽂는다 — 이 저장소의 확립된 "Judge ABC = 교체 이음새" 패턴과 같다.

⚠️ 이 훅은 **절대 실행을 막지 않는다.** resolver 가 죽으면 재정의만 없던 일이
되고 실행은 그대로 간다. 저장소 장애가 에이전트를 멈추면 안 된다.

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나 (32건). 예전엔 `main()` 하나뿐이라 pytest 가
    **0건을 수집**했고, 회귀가 자동으로 잡히지 않았다.
  - 직접 실행: python tests/test_harness_override.py  → 마지막 줄 `✅ 전부 통과`

import 시점에 프로세스 전역을 건드리지 않는다. env 는 monkeypatch 로, resolver
(모듈 전역)는 `_teardown` 이 매 테스트 뒤 해제한다.
"""
import asyncio
import inspect
import os
import sys

_HARNESS_ENV = ("LOGOSAI_HARNESS", "LOGOSAI_HARNESS_TIMEOUT",
                "LOGOSAI_HARNESS_MAX_CALLS", "LOGOSAI_HARNESS_MAX_TOKENS")

# ── 8. 쓰레기 값 — 저장소가 오염돼도 실행 한도가 이상해지면 안 된다 ──
_BAD_TIMEOUT = ({"timeout_s": 0}, {"timeout_s": -5}, {"timeout_s": "삼백"},
                {"timeout_s": None}, {}, "문자열", 42, [])
_BAD_BUDGET = ({"max_llm_calls": 0}, {"max_llm_calls": -1},
               {"max_llm_calls": "다섯"}, {"max_tokens": None})

# pytest_generate_tests / 스크립트 러너가 함께 쓰는 매개변수 표.
_PARAMS = {"bad_timeout": _BAD_TIMEOUT, "bad_budget": _BAD_BUDGET}


class _Agent:
    """최소 에이전트 — resolve_* 가 보는 것은 `_harness` 와 `id` 뿐이다."""

    def __init__(self, agent_id="test_agent", harness=None):
        self.id = agent_id
        if harness is not None:
            self._harness = harness


def _obs():
    import logosai.observability as obs
    return obs


def _setup(mp):
    """테스트 하나의 환경. `mp` = pytest monkeypatch 또는 `_ScriptPatch` — 끝나면 전부 되돌려진다."""
    for k in _HARNESS_ENV + ("LOGOSAI_PULSE_ALLOW_IN_TESTS",):
        mp.delenv(k, raising=False)
    # 관측 DB 에 테스트 흔적을 남기지 않는다 (이 저장소의 확립된 규칙).
    mp.setenv("LOGOS_PULSE_DISABLED", "1")
    _obs().set_harness_override_resolver(None)


def _teardown():
    # resolver 는 모듈 전역이다 — 남기면 다른 파일의 한도 계산이 조용히 바뀐다.
    _obs().set_harness_override_resolver(None)


def _resolver(fn):
    _obs().set_harness_override_resolver(fn)


def _timeout(agent=None):
    return _obs().resolve_harness(agent if agent is not None else _Agent())


def _budget(agent=None):
    return _obs().resolve_harness_budget(agent if agent is not None else _Agent())


# ── 1. 미등록 = 현재 동작 그대로 (회귀 0) ───────────────────

def test_unregistered_default_timeout_120s():
    """미등록이면 기본 120초"""
    assert _timeout() == (True, 120.0)


def test_unregistered_default_budget_25_calls_200000_tokens():
    """미등록이면 기본 예산 25/200000"""
    assert _budget() == (25, 200000)


# ── 2. 재정의가 env·기본값을 이긴다 ─────────────────────────

def test_override_timeout_beats_default():
    """재정의 300초가 기본값을 이김"""
    _resolver(lambda aid: {"timeout_s": 300})
    assert _timeout() == (True, 300.0)


def test_override_timeout_beats_env(monkeypatch):
    """재정의가 env(60) 를 이김"""
    _resolver(lambda aid: {"timeout_s": 300})
    monkeypatch.setenv("LOGOSAI_HARNESS_TIMEOUT", "60")
    assert _timeout() == (True, 300.0)


# ── 3. 코드가 왕 — _harness 가 재정의를 이긴다 ───────────────

def test_code_harness_number_beats_override():
    """코드 _harness=90 이 재정의 300 을 이김"""
    _resolver(lambda aid: {"timeout_s": 300})
    assert _timeout(_Agent(harness=90)) == (True, 90.0)


def test_code_harness_dict_beats_override():
    """코드 _harness dict 도 재정의를 이김"""
    _resolver(lambda aid: {"timeout_s": 300})
    assert _timeout(_Agent(harness={"timeout_s": 45})) == (True, 45.0)


# ── 4. opt-out 은 재정의로 뚫리지 않는다 ────────────────────
# 재정의로 하네스를 되살릴 수 있으면 코드의 명시적 거부가 무의미해진다.

def test_harness_false_not_revived_by_override():
    """_harness=False 는 재정의가 있어도 미적용"""
    _resolver(lambda aid: {"timeout_s": 300})
    assert _timeout(_Agent(harness=False)) == (False, 0.0)


def test_env_off_not_revived_by_override(monkeypatch):
    """env off 는 재정의가 있어도 미적용"""
    _resolver(lambda aid: {"timeout_s": 300})
    monkeypatch.setenv("LOGOSAI_HARNESS", "off")
    assert _timeout() == (False, 0.0)


# ── 5. resolver 가 죽어도 실행은 간다 (fail-open, 재정의만 무시) ──

def _boom(aid):
    raise RuntimeError("저장소 장애")


def test_resolver_exception_falls_back_to_default_timeout():
    """resolver 예외 → 삼키고 기본값"""
    _resolver(_boom)
    assert _timeout() == (True, 120.0)


def test_resolver_exception_falls_back_to_default_budget():
    """resolver 예외 → 예산도 기본값"""
    _resolver(_boom)
    assert _budget() == (25, 200000)


def test_resolver_returning_none_falls_back_to_default():
    """resolver None → 기본값"""
    _resolver(lambda aid: None)
    assert _timeout() == (True, 120.0)


# ── 6. 예산도 같은 우선순위 ─────────────────────────────────

def test_override_budget_applied():
    """재정의 예산 40/400000"""
    _resolver(lambda aid: {"max_llm_calls": 40, "max_tokens": 400000})
    assert _budget() == (40, 400000)


def test_override_budget_beats_env(monkeypatch):
    """재정의 예산이 env(10) 를 이김"""
    _resolver(lambda aid: {"max_llm_calls": 40, "max_tokens": 400000})
    monkeypatch.setenv("LOGOSAI_HARNESS_MAX_CALLS", "10")
    assert _budget()[0] == 40


def test_code_harness_budget_beats_override():
    """코드 _harness 예산이 재정의를 이김"""
    _resolver(lambda aid: {"max_llm_calls": 40})
    assert _budget(_Agent(harness={"max_llm_calls": 5}))[0] == 5


# ── 7. 부분 재정의 — 준 것만 바뀐다 ─────────────────────────

def test_timeout_only_override_leaves_budget_default():
    """timeout 만 재정의하면 예산은 기본값"""
    _resolver(lambda aid: {"timeout_s": 300})
    assert _budget() == (25, 200000)


def test_budget_only_override_leaves_timeout_default():
    """예산만 재정의하면 timeout 은 기본값"""
    _resolver(lambda aid: {"max_tokens": 400000})
    assert _timeout() == (True, 120.0)


# ── 8. 쓰레기 값은 무시하고 다음 단계로 ─────────────────────

def test_garbage_timeout_override_ignored(bad_timeout):
    """쓰레기 재정의 {bad_timeout!r} 는 무시"""
    _resolver(lambda aid, b=bad_timeout: b)
    assert _timeout() == (True, 120.0)


def test_garbage_budget_override_ignored(bad_budget):
    """쓰레기 예산 재정의 {bad_budget!r} 는 무시"""
    _resolver(lambda aid, b=bad_budget: b)
    assert _budget() == (25, 200000)


# ── 9. resolver 가 받는 id = span 에 기록되는 id ────────────
# 이게 어긋나면 운영자는 'desktop_agent' 에 재정의를 걸고, resolver 는
# 'DesktopAgent' 를 찾다 못 찾는다. 조용히 안 먹는 가장 나쁜 실패다.

class DesktopAgent:  # id 속성이 없는 경우
    pass


def _seen_ids(agent):
    seen = []
    _resolver(lambda aid: seen.append(aid) or None)
    _timeout(agent)
    return seen


def test_resolver_receives_agent_id():
    """resolver 는 agent.id 를 받는다"""
    seen = _seen_ids(_Agent(agent_id="desktop_agent"))
    assert seen and seen[-1] == "desktop_agent"


def test_resolver_receives_class_name_when_no_id():
    """id 없으면 클래스명"""
    seen = _seen_ids(DesktopAgent())
    assert seen and seen[-1] == "DesktopAgent"


def test_resolver_id_equals_harness_agent_id():
    """resolver 가 받는 id == harness_agent_id() 결과"""
    a = DesktopAgent()
    seen = _seen_ids(a)
    assert seen and seen[-1] == _obs().harness_agent_id(a)


# ── 10. 해제 가능 (테스트·운영 모두 필요) ───────────────────

def test_unregistering_restores_default():
    """해제하면 기본 동작 복귀"""
    _resolver(lambda aid: {"timeout_s": 300})
    assert _timeout() == (True, 300.0)   # 대조군: 걸려 있었다
    _resolver(None)
    assert _timeout() == (True, 120.0)


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
    print()
    if fails:
        print(f"❌ {len(fails)} FAILED: {fails}")
        return 1
    print("✅ 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
