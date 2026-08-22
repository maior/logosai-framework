"""증거가 될 수 있는 영역과 없는 영역 (2026-08-21).

Phase 0 표본이 찾아낸 거짓양성에서 나왔다. tetris_game_agent.py:885-897 이
R-001(껍데기)로 10건 잡혔는데, 실제로는 사용자에게 보여줄 안내 문자열 안의 기능
목록이었다 — 리뷰어가 프로그램 **데이터**를 코드의 주장으로 읽었다.

경계는 '문자열이냐'가 아니라 '저자의 진술이냐'다:

    주석        저자가 코드에 대해 하는 말   → 증거 가능
    docstring   저자가 코드에 대해 하는 말   → 증거 가능
    데이터 문자열  프로그램이 다루는 값       → 증거 불가

이 구분을 지켜야 하는 이유는 실증적이다 — 387dc0b3 에서 가장 강한 증거 두 개가
주석과 docstring 이었다. 문자열이라고 전부 막으면 진짜 결함을 잃는다.

한 줄짜리 문자열도 막으면 안 된다. R-003·R-009(하드코딩 열거)의 증거가 바로
`("ppt", "프레젠테이션")` 같은 코드 안의 문자열이기 때문이다. 그래서 막는 것은
**다중행 문자열의 내부 행**뿐이고, 첫 행은 코드가 함께 있을 수 있어 남긴다.

프롬프트로 타이르지 않고 구조로 막는 이유: 형태 지시를 프롬프트로 고치려다 실패한
전례가 있다(R-010 이 그 사고에서 나온 규칙이다). 판정 가능한 것은 판정한다.
"""

import ast
from typing import Optional, Set


def _docstring_spans(tree: ast.AST) -> Set[tuple]:
    """docstring 노드의 (시작행, 끝행) 집합.

    docstring 은 저자의 진술이므로 증거가 될 수 있다 — 데이터 문자열과 구별해야 한다.
    """
    spans = set()
    targets = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, targets):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(getattr(first, "value", None), ast.Constant)
            and isinstance(first.value.value, str)
        ):
            spans.add((first.value.lineno, getattr(first.value, "end_lineno", first.value.lineno)))
    return spans


def prose_lines(source: str) -> Optional[Set[int]]:
    """증거로 쓸 수 없는 행 번호 집합 — 다중행 데이터 문자열의 내부.

    Returns:
        행 번호 집합. 파싱할 수 없으면 **None**.

    None 과 빈 집합을 구분하는 이유: 확인하지 못한 것을 "제외할 것 없음"으로
    뭉개면 모름이 정상으로 위장한다(R-008 이 그 사고에서 나온 규칙이다).
    호출자는 None 일 때 필터를 걸지 않는다 — 거짓양성을 남기는 쪽이 진짜 발견을
    잃는 것보다 낫다.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    docstrings = _docstring_spans(tree)
    out: Set[int] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            start, end = node.lineno, getattr(node, "end_lineno", node.lineno)
        elif isinstance(node, ast.JoinedStr):  # f-string
            start, end = node.lineno, getattr(node, "end_lineno", node.lineno)
        else:
            continue

        if end <= start:
            continue  # 한 줄 문자열 — 코드의 일부다
        if (start, end) in docstrings:
            continue  # 저자의 진술

        # 첫 행에는 `return f\"\"\"` 처럼 코드가 함께 있다. 내부만 제외한다.
        out.update(range(start + 1, end + 1))

    # f-string 내부에 중첩된 상수가 docstring 범위를 덮는 경우를 되돌린다.
    for start, end in docstrings:
        out.difference_update(range(start, end + 1))

    return out
