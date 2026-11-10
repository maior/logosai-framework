"""스크립트 모드 러너 — `python tests/test_x.py` 로도 도는 테스트 파일들의 공용 부품 (2026-11-10).

배경: `tests/test_*.py` 의 상당수가 `def main()` 하나뿐인 스크립트라 pytest 가
0건을 수집했다. 검사를 `test_*` 함수로 꺼내면서도 직접 실행(마지막 줄
`RESULT: GREEN`)은 그대로 살려 두기 위한 최소 부품이다.

  - `ScriptPatch`      pytest `monkeypatch` 의 최소 대역. 세운 것은 `undo()` 로 전부 되돌린다.
  - `run_tests`        모듈의 `test_*` 를 정의 순서대로 찾아 부른다 — 목록을 따로 두지
                       않으므로 테스트를 추가하고 러너에 빠뜨리는 일이 생길 수 없다.
  - `generate_tests`   `pytest_generate_tests` 본문 (매개변수 표를 두 모드가 함께 쓴다).
  - `block_pulse`      테스트가 LogosPulse 로 전송·스풀하지 못하게 막는다.
  - `use_fake_api_keys` 진짜 키가 환경에 있어도 테스트가 그것을 쥐지 못하게 한다.

이 모듈은 import 시점에 프로세스 전역(os.environ·모듈 속성)을 건드리지 않는다.
먼저 변환된 하네스 파일 6개(test_harness_*.py 등)는 같은 러너를 파일 안에 갖고
있다 — 그쪽은 일부러 건드리지 않았다.
"""
import asyncio
import inspect
import os
import pathlib
import sys
import tempfile
import traceback

_FAKE_KEY = "test-key-not-real"
_PROVIDER_KEY_ENVS = (
    "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
)


class ScriptPatch:
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


def block_pulse(mp):
    """LogosPulse 전송을 막고, 막혔는지 확인한다. `mp` = monkeypatch 또는 ScriptPatch."""
    mp.delenv("LOGOSAI_PULSE_ALLOW_IN_TESTS", raising=False)
    mp.setenv("LOGOS_PULSE_DISABLED", "1")
    from logosai.utils import pulse_client

    assert pulse_client._sending_blocked(), (
        "Pulse 전송이 막혀 있지 않다 — 테스트가 관측 DB 를 오염시킨다")
    # 루프 밖에서 부른 배경 전송은 차단 판정 전에 스풀로 간다(pulse_client._fire_and_forget).
    # 스풀은 나중에 진짜 프로세스가 재전송하므로, 테스트가 거기에 쓰지 못하게 막는다.
    mp.setattr(pulse_client, "_spool_append", lambda *a, **k: None)


def use_fake_api_keys(mp):
    """프로바이더 키를 가짜로 덮는다 — 가짜 SDK 가 빠진 경로가 있어도 진짜 호출은 인증에서 죽는다."""
    for key in _PROVIDER_KEY_ENVS:
        mp.setenv(key, _FAKE_KEY)


def run(coro):
    """코루틴 하나를 새 루프에서 끝까지 돌리고 루프를 닫는다."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def generate_tests(metafunc, params):
    """`pytest_generate_tests` 본문 — `params` = {인자 이름: 값 목록}."""
    for key, values in params.items():
        if key in metafunc.fixturenames:
            metafunc.parametrize(key, values, ids=[str(v) for v in values])


def _cases(namespace, params):
    """(라벨, 함수, kwargs) — 라벨은 docstring 첫 줄, 매개변수화된 것은 값마다 편다."""
    for name, fn in list(namespace.items()):
        if not name.startswith("test_") or not inspect.isfunction(fn):
            continue
        label = (fn.__doc__ or name).strip().splitlines()[0]
        key = next((p for p in inspect.signature(fn).parameters if p in params), None)
        if key is None:
            yield label, fn, {}
        else:
            for value in params[key]:
                yield label.format(**{key: value}), fn, {key: value}


def _run_case(fn, kwargs, setup, teardown):
    mp = ScriptPatch()
    tmp = None
    try:
        if setup is not None:
            setup(mp)
        wanted = inspect.signature(fn).parameters
        if "monkeypatch" in wanted:
            kwargs = dict(kwargs, monkeypatch=mp)
        if "tmp_path" in wanted:
            tmp = tempfile.TemporaryDirectory()
            kwargs = dict(kwargs, tmp_path=pathlib.Path(tmp.name))
        result = fn(**kwargs)
        if inspect.iscoroutine(result):
            asyncio.run(result)
        return True
    except AssertionError as e:
        if str(e):
            print("   " + str(e).splitlines()[0])
        return False
    except Exception:  # noqa: BLE001 — 스크립트 모드에서도 한 검사의 예외가 나머지를 가리지 않게
        print("   " + traceback.format_exc().strip().splitlines()[-1])
        return False
    finally:
        mp.undo()
        if tmp is not None:
            tmp.cleanup()
        if teardown is not None:
            teardown()


def run_tests(namespace, setup=None, teardown=None, params=None,
              pass_prefix="PASS ", fail_prefix="FAIL ", blank_before_result=False):
    """`namespace`(보통 `globals()`)의 `test_*` 를 전부 돌리고 종료 코드를 돌려준다.

    순서: setup(mp) → 테스트 → mp.undo() → teardown(). teardown 이 되돌려진 환경을
    보고 캐시를 다시 읽을 수 있도록 undo 가 먼저다.
    """
    fails = []
    for label, fn, kwargs in _cases(namespace, params or {}):
        ok = _run_case(fn, kwargs, setup, teardown)
        print((pass_prefix if ok else fail_prefix) + label)
        if not ok:
            fails.append(label)
    if blank_before_result:
        print()
    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    sys.stdout.flush()
    return 1 if fails else 0
