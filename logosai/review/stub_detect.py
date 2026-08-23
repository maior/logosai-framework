"""저자가 스스로 "이건 껍데기다"라고 밝힌 코드 (2026-08-22).

왜 LLM 리뷰어를 게이트로 쓰지 않는가
──────────────────────────────
정밀도 감사(G2) 결과 리뷰 장부의 모집단 정밀도는 **37.3%** [30.0, 44.6] 이다.
그 장부로 배포를 막으면 멀쩡한 개선을 열 번 중 여섯 번 차단한다. 사상 ④ 대로
장부는 **판단의 재료**이지 자동 차단의 근거가 아니다.

그래서 이 모듈은 판단하지 않는다. **저자의 진술을 인용**할 뿐이다 —
"For demonstration purposes, let's define dummy classes" 라고 코드가 스스로
말했으면 그건 추정이 아니라 인용이다. 재검증도 언제든 가능하다.

무엇이 이 모듈을 만들게 했나
──────────────────────────
성공 신호를 살리자 지속 개선 루프가 잠에서 깨어 첫 산출물로
`summarization_agent` 에 더미 클래스를 주입했다:

    # Assuming AgentConfig, AgentType, and LLMClient are defined elsewhere
    # For demonstration purposes, let's define dummy classes:
    class AgentConfig: ...

진짜 import 를 가렸는데 **구문은 통과**해서 기존 게이트 셋(보호 에이전트 ·
confidence ≥ 0.5 · Shadow test 66%)을 모두 지나 배포됐다. 실행이 되느냐만
보는 게이트는 이 부류를 영원히 못 잡는다.

경계: 모듈 docstring 은 세지 않는다
─────────────────────────────────
실측에서 `code_review_agent.py` 가 자기 모듈 docstring 에서 이 사고를
**인용**하다가 잡혔다. 인용과 자기 진술은 다르다. 그래서 판정 대상은
**함수·클래스 본문 안의** 주석과 docstring 뿐이다 — "이 코드 단위가
동작하지 않는다"는 저자의 진술만 본다.

실측 정밀도 (acp_server/agents 285파일)
────────────────────────────────────
발화 11파일 · 전부 `forge_generated_*` 의 진짜 껍데기 · **수기 에이전트 0건**.
census 가 찾은 껍데기 7개와 겹친다.

표준 라이브러리만 쓴다.
"""

import ast
import io
import re
import tokenize
from typing import List, Optional, Tuple

__all__ = ["self_declared_stub", "stub_findings", "STUB_PHRASES"]

#: 저자가 "이 코드는 아직 동작하지 않는다"고 밝히는 관용구.
#:
#: 늘리기 전에 실측할 것 — 목록을 넓히면 오탐이 늘고, 오탐이 늘면 게이트가
#: 무시된다. 각 항목은 실제 생성물에서 관측된 문장에서 왔다.
STUB_PHRASES: Tuple[str, ...] = (
    r"for demonstration purposes",
    r"for illustrative purposes",
    r"dummy class(es)?",
    r"non-?functional placeholder",
    r"this is a placeholder",
    r"placeholder implementation",
    r"placeholder for actual",
    r"in a real (implementation|application)",
    r"replace (this )?with (the )?actual",
    r"실제 구현은 생략",
    r"예시를 위한 (더미|가짜)",
)

_PAT = re.compile("|".join(STUB_PHRASES), re.IGNORECASE)


def _body_ranges(tree: ast.AST) -> List[Tuple[int, int]]:
    """함수·클래스 **본문**의 행 범위. 모듈 최상위는 포함하지 않는다.

    모듈 docstring 에서 사고를 인용하는 것과 함수가 자기를 껍데기라고 밝히는
    것은 다른 진술이다. 실측에서 리뷰어 자신이 전자로 걸렸다.
    """
    out: List[Tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not node.body:
            continue
        start = node.body[0].lineno
        end = max(
            (getattr(n, "end_lineno", None) or n.lineno)
            for n in ast.walk(node)
            if hasattr(n, "lineno")
        )
        out.append((start, end))
    return out


def _in_body(line: int, ranges: List[Tuple[int, int]]) -> bool:
    return any(lo <= line <= hi for lo, hi in ranges)


def _prose_spans(source: str, tree: ast.AST) -> List[Tuple[int, str]]:
    """저자의 진술만 모은다 — 주석 + docstring. 데이터 문자열은 제외.

    (regions.py 가 '증거로 쓸 수 있는 영역'을 판정하는 것과 같은 경계지만,
     여기서는 반대로 **진술 자체를 모으는** 것이라 목적이 다르다.)
    """
    spans: List[Tuple[int, str]] = []

    # 주석
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                spans.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass  # 부분적으로라도 모은다 — 못 읽은 것은 없는 것이 아니다

    # docstring (함수·클래스만. 모듈 docstring 은 위 설명대로 제외)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            continue
        first = node.body[0]
        base = first.lineno
        for off, ln in enumerate(doc.splitlines()):
            spans.append((base + off, ln))
    return spans


def stub_findings(source: str) -> List[Tuple[int, str, str]]:
    """저자가 껍데기라고 밝힌 지점 전부. `(행, 관용구, 그 줄)`.

    파싱 불가면 빈 목록 — 모름을 '있음'으로도 '없음'으로도 단정하지 않고,
    호출자가 별도로 구문 검사를 하도록 둔다 (사상 ⑦).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    ranges = _body_ranges(tree)
    out: List[Tuple[int, str, str]] = []
    seen = set()
    for line, text in _prose_spans(source, tree):
        if not _in_body(line, ranges):
            continue
        m = _PAT.search(text)
        if not m:
            continue
        key = (line, m.group(0).lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((line, m.group(0), text.strip()[:120]))
    return sorted(out)


def self_declared_stub(source: str) -> str:
    """껍데기라고 밝힌 첫 지점의 사유. 아니면 빈 문자열.

    빈 문자열이 통과이므로 `if self_declared_stub(code):` 로 그대로 쓴다.
    사유에는 **저자의 문장을 그대로** 담는다 — 판정이 아니라 인용이라는 것이
    이 게이트를 신뢰할 수 있는 유일한 근거다.
    """
    hits = stub_findings(source)
    if not hits:
        return ""
    line, phrase, text = hits[0]
    more = f" (외 {len(hits) - 1}곳)" if len(hits) > 1 else ""
    return f"{line}행에서 스스로 껍데기라고 밝힘 [{phrase}]: {text}{more}"
