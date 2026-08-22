"""증거가 될 수 있는 영역과 없는 영역 (2026-08-21).

Phase 0 표본에서 드러난 거짓양성
────────────────────────────
tetris_game_agent.py:885-897 이 R-001(껍데기)로 10건 잡혔다. 실제로는 사용자에게
보여줄 **안내 문자열** 안의 기능 목록이었다 — "- 완전한 테트리스 게임 구현",
"- 반응형 디자인 적용". 리뷰어가 프로그램 **데이터**를 코드의 주장으로 읽었다.

경계는 '문자열이냐'가 아니라 '저자의 진술이냐'다
──────────────────────────────────────────
  주석      저자가 코드에 대해 하는 말   → 증거 가능
  docstring 저자가 코드에 대해 하는 말   → 증거 가능
  데이터 문자열 프로그램이 다루는 값     → 증거 불가

이 구분이 중요한 이유: 387dc0b3 의 가장 강한 증거는 주석("# non-functional
placeholder")과 docstring 이었다. 문자열이라고 전부 막으면 진짜를 잃는다.

그리고 한 줄짜리 문자열은 막으면 안 된다
──────────────────────────────────────
R-003·R-009(하드코딩 열거)의 증거는 `("ppt", "프레젠테이션")` 같은 **코드 안의
문자열**이다. 그래서 막는 것은 다중행 문자열의 **내부 행**뿐이다 — 첫 행은
코드가 함께 있을 수 있으므로 남긴다.

파싱 실패는 빈 집합이 아니라 None
──────────────────────────────
확인하지 못한 것을 "제외할 것 없음"으로 뭉개면 모름이 정상으로 위장한다(R-008).
None 으로 구분하고, 그때는 필터를 걸지 않는다 — 진짜 발견을 잃는 쪽이 더 나쁘다.

직접 실행: python tests/test_review_regions.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logosai.review.parse import parse_llm_findings  # noqa: E402
from logosai.review.regions import prose_lines  # noqa: E402

# 실물 구조를 그대로 옮긴 표본 (tetris + 387dc0b3 의 두 형태를 한 파일에)
SOURCE = '''\
class Demo:
    """이 클래스는 시연용이다.

    This is a placeholder and would ideally use a real table.
    """

    def render(self, difficulty, theme):
        # A very basic, non-functional placeholder to demonstrate structure.
        return f"""
2. HTML5 Canvas 및 JavaScript 기반 게임 생성
   - 완전한 테트리스 게임 구현
   - 반응형 디자인 적용
"""

    def route(self, q):
        if any(w in q for w in ("ppt", "프레젠테이션", "발표")):
            return "pptx"
        return "other"
'''
# 행 번호:
#   2-5   클래스 docstring        (증거 가능)
#   8     주석                    (증거 가능)
#   9-13  반환용 다중행 f-string   (10-13 이 내부 = 증거 불가)
#   16    한 줄 안의 문자열 튜플   (증거 가능)


def test_prose_excludes_interior_of_multiline_data_string():
    lines = prose_lines(SOURCE)
    assert 11 in lines, "데이터 문자열 내부가 제외되지 않았다"
    assert 12 in lines


def test_prose_keeps_docstring_usable_as_evidence():
    """387dc0b3 의 가장 강한 증거가 docstring 이었다. 막으면 진짜를 잃는다."""
    lines = prose_lines(SOURCE)
    assert 4 not in lines, "docstring 이 증거에서 배제됐다"


def test_prose_keeps_comment_usable_as_evidence():
    lines = prose_lines(SOURCE)
    assert 8 not in lines, "주석이 증거에서 배제됐다"


def test_prose_keeps_single_line_string_literals():
    """R-003·R-009 의 증거는 코드 안의 문자열이다. 막으면 그 규칙이 죽는다."""
    lines = prose_lines(SOURCE)
    assert 16 not in lines, "한 줄 문자열이 배제되어 하드코딩 규칙이 무력화된다"


def test_prose_keeps_first_line_of_multiline_string():
    """첫 행에는 코드가 함께 있다 (return f\"\"\" 처럼)."""
    lines = prose_lines(SOURCE)
    assert 9 not in lines


def test_prose_returns_none_when_source_unparseable():
    """모름 ≠ 없음. 확인 못 했으면 필터를 걸지 않는다."""
    assert prose_lines("def broken(:\n    pass\n") is None


# ─────────────────────────────────────────────────────────────
# 파서 통합
# ─────────────────────────────────────────────────────────────

CTX = dict(path="agents/demo.py", subject_agent="demo", agent_revision="r1")


def test_parser_rejects_evidence_inside_data_string():
    found, rejected = parse_llm_findings([{
        "rule_id": "R-001", "severity": "blocker", "line": 11,
        "excerpt": "완전한 테트리스 게임 구현", "message": "기능을 과장한다",
    }], SOURCE, **CTX)
    assert not found, "데이터 문자열이 증거로 통과했다"
    assert rejected and ("문자열" in rejected[0]["reason"] or "데이터" in rejected[0]["reason"])


def test_parser_accepts_evidence_in_comment():
    found, rejected = parse_llm_findings([{
        "rule_id": "R-001", "severity": "blocker", "line": 8,
        "excerpt": "non-functional placeholder", "message": "껍데기다",
    }], SOURCE, **CTX)
    assert len(found) == 1, rejected


def test_parser_accepts_evidence_in_docstring():
    found, rejected = parse_llm_findings([{
        "rule_id": "R-001", "severity": "blocker", "line": 4,
        "excerpt": "This is a placeholder", "message": "껍데기다",
    }], SOURCE, **CTX)
    assert len(found) == 1, rejected


def test_parser_accepts_hardcoded_keyword_list_as_evidence():
    found, rejected = parse_llm_findings([{
        "rule_id": "R-009", "severity": "minor", "line": 16,
        "excerpt": '"ppt", "프레젠테이션"', "message": "열거 하드코딩",
    }], SOURCE, **CTX)
    assert len(found) == 1, rejected


def test_parser_does_not_filter_when_source_unparseable():
    broken = "def f(:\n  pass\n# non-functional placeholder\n"
    found, rejected = parse_llm_findings([{
        "rule_id": "R-001", "severity": "blocker", "line": 3,
        "excerpt": "non-functional placeholder",        "message": "껍데기다",
    }], broken, **CTX)
    assert len(found) == 1, rejected


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
