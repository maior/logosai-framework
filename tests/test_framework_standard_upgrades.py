"""Phase 1 표준 준비도 업그레이드 테스트 (2026-07-06).

전문가 진단(logosai-framework-standard-readiness) Phase 1 의 저위험 3건:
  G1 — SimpleACPServer.add() 가 _agent_registry 주입 (call_agent standalone 작동)
  G4 — py.typed 마커 존재 (타입 배포)
  G5 — 버전 단일 소스 (__init__ 0.10.0 vs pyproject 0.11.2 불일치 해소)

직접 실행:
    python logosai/tests/test_framework_standard_upgrades.py
"""
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # logosai/ (repo)
sys.path.insert(0, _PKG)


def main():
    fails = []

    def t(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # ── G4: py.typed 마커 ──
    py_typed = os.path.join(_PKG, "logosai", "py.typed")
    t("G4 py.typed 마커 존재", os.path.isfile(py_typed))

    # ── G5: 버전 단일 소스 (0.10.0 아님, pyproject와 일치) ──
    import re
    import logosai
    ver = getattr(logosai, "__version__", None)
    t("G5 __version__ 존재", isinstance(ver, str) and ver)
    # 핵심: 하드코딩 stale "0.10.0" drift 해소. 이제 metadata(설치본, 권위본) →
    # pyproject 폴백 순으로 단일 소스에서 온다.
    t("G5 하드코딩 0.10.0 drift 해소", ver != "0.10.0")
    t("G5 유효한 버전 문자열 (semver)", bool(re.match(r"^\d+\.\d+", ver)))
    # 설치 메타데이터가 있으면 그것과 일치(단일 소스), 없으면 pyproject 폴백값과 일치
    pyproj = open(os.path.join(_PKG, "pyproject.toml")).read()
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproj, re.M)
    pyproj_ver = m.group(1) if m else None
    try:
        from importlib.metadata import version as _mv
        meta_ver = _mv("logosai")
    except Exception:
        meta_ver = None
    expected = meta_ver or pyproj_ver
    t("G5 버전이 단일 소스와 일치 (metadata|pyproject)", ver == expected)

    # ── G1: SimpleACPServer.add() registry 주입 ──
    from logosai.acp import SimpleACPServer
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse

    class _A(SimpleAgent):  # config optional — 바이브코딩 경로
        async def handle(self, query, context=None):
            return AgentResponse.success(content={"answer": "ok"})

    srv = SimpleACPServer(port=9911)
    a = _A()
    aid = srv.add(a, "agent_a")
    b = _A()
    srv.add(b, "agent_b")

    t("G1 add() → _agent_registry 주입", getattr(a, "_agent_registry", None) is srv.agents)
    t("G1 registry 로 형제 조회 가능", a._agent_registry.get("agent_b") is b)
    t("G1 _acp_server 참조 주입", getattr(a, "_acp_server", None) is srv)

    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
