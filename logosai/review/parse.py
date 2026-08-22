"""LLM 리뷰 출력 → ReviewFinding (2026-08-21).

형태 고정은 소비하는 쪽에서 한다
──────────────────────────
"이 스키마로 달라"고 지시해도 다른 모양이 온다 — 배열 대신 객체, 코드펜스,
문자열화된 JSON. 프롬프트로 고치려다 실패한 전례가 있고 결론은 소비자 정규화였다.
R-010 이 그 사고에서 나온 규칙이니, 리뷰어 자신이 그걸 어기면 우습다.

버린 것은 이유와 함께 돌려준다
──────────────────────────
조용히 떨구면 R-002(침묵 실패)를 우리가 저지르는 셈이다. 더 실질적으로는
"리뷰어가 아무것도 못 찾았다"와 "리뷰어 출력이 깨졌다"를 구분할 수 없게 되고,
그러면 Phase 0 census 의 숫자를 믿을 수 없다.

이 모듈도 표준 라이브러리만 쓴다.
"""

import json
import re
from typing import Any, Dict, List, Tuple

from .finding import EvidenceError, ReviewFinding, bind_evidence, validate_finding
from .regions import prose_lines

_FENCE = re.compile(r"^\s*```(?:json|python)?\s*|\s*```\s*$", re.IGNORECASE)


def _strip_fence(text: str) -> str:
    out = _FENCE.sub("", text.strip())
    return out.strip()


def _salvage_objects(text: str) -> List[dict]:
    """잘린 JSON 에서 **완결된** 최상위 객체만 건진다.

    LLM 출력에는 토큰 상한이 있어 큰 파일에서는 반드시 잘린다. 통째로 버리면 그
    조각의 발견이 전부 사라지는데, 로그에는 "JSON 못 읽음" 한 줄만 남아
    **발견 0건과 구분되지 않는다** — census 숫자를 믿을 수 없게 된다.

    반쯤 온 객체는 **추측으로 완성하지 않는다**. 지어내는 것이 놓치는 것보다 나쁘다.
    """
    out: List[dict] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                    except ValueError:
                        pass
                    else:
                        if isinstance(obj, dict):
                            out.append(obj)
                    start = -1
    return out


def _as_items(raw: Any) -> Tuple[List[Any], str]:
    """어떤 모양으로 와도 항목 목록으로 편다.

    Returns:
        (항목, 사유). **둘 다 비지 않을 수 있다** — 잘린 출력에서 일부를 건진 경우다.
        호출자는 사유를 거부로 기록하되 건진 항목은 처리해야 한다.
    """
    if isinstance(raw, str):
        text = _strip_fence(raw)
        if not text:
            return [], ""
        try:
            raw = json.loads(text)
        except (ValueError, TypeError) as e:
            salvaged = _salvage_objects(text)
            if salvaged:
                return salvaged, (
                    f"출력이 잘린 것으로 보인다 — 완결된 {len(salvaged)}건만 건졌다 "
                    f"(그 뒤 발견은 유실). 원인: {e}"
                )
            return [], f"JSON 으로 읽을 수 없다: {e}"

    if isinstance(raw, dict):
        for key in ("findings", "results", "items"):
            if isinstance(raw.get(key), list):
                return raw[key], ""
        # 감싸지 않고 단건으로 온 경우
        if "rule_id" in raw:
            return [raw], ""
        return [], f"발견 목록을 찾을 수 없다 (키: {sorted(raw)[:6]})"

    if isinstance(raw, list):
        return raw, ""

    return [], f"지원하지 않는 출력 타입: {type(raw).__name__}"


def _coerce_line(value: Any) -> int:
    """LLM 은 행 번호를 문자열로 주기도 한다. 숫자면 받되 지어내지는 않는다."""
    if isinstance(value, bool):
        return -1
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return -1


def parse_llm_findings(
    raw: Any,
    source: str,
    *,
    path: str,
    subject_agent: str = "",
    agent_revision: str = "",
    window: int = 3,
) -> Tuple[List[ReviewFinding], List[Dict[str, Any]]]:
    """리뷰어 출력을 검증된 발견으로 바꾼다.

    Returns:
        (통과한 발견, 버린 것들[{"raw": ..., "reason": ...}])

    한 건이 깨져도 나머지는 살린다 — 리뷰어는 한 번에 수십 건을 낸다.
    소재지(target)는 여기서 판정하지 않는다. 개체 하나만 보고는 템플릿 결함인지
    알 수 없고, classify_target 이 파일 간 집계로 정한다.
    """
    accepted: List[ReviewFinding] = []
    rejected: List[Dict[str, Any]] = []

    items, err = _as_items(raw)
    if err:
        rejected.append({"raw": raw, "reason": err})
    if not items:
        # 사유는 이미 기록됐다. 건질 것이 없을 때만 여기서 끝난다.
        return accepted, rejected

    # 증거로 쓸 수 없는 행 — 다중행 데이터 문자열의 내부.
    # None 이면 파싱 불가라 확인하지 못한 것이므로 필터를 걸지 않는다.
    prose = prose_lines(source)

    for item in items:
        if not isinstance(item, dict):
            rejected.append({"raw": item, "reason": f"항목이 dict 가 아니다: {type(item).__name__}"})
            continue

        candidate = ReviewFinding(
            rule_id=str(item.get("rule_id", "")).strip(),
            severity=str(item.get("severity", "")).strip().lower(),
            path=path,
            line=_coerce_line(item.get("line")),
            excerpt=str(item.get("excerpt", "") or ""),
            target="instance",
            message=str(item.get("message", "") or ""),
            subject_agent=subject_agent,
            agent_revision=agent_revision,
        )

        errs = validate_finding(candidate)
        if errs:
            rejected.append({"raw": item, "reason": "; ".join(errs)})
            continue

        try:
            bound = bind_evidence(candidate, source, window=window)
        except EvidenceError as e:
            rejected.append({"raw": item, "reason": str(e)})
            continue

        # 결착된 **교정 후** 행으로 판정한다 — 교정 전 행으로 보면 어긋난다.
        if prose is not None and bound.line in prose:
            rejected.append({
                "raw": item,
                "reason": (
                    f"{bound.path}:{bound.line} 은 데이터 문자열 내부다 — "
                    f"프로그램이 다루는 값이지 코드의 주장이 아니다"
                ),
            })
            continue

        accepted.append(bound)

    return accepted, rejected
