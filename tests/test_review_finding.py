"""ReviewFinding 계약 + 순수 함수 테스트 (2026-08-21).

배경
────
생성된 에이전트 74개(18,103줄)를 실측하니 껍데기 7개·침묵 실패 41곳이 있었다.
`forge_generated_387dc0b3.py:76` 은 자기 코드에 "non-functional placeholder" 라고
써 놓고도 등록되어 살아 있었다.

왜 아무 게이트도 못 잡았나 — 모든 게이트가 **실행 성공 여부**에 걸려 있기 때문이다
(failure_logger 는 execution_feedback.success, shadow test 는 3개 중 66%).
껍데기는 예외 없이 문자열을 반환하므로 성공률 100% 다. "실행 성공, 결과 틀림"은
이 신호로 영원히 안 잡힌다.

설계의 핵심
──────────
프롬프트 자동 주입은 과거에 **의도적으로 보류**됐다(CLAUDE.md:659 "잘못된 학습
주입 → 연쇄 장애 위험"). 그 위험을 뚫는 열쇠는 리뷰 발견이 행동 학습과 종류가
다르다는 점이다 — 행동 학습은 '세상에 대한 주장'이라 검증 불가지만, 리뷰 발견은
'존재하는 텍스트에 대한 주장'이라 **재검증 가능하다**.

그래서 증거(path·line·excerpt) 없는 발견은 저장 자체를 거부하고, 코드가 바뀌면
스스로 만료한다. 이 파일의 테스트는 그 규율이 실제로 강제되는지를 고정한다.

또한 판단(LLM)과 장부(순수 함수)를 분리한다. 여기 있는 것은 전부 장부이며
결정적이다. 리뷰어 LLM 을 바꿔도 이 테스트는 흔들리지 않아야 한다.

직접 실행: python tests/test_review_finding.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logosai.review.finding import (  # noqa: E402
    EvidenceError,
    ReviewFinding,
    bind_evidence,
    classify_target,
    dedupe,
    finding_id_for,
    recheck,
    revision_of,
    validate_finding,
)
from logosai.review.rules import RULES, get_rule  # noqa: E402


# ─────────────────────────────────────────────────────────────
# 표본: 실물에서 가져온 코드 조각 (합성 금지 — 관측에 가짜 데이터를 넣지 않는다)
# ─────────────────────────────────────────────────────────────

SOURCE_PLACEHOLDER = '''\
class ConvertToBrailleAgent(LogosAIAgent):
    async def process(self, query, context=None):
        """Converts Korean text to Korean braille."""
        try:
            # A very basic, non-functional placeholder to demonstrate structure.
            result = f"braille_representation_of: {query}"
            return {"success": True, "response": result}
        except Exception:
            pass
'''

SOURCE_FIXED = '''\
class ConvertToBrailleAgent(LogosAIAgent):
    async def process(self, query, context=None):
        """Converts Korean text to Korean braille."""
        try:
            result = self._braille_table.convert(query)
            return {"success": True, "response": result}
        except Exception as e:
            logger.warning("braille conversion failed: %s", e)
            return {"success": False, "error": str(e)}
'''


def _finding(**over):
    base = dict(
        rule_id="R-001",
        severity="blocker",
        path="acp_server/agents/forge_generated_387dc0b3.py",
        line=5,
        excerpt="non-functional placeholder",
        target="instance",
        message="에이전트가 자기 코드를 동작하지 않는 껍데기라고 밝히고 있다",
        subject_agent="forge_generated_387dc0b3",
    )
    base.update(over)
    return ReviewFinding(**base)


# ─────────────────────────────────────────────────────────────
# 규칙 레지스트리 — 증거 상한이 규율이다
# ─────────────────────────────────────────────────────────────

def test_every_rule_cites_a_real_incident():
    """규칙의 개수를 제한하지 않는 대신 근거를 강제한다.

    근거 없는 규칙을 허용하면 레지스트리가 취향 목록으로 변하고, 취향은 소음을
    낳고, 소음은 리뷰어를 무시하게 만든다. 개수 상한이 아니라 증거 상한이다.
    """
    assert RULES, "레지스트리가 비어 있다"
    for rule in RULES:
        assert rule.incident.strip(), f"{rule.id}: incident(근거 사고)가 비어 있다"
        assert rule.not_covered_by.strip(), (
            f"{rule.id}: ruff/mypy 가 이미 잡는지 판단한 근거가 없다"
        )


def test_rule_ids_are_unique():
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids)), f"중복 rule_id: {ids}"


def test_get_rule_returns_none_for_unknown():
    assert get_rule("R-999") is None


# ─────────────────────────────────────────────────────────────
# 계약 검증
# ─────────────────────────────────────────────────────────────

def test_validate_accepts_well_formed_finding():
    assert validate_finding(_finding()) == []


def test_validate_rejects_unknown_rule_id():
    errs = validate_finding(_finding(rule_id="R-999"))
    assert any("rule_id" in e for e in errs), errs


def test_validate_rejects_missing_evidence():
    """증거 없는 발견은 저장 자체를 거부한다.

    excerpt 가 없으면 재검증이 불가능하고, 재검증 불가능한 발견은 영원히
    만료되지 않는다 — 오학습이 죽지 않고 계속 주입된다.
    """
    errs = validate_finding(_finding(excerpt="   "))
    assert any("excerpt" in e for e in errs), errs


def test_validate_rejects_bad_severity():
    errs = validate_finding(_finding(severity="critical"))
    assert any("severity" in e for e in errs), errs


def test_validate_rejects_bad_target():
    errs = validate_finding(_finding(target="module"))
    assert any("target" in e for e in errs), errs


def test_validate_rejects_nonpositive_line():
    errs = validate_finding(_finding(line=0))
    assert any("line" in e for e in errs), errs


# ─────────────────────────────────────────────────────────────
# 증거 결착 — LLM 이 지어낸 위치를 차단한다
# ─────────────────────────────────────────────────────────────

def test_bind_evidence_accepts_matching_line():
    bound = bind_evidence(_finding(line=5), SOURCE_PLACEHOLDER)
    assert bound.line == 5


def test_bind_evidence_corrects_off_by_a_few():
    """LLM 은 행 번호를 자주 한두 줄 틀린다. 발췌가 창 안에 있으면 교정한다.

    관대함의 범위는 '위치'까지다. 발췌 자체가 없으면 아래 테스트대로 거부한다.
    """
    bound = bind_evidence(_finding(line=7), SOURCE_PLACEHOLDER, window=3)
    assert bound.line == 5, "발췌가 실제로 있는 행으로 교정돼야 한다"


def test_bind_evidence_rejects_fabricated_excerpt():
    """소스에 없는 문장을 인용하면 발견을 버린다 — 환각 차단의 핵심."""
    try:
        bind_evidence(_finding(excerpt="TODO: 여기에 구현"), SOURCE_PLACEHOLDER)
    except EvidenceError:
        return
    raise AssertionError("소스에 없는 발췌가 통과했다")


def test_bind_evidence_rejects_line_out_of_range():
    try:
        bind_evidence(_finding(line=9999), SOURCE_PLACEHOLDER)
    except EvidenceError:
        return
    raise AssertionError("범위 밖 행 번호가 통과했다")


def test_bind_evidence_picks_nearest_when_excerpt_repeats():
    """발췌가 창 안에 여러 번 나오면 보고된 행에 가장 가까운 것을 고른다.

    finding_id 가 행 번호를 포함하므로, 여기서 흔들리면 같은 결함이 매번 다른
    id 를 받아 재발 집계가 무너진다. 결정성이 필요하다.
    """
    src = "\n".join([
        "a = 1",              # 1
        "except Exception:",  # 2
        "b = 2",              # 3
        "c = 3",              # 4
        "except Exception:",  # 5
        "d = 4",              # 6
    ])
    bound = bind_evidence(_finding(rule_id="R-002", line=4, excerpt="except Exception:"),
                          src, window=3)
    assert bound.line == 5, f"가장 가까운 행이 아니라 {bound.line} 을 골랐다"


def test_bind_evidence_rejects_match_outside_window():
    """창 밖에서 우연히 일치하는 것을 근거로 삼지 않는다."""
    long_source = "\n".join(["# filler"] * 40) + "\n" + SOURCE_PLACEHOLDER
    try:
        bind_evidence(_finding(line=1), long_source, window=2)
    except EvidenceError:
        return
    raise AssertionError("창 밖 일치가 통과했다")


# ─────────────────────────────────────────────────────────────
# 재검증 — 발견은 스스로 만료한다
# ─────────────────────────────────────────────────────────────

def test_recheck_holds_when_code_unchanged():
    assert recheck(_finding(), SOURCE_PLACEHOLDER) is True


def test_recheck_expires_when_defect_removed():
    """결함이 고쳐지면 발견은 죽는다.

    이것이 행동 학습과 리뷰 발견의 결정적 차이다. 행동 학습은 틀려도 조용히
    남아 계속 주입되지만, 리뷰 발견은 근거가 사라지면 만료된다.
    """
    assert recheck(_finding(), SOURCE_FIXED) is False


# ─────────────────────────────────────────────────────────────
# 식별자 — 재발을 세려면 같은 결함이 같은 id 를 가져야 한다
# ─────────────────────────────────────────────────────────────

def test_finding_id_is_deterministic():
    a = finding_id_for("R-001", "a/b.py", 5, "non-functional placeholder")
    b = finding_id_for("R-001", "a/b.py", 5, "non-functional placeholder")
    assert a == b


def test_finding_id_differs_by_rule_and_location():
    base = finding_id_for("R-001", "a/b.py", 5, "x")
    assert finding_id_for("R-002", "a/b.py", 5, "x") != base
    assert finding_id_for("R-001", "a/c.py", 5, "x") != base
    assert finding_id_for("R-001", "a/b.py", 6, "x") != base


def test_revision_changes_with_source():
    """리비전 스탬프가 없으면 개선을 코드 개정에 귀속시킬 수 없다.

    Pulse 실측 결과 agent_executions 에 버전 컬럼이 전혀 없어, 오늘은 '나아졌다'가
    상관일 뿐 귀속이 아니다. 발견 단계에서부터 리비전을 박아 둔다.
    """
    assert revision_of(SOURCE_PLACEHOLDER) != revision_of(SOURCE_FIXED)
    assert revision_of(SOURCE_PLACEHOLDER) == revision_of(SOURCE_PLACEHOLDER)
    assert len(revision_of(SOURCE_PLACEHOLDER)) == 12


# ─────────────────────────────────────────────────────────────
# 중복 제거 · 소재지 판정 — 레버리지를 만드는 곳
# ─────────────────────────────────────────────────────────────

def test_dedupe_collapses_same_rule_path_line():
    out = dedupe([_finding(), _finding(message="다르게 설명해도 같은 결함")])
    assert len(out) == 1


def test_dedupe_keeps_distinct_locations():
    out = dedupe([_finding(line=5), _finding(line=9)])
    assert len(out) == 2


def test_classify_target_promotes_repeated_defect_to_template():
    """318곳의 except Exception 은 74개의 결함이 아니라 템플릿 결함 1개다.

    소재지를 template 으로 승격해야 Phase 2 에서 생성기를 고칠 신호가 된다.
    개체를 74번 고치는 것과 생성기를 1번 고치는 것의 차이가 이 함수에 달렸다.
    """
    findings = [
        _finding(rule_id="R-002", path=f"agents/gen_{i}.py", excerpt="except Exception:")
        for i in range(3)
    ]
    out = classify_target(findings, template_threshold=3)
    assert all(f.target == "template" for f in out), [f.target for f in out]


def test_classify_target_keeps_single_occurrence_as_instance():
    out = classify_target([_finding(rule_id="R-002")], template_threshold=3)
    assert out[0].target == "instance"


def test_classify_target_counts_distinct_files_not_occurrences():
    """같은 파일에서 10번 터진 것은 템플릿 결함의 증거가 아니다."""
    findings = [
        _finding(rule_id="R-002", path="agents/gen_1.py", line=i, excerpt="except Exception:")
        for i in range(10)
    ]
    out = classify_target(findings, template_threshold=3)
    assert all(f.target == "instance" for f in out), [f.target for f in out]


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
