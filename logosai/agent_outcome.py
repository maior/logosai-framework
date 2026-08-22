"""에이전트 결과가 실패인가 — 판정의 정본 (2026-08-22).

왜 이 모듈이 생겼나
─────────────────
`execution_feedback` 2,312행 중 실패 기록이 **0건**이었다. 실패율 0%가 아니라
실패를 기록할 수 없는 상태였다. sse_handlers 의 `_is_error` 가 비스트리밍
분기에서만 대입되는데 실측 191건이 전부 스트리밍 분기였다 — 탐지 블록은 그
로그에서 한 번도 실행되지 않았다.

그 위에서 CLAUDE.md 가 열거한 품질 게이트가 전부 상수를 재고 있었다:
회로차단기(실패율)는 열리지 않고, Shadow test(3중 66%)는 항상 통과하고,
지속 개선 스캔은 약한 에이전트를 찾지 못한다. G1 리비전 귀속은
`calculator_agent 5a8206550824 → success 5 / failure 0` 을 보고했는데,
그날 그 에이전트는 **모든 호출이 429 로 실패**했다.

'예외가 안 났다' 는 성공이 아니다
──────────────────────────────
멀티 경로는 try/except 를 벗어나면 `success=True` 를 박았다. 그런데 잘 만든
에이전트일수록 예외를 스스로 잡아 `AgentResponse(type=ERROR)` 로 바꾼다 —
즉 **예외를 잘 다룰수록 실패가 안 보인다**. 신호가 거꾸로 걸려 있었다.

판정이 왜 여기 하나뿐인가
──────────────────────
같은 질문이 4곳 이상에서 필요한데 오늘은 서로 다르게 중복돼 있었다:
비스트리밍엔 풍부한 판정, 스트리밍엔 execution_result 만 보는 반쪽,
멀티엔 없음. 사고 자체가 **3벌이 따로 논 결과**다. 복제하면 곧 갈라진다.

지어내지 않는다
─────────────
판정할 근거가 없으면(None, 스칼라, 빈 dict) 실패라고 하지 않는다. 오탐은
회로차단기를 헛되이 열고 멀쩡한 에이전트를 개선 대상으로 만든다 — 지금 문제의
정반대 방향으로 같은 크기의 손상이다.

표준 라이브러리만 쓴다 — 판정은 순수해야 어디서든 같은 답을 낸다.
"""

from typing import Any

__all__ = ["failure_reason"]

_MAX_REASON = 500

# 봉투(AgentResponse.type / 스트리밍 complete 의 response_type)가 실패를 뜻하는 값.
# 대소문자를 섞어 쓰는 곳이 실제로 있어 소문자로 비교한다.
_ERROR_TYPES = ("error",)

# 코드 생성 에이전트가 실패를 알리는 방식. execution_verified=False 만으로는
# 실패가 아니다 — 검증을 못 했다는 것과 실패했다는 것은 다르다 (사상 ⑦).
_CODEGEN_ERROR_PREFIX = "# 코드 생성 오류"
_CODEGEN_ERROR_PHRASE = "오류가 발생"


def _clip(text: Any) -> str:
    s = str(text or "").strip()
    return s[:_MAX_REASON]


def _envelope_type(obj: Any) -> str:
    """봉투의 타입 문자열을 소문자로. 없으면 빈 문자열."""
    t = getattr(obj, "type", None)
    if t is not None:
        return str(getattr(t, "value", t) or "").strip().lower()
    if isinstance(obj, dict):
        return str(obj.get("response_type") or "").strip().lower()
    return ""


def _content_of(obj: Any) -> Any:
    """검사할 본문. AgentResponse 면 .content, dict 면 자기 자신."""
    if hasattr(obj, "content"):
        return obj.content
    return obj


def _reason_in_content(content: Any) -> str:
    """본문에서 실패 사유를 찾는다. 없으면 빈 문자열."""
    if not isinstance(content, dict):
        return ""

    # 일부 에이전트는 {"result": {...}} 로 한 겹 감싼다. 감싼 쪽에 실패 표시가
    # 없어도 안쪽에 있을 수 있으므로 두 겹 다 본다.
    layers = [content]
    inner = content.get("result")
    if isinstance(inner, dict):
        layers.append(inner)

    for layer in layers:
        err = layer.get("error")
        if err:  # 키 존재가 아니라 값이 있어야 실패다 ("" / None 은 아니다)
            return _clip(err)

        exec_result = layer.get("execution_result")
        if isinstance(exec_result, dict) and exec_result.get("success") is False:
            return _clip(exec_result.get("error") or "execution_result.success=False")

        if layer.get("execution_verified") is False:
            code = str(layer.get("code") or "")
            explanation = str(layer.get("explanation") or "")
            if code.startswith(_CODEGEN_ERROR_PREFIX):
                return _clip(code)
            if _CODEGEN_ERROR_PHRASE in explanation:
                return _clip(explanation)
    return ""


def failure_reason(obj: Any) -> str:
    """이 결과가 실패면 사유를, 아니면 빈 문자열을 돌려준다.

    bool 이 아니라 사유인 이유: 모든 호출부가 "실패했나"와 "왜"를 둘 다 쓴다
    (error_message 컬럼). bool 이면 사유 추출이 호출부마다 또 중복된다.

    Args:
        obj: AgentResponse 같은 객체, 스트리밍 complete 이벤트의 data(dict),
             또는 본문 dict. 그 밖의 타입은 판정 근거가 없으므로 성공으로 본다.

    Returns:
        실패 사유 (최대 500자) 또는 "". 빈 문자열이 성공이므로
        `if failure_reason(x):` 로 그대로 쓴다.
    """
    content = _content_of(obj)

    # 본문 사유가 봉투보다 구체적이라 먼저 찾는다 — 봉투가 SUCCESS 인데
    # 내용이 실패인 부류가 코드 리뷰 계층의 출발점이었다.
    reason = _reason_in_content(content)
    if reason:
        return reason

    if _envelope_type(obj) in _ERROR_TYPES:
        # 봉투만 ERROR 이고 사유를 못 찾은 경우. 사유를 비워 두면
        # "실패했는데 왜인지 모름"이 "성공"과 구분되지 않는다.
        msg = getattr(obj, "message", None)
        if not msg and isinstance(obj, dict):
            msg = obj.get("message")
        return _clip(msg) or "response_type=ERROR (사유 미상)"

    return ""
