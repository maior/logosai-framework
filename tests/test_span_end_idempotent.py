"""TraceSpan.end() 는 두 번 불려도 한 번만 센다 (2026-08-09).

배경: 여정의 root span 종료가 **분기마다 손으로** 호출되고 있었고,
`FORGE_VIA_API` gap 분기 하나가 `end()` 없이 `return` 했다 → 그 경로에서만
ingress 행이 통째로 사라졌다 (자식들은 ContextVar 로 trace_id·parent_id 를
받았으므로 계보는 멀쩡한 채 부모만 없는 trace 가 됐다).

올바른 수정은 "빠뜨린 분기에 한 줄 더" 가 아니라 **finally 로 보장**하는 것이다.
그러려면 이미 닫힌 span 을 다시 닫아도 안전해야 한다 — 안 그러면
정상 분기가 이중 전송하고, ContextVar 토큰 재사용으로 예외까지 난다.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 전송 차단은 pytest 하에서 자동이다(`pulse_client._sending_blocked`).
# 여기서 `os.environ` 을 세우면 **프로세스 전역**으로 남아 다른 파일의
# 전송 검증 테스트를 죽인다 — 오늘 그 결함을 고치고 나서 똑같이 반복했다.
from logosai.utils.trace_span import TraceSpan  # noqa: E402


def _count_sends(fn):
    """end() 가 전송을 몇 번 시도하는지 센다."""
    import logosai.utils.pulse_client as pc
    calls = []
    original = pc.send_span_bg
    pc.send_span_bg = lambda **kw: calls.append(kw)
    try:
        fn()
    finally:
        pc.send_span_bg = original
    return calls


def test_second_end_does_not_send_again():
    span = TraceSpan.start("test.idempotent", agent_id="t")
    calls = _count_sends(lambda: (span.end(success=True, output="first"),
                                  span.end(success=True, output="second")))
    assert len(calls) == 1, f"end() 두 번에 전송 {len(calls)}회 — 이중 계상"
    assert calls[0]["output_text"] == "first", "두 번째 호출이 결과를 덮어썼다"


def test_second_end_does_not_raise():
    """ContextVar 토큰을 두 번 reset 하면 ValueError 가 난다."""
    span = TraceSpan.start("test.idempotent2", agent_id="t")
    span.end()
    span.end()  # 예외 없이 통과해야 한다


def test_context_restored_only_once():
    """중복 종료가 부모 컨텍스트를 엉뚱하게 되돌리지 않는다."""
    from logosai.utils.trace_span import get_current_trace_id
    outer = TraceSpan.start("test.outer", agent_id="t")
    inner = TraceSpan.start("test.inner", agent_id="t")
    inner.end()
    inner.end()
    assert get_current_trace_id() == outer.trace_id, "이중 종료가 컨텍스트를 깨뜨렸다"
    outer.end()


def test_first_end_still_sends():
    """멱등성을 넣다가 아예 안 보내는 회귀를 막는다."""
    span = TraceSpan.start("test.sends_once", agent_id="t")
    calls = _count_sends(lambda: span.end(success=False, output="boom"))
    assert len(calls) == 1
    assert calls[0]["status"] == "error"


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = f = 0
    for k, fn in fns:
        try:
            fn(); print(f"  ✓ {k}"); p += 1
        except Exception as e:
            print(f"  ✗ {k}: {type(e).__name__}: {e}"); f += 1
    print(f"\npass={p} fail={f}")
    sys.exit(1 if f else 0)
