"""정밀도 감사의 순수 계산부 — 표본 추출과 층화 집계 (G2, 2026-08-22).

왜 순수 함수로 떼어내는가
────────────────────────
사상 ③: 리뷰어는 틀려도 되고 장부는 틀리면 안 된다. 감사도 마찬가지다 —
"이게 진짜 결함인가"라는 **판단**만 모델이 하고, 표본을 어떻게 뽑았는지와
그 표본에서 모집단 정밀도를 어떻게 계산했는지는 **재현 가능한 산술**이어야 한다.
감사 결과가 Phase 1 을 허가하는 근거가 되므로, 그 산술이 틀리면 허가가 틀린다.

직접 실행: python tests/test_review_audit.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logosai.review.audit import (  # noqa: E402
    Verdict,
    aggregate,
    build_audit_prompt,
    parse_verdict,
    stratify,
    stratum_precision,
)


def _findings(spec):
    """(rule_id, target, n) → 가짜 발견 목록."""
    out = []
    for rule, target, n in spec:
        for i in range(n):
            out.append({
                "finding_id": f"{rule}-{target}-{i:04d}",
                "rule_id": rule,
                "target": target,
                "path": f"a/{rule}_{i % 7}.py",
                "line": i + 1,
                "excerpt": f"code_{i}",
            })
    return out


# ── 표본 추출 ────────────────────────────────────────────

def test_every_stratum_is_represented():
    """작은 층도 빠지지 않는다 — 비례 배분이면 R-013(3건)이 통째로 사라진다."""
    pop = _findings([("R-001", "instance", 456), ("R-013", "instance", 3)])
    sample = stratify(pop, per_stratum=15, seed=1)
    strata = {(f["rule_id"], f["target"]) for f in sample}
    assert ("R-013", "instance") in strata, "작은 층이 탈락했다"
    print("PASS every_stratum_is_represented")


def test_caps_at_availability():
    """층이 목표보다 작으면 전수. 없는 것을 만들어내지 않는다."""
    pop = _findings([("R-013", "instance", 3)])
    sample = stratify(pop, per_stratum=15, seed=1)
    assert len(sample) == 3, len(sample)
    print("PASS caps_at_availability")


def test_deterministic_given_seed():
    """같은 시드 → 같은 표본. 감사가 감사받으려면 재현 가능해야 한다."""
    pop = _findings([("R-001", "instance", 100), ("R-002", "template", 50)])
    a = [f["finding_id"] for f in stratify(pop, per_stratum=15, seed=42)]
    b = [f["finding_id"] for f in stratify(pop, per_stratum=15, seed=42)]
    c = [f["finding_id"] for f in stratify(pop, per_stratum=15, seed=43)]
    assert a == b, "같은 시드가 다른 표본을 냈다"
    assert a != c, "시드를 바꿔도 표본이 같다 — 무작위가 아니다"
    print("PASS deterministic_given_seed")


def test_no_duplicates_and_all_from_population():
    pop = _findings([("R-001", "instance", 40), ("R-005", "template", 40)])
    sample = stratify(pop, per_stratum=15, seed=7)
    ids = [f["finding_id"] for f in sample]
    assert len(ids) == len(set(ids)), "중복 추출"
    assert set(ids) <= {f["finding_id"] for f in pop}, "모집단에 없는 것이 섞였다"
    assert len(sample) == 30, len(sample)
    print("PASS no_duplicates_and_all_from_population")


# ── 층별 정밀도 ──────────────────────────────────────────

def test_unknown_becomes_a_range_not_a_number():
    """모름을 어느 쪽으로도 강제 배분하지 않는다 (사상 ⑦)."""
    v = [Verdict.TRUE] * 6 + [Verdict.FALSE] * 2 + [Verdict.UNKNOWN] * 2
    p = stratum_precision(v)
    assert p.decided == 8 and p.unknown == 2
    assert abs(p.point - 0.75) < 1e-9, p.point          # 6/8, 모름 제외
    assert abs(p.low - 0.60) < 1e-9, p.low              # 6/10, 모름=오답
    assert abs(p.high - 0.80) < 1e-9, p.high            # 8/10, 모름=정답
    print("PASS unknown_becomes_a_range_not_a_number")


def test_all_unknown_has_no_point_estimate():
    """전부 모름이면 점추정이 없다 — 0 도 1 도 아니다."""
    p = stratum_precision([Verdict.UNKNOWN] * 5)
    assert p.point is None, p.point
    assert p.low == 0.0 and p.high == 1.0
    print("PASS all_unknown_has_no_point_estimate")


def test_empty_stratum_is_none_not_zero():
    """판정이 하나도 없으면 '모름'이지 '정밀도 0' 이 아니다."""
    p = stratum_precision([])
    assert p.point is None and p.decided == 0
    print("PASS empty_stratum_is_none_not_zero")


# ── 층화 집계 ────────────────────────────────────────────

def test_weighting_follows_population_not_sample():
    """큰 층이 표본에서 작아도 모집단 비중대로 가중된다.

    이게 없으면 R-013(3건)이 R-001(474건)과 동등하게 전체 정밀도를 흔든다.
    """
    strata = {
        ("R-001", "instance"): dict(N=474, verdicts=[Verdict.TRUE] * 15),
        ("R-013", "instance"): dict(N=3, verdicts=[Verdict.FALSE] * 3),
    }
    agg = aggregate(strata)
    # 474/477 이 1.0, 3/477 이 0.0 → ≈0.9937
    assert 0.99 < agg.point < 0.995, agg.point
    print("PASS weighting_follows_population_not_sample")


def test_fpc_shrinks_interval_on_near_census():
    """층을 거의 전수 조사하면 신뢰구간이 좁아져야 한다 (유한모집단 보정).

    18건 중 15건을 뽑는 셀이 실제로 있다. FPC 가 없으면 그 층의 불확실성이
    무한 모집단인 것처럼 과대평가된다.
    """
    v = [Verdict.TRUE] * 12 + [Verdict.FALSE] * 3
    near = aggregate({("R", "t"): dict(N=16, verdicts=v)})     # 16 중 15
    far = aggregate({("R", "t"): dict(N=10000, verdicts=v)})   # 10000 중 15
    assert near.half_width < far.half_width, (near.half_width, far.half_width)
    print("PASS fpc_shrinks_interval_on_near_census")


def test_full_census_stratum_has_no_uncertainty():
    """전수 조사한 층은 표집 불확실성이 0 이다."""
    agg = aggregate({("R-013", "instance"): dict(N=3, verdicts=[Verdict.TRUE] * 3)})
    assert abs(agg.half_width) < 1e-9, agg.half_width
    print("PASS full_census_stratum_has_no_uncertainty")


def test_interval_stays_within_bounds():
    """구간이 [0,1] 을 벗어나지 않는다."""
    agg = aggregate({("R", "t"): dict(N=1000, verdicts=[Verdict.TRUE] * 15)})
    assert 0.0 <= agg.ci_low <= agg.point <= agg.ci_high <= 1.0, agg
    print("PASS interval_stays_within_bounds")


def test_unknown_range_propagates_to_overall():
    """모름 구간은 전체 집계까지 살아 남는다 — 중간에 뭉개지지 않는다."""
    agg = aggregate({
        ("R", "t"): dict(
            N=100,
            verdicts=[Verdict.TRUE] * 6 + [Verdict.FALSE] * 2 + [Verdict.UNKNOWN] * 7,
        ),
    })
    assert agg.unknown == 7
    assert abs(agg.point - 0.75) < 1e-9, agg.point          # 6/8
    assert abs(agg.low - 6 / 15) < 1e-9, agg.low            # 모름=오답
    assert abs(agg.high - 13 / 15) < 1e-9, agg.high         # 모름=정답
    assert agg.low < agg.point < agg.high
    print("PASS unknown_range_propagates_to_overall")


def test_point_may_touch_bound_when_all_decided_agree():
    """판정된 것이 전부 '맞다'면 점추정 == 상한이다 — 구간이 열려 있어야 하는 게
    아니라, 모름이 전부 정답이어도 1.0 을 넘을 수 없기 때문이다.

    이 경계를 안 박아 두면 나중에 '구간을 벌리는' 잘못된 수정이 들어온다.
    """
    agg = aggregate({("R", "t"): dict(
        N=100, verdicts=[Verdict.TRUE] * 8 + [Verdict.UNKNOWN] * 7)})
    assert agg.point == 1.0 and agg.high == 1.0
    assert abs(agg.low - 8 / 15) < 1e-9, agg.low
    print("PASS point_may_touch_bound_when_all_decided_agree")


def test_all_unknown_stratum_excluded_from_point_but_shown():
    """판정 불가 층은 점추정에서 빠지되 **빠졌다는 사실이 보여야** 한다.

    조용히 제외하면 "전체 정밀도 95%"가 실제로는 모집단의 60% 에 대한 말이
    되는데 화면에는 그렇게 안 보인다. 사상 ⑦ — 버린 것은 이유와 함께.
    """
    agg = aggregate({
        ("R-001", "instance"): dict(N=100, verdicts=[Verdict.TRUE] * 10),
        ("R-009", "instance"): dict(N=400, verdicts=[Verdict.UNKNOWN] * 10),
    })
    assert abs(agg.point - 1.0) < 1e-9, agg.point
    assert abs(agg.covered_share - 0.2) < 1e-9, (
        f"점추정이 덮는 모집단 비중이 보고되지 않는다: {agg.covered_share}"
    )
    assert agg.undecided_strata == [("R-009", "instance")], agg.undecided_strata
    print("PASS all_unknown_stratum_excluded_from_point_but_shown")


def test_controls_are_not_mixed_into_precision():
    """대조군은 정밀도 계산에 들어가면 안 된다 — 모집단이 다르다."""
    strata = {
        ("R-001", "instance"): dict(N=474, verdicts=[Verdict.TRUE] * 10),
        ("__control__", ""): dict(N=40, verdicts=[Verdict.FALSE] * 10),
    }
    agg = aggregate(strata)
    assert abs(agg.point - 1.0) < 1e-9, (
        f"대조군이 정밀도를 오염시켰다: {agg.point}"
    )
    assert agg.control_flagged_rate == 0.0, agg.control_flagged_rate
    print("PASS controls_are_not_mixed_into_precision")


def test_control_rate_is_reported_ambiguously():
    """대조군에서 '맞다'가 나오면 **양쪽 다 가능**하다 — 귀속하지 않는다.

    판정자 과잉동의일 수도, 리뷰어 누락일 수도 있다. 한쪽으로 단정하면
    사상 ⑦(모름 ≠ 없음)을 어긴다. 여기서는 비율만 내고 해석은 사람이 한다.
    """
    agg = aggregate({
        ("R-001", "instance"): dict(N=100, verdicts=[Verdict.TRUE] * 10),
        ("__control__", ""): dict(N=40, verdicts=[Verdict.TRUE] * 3 + [Verdict.FALSE] * 7),
    })
    assert abs(agg.control_flagged_rate - 0.3) < 1e-9, agg.control_flagged_rate
    assert agg.control_n == 10
    print("PASS control_rate_is_reported_ambiguously")


# ── 판정자 프롬프트 계약 ─────────────────────────────────

def test_prompt_hides_reviewer_message():
    """판정자는 리뷰어의 설명을 보지 않는다 — 보면 채점이지 독립 판정이 아니다.

    사상 ⑨. 리뷰어 문장에 정박되면 "그럴듯한가"를 재는 것이지 "코드가 실제로
    그런가"를 재는 것이 아니다. 규칙과 코드만 주고 스스로 재도출시킨다.
    """
    item = {
        "rule_id": "R-002",
        "path": "a/x.py",
        "line": 3,
        "excerpt": "except Exception:",
        "message": "예외를 삼켜 실패가 성공으로 집계된다",  # ← 절대 새면 안 됨
    }
    p = build_audit_prompt(item, context="1|a\n2|b\n3|except Exception:\n")
    assert "실패가 성공으로 집계" not in p, "리뷰어의 설명이 프롬프트로 샜다"
    assert "except Exception:" in p, "정작 코드가 없다"
    print("PASS prompt_hides_reviewer_message")


def test_prompt_excludes_incident():
    """`incident` 에는 정답(파일·행)이 적혀 있다 — 리뷰어와 같은 규율을 적용한다."""
    from logosai.review.rules import RULES

    item = {"rule_id": "R-001", "path": "a/x.py", "line": 1,
            "excerpt": "return 'ok'", "message": "m"}
    p = build_audit_prompt(item, context="1|return 'ok'\n")
    rule = next(r for r in RULES if r.id == "R-001")
    assert rule.incident and rule.incident[:40] not in p, "사고 원문(정답)이 샜다"
    assert "forge_generated_387dc0b3" not in p, "정답 파일명이 샜다"
    print("PASS prompt_excludes_incident")


def test_prompt_offers_unknown_verdict():
    """모름을 선택지로 제시하지 않으면 모름이 오답으로 위장한다 (사상 ⑦)."""
    p = build_audit_prompt(
        {"rule_id": "R-001", "path": "a/x.py", "line": 1, "excerpt": "x", "message": ""},
        context="1|x\n",
    )
    assert "모름" in p, "모름 선택지가 없다"
    print("PASS prompt_offers_unknown_verdict")


def test_control_item_is_indistinguishable():
    """대조군 항목이 프롬프트에서 표시 나면 자기 감사가 무의미해진다."""
    real = build_audit_prompt(
        {"rule_id": "R-002", "path": "a/x.py", "line": 3, "excerpt": "except Exception:",
         "message": "m", "is_control": False},
        context="3|except Exception:\n",
    )
    ctrl = build_audit_prompt(
        {"rule_id": "R-002", "path": "a/x.py", "line": 3, "excerpt": "except Exception:",
         "message": "", "is_control": True},
        context="3|except Exception:\n",
    )
    assert real == ctrl, "대조군이 프롬프트에서 구분된다 — 판정자가 알아챌 수 있다"
    print("PASS control_item_is_indistinguishable")


def test_verdict_parsing_rejects_unknown_labels():
    """모르는 라벨은 모름으로 떨어뜨린다 — 임의로 맞다/틀렸다에 배정하지 않는다."""
    assert parse_verdict('{"verdict":"맞다","evidence":"x"}')[0] is Verdict.TRUE
    assert parse_verdict('{"verdict":"틀렸다","evidence":"x"}')[0] is Verdict.FALSE
    assert parse_verdict('{"verdict":"모름","evidence":"x"}')[0] is Verdict.UNKNOWN
    assert parse_verdict('{"verdict":"아마도"}')[0] is Verdict.UNKNOWN
    assert parse_verdict("완전 쓰레기")[0] is Verdict.UNKNOWN
    print("PASS verdict_parsing_rejects_unknown_labels")


def test_verdict_requires_evidence():
    """근거 없는 '맞다'는 모름으로 강등한다 (사상 ②)."""
    v, reason = parse_verdict('{"verdict":"맞다","evidence":""}')
    assert v is Verdict.UNKNOWN, v
    assert "근거" in reason, reason
    print("PASS verdict_requires_evidence")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    print("\n전부 통과")
