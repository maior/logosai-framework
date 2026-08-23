"""저자가 스스로 밝힌 껍데기 — 실물 표본으로 검증 (2026-08-22).

이 검사기는 배포를 막는다. 그러므로 **오탐이 곧 개선 차단**이다.
그래서 합성 예제가 아니라 실제 코드베이스로 정밀도를 잰다:
`acp_server/agents` 285파일에서 발화 11파일, 전부 forge_generated 의 진짜
껍데기, 수기 에이전트 0건.

원본 사고: 지속 개선 루프가 summarization_agent 에 더미 클래스를 주입했고
구문이 통과해 기존 게이트 셋(보호 · confidence · Shadow)을 모두 지났다.

직접 실행: python tests/test_stub_detect.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logosai.review.stub_detect import (  # noqa: E402
    self_declared_stub, stub_findings,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_AGENTS = os.path.join(_ROOT, "acp_server", "agents")


# 2026-08-22 18:47 에 지속 개선 루프가 실제로 주입한 코드. 다듬지 않는다.
CORRUPTED = '''\
class SummarizationAgent:
    """텍스트/문서 요약 에이전트"""

    def __init__(self, config):
        # Assuming AgentConfig, AgentType, and LLMClient are defined elsewhere
        # For demonstration purposes, let's define dummy classes:
        self.name = "요약"
'''

CLEAN = '''\
class SummarizationAgent:
    """텍스트/문서 요약 에이전트"""

    def __init__(self, config):
        self.name = config.name if hasattr(config, "name") else "요약 에이전트"
        self.llm_client = LLMClient(provider="google", model="gemini-2.5-flash-lite")
'''

# 리뷰어가 자기 모듈 docstring 에서 사고를 **인용**하는 형태.
# 인용과 자기 진술은 다르다 — 이걸 막지 못하면 리뷰어가 자기를 차단한다.
QUOTING = '''\
"""코드 리뷰 계층.

`forge_generated_387dc0b3.py:76` 은 자기 코드에 "non-functional placeholder"
라고 써 놓고도 등록되어 라이브였다.
"""

def review(code):
    return []
'''


def test_catches_the_actual_injected_code():
    reason = self_declared_stub(CORRUPTED)
    assert reason, "실제로 배포된 손상 코드를 놓쳤다"
    assert "demonstration purposes" in reason.lower()


def test_clean_code_passes():
    assert self_declared_stub(CLEAN) == ""


def test_module_docstring_quotation_is_not_a_self_declaration():
    """리뷰어는 자기 규칙의 첫 피고지만, 인용까지 유죄는 아니다."""
    assert self_declared_stub(QUOTING) == "", "인용을 자기 진술로 읽었다"


def test_reason_quotes_the_author_not_a_judgment():
    """이 게이트가 신뢰받는 유일한 근거는 '판정이 아니라 인용'이라는 것이다."""
    reason = self_declared_stub(CORRUPTED)
    assert "For demonstration purposes" in reason or \
           "for demonstration purposes" in reason.lower()
    assert "행에서" in reason  # 어디인지 지목해야 재검증할 수 있다


def test_unparseable_source_returns_empty_not_a_guess():
    """모름 ≠ 있음. 구문 검사는 호출자의 몫으로 남긴다."""
    assert self_declared_stub("def broken(:\n  pass\n") == ""


def test_all_findings_are_reported_not_just_the_first():
    src = CORRUPTED + '''
    def helper(self):
        # This is a placeholder for actual logic
        pass
'''
    assert len(stub_findings(src)) >= 2


# ─────────────────────────────────────────────────────────────
# 실물 정밀도 — 오탐은 곧 개선 차단이다
# ─────────────────────────────────────────────────────────────

def _scan_agents():
    fired, total = {}, 0
    for root, _dirs, files in os.walk(_AGENTS):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            total += 1
            path = os.path.join(root, fn)
            try:
                src = open(path, encoding="utf-8").read()
            except Exception:
                continue
            hits = stub_findings(src)
            if hits:
                fired[os.path.relpath(path, _AGENTS)] = hits
    return total, fired


def test_handwritten_agents_do_not_fire():
    """수기 에이전트에서 한 건이라도 터지면 게이트가 무시당하기 시작한다."""
    if not os.path.isdir(_AGENTS):
        return  # 저장소 밖에서 실행 — 건너뛴다
    total, fired = _scan_agents()
    handwritten = [p for p in fired if "forge_generated" not in p]
    assert not handwritten, (
        f"수기 에이전트 오탐 {len(handwritten)}건 (전체 {total}파일): {handwritten}"
    )


def test_known_stubs_are_caught():
    """census 가 찾은 껍데기를 실제로 잡는가 — 재현율의 하한."""
    if not os.path.isdir(_AGENTS):
        return
    _total, fired = _scan_agents()
    assert len(fired) >= 5, f"알려진 껍데기를 못 잡는다 (발화 {len(fired)}파일)"


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
    if os.path.isdir(_AGENTS):
        total, fired = _scan_agents()
        hw = [p for p in fired if "forge_generated" not in p]
        print(f"\n실물 스캔: {total}파일 · 발화 {len(fired)}파일 · 수기 오탐 {len(hw)}건")
    print(f"{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
