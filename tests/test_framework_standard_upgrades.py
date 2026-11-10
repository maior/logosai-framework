"""Phase 1 표준 준비도 업그레이드 테스트 (2026-07-06).

전문가 진단(logosai-framework-standard-readiness) Phase 1 의 저위험 3건:
  G1 — SimpleACPServer.add() 가 _agent_registry 주입 (call_agent standalone 작동)
  G4 — py.typed 마커 존재 (타입 배포)
  G5 — 버전 단일 소스 (__init__ 0.10.0 vs pyproject 0.11.2 불일치 해소)

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가 0건을 수집했다.
  - 직접 실행: python tests/test_framework_standard_upgrades.py  → 마지막 줄 `RESULT: GREEN`
"""
import os
import re
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # logosai/ (repo)
if __name__ == "__main__":      # 스크립트 모드에서만 — pytest 는 pyproject 의 pythonpath 를 쓴다
    sys.path.insert(0, _PKG)

from _script_runner import block_pulse, run_tests  # noqa: E402


def _setup(mp):
    block_pulse(mp)


def _teardown():
    pass


def _version():
    import logosai
    return getattr(logosai, "__version__", None)


def _pyproject_version():
    pyproj = open(os.path.join(_PKG, "pyproject.toml"), encoding="utf-8").read()
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproj, re.M)
    return m.group(1) if m else None


def _fallback_literal():
    init_src = open(os.path.join(_PKG, "logosai", "__init__.py"), encoding="utf-8").read()
    fm = re.search(r'__version__\s*=\s*"([^"]+)"', init_src)
    return fm.group(1) if fm else None


# ── G4: py.typed 마커 ──

def test_g4_py_typed_marker_exists():
    """G4 py.typed 마커 존재"""
    assert os.path.isfile(os.path.join(_PKG, "logosai", "py.typed"))


# ── G5: 버전 단일 소스 (0.10.0 아님, pyproject와 일치) ──

def test_g5_version_attribute_exists():
    """G5 __version__ 존재"""
    ver = _version()
    assert isinstance(ver, str) and ver


def test_g5_hardcoded_0_10_0_drift_is_gone():
    """G5 하드코딩 0.10.0 drift 해소"""
    # 핵심: 하드코딩 stale "0.10.0" drift 해소. 이제 metadata(설치본, 권위본) →
    # pyproject 폴백 순으로 단일 소스에서 온다.
    ver = _version()
    assert isinstance(ver, str) and ver     # 대조군: 값이 있다 (None != "0.10.0" 은 공허하게 참)
    assert ver != "0.10.0"


def test_g5_version_is_semver_like():
    """G5 유효한 버전 문자열 (semver)"""
    assert re.match(r"^\d+\.\d+", _version())


def test_g5_version_matches_single_source():
    """G5 버전이 단일 소스와 일치 (metadata|pyproject)"""
    # 설치 메타데이터가 있으면 그것과 일치(단일 소스), 없으면 pyproject 폴백값과 일치
    try:
        from importlib.metadata import version as _mv
        meta_ver = _mv("logosai")
    except Exception:  # noqa: BLE001 — 미설치(dev/sdist) 환경
        meta_ver = None
    expected = meta_ver or _pyproject_version()
    assert expected, "비교할 단일 소스(metadata·pyproject)를 하나도 못 읽었다"
    assert _version() == expected


# ── P1-3: fallback 리터럴 drift-lock ──
# metadata 미설치(dev/sdist) 경로에서 쓰이는 __init__ 하드코딩 폴백이
# pyproject 와 어긋나면, 미설치 환경에서 stale 버전을 보고한다. 잠근다.

def test_p1_3_init_fallback_literal_exists():
    """P1-3 __init__ 폴백 리터럴 존재"""
    assert _fallback_literal()


def test_p1_3_fallback_literal_equals_pyproject():
    """P1-3 폴백 리터럴 == pyproject (drift 없음)"""
    assert _pyproject_version(), "pyproject 에서 version 을 못 읽었다"   # None == None 방지
    assert _fallback_literal() == _pyproject_version()


# ── G1: SimpleACPServer.add() registry 주입 ──

def _server_with_two_agents():
    from logosai.acp import SimpleACPServer
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse

    class _A(SimpleAgent):  # config optional — 바이브코딩 경로
        async def handle(self, query, context=None):
            return AgentResponse.success(content={"answer": "ok"})

    srv = SimpleACPServer(port=9911)    # 객체만 만든다 — 포트를 열지 않는다
    a = _A()
    srv.add(a, "agent_a")
    b = _A()
    srv.add(b, "agent_b")
    return srv, a, b


def test_g1_add_injects_agent_registry():
    """G1 add() → _agent_registry 주입"""
    srv, a, _ = _server_with_two_agents()
    assert getattr(a, "_agent_registry", None) is srv.agents


def test_g1_sibling_lookup_through_registry():
    """G1 registry 로 형제 조회 가능"""
    _, a, b = _server_with_two_agents()
    assert a._agent_registry.get("agent_b") is b


def test_g1_acp_server_reference_injected():
    """G1 _acp_server 참조 주입"""
    srv, a, _ = _server_with_two_agents()
    assert getattr(a, "_acp_server", None) is srv


# ══ pytest 배선 ═══════════════════════════════════════════════════════════

if "pytest" in sys.modules:
    import pytest

    @pytest.fixture(autouse=True)
    def _env(monkeypatch):
        _setup(monkeypatch)
        yield
        monkeypatch.undo()
        _teardown()


def main():
    return run_tests(globals(), setup=_setup, teardown=_teardown)


if __name__ == "__main__":
    sys.exit(main())
