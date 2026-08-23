"""테스트가 프로덕션 관측 시스템을 오염시키지 못하게 한다 (2026-08-09).

실측 사고: 어제 작성한 `test_forge_trace_propagation.py` 가
`TraceSpan.start("orchestrator.stream_with_orchestrator", ...)` 를 호출했고,
그 span 25건이 **실제 Pulse DB** 에 들어갔다. 지문:

    duration 0.012ms · input_text='' · metadata={} · parent 없음 · 자기 trace 안에 혼자
    created_at 이 start_time 보다 7분 늦음  ← 스풀 재전송

그 탓에 (1) 여정 화면에서 "ingress 가 유실된 trace" 로 오독됐고,
(2) "pytest 오염 아님" 이라는 소거 실험이 틀렸다 — 스풀이 7분 뒤 배달해서
즉시 측정에 안 잡혔다.

`LOGOS_PULSE_DISABLED` 스위치는 2026-08-02 에 이미 있었다. 문제는 **사람이
켜야 했다는 것**이다. 여기서는 테스트 실행이 감지되면 기본으로 막고,
명시적 opt-in 으로만 푼다 — 잊을 수 있는 방어는 방어가 아니다.
"""

import ast
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logosai.utils import pulse_client as pc  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]

# 프로덕션 span 방출 지점을 담은 저장소. 없으면 건너뛴다
# (logosai 는 public repo 라 단독 clone 에서도 통과해야 한다).
PROD_DIRS = [
    REPO_ROOT / "logosai" / "logosai",
    REPO_ROOT / "acp_server" / "acp_modules",
    REPO_ROOT / "acp_server" / "agents",
    REPO_ROOT / "logos_api" / "app",
    REPO_ROOT / "ontology" / "orchestrator",
    REPO_ROOT / "ontology" / "core",
    REPO_ROOT / "forge" / "core",
]

TEST_DIRS = [
    REPO_ROOT / "logosai" / "tests",
    REPO_ROOT / "acp_server" / "tests",
    REPO_ROOT / "logos_api" / "tests",
    REPO_ROOT / "ontology" / "tests",
    REPO_ROOT / "forge" / "tests",
]

# 방출 지점이지만 stage 를 못 정하는 곳. 비워 둔다 — 예외를 만들려면
# 여기 이름과 이유를 적어야 하므로, 조용히 빠지는 일이 없다.
STAGE_EXEMPT: dict = {}


# ── 정적 스캐너 ─────────────────────────────────────────────────────

class _Boom:
    """import 되면 즉시 터지는 가짜 aiohttp — 네트워크를 탔는지 감지한다."""

    def ClientSession(self, *a, **k):  # noqa: N802
        raise AssertionError("차단됐어야 하는데 네트워크를 탔다")


def _iter_py(dirs):
    for d in dirs:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if "_backups" in p.parts or ".venv" in p.parts:
                continue
            yield p


def _span_calls(path: Path):
    """(함수명, name 인자 리터럴 or None, kwargs 집합, lineno) 를 낸다."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr in ("start", "record")):
            continue
        if not (isinstance(f.value, ast.Name) and f.value.id == "TraceSpan"):
            continue
        kwargs = {kw.arg for kw in node.keywords if kw.arg}
        name = None
        for kw in node.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                name = kw.value.value
        if name is None and node.args and isinstance(node.args[0], ast.Constant):
            name = node.args[0].value
        yield (f.attr, name, kwargs, node.lineno)


def _production_span_names() -> set:
    names = set()
    for p in _iter_py(PROD_DIRS):
        if p.name.startswith("test_") or "tests" in p.parts:
            continue
        for _fn, name, _kw, _ln in _span_calls(p):
            if isinstance(name, str) and name:
                names.add(name)
    return names


# ── ① 전송 격리 ─────────────────────────────────────────────────────

def _run_post(endpoint="/api/v1/ingest/__isolation_probe__", data=None):
    """_post 를 돌리고 '네트워크를 탔는가' 를 돌려준다.

    _post 는 예외를 삼키고 실패로 집계하므로, 실패 카운터의 증가로 판정한다.
    기본 endpoint 는 **스풀 대상이 아닌 것**을 쓴다 — opt-in 경로에서 실패가
    스풀에 남으면 나중에 재전송돼, 막으려던 그 오염이 된다.
    """
    saved = sys.modules.get("aiohttp")
    sys.modules["aiohttp"] = _Boom()
    before = pc._stats["failed"]
    try:
        asyncio.run(pc._post(endpoint, data or {}))
    finally:
        if saved is None:
            sys.modules.pop("aiohttp", None)
        else:
            sys.modules["aiohttp"] = saved
    return pc._stats["failed"] > before


def test_blocked_by_default_when_running_under_pytest():
    """사람이 env 를 켜지 않아도 막힌다 — 어제 그걸 잊어서 25건이 샜다."""
    os.environ.pop("LOGOS_PULSE_DISABLED", None)
    os.environ.pop("LOGOSAI_PULSE_ALLOW_IN_TESTS", None)
    assert not _run_post(), "테스트 실행 중인데 전송을 시도했다"


def test_explicit_optin_allows_sending():
    """Pulse 전송 자체를 검증하는 테스트는 명시적으로 풀 수 있어야 한다."""
    os.environ.pop("LOGOS_PULSE_DISABLED", None)
    os.environ["LOGOSAI_PULSE_ALLOW_IN_TESTS"] = "1"
    try:
        assert _run_post(), "opt-in 했는데도 막혔다"
    finally:
        os.environ.pop("LOGOSAI_PULSE_ALLOW_IN_TESTS", None)


def test_explicit_disable_still_wins():
    """기존 스위치(2026-08-02)를 깨지 않는다."""
    os.environ["LOGOS_PULSE_DISABLED"] = "1"
    os.environ["LOGOSAI_PULSE_ALLOW_IN_TESTS"] = "1"
    try:
        assert not _run_post(), "명시적 차단이 opt-in 에 밀렸다"
    finally:
        os.environ.pop("LOGOS_PULSE_DISABLED", None)
        os.environ.pop("LOGOSAI_PULSE_ALLOW_IN_TESTS", None)


def test_blocked_send_leaves_no_spool():
    """스풀에 쌓이면 나중에 재전송돼 같은 오염이 된다 — 실제로 7분 뒤 도착했다."""
    os.environ.pop("LOGOS_PULSE_DISABLED", None)
    os.environ.pop("LOGOSAI_PULSE_ALLOW_IN_TESTS", None)
    spool = Path(pc._SPOOL_PATH)
    before = spool.stat().st_size if spool.exists() else -1
    # 반드시 **스풀 대상** endpoint 로 시험한다 — 아니면 이 테스트는 공허하다
    assert "/api/v1/ingest/span" in pc._SPOOLABLE
    _run_post("/api/v1/ingest/span")
    after = spool.stat().st_size if spool.exists() else -1
    assert after == before, "차단됐는데 스풀에 쌓였다"


# ── ② 테스트가 프로덕션 span 이름을 쓰지 못한다 ──────────────────────

def test_tests_do_not_reuse_production_span_names():
    """이름이 겹치면 진짜 신호와 구분할 수 없다.

    전송이 막혀도 이 계약은 남긴다 — opt-in 으로 푼 순간 다시 새기 때문이다.
    일반 이름("a", "부모")은 겹치지 않으므로 걸리지 않는다.
    """
    prod = _production_span_names()
    assert prod, "프로덕션 span 이름을 하나도 못 찾았다 — 스캐너가 고장났다"
    offenders = []
    for p in _iter_py(TEST_DIRS):
        for _fn, name, _kw, ln in _span_calls(p):
            if isinstance(name, str) and name in prod:
                offenders.append(f"{p.relative_to(REPO_ROOT)}:{ln} → {name!r}")
    assert not offenders, "테스트가 프로덕션 span 이름을 쓴다:\n  " + "\n  ".join(offenders)


# ── ③ 방출 지점은 stage 를 선언한다 ─────────────────────────────────

def test_all_production_span_sites_declare_stage():
    """stage 없는 span 은 여정에서 '미분류' 로 떨어진다.

    실측: forge_bridge(forge.negotiation) / collaborative_evolution(forge.collaboration)
    두 곳이 누락돼 있었다 — logos_api 쪽 같은 이름만 고치고 ACP 쪽을 놓쳤다.
    """
    missing = []
    for p in _iter_py(PROD_DIRS):
        if p.name.startswith("test_") or "tests" in p.parts:
            continue
        for _fn, name, kwargs, ln in _span_calls(p):
            rel = f"{p.relative_to(REPO_ROOT)}:{ln}"
            if rel in STAGE_EXEMPT:
                continue
            if "stage" not in kwargs:
                missing.append(f"{rel} → {name or '(동적 이름)'}")
    assert not missing, "stage 를 선언하지 않는 span 방출 지점:\n  " + "\n  ".join(missing)


# ── ④ 테스트가 env 를 프로세스 전역으로 흘리지 않는다 ─────────────────

_LEAKY_ENVS = ("LOGOS_PULSE_DISABLED", "LOGOSAI_PULSE_ALLOW_IN_TESTS")


def test_tests_do_not_leak_pulse_env_globally():
    """`os.environ[...] = ...` 는 되돌려지지 않고 프로세스 전역에 남는다.

    실측: 3개 파일이 import 시점에 `LOGOS_PULSE_DISABLED=1` 을 세워 다른 파일의
    전송 검증 테스트 8건이 **전체 스위트에서만** 죽어 있었다 (파일 단독 실행은
    통과 → 오래 안 보임). 허용 형태는 `monkeypatch.setenv` 또는
    `if "pytest" not in sys.modules:` 로 가둔 직접 실행 경로뿐이다.
    """
    offenders = []
    for p in _iter_py(TEST_DIRS):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for t in node.targets:
                if not (isinstance(t, ast.Subscript)
                        and isinstance(t.value, ast.Attribute)
                        and t.value.attr == "environ"):
                    continue
                key = t.slice.value if isinstance(t.slice, ast.Constant) else None
                if key not in _LEAKY_ENVS:
                    continue
                seg = ast.get_source_segment(p.read_text(encoding="utf-8"), node) or ""
                # 직접 실행 경로(`__main__`)나 pytest 가드 안이면 허용 — 줄 앞의
                # 들여쓰기가 있으면 어떤 블록 안이라는 뜻이다
                line = p.read_text(encoding="utf-8").splitlines()[node.lineno - 1]
                if line.startswith(" ") or line.startswith("\t"):
                    continue
                offenders.append(f"{p.relative_to(REPO_ROOT)}:{node.lineno} → {key}")
    assert not offenders, ("테스트가 Pulse env 를 전역으로 세운다:\n  "
                           + "\n  ".join(offenders))


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = f = 0
    for k, fn in fns:
        try:
            fn()
            print(f"  ✓ {k}")
            p += 1
        except Exception as e:
            print(f"  ✗ {k}: {type(e).__name__}: {e}")
            f += 1
    print(f"\npass={p} fail={f}")
    sys.exit(1 if f else 0)
