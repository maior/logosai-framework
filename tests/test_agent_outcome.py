"""에이전트 결과가 실패인가 — 판정의 정본 (2026-08-22).

왜 이 파일이 생겼나
─────────────────
`execution_feedback` 2,312행 중 실패 기록이 **0건**이었다. 실패율 0%가 아니라
실패를 **기록할 수 없는** 상태였다. 원인은 sse_handlers 의 `_is_error` 가
비스트리밍 분기 안에서만 대입되는데, 실측 191건이 전부 스트리밍 분기였다는 것 —
탐지 블록은 그 로그에서 단 한 번도 실행된 적이 없다.

그 결과 CLAUDE.md 가 열거한 품질 게이트가 전부 상수 위에서 돌았다:
회로차단기(실패율)는 열리지 않고, Shadow test(3중 66%)는 항상 통과하고,
지속 개선 스캔은 약한 에이전트를 찾지 못하고, G1 리비전 귀속은
`calculator_agent 5a8206550824 → success 5 / failure 0` 을 보고했다 —
그날 그 에이전트는 **모든 호출이 429 로 실패**했다.

판정을 왜 순수 함수로 내리나
──────────────────────────
같은 질문("이 결과가 실패인가")이 4곳 이상에서 필요한데 오늘은 **서로 다르게**
중복돼 있다 — 비스트리밍엔 풍부한 판정이, 스트리밍엔 execution_result 만 보는
반쪽이, multi 엔 아예 없다(예외가 안 났으면 성공). 한 곳에서만 고치면 나머지가
곧 갈라진다. 그래서 판정은 여기 하나뿐이고 호출부는 배선만 한다.

bool 이 아니라 사유 문자열을 돌려주는 이유
──────────────────────────────────────
모든 호출부가 "실패했나"와 "왜"를 **둘 다** 필요로 한다(error_message).
bool 을 돌려주면 사유 추출이 호출부마다 또 중복된다. 빈 문자열이 성공이므로
`if failure_reason(x):` 로 그대로 쓴다.

직접 실행: python tests/test_agent_outcome.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logosai.agent_outcome import failure_reason  # noqa: E402


class _Type:
    def __init__(self, value):
        self.value = value


class _Resp:
    """AgentResponse 의 최소 모양 (실물을 import 하면 pydantic 을 끌고 온다)."""

    def __init__(self, value, content):
        self.type = _Type(value)
        self.content = content


# ─────────────────────────────────────────────────────────────
# 실제로 유실됐던 모양 — 이게 이 파일의 존재 이유다
# ─────────────────────────────────────────────────────────────

# 2026-08-22 02:52, ACP /stream 에서 그대로 받아낸 complete 이벤트의 data.
# 요약하거나 다듬지 않는다 — 실물이어야 회귀를 잡는다.
WIRE_429 = {
    "result": {
        "error": "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
                 "'Your prepayment credits are depleted.', 'status': 'RESOURCE_EXHAUSTED'}}"
    },
    "response_type": "ERROR",
    "message": "계산 처리 오류: 429 RESOURCE_EXHAUSTED.",
    "metadata": {},
}


def test_streaming_complete_event_with_error_is_a_failure():
    """이 한 건이 191번 성공으로 기록됐다."""
    reason = failure_reason(WIRE_429)
    assert reason, "429 실패가 성공으로 판정됐다"
    assert "429" in reason, f"사유에 원인이 남지 않았다: {reason!r}"


def test_response_type_error_alone_is_a_failure():
    """result 안에 error 키가 없어도 response_type 만으로 실패다."""
    assert failure_reason({"response_type": "ERROR", "result": {"answer": "x"}})


def test_response_type_is_case_insensitive():
    assert failure_reason({"response_type": "error", "result": {}})


def test_success_response_type_is_not_a_failure():
    assert failure_reason({"response_type": "success", "result": {"answer": "7"}}) == ""


# ─────────────────────────────────────────────────────────────
# 비스트리밍 분기가 이미 잡던 것들 — 이관하며 잃지 않았는지
# ─────────────────────────────────────────────────────────────

def test_agent_response_error_type():
    assert failure_reason(_Resp("ERROR", {"error": "boom"}))


def test_agent_response_lowercase_error_type():
    assert failure_reason(_Resp("error", {}))


def test_agent_response_success_type():
    assert failure_reason(_Resp("SUCCESS", {"answer": "ok"})) == ""


def test_nested_result_is_unwrapped():
    """일부 에이전트는 {"result": {...}} 로 한 겹 감싼다."""
    assert failure_reason({"result": {"error": "inner failure"}})


def test_execution_result_success_false():
    assert failure_reason({"execution_result": {"success": False, "error": "런타임 오류"}})


def test_execution_result_success_true_is_not_a_failure():
    assert failure_reason({"execution_result": {"success": True}}) == ""


def test_execution_verified_false_with_codegen_error():
    assert failure_reason({"execution_verified": False, "code": "# 코드 생성 오류\npass"})


def test_execution_verified_false_with_error_explanation():
    assert failure_reason({"execution_verified": False, "explanation": "오류가 발생했습니다"})


def test_execution_verified_false_alone_is_not_a_failure():
    """검증을 못 했다는 것과 실패했다는 것은 다르다 (사상 ⑦: 모름 ≠ 없음)."""
    assert failure_reason({"execution_verified": False, "code": "print(1)"}) == ""


# ─────────────────────────────────────────────────────────────
# 지어내지 않기 — 애매하면 실패라고 하지 않는다
# ─────────────────────────────────────────────────────────────

def test_empty_error_string_is_not_a_failure():
    """error 키가 있으나 비어 있으면 실패가 아니다. 키 존재 ≠ 실패."""
    assert failure_reason({"error": ""}) == ""
    assert failure_reason({"error": None}) == ""


def test_plain_success_content():
    assert failure_reason({"answer": "42", "confidence": 0.9}) == ""


def test_none_and_scalars_are_not_failures():
    """판정할 근거가 없으면 실패라고 하지 않는다."""
    assert failure_reason(None) == ""
    assert failure_reason("텍스트 응답") == ""
    assert failure_reason(42) == ""
    assert failure_reason({}) == ""


def test_response_object_content_is_inspected():
    """봉투는 SUCCESS 인데 내용이 실패인 경우 — 이 부류가 리뷰 계층의 출발점이었다."""
    assert failure_reason(_Resp("SUCCESS", {"execution_result": {"success": False}}))


def test_list_content_does_not_crash():
    assert failure_reason(_Resp("SUCCESS", ["a", "b"])) == ""


# ─────────────────────────────────────────────────────────────
# 사유는 쓸 만해야 한다
# ─────────────────────────────────────────────────────────────

def test_reason_is_bounded():
    """error_message 컬럼에 그대로 들어간다. 무한정 길면 안 된다."""
    huge = {"error": "x" * 10000}
    assert 0 < len(failure_reason(huge)) <= 500


def test_reason_names_the_signal_when_no_message_available():
    """response_type 만으로 실패인 경우에도 사유가 비면 안 된다 —
    빈 사유는 '실패했는데 왜인지 모름'을 '성공'과 구분 못 하게 만든다."""
    reason = failure_reason({"response_type": "ERROR", "result": {}})
    assert reason.strip(), "사유가 비었다"


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
