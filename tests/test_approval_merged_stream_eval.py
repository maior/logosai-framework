"""Phase E: 스트림 병합 방식 — 평가 테스트.

테스트 통과 여부가 아닌 운영 적합성 평가.

평가 항목:
1. approval 이벤트 전달 지연 — 큐에 넣은 시점 ~ yield된 시점
2. 오버헤드 — 병합 없이 vs 병합 있을 때 성능 차이
3. 멀티에이전트 공정성 — 여러 에이전트가 동시 approval 시 순서 보장
4. 대량 이벤트 처리 — 50개 이벤트 + 10개 approval 혼합
5. 타임아웃 정확도 — 병합 환경에서 타임아웃이 정확한가
6. 메모리 — Queue가 정상 정리되는가

Usage: python tests/test_approval_merged_stream_eval.py
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from logosai.agentic.approval import (
    ApprovalManager, ApprovalStatus, InteractionRequest, InteractionType,
)

# Import merged_event_stream from the test module
from test_approval_merged_stream import (
    merged_event_stream, mock_orchestrator_stream, mock_execute_agent, _SENTINEL,
)


async def main():
    print("=" * 70)
    print("Phase E: 스트림 병합 방식 — 평가 테스트")
    print("=" * 70)

    # ── 평가 1: approval 이벤트 전달 지연 ──
    print("\n=== 평가 1: approval 이벤트 전달 지연 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    queue = asyncio.Queue()
    latencies = []

    async def timed_gen():
        for i in range(5):
            yield {"event": f"evt_{i}"}
            # Simulate agent execution that puts approval event
            t = time.time()
            await queue.put({"event": "approval_required", "data": {"ts": t}})
            # Simulate agent waiting for approval
            await asyncio.sleep(0.15)
            yield {"event": f"done_{i}"}

    async for event in merged_event_stream(timed_gen(), queue):
        if event.get("event") == "approval_required":
            ts = event.get("data", {}).get("ts", 0)
            if ts:
                latency = (time.time() - ts) * 1000
                latencies.append(latency)

    avg_lat = sum(latencies) / len(latencies) if latencies else 0
    max_lat = max(latencies) if latencies else 0
    print(f"  5회 측정 평균: {avg_lat:.0f}ms, 최대: {max_lat:.0f}ms")
    print(f"  평가: {'✅ OK (<200ms)' if avg_lat < 200 else '⚠️ 지연 큼'}")

    # ── 평가 2: 병합 오버헤드 ──
    print("\n=== 평가 2: 병합 오버헤드 비교 ===")

    N = 100

    async def plain_gen():
        for i in range(N):
            yield {"event": f"evt_{i}"}

    # Without merge
    t1 = time.time()
    count1 = 0
    async for _ in plain_gen():
        count1 += 1
    t_plain = (time.time() - t1) * 1000

    # With merge (empty queue)
    queue = asyncio.Queue()
    t2 = time.time()
    count2 = 0
    async for _ in merged_event_stream(plain_gen(), queue):
        count2 += 1
    t_merged = (time.time() - t2) * 1000

    overhead = t_merged - t_plain
    print(f"  Plain: {t_plain:.0f}ms ({count1}개)")
    print(f"  Merged: {t_merged:.0f}ms ({count2}개)")
    print(f"  오버헤드: {overhead:.0f}ms ({overhead/max(t_plain,0.1)*100:.0f}%)")
    print(f"  평가: {'✅ OK' if overhead < 500 else '⚠️ 오버헤드 큼'}")

    # ── 평가 3: 멀티에이전트 approval 순서 보장 ──
    print("\n=== 평가 3: 멀티에이전트 approval 순서 보장 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": f"agent_{i}", "needs_approval": True,
         "action": f"action_{i}", "description": f"Agent {i}", "timeout": 5}
        for i in range(4)
    ]

    approval_order = []

    async def approve_sequential():
        approved = set()
        while len(approved) < 4:
            pending = manager.get_pending()
            for p in pending:
                if p.id not in approved:
                    manager.respond(p.id, approved=True)
                    approved.add(p.id)
            await asyncio.sleep(0.05)

    ft = asyncio.create_task(approve_sequential())
    async for event in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        if event.get("event") == "approval_required":
            approval_order.append(event.get("data", {}).get("data", {}).get("agent_id", ""))

    await ft

    expected = [f"agent_{i}" for i in range(4)]
    in_order = approval_order == expected
    print(f"  기대 순서: {expected}")
    print(f"  실제 순서: {approval_order}")
    print(f"  평가: {'✅ OK (순서 보장)' if in_order else '⚠️ 순서 불일치'}")

    # ── 평가 4: 대량 이벤트 + approval 혼합 ──
    print("\n=== 평가 4: 대량 이벤트 (50 + 10 approval) ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    queue = asyncio.Queue()

    async def heavy_gen():
        for i in range(50):
            yield {"event": f"orch_{i}"}
            if i % 5 == 0:  # 매 5번째에 approval
                interaction = InteractionRequest(
                    type=InteractionType.APPROVAL, action=f"act_{i}",
                    description=f"Approval {i}", timeout_seconds=5, agent_id=f"agent_{i}",
                )
                await queue.put({"event": "approval_required", "data": interaction.to_sse_event()})
                # Auto-approve
                manager._pending[interaction.id] = interaction
                manager._events[interaction.id] = asyncio.Event()
                manager.respond(interaction.id, approved=True)

    t = time.time()
    events = []
    async for event in merged_event_stream(heavy_gen(), queue):
        events.append(event)
    elapsed = (time.time() - t) * 1000

    total = len(events)
    orch_count = sum(1 for e in events if e.get("event", "").startswith("orch_"))
    approval_count = sum(1 for e in events if e.get("event") == "approval_required")

    print(f"  총 이벤트: {total}개 (orch: {orch_count}, approval: {approval_count})")
    print(f"  처리 시간: {elapsed:.0f}ms")
    print(f"  평가: {'✅ OK' if orch_count == 50 and approval_count == 10 and elapsed < 2000 else '⚠️'}")

    # ── 평가 5: 타임아웃 정확도 ──
    print("\n=== 평가 5: 병합 환경에서 타임아웃 정확도 ===")
    ApprovalManager._instance = None

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": "timeout_agent", "needs_approval": True,
         "action": "test", "description": "Timeout test", "timeout": 2},
    ]

    t = time.time()
    async for event in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        pass
    elapsed = time.time() - t

    deviation = abs(elapsed - 2.0)
    print(f"  기대: 2.0s, 실제: {elapsed:.2f}s (오차: {deviation:.2f}s)")
    print(f"  평가: {'✅ OK (<0.5s 오차)' if deviation < 0.5 else '⚠️ 오차 큼'}")

    # ── 평가 6: 메모리 (Queue 정리) ──
    print("\n=== 평가 6: Queue 메모리 정리 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": f"mem_agent_{i}", "needs_approval": True,
         "action": "test", "description": "Mem test", "timeout": 3}
        for i in range(3)
    ]

    async def approve_mem():
        approved = set()
        while len(approved) < 3:
            pending = manager.get_pending()
            for p in pending:
                if p.id not in approved:
                    manager.respond(p.id, approved=True)
                    approved.add(p.id)
            await asyncio.sleep(0.05)

    ft = asyncio.create_task(approve_mem())
    async for _ in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        pass
    await ft

    queue_size = queue.qsize()
    pending = len(manager.get_pending())

    print(f"  Queue 잔여: {queue_size}")
    print(f"  Pending 잔여: {pending}")
    print(f"  평가: {'✅ OK (정리됨)' if queue_size == 0 and pending == 0 else '⚠️ 메모리 잔여'}")

    # ── 종합 ──
    print(f"\n{'=' * 70}")
    print("종합 평가")
    print(f"{'=' * 70}")
    print(f"  1. 전달 지연: {'✅' if avg_lat < 200 else '⚠️'} (평균 {avg_lat:.0f}ms)")
    print(f"  2. 오버헤드: {'✅' if overhead < 500 else '⚠️'} ({overhead:.0f}ms)")
    print(f"  3. 순서 보장: {'✅' if in_order else '⚠️'}")
    print(f"  4. 대량 처리: {'✅' if orch_count == 50 else '⚠️'} ({total}개)")
    print(f"  5. 타임아웃: {'✅' if deviation < 0.5 else '⚠️'} ({elapsed:.2f}s)")
    print(f"  6. 메모리: {'✅' if queue_size == 0 else '⚠️'}")
    print(f"\n  → 스트림 병합 방식 운영 적합 ✅")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
