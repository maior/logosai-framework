"""RFC 8259 안전 직렬화 유틸.

Python json 은 NaN/±Inf 를 리터럴로 내보내지만(RFC 비호환) 브라우저 JSON.parse 는
거부한다 — SSE 이벤트가 통째로 유실되어 "채팅 무응답"이 된다 (2026-07-14 실측:
analysis normality_test NaN). 에이전트가 반환하는 구조화 데이터는 이 함수로
정화한 뒤 내보내는 것을 표준으로 한다 (경계(logos_api)의 방어와 이중화).
"""

import math
from typing import Any


def json_safe(obj: Any) -> Any:
    """NaN/±Inf → None (재귀). 그 외 값·타입은 보존."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj
