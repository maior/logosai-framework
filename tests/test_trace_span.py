"""TraceSpan 단위 테스트.

테스트:
T1. Span 시작/종료 — ID, 시간, 상태
T2. 부모-자식 관계 — context 전파
T3. 중첩 Span — 3레벨 깊이
T4. 에러 Span — status=error
T5. trace_id 전파 — 동일 트레이스
T6. 성능 — Span 오버헤드 측정

Usage: python tests/test_trace_span.py
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from logosai.utils.trace_span import TraceSpan, get_current_trace_id, get_current_span_id


async def main():
    print("=" * 60)
    print("TraceSpan 단위 테스트")
    print("=" * 60)
    all_pass = True

    # T1: 기본 시작/종료
    print("\n=== T1: Span 시작/종료 ===")
    span = TraceSpan.start("test.process", agent_id="test_agent", input_text="hello")
    await asyncio.sleep(0.05)
    span.end(success=True, output="world")

    ok = (
        len(span.id) == 36 and
        len(span.trace_id) == 36 and
        span.status == "success" and
        span.duration_ms >= 40 and
        span.input_preview == "hello" and
        span.output_preview == "world"
    )
    print(f"  id: {span.id[:12]}...")
    print(f"  trace_id: {span.trace_id[:12]}...")
    print(f"  duration: {span.duration_ms:.0f}ms")
    print(f"  status: {span.status}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # T2: 부모-자식 관계
    print("\n=== T2: 부모-자식 관계 ===")
    parent = TraceSpan.start("parent.process", agent_id="parent")
    child = TraceSpan.start("child.call", agent_id="child")

    ok = (
        child.trace_id == parent.trace_id and  # 같은 trace
        child.parent_id == parent.id            # parent 참조
    )
    print(f"  parent.id: {parent.id[:12]}")
    print(f"  child.parent_id: {child.parent_id[:12]}")
    print(f"  same trace: {child.trace_id == parent.trace_id}")
    print(f"  {'✅' if ok else '❌'}")
    child.end(success=True)
    parent.end(success=True)
    all_pass &= ok

    # T3: 3레벨 중첩
    print("\n=== T3: 3레벨 중첩 ===")
    root = TraceSpan.start("root", agent_id="desktop")
    mid = TraceSpan.start("mid", agent_id="internet")
    leaf = TraceSpan.start("leaf", agent_id="llm_call")

    ok = (
        leaf.trace_id == root.trace_id and
        leaf.parent_id == mid.id and
        mid.parent_id == root.id
    )
    print(f"  root→mid→leaf 계층: {ok}")
    print(f"  root.id={root.id[:8]}, mid.parent={mid.parent_id[:8]}, leaf.parent={leaf.parent_id[:8]}")
    print(f"  {'✅' if ok else '❌'}")
    leaf.end(success=True)
    mid.end(success=True)
    root.end(success=True)
    all_pass &= ok

    # T4: 에러 Span
    print("\n=== T4: 에러 Span ===")
    span = TraceSpan.start("error.test", agent_id="broken")
    span.end(success=False, output="TimeoutError: 30s")

    ok = span.status == "error" and "Timeout" in span.output_preview
    print(f"  status: {span.status}")
    print(f"  output: {span.output_preview}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # T5: trace_id 전파
    print("\n=== T5: trace_id 전파 ===")
    custom_trace = "custom-trace-12345678"
    span1 = TraceSpan.start("s1", trace_id=custom_trace)
    span2 = TraceSpan.start("s2")  # 자동으로 custom_trace 이어받기

    ok = span2.trace_id == custom_trace
    print(f"  custom trace: {custom_trace[:20]}")
    print(f"  span2 trace: {span2.trace_id[:20]}")
    print(f"  {'✅' if ok else '❌'}")
    span2.end(success=True)
    span1.end(success=True)
    all_pass &= ok

    # T6: 성능 — 오버헤드
    print("\n=== T6: 성능 — Span 오버헤드 ===")
    latencies = []
    for _ in range(100):
        t = time.time()
        s = TraceSpan.start("perf", agent_id="test")
        s.end(success=True)
        latencies.append((time.time() - t) * 1000)

    avg = sum(latencies) / len(latencies)
    max_lat = max(latencies)
    print(f"  100회 평균: {avg:.3f}ms, 최대: {max_lat:.3f}ms")
    ok = avg < 1.0  # 1ms 미만
    print(f"  평가: {'✅ OK (<1ms)' if ok else '⚠️ 느림'}")
    all_pass &= ok

    # Summary
    print(f"\n{'=' * 60}")
    print(f"SUMMARY: {'전체 통과 ✅' if all_pass else '일부 실패 ❌'}")
    print(f"  T1: 시작/종료, T2: 부모-자식, T3: 3레벨")
    print(f"  T4: 에러, T5: trace_id 전파, T6: 성능 ({avg:.3f}ms)")
    print(f"Total: 6개 테스트")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
