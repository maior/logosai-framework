"""규칙 레지스트리 — 메커니즘과 인스턴스의 분리 (2026-08-23).

무엇이 이 분리를 만들게 했나
──────────────────────────
`rules.py` 의 docstring 은 *"근거를 댈 수 없는 규칙은 **등록할 수 없다**"* 라고
선언했다. 그런데 강제하는 것은 내장 튜플을 훑는 테스트 하나뿐이었고, `Rule` 은
`frozen=True` 이면서 `__post_init__` 검증이 없었다:

    Rule(id="X", title="t", severity="major", incident="", ...)   # 통과했다

즉 불변식이 **코드가 아니라 문서**에 있었다. 우리 튜플만 검사받고 다른 경로로
만든 규칙은 검사받지 않는다 — 2026-08-22 하루에 네 번 만난 그 형태
(*게이트는 있고, 그 자원에 도달하는 다른 경로엔 없었다*)가 계약 계층 자신에
있었다. 공개 SDK 로 나가면 외부 채택자가 정확히 그 경로로 들어온다.

두 번째 문제: 13개 Logos 규칙이 프레임워크의 **정본**이었다. 다른 조직이 이
SDK 를 쓰면 우리 사고를 자기 헌법으로 물려받고 자기 규칙을 넣을 자리가 없다.
라이브러리가 줘야 할 것은 *메커니즘*(Rule 계약 · 증거 강제 · 프롬프트 경계)이고
13개는 **그 메커니즘의 한 인스턴스**다.

왜 전역 레지스트리를 만들지 않았나
────────────────────────────────
`use_rules()` 같은 프로세스 전역 상태는 R-013 이 기록한 사고와 같은 부류다 —
import 시점에 env 를 세운 파일 3개가 다른 파일의 테스트 8건을 조용히 죽였고,
단독 실행은 통과해서 오래 안 보였다. 대신 **매개변수 주입 + 기본값**으로 간다.
"등록"은 `RuleSet` 생성 시점의 검증이므로 불변식이 코드가 된다.

직접 실행: python tests/test_review_rule_registry.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logosai.review import RULES  # noqa: E402
from logosai.review.audit import build_audit_prompt  # noqa: E402
from logosai.review.prompt import build_review_prompt  # noqa: E402
from logosai.review.rules import Rule, RuleSet, get_rule  # noqa: E402
from logosai.review.rules_logos import DEFAULT_RULES  # noqa: E402

#: 외부 채택자가 만들 법한 규칙. 우리 사고가 아닌 남의 사고를 인용한다.
FOREIGN = Rule(
    id="ACME-001",
    title="결제 금액을 float 로 계산하지 않는다",
    severity="blocker",
    incident="2026-01-정산에서 float 반올림이 건당 0.01 씩 어긋나 3,412건이 재정산됐다.",
    detect_hint="통화 금액을 float 로 더하거나 곱하는 경우.",
    applies_when="그 값이 **통화 금액**이다.",
    excludes="비율·수량·좌표는 대상이 아니다.",
    not_covered_by="float 연산은 문법상 정상이라 린터가 볼 신호가 없다.",
)


def _rule(**over):
    """유효한 규칙을 만들고 지정한 필드만 덮어쓴다."""
    base = dict(
        id="T-001",
        title="t",
        severity="major",
        incident="실제로 있었던 일.",
        detect_hint="h",
        applies_when="a",
        excludes="e",
        not_covered_by="n",
    )
    base.update(over)
    return Rule(**base)


# ── 불변식이 코드가 된다 ────────────────────────────────────────────────

def test_rule_without_incident_cannot_be_constructed():
    """근거를 댈 수 없는 규칙은 **만들어지지 않는다** — 문서가 아니라 코드로."""
    for bad in ("", "   ", "\n"):
        try:
            _rule(incident=bad)
        except ValueError:
            continue
        raise AssertionError(f"incident={bad!r} 인 규칙이 생성됐다")
    print("PASS rule_without_incident_cannot_be_constructed")


def test_rule_without_scope_cannot_be_constructed():
    """적용 조건·제외 조항 없는 규칙은 아무 코드에나 발화한다 (감사에서 확인된 주 오탐 형태)."""
    for field in ("applies_when", "excludes"):
        try:
            _rule(**{field: ""})
        except ValueError:
            continue
        raise AssertionError(f"{field} 가 빈 규칙이 생성됐다")
    print("PASS rule_without_scope_cannot_be_constructed")


def test_rule_with_unknown_severity_is_refused():
    """severity 는 세 값뿐 — 오타가 조용히 통과하면 집계가 갈린다."""
    try:
        _rule(severity="critical")
    except ValueError:
        print("PASS rule_with_unknown_severity_is_refused")
        return
    raise AssertionError("모르는 severity 가 통과했다")


def test_rule_with_evidence_constructs_fine():
    """증거를 갖춘 규칙은 아무 마찰 없이 만들어져야 한다 — 규율이 장벽이 되면 안 된다."""
    r = _rule()
    assert r.id == "T-001" and r.incident
    print("PASS rule_with_evidence_constructs_fine")


# ── RuleSet — 조회는 지어내지 않고, 솎기는 조용히 비지 않는다 ──────────────

def test_ruleset_rejects_duplicate_ids():
    """같은 id 가 둘이면 어느 쪽이 이겼는지 아무도 모른다."""
    try:
        RuleSet.of(_rule(id="D-1"), _rule(id="D-1"))
    except ValueError:
        print("PASS ruleset_rejects_duplicate_ids")
        return
    raise AssertionError("중복 id 가 통과했다")


def test_ruleset_get_returns_none_for_unknown():
    """모르는 것을 지어내지 않는다 (사상 ⑦)."""
    rs = RuleSet.of(_rule(id="A-1"))
    assert rs.get("A-1") is not None
    assert rs.get("없는규칙") is None
    print("PASS ruleset_get_returns_none_for_unknown")


def test_ruleset_subset_refuses_unknown_ids():
    """오타난 id 로 솎으면 **조용히 0개**가 된다 — 모름 ≠ 없음 (R-008)."""
    rs = RuleSet.of(_rule(id="A-1"), _rule(id="A-2"))
    assert rs.subset(["A-1"]).ids == ("A-1",)
    try:
        rs.subset(["A-1", "A-3"])
    except ValueError:
        print("PASS ruleset_subset_refuses_unknown_ids")
        return
    raise AssertionError("모르는 id 로 솎기가 조용히 통과했다")


def test_ruleset_is_iterable_and_sized():
    """소비자가 `for r in rules` / `len(rules)` 를 쓴다."""
    rs = RuleSet.of(_rule(id="A-1"), _rule(id="A-2"))
    assert len(rs) == 2
    assert [r.id for r in rs] == ["A-1", "A-2"]
    print("PASS ruleset_is_iterable_and_sized")


# ── 인스턴스 분리 — 명목이 아니라 실질 ──────────────────────────────────

def test_default_ruleset_is_the_logos_reference_set():
    """13규칙은 사라진 게 아니라 인스턴스로 옮겨졌을 뿐이다."""
    assert len(DEFAULT_RULES) == 13
    assert DEFAULT_RULES.ids == tuple(f"R-{i:03d}" for i in range(1, 14))
    print("PASS default_ruleset_is_the_logos_reference_set")


def test_legacy_RULES_name_still_works():
    """`RULES` 는 `__all__` 에 있었다 — 이름을 깨면 외부 코드가 죽는다."""
    assert tuple(RULES) == DEFAULT_RULES.rules
    assert get_rule("R-001") is not None
    assert get_rule("R-999") is None
    print("PASS legacy_RULES_name_still_works")


def test_mechanism_module_carries_no_logos_incidents():
    """분리가 실질인지 검사한다 — 메커니즘 모듈에 우리 사고 원문이 남아 있으면 안 된다."""
    src = (Path(__file__).resolve().parents[1] / "logosai" / "review" / "rules.py").read_text(
        encoding="utf-8"
    )
    for rule in DEFAULT_RULES:
        head = rule.incident[:30]
        assert head not in src, f"{rule.id} 의 사고 원문이 메커니즘 모듈에 남아 있다"
    print("PASS mechanism_module_carries_no_logos_incidents")


# ── 외부 채택자 경로 ───────────────────────────────────────────────────

def test_adopter_can_use_their_own_ruleset():
    """자기 규칙셋으로 프롬프트가 만들어져야 한다 — 이게 이 작업의 목적이다."""
    p = build_review_prompt(rules=RuleSet.of(FOREIGN))
    assert "ACME-001" in p
    assert "R-001" not in p, "우리 규칙이 남의 프롬프트에 섞였다"
    print("PASS adopter_can_use_their_own_ruleset")


def test_foreign_rule_incident_never_reaches_the_prompt():
    """프롬프트 경계는 Logos 규칙 전용이 아니다.

    incident 에는 정답이 적혀 있다. 그 보장이 우리 13개에만 걸려 있으면
    외부 채택자는 자기 규칙에서 그대로 새고, 우리는 그걸 모른다 (R-006).
    """
    p = build_review_prompt(rules=RuleSet.of(FOREIGN))
    assert FOREIGN.incident[:30] not in p, "남의 사고 원문이 리뷰 프롬프트에 샜다"
    assert FOREIGN.applies_when not in p, "적용 조건은 프롬프트에 싣지 않기로 측정됐다"
    print("PASS foreign_rule_incident_never_reaches_the_prompt")


def test_foreign_rule_incident_never_reaches_the_audit_prompt():
    """판정자 쪽 경계도 같다 — 리뷰어에게 안 준 것을 판정자에게 주면 우리가 규율을 어긴다."""
    item = {"rule_id": "ACME-001", "path": "pay.py", "line": 3, "excerpt": "total += x"}
    p = build_audit_prompt(item, context="3|total += x\n", rules=RuleSet.of(FOREIGN))
    assert FOREIGN.title in p, "규칙 제목이 판정자에게 전달되지 않았다"
    assert FOREIGN.incident[:30] not in p, "남의 사고 원문이 판정 프롬프트에 샜다"
    print("PASS foreign_rule_incident_never_reaches_the_audit_prompt")


def test_empty_ruleset_prompt_is_refused():
    """규칙 0개짜리 프롬프트는 '목록에 있는 것만 보고하라'는 지시와 함께 빈 목록을 준다.

    반드시 빈 결과를 내는 LLM 호출이므로, 조용히 태우지 말고 거절한다.
    """
    try:
        build_review_prompt(rules=RuleSet.of())
    except ValueError:
        print("PASS empty_ruleset_prompt_is_refused")
        return
    raise AssertionError("빈 규칙셋으로 프롬프트가 만들어졌다")


def test_subset_and_custom_ruleset_compose():
    """솎기(측정상 유일하게 통한 지렛대)가 남의 규칙셋에서도 동작해야 한다."""
    rs = RuleSet.of(FOREIGN, _rule(id="ACME-002"))
    p = build_review_prompt(rule_ids=["ACME-002"], rules=rs)
    assert "ACME-002" in p and "ACME-001" not in p
    print("PASS subset_and_custom_ruleset_compose")


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
        except Exception:
            failed += 1
            print(f"  ❌ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
