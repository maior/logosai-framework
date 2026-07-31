"""fire-and-forget 전송이 실제로 실행돼야 한다 (2026-07-31).

배경 — FORGE 생성 과정을 Pulse 로 보려는데 span 이 **한 건도 도착하지 않았다**.
그런데 로그에는 전송 실패조차 없었다:

    Span start: agent.QueryAnalyzerAgent (trace=7485943a, parent=root)
    Span end:   agent.QueryAnalyzerAgent (1250ms, success)
    (pulse 관련 로그 없음 — 실패도 성공도)

원인: `send_span_bg` 가
    asyncio.ensure_future(send_span(**kwargs))
로 태스크만 만들고 **참조를 잡지 않는다**. 파이썬은 참조 없는 Task 를 GC 할 수
있고, 바쁜 루프(LLM·AST·파일 IO)에서는 실행 기회를 얻기 전에 사라진다.
게다가 감싼 `except: pass` 가 흔적을 지운다.

즉 "전송 실패"가 아니라 **전송 자체가 일어나지 않았다**. 관측이 통째로 비는데
경고 하나 남지 않는 종류의 결함이다.

계약:
  B1. 배경 전송 태스크는 완료될 때까지 참조가 유지된다.
  B2. 실행 중인 루프가 없으면 조용히 버리지 않는다 (스풀 또는 실패 기록).

직접 실행: python3 tests/test_pulse_bg_task_retention.py
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logosai.utils import pulse_client


def test_b1_background_task_is_retained_and_runs():
    """B1 ★ 실측 재현: 참조를 안 잡으면 태스크가 실행되지 않는다."""
    calls = []

    async def _fake_post(endpoint, data):
        calls.append(endpoint)

    orig = pulse_client._post
    pulse_client._post = _fake_post
    try:
        async def scenario():
            pulse_client.send_span_bg(
                span_id="s1", trace_id="t1", name="probe",
                agent_id="probe", duration_ms=1, status="success")
            # 루프가 바쁜 상황 흉내 — 여러 틱 양보
            for _ in range(5):
                await asyncio.sleep(0)
            await asyncio.sleep(0.05)
            pending = [t for t in asyncio.all_tasks()
                       if t is not asyncio.current_task()]
            for t in pending:
                try:
                    await asyncio.wait_for(t, timeout=2)
                except Exception:
                    pass

        asyncio.run(scenario())
    finally:
        pulse_client._post = orig

    assert calls, "배경 전송이 실행되지 않았다 (태스크 참조 미보유 → GC)"
    assert calls[0].endswith("/span"), f"엉뚱한 엔드포인트: {calls}"


def test_b2_no_running_loop_is_not_silently_dropped():
    """B2: 루프 없이 호출되면 조용히 사라지면 안 된다 (스풀 또는 실패 기록)."""
    spool = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "_probe_spool.jsonl")
    if os.path.exists(spool):
        os.unlink(spool)
    orig_spool = pulse_client._SPOOL_PATH
    pulse_client._SPOOL_PATH = spool
    before = dict(pulse_client._stats)
    try:
        pulse_client.send_span_bg(
            span_id="s2", trace_id="t2", name="noloop",
            agent_id="probe", duration_ms=1, status="success")
        spooled = os.path.exists(spool) and os.path.getsize(spool) > 0
        after = dict(pulse_client._stats)
        recorded = after.get("failed", 0) > before.get("failed", 0)
        assert spooled or recorded, \
            "루프 없이 호출된 전송이 흔적 없이 사라졌다"
    finally:
        pulse_client._SPOOL_PATH = orig_spool
        if os.path.exists(spool):
            os.unlink(spool)


def _run():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failed.append(name)
        except Exception as e:
            print(f"  💥 {name}: {type(e).__name__}: {e}")
            failed.append(name)
    print(f"\n{passed}/{len(tests)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(_run())
