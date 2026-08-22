"""opt-in 플래그는 값을 본다 — 존재만 보면 off 가 on 이 된다 (2026-08-22).

무엇이 있었나
────────────
`LOGOSAI_CONTINUOUS_IMPROVE=false` 로 지속 개선 루프를 껐는데 재기동 후에도
`Continuous Improvement: started` 가 찍혔다. 게이트가 이랬다:

    if not os.environ.get("LOGOSAI_CONTINUOUS_IMPROVE"):
        return

**존재만 보고 값을 안 본다.** `"false"` 는 비지 않은 문자열이라 참이고,
따라서 **끄려고 쓴 값이 켜는 값**이 된다. docstring 에는 "only runs when
LOGOSAI_CONTINUOUS_IMPROVE=true" 라고 적혀 있었다 — 문서와 코드가 갈렸다.

왜 이게 위험한가
──────────────
이 루프는 이날 프로덕션 에이전트를 망가뜨린 당사자다. 성공 신호가 상수 True
이던 동안 약한 에이전트를 못 찾아 잠들어 있다가, 신호를 살리자 곧바로 대상을
찾아 `summarization_agent` 에 *"For demonstration purposes, let's define dummy
classes"* 를 주입했다(구문은 통과해서 파이프라인이 받아들였다).

즉 **안전 플래그의 off 가 동작하지 않는 상태**였다. 끄는 방법이 "변수를 지우는
것"뿐이라면 그건 플래그가 아니다.

판정은 `pulse_client._truthy` 하나를 쓴다 — 세 번째 사본을 만들지 않는다.

직접 실행: python tests/test_env_flag_semantics.py
"""

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logosai.utils.pulse_client import _truthy  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: 값으로 판정해야 하는 opt-in 안전 플래그. 존재만 보면 off 가 on 이 된다.
GATED_FLAGS = (
    "LOGOSAI_CONTINUOUS_IMPROVE",
    "LOGOSAI_SELF_EVAL",
    "FORGE_ENABLE_SELF_HEALING",
    "ACP_AUTH_ENFORCE",
    "FORGE_VIA_API",
    "FORGE_COLLAB_EVOLUTION",
)

#: 검사할 프로덕션 소스 (테스트는 제외 — 테스트는 일부러 값을 흉내낸다).
SCAN_DIRS = (
    os.path.join(_ROOT, "acp_server", "acp_modules"),
    os.path.join(_ROOT, "logosai", "logosai"),
    os.path.join(_ROOT, "logos_api", "app"),
)


def test_truthy_accepts_the_documented_on_values():
    for v in ("1", "true", "TRUE", "True", "yes", "on", " true "):
        os.environ["__flag_probe__"] = v
        assert _truthy("__flag_probe__"), f"{v!r} 를 on 으로 읽지 못했다"
    os.environ.pop("__flag_probe__", None)


def test_truthy_rejects_off_values():
    """이게 핵심이다 — 'false' 로 껐는데 켜지면 안 된다."""
    for v in ("false", "False", "0", "no", "off", "", "  "):
        os.environ["__flag_probe__"] = v
        assert not _truthy("__flag_probe__"), f"{v!r} 를 on 으로 읽었다 — off 가 동작하지 않는다"
    os.environ.pop("__flag_probe__", None)


def test_unset_is_off():
    os.environ.pop("__flag_probe_unset__", None)
    assert not _truthy("__flag_probe_unset__")


def _presence_only_checks(tree):
    """`os.environ.get(FLAG)` / `os.getenv(FLAG)` 가 **비교 없이** 쓰인 곳.

    ⚠️ 트리를 **인자로 받는다**. 처음엔 이 함수가 파일을 다시 파싱했는데,
    그러면 아래 `wrapped` 가 모은 노드와 **다른 객체**가 나와 `id()` 비교가
    영원히 어긋난다 — 값을 제대로 보는 `acp_auth.is_enforced()` 가 오탐으로
    잡혔다. 하마터면 멀쩡한 보안 게이트를 '고칠' 뻔했다.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "attr", "") or getattr(fn, "id", "")
        if name not in ("get", "getenv"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        flag = node.args[0].value
        if flag not in GATED_FLAGS:
            continue
        # 이 Call 이 비교/메서드체인 안에 감싸여 있으면 값을 보는 것이다.
        # 감싸이지 않고 그대로 조건이면 존재만 보는 것.
        found.append((flag, node.lineno, node))
    return found


def test_no_production_gate_reads_presence_only():
    """존재만 보는 게이트가 남아 있으면 그 플래그는 off 를 지원하지 않는다."""
    offenders = []
    for d in SCAN_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            if "test" in root:
                continue
            for fn in files:
                if not fn.endswith(".py") or fn.startswith("test_"):
                    continue
                path = os.path.join(root, fn)
                with open(path, encoding="utf-8") as f:
                    src = f.read()
                try:
                    tree = ast.parse(src)
                except SyntaxError:
                    continue
                # 값을 보는 표현(비교·lower()·in)에 감싸인 Call 을 모아 둔다
                wrapped = set()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Compare, ast.Attribute)):
                        for sub in ast.walk(node):
                            if isinstance(sub, ast.Call):
                                wrapped.add(id(sub))
                for flag, lineno, call in _presence_only_checks(tree):
                    if id(call) not in wrapped:
                        rel = os.path.relpath(path, _ROOT)
                        offenders.append(f"{rel}:{lineno} ({flag})")

    assert not offenders, (
        "값을 보지 않고 존재만 보는 안전 플래그 게이트 — off 로 끌 수 없다:\n  "
        + "\n  ".join(offenders)
    )


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  ❌ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
