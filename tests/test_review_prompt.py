"""리뷰어 프롬프트 구성 테스트 (2026-08-21).

여기서 막는 사고
──────────────
규칙 레지스트리의 `incident` 필드에는 정답이 적혀 있다 —
"forge_generated_387dc0b3.py:76 이 non-functional placeholder 라고 써 놓고도…".

이걸 프롬프트에 실으면 그 파일을 리뷰할 때 리뷰어는 발견하는 게 아니라
**받아적는다**. 골든 코퍼스 평가가 통째로 무의미해지고, 더 나쁘게는 다른 파일에서
같은 문장을 환각할 근거가 된다.

R-006(검증 신호 누설 금지)이 바로 그 사고에서 나온 규칙이다. 스모크 테스트의
expected:'' 가 LLM 에 플레이스홀더를 학습시켰던 일. 리뷰어를 만들면서 같은 실수를
반복하면 이 도구는 자기 규칙조차 못 지키는 물건이 된다.

`incident` 는 사람이 규칙의 정당성을 감사하기 위한 필드이지 모델 입력이 아니다.

직접 실행: python tests/test_review_prompt.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logosai.review.prompt import build_review_prompt  # noqa: E402
from logosai.review.rules import RULES  # noqa: E402


def test_prompt_lists_every_rule_id_and_hint():
    p = build_review_prompt()
    for rule in RULES:
        assert rule.id in p, f"{rule.id} 가 프롬프트에 없다"
        assert rule.detect_hint[:20] in p, f"{rule.id} 판정 지침이 없다"


def test_prompt_never_leaks_incident_text():
    """정답을 알려주고 찾게 하면 그건 평가가 아니다."""
    p = build_review_prompt()
    for rule in RULES:
        head = rule.incident.strip()[:30]
        assert head not in p, f"{rule.id}: incident 가 프롬프트에 샜다 — {head!r}"


def test_prompt_never_leaks_known_defect_locations():
    """사고 기록에 담긴 구체적 파일·행이 프롬프트로 새면 환각의 씨앗이 된다."""
    p = build_review_prompt()
    for marker in ("forge_generated_387dc0b3", "non-functional placeholder", ":76"):
        assert marker not in p, f"알려진 결함 위치가 샜다: {marker!r}"


def test_prompt_demands_verbatim_evidence():
    """발췌를 요구하지 않으면 증거 결착이 전부 실패해 발견이 0건이 된다."""
    p = build_review_prompt()
    assert "excerpt" in p
    assert "line" in p
    assert "rule_id" in p


def test_prompt_forbids_inventing_rules():
    p = build_review_prompt()
    assert "R-0" in p
    lowered = p.lower()
    assert ("only" in lowered) or ("만" in p), "레지스트리 밖 규칙 금지 지시가 없다"


def test_prompt_can_restrict_to_subset():
    """census 이후 값 없는 규칙을 솎아낼 수 있어야 한다."""
    p = build_review_prompt(rule_ids=["R-001"])
    assert "R-001" in p and "R-002" not in p


def test_prompt_is_stable():
    """같은 입력에 같은 프롬프트 — 아니면 census 결과를 비교할 수 없다."""
    assert build_review_prompt() == build_review_prompt()


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
