"""규칙의 적용 범위 — 그리고 **실패한 실험 하나**의 기록 (Phase 0.5, 2026-08-22).

측정된 음성 결과 — 다시 시도하기 전에 읽을 것
──────────────────────────────────────
정밀도 감사(G2)가 장부 정밀도 37.3% 를 냈고, 규칙별 오탐 사유를 읽으니 실패
형태가 다섯 규칙에서 **동일**했다 — 리뷰어가 규칙의 **선행 조건을 확인하지 않고**
눈에 띄는 절반만 보고 발화한다(R-007 을 `subprocess.run` 에, R-010 을
`fig.update_xaxes` 에, R-013 을 객체 생성에).

진단은 맞았다. 처방은 **둘 다 틀렸다.** 같은 6개 파일에서 실측:

    A 옛 프롬프트 (자연 구성 재가중)        발견 377   정밀도 61.0%
    B 프롬프트 + 선행조건 증거 결착 관문     발견  24   정밀도 23.8%   ← 최악
    C 프롬프트만 (적용/판정/제외 3단 지시)   발견 335   정밀도 51.2%

**B (구조적 관문) 가 왜 실패했나** — 발견의 94% 를 죽이면서 정밀도까지 떨어뜨렸다.
거부 284건이 "선행 조건 증거 환각"이었다. 리뷰어 모델(flash-lite)이 파일 멀리
있는 문자열을 그대로 옮기지 못한다. 즉 그 관문은 *적용 가능성*이 아니라
**전사 능력**을 재고 있었고, 참·거짓 발견을 가리지 않고 죽였다.

**C (프롬프트) 가 왜 실패했나** — 정확한 규칙에서 부정확한 규칙으로 **물량을
옮겼다**. R-010(정밀도 12%) 발견이 7→63 건으로 늘고 R-009(93%)는 190→114 로 줄었다.

**무엇이 실제로 통했나 — 솎기.** 같은 C 측정에서 규칙만 걷어내면:

    전체 13 규칙                발견 320   51.2%
    R-007·R-013 제거            발견 304   53.9%
    + R-002·R-010 제거          발견 181   79.6%   (진짜 발견 164→144, 88% 유지)
    + R-003 제거                발견 169   84.0%

프롬프트 작업은 61%→51% 로 악화시켰고, 솎기는 진짜 발견 88% 를 지키며 80% 로 올린다.
**사상 ⑧ 그대로다 — 규칙은 사고로 심사받고, 값을 못 내는 규칙은 솎아낸다.**
표현을 다듬는 일이 아니라 목록을 줄이는 일이었다.

그래서 `applies_when`/`excludes` 는 **레지스트리에 남기되 프롬프트에 싣지 않는다**.
감사 근거로 도출된 정확한 기록이고 규칙을 다시 쓸 때 필요하지만, 모델에 먹이는
것이 도움이 된다는 증거는 없다(있다는 증거의 반대가 측정됐다).

직접 실행: python tests/test_review_rule_scope.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logosai.review.prompt import build_review_prompt  # noqa: E402
from logosai.review.rules import RULES  # noqa: E402


def test_every_rule_declares_its_scope():
    """적용 조건·제외 조항 없는 규칙은 등록할 수 없다.

    `incident` 강제와 같은 규율이다. 대상을 말할 수 없는 규칙은 아무 코드에나
    발화하고, 감사에서 그것이 오탐의 주된 형태로 확인됐다.
    """
    for field in ("applies_when", "excludes"):
        missing = [r.id for r in RULES if not (getattr(r, field) or "").strip()]
        assert not missing, f"{field} 가 비어 있다: {missing}"
    print("PASS every_rule_declares_its_scope")


def test_scope_is_not_a_restatement_of_the_hint():
    """적용 조건이 판정 지침의 복사본이면 아무것도 분리하지 못한 것이다."""
    same = [r.id for r in RULES if r.applies_when.strip() == r.detect_hint.strip()]
    assert not same, f"applies_when 이 detect_hint 와 동일: {same}"
    print("PASS scope_is_not_a_restatement_of_the_hint")


def test_scope_is_not_fed_to_the_model():
    """측정된 음성 결과의 회귀 방어 — 모듈 docstring 참조.

    이걸 프롬프트에 다시 넣고 싶어지면, 먼저 같은 6개 파일에서 재측정해
    51.2% 를 넘는지 보여야 한다. 그럴듯함은 근거가 아니다.
    """
    p = build_review_prompt()
    for r in RULES:
        assert r.applies_when not in p, (
            f"{r.id} 의 적용 조건이 프롬프트에 실렸다 — 2026-08-22 측정에서 "
            f"이 방식은 정밀도를 61%→51% 로 낮췄다"
        )
    assert "applies_evidence" not in p, (
        "선행 조건 증거 요구가 되살아났다 — 발견의 94% 를 죽이고 정밀도도 낮췄다"
    )
    print("PASS scope_is_not_fed_to_the_model")


def test_prompt_still_hides_incident():
    """확장·되돌림과 무관하게 유지되는 규율 (R-006)."""
    p = build_review_prompt()
    for r in RULES:
        assert r.incident[:40] not in p, f"{r.id} 의 사고 원문이 샜다"
    assert "forge_generated_387dc0b3" not in p
    print("PASS prompt_still_hides_incident")


def test_rule_subset_is_the_pruning_mechanism():
    """솎기는 `rule_ids` 로 한다 — 측정상 이것이 유일하게 통한 지렛대다."""
    keep = ["R-001", "R-005", "R-008", "R-009"]
    p = build_review_prompt(keep)
    for r in RULES:
        assert (r.id in p) == (r.id in keep), f"{r.id} 솎기 실패"
    print("PASS rule_subset_is_the_pruning_mechanism")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    print("\n전부 통과")
