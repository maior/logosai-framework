"""LLM 리뷰 출력 파싱 테스트 (2026-08-21).

왜 파서가 따로 필요한가
─────────────────────
"문자열 배열로 달라"고 지시해도 객체 배열이 돌아온다. 프롬프트로 고치려다 실패한
전례가 있고, 결론은 **형태 고정은 소비하는 쪽에서 한다**였다(R-010 이 그 사고에서
나온 규칙이다). 리뷰어가 우리 규칙을 어기면 우습다.

침묵 금지 — 우리 자신의 규칙을 우리가 지킨다
──────────────────────────────────────
버려진 발견은 **이유와 함께 반환한다**. 조용히 떨구면 R-002(침묵 실패)를 우리가
저지르는 셈이고, "리뷰어가 아무것도 못 찾았다"와 "리뷰어 출력이 깨졌다"를
구분할 수 없게 된다. Phase 0 census 의 신뢰도가 여기 걸린다.

직접 실행: python tests/test_review_parse.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logosai.review.parse import parse_llm_findings  # noqa: E402

SOURCE = '''\
class Agent:
    async def process(self, query, context=None):
        try:
            # A very basic, non-functional placeholder to demonstrate structure.
            return {"success": True, "response": query}
        except Exception:
            pass
'''

CTX = dict(path="agents/x.py", subject_agent="x", agent_revision="rev001")

GOOD = {
    "rule_id": "R-001",
    "severity": "blocker",
    "line": 4,
    "excerpt": "non-functional placeholder",
    "message": "껍데기임을 스스로 밝히고 있다",
}


def _parse(raw):
    return parse_llm_findings(raw, SOURCE, **CTX)


# ─────────────────────────────────────────────────────────────
# 형태 변이 흡수 — 지시해도 다른 모양이 온다
# ─────────────────────────────────────────────────────────────

def test_accepts_bare_list():
    found, rejected = _parse([GOOD])
    assert len(found) == 1 and not rejected


def test_accepts_findings_key_wrapper():
    found, rejected = _parse({"findings": [GOOD]})
    assert len(found) == 1, rejected


def test_accepts_json_string():
    import json
    found, rejected = _parse(json.dumps({"findings": [GOOD]}))
    assert len(found) == 1, rejected


def test_accepts_markdown_fenced_json():
    """LLM 은 지시해도 코드펜스를 붙인다."""
    import json
    raw = "```json\n" + json.dumps([GOOD]) + "\n```"
    found, rejected = _parse(raw)
    assert len(found) == 1, rejected


def test_accepts_single_object_not_wrapped_in_list():
    found, rejected = _parse(GOOD)
    assert len(found) == 1, rejected


def test_empty_output_is_not_an_error():
    """아무것도 못 찾은 것은 정상이다. 조용한 시스템을 매번 경고로 만들지 않는다."""
    found, rejected = _parse([])
    assert found == [] and rejected == []


# ─────────────────────────────────────────────────────────────
# 거부는 조용하지 않다
# ─────────────────────────────────────────────────────────────

def test_unknown_rule_is_rejected_with_reason():
    found, rejected = _parse([dict(GOOD, rule_id="R-999")])
    assert not found and len(rejected) == 1
    assert "rule_id" in rejected[0]["reason"], rejected


def test_fabricated_excerpt_is_rejected_with_reason():
    """리뷰어가 지어낸 인용은 버린다 — 이게 오학습 차단의 최전선이다."""
    found, rejected = _parse([dict(GOOD, excerpt="TODO: 여기에 구현")])
    assert not found and len(rejected) == 1
    assert "증거" in rejected[0]["reason"] or "발췌" in rejected[0]["reason"], rejected


def test_missing_field_is_rejected_not_crashed():
    bad = {k: v for k, v in GOOD.items() if k != "excerpt"}
    found, rejected = _parse([bad])
    assert not found and len(rejected) == 1


def test_unparseable_output_is_rejected_not_crashed():
    found, rejected = _parse("나는 리뷰를 잘 수행했습니다. 문제가 없어 보입니다.")
    assert not found and len(rejected) == 1
    assert rejected[0]["reason"], "이유 없이 버리지 않는다"


def test_non_integer_line_is_coerced_or_rejected():
    found, rejected = _parse([dict(GOOD, line="4")])
    assert len(found) == 1 or (rejected and "line" in rejected[0]["reason"])


def test_partial_batch_keeps_good_and_reports_bad():
    """한 건이 깨졌다고 나머지를 버리지 않는다 — 리뷰어는 한 번에 수십 건을 낸다."""
    found, rejected = _parse([GOOD, dict(GOOD, rule_id="R-999")])
    assert len(found) == 1 and len(rejected) == 1


# ─────────────────────────────────────────────────────────────
# 문맥 주입 — 리뷰어는 자기가 무엇을 보고 있는지 모른다
# ─────────────────────────────────────────────────────────────

def test_parser_stamps_path_and_revision():
    """리비전 스탬프가 없으면 나중에 개선을 코드 개정에 귀속시킬 수 없다."""
    found, _ = _parse([GOOD])
    assert found[0].path == "agents/x.py"
    assert found[0].agent_revision == "rev001"
    assert found[0].subject_agent == "x"


def test_parser_defaults_target_to_instance():
    """소재지는 리뷰어가 아니라 classify_target 이 집계로 판정한다."""
    found, _ = _parse([GOOD])
    assert found[0].target == "instance"


def test_parser_corrects_off_by_one_line():
    found, _ = _parse([dict(GOOD, line=6)])
    assert found[0].line == 4, "증거 결착으로 교정돼야 한다"


# ─────────────────────────────────────────────────────────────
# 출력 잘림 — 조용히 잃지 않는다
# ─────────────────────────────────────────────────────────────

def test_truncated_output_salvages_complete_findings():
    """LLM 출력에는 토큰 상한이 있고, 큰 파일에서는 반드시 잘린다.

    통째로 버리면 그 조각의 발견이 전부 사라지는데, 로그에는 "JSON 못 읽음"
    한 줄만 남아 **발견 0건과 구분되지 않는다**. census 숫자를 믿을 수 없게 된다.
    완결된 객체는 건지고, 잘렸다는 사실은 이유로 남긴다.
    """
    import json
    body = json.dumps([GOOD, dict(GOOD, line=6, excerpt="except Exception:")])
    truncated = body[:-12] + ', {"rule_id": "R-00'   # 마지막 객체가 잘린 모양
    found, rejected = _parse(truncated)
    assert len(found) >= 1, f"완결된 발견을 건지지 못했다: {rejected}"
    assert rejected, "잘렸다는 사실이 보고되지 않았다"
    assert "잘" in rejected[0]["reason"], rejected


def test_truncation_reason_is_distinct_from_garbage():
    """'잘림'과 '애초에 JSON 이 아님'은 다른 처방이 필요하다 — 구분한다."""
    _, rej_garbage = _parse("리뷰를 마쳤습니다. 특이사항 없습니다.")
    assert rej_garbage and "잘" not in rej_garbage[0]["reason"], rej_garbage


def test_salvage_does_not_invent_partial_objects():
    """반쯤 온 객체를 추측으로 완성하지 않는다."""
    import json
    body = json.dumps([GOOD])
    truncated = body[:-1] + ', {"rule_id": "R-002", "severity": "ma'
    found, _ = _parse(truncated)
    assert all(f.rule_id == "R-001" for f in found), [f.rule_id for f in found]


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
