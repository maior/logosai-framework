"""Phase E: SSE Bidirectional — 스트림 병합 방식 검증 테스트.

문제: orchestrator.run_streaming() 내부에서 _execute_agent_via_acp가 실행되는 동안
      메인 generator가 블로킹되어 approval 이벤트를 프론트엔드로 보낼 수 없음.

해결: asyncio.Queue + 스트림 병합
      - _execute_agent_via_acp → approval 이벤트 → Queue
      - 메인 루프: orchestrator 이벤트 + Queue 이벤트를 동시에 대기

테스트:
Part A: 스트림 병합 핵심 로직 검증
  A1. 단순 병합 — orchestrator 이벤트만
  A2. 병합 + approval 이벤트 끼어들기
  A3. 병합 + 다중 approval (연속)
  A4. 병합 + approval 타임아웃 (큐 비어있음)

Part B: 실제 시나리오 시뮬레이션
  B1. 단일 에이전트 + 삭제 approval
  B2. 멀티 에이전트 (2개) + 중간 approval
  B3. 멀티 에이전트 (3개) + 2개 에이전트 각각 approval
  B4. approval 승인 후 에이전트 계속 실행
  B5. approval 거부 후 에이전트 취소 결과

Part C: 에지케이스
  C1. approval 이벤트가 orchestrator 완료 후 도착
  C2. Queue에 동시에 여러 이벤트
  C3. 빈 스트림 + approval만

Usage: python tests/test_approval_merged_stream.py
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from logosai.agentic.approval import (
    ApprovalManager, ApprovalStatus, InteractionRequest, InteractionType,
)


# ═══════════════════════════════════════════
# Core: Merged Stream Implementation
# ═══════════════════════════════════════════

async def merged_event_stream(orchestrator_gen, approval_queue):
    """Merge orchestrator events with approval events from the queue.

    Yields events from whichever source is ready first.
    Orchestrator events flow normally; approval events are injected
    whenever they appear in the queue (put by _execute_agent_via_acp).

    Key insight: orchestrator_gen yields events including agent_started/agent_complete.
    During agent execution (between agent_started and agent_complete), the generator
    is blocked. During this time, approval events appear in the queue and must be
    forwarded to the frontend.
    """
    orch_iter = orchestrator_gen.__aiter__()
    orch_task = None

    while True:
        # Start waiting for next orchestrator event if not already waiting
        if orch_task is None:
            orch_task = asyncio.ensure_future(_safe_anext(orch_iter))

        # Wait for either: orchestrator event OR queue event (100ms poll)
        done, _ = await asyncio.wait(
            {orch_task},
            timeout=0.1,  # Check queue every 100ms while orchestrator is blocked
        )

        # Drain approval queue (non-blocking)
        while not approval_queue.empty():
            try:
                yield approval_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Process orchestrator event if ready
        if done:
            result = orch_task.result()
            orch_task = None
            if result is _SENTINEL:
                break
            yield result

    # Final drain
    while not approval_queue.empty():
        try:
            yield approval_queue.get_nowait()
        except asyncio.QueueEmpty:
            break


_SENTINEL = object()


async def _safe_anext(aiter):
    """Get next from async iterator, return _SENTINEL on StopAsyncIteration."""
    try:
        return await aiter.__anext__()
    except StopAsyncIteration:
        return _SENTINEL


# ═══════════════════════════════════════════
# Mock: Orchestrator + Agent Execution
# ═══════════════════════════════════════════

async def mock_orchestrator_stream(agent_tasks, approval_queue):
    """Simulate WorkflowOrchestrator.run_streaming().

    Yields planning events, then executes each agent (which may put
    approval events into the queue), then yields completion events.
    """
    yield {"event": "planning_complete", "data": {"agents": [t["agent_id"] for t in agent_tasks]}}

    for task in agent_tasks:
        yield {"event": "agent_started", "data": {"agent_id": task["agent_id"]}}

        # Simulate _execute_agent_via_acp (this is where approval happens)
        result = await mock_execute_agent(task, approval_queue)

        yield {"event": "agent_complete", "data": {"agent_id": task["agent_id"], "result": result}}

    yield {"event": "final_result", "data": {"result": "All done"}}


async def mock_execute_agent(task, approval_queue):
    """Simulate _execute_agent_via_acp with approval support.

    If task has needs_approval=True, puts an approval event into the queue
    and waits for the ApprovalManager response.
    """
    agent_id = task["agent_id"]

    if task.get("needs_approval"):
        manager = ApprovalManager.get()
        interaction = InteractionRequest(
            type=InteractionType.APPROVAL,
            action=task.get("action", "test"),
            description=task.get("description", f"{agent_id} needs approval"),
            details=task.get("details", {}),
            timeout_seconds=task.get("timeout", 5),
            agent_id=agent_id,
        )

        # Put approval event into queue (this is what _execute_agent_via_acp would do)
        await approval_queue.put({
            "event": "approval_required",
            "data": interaction.to_sse_event(),
        })

        # Wait for approval (blocks this agent execution)
        result = await manager.request(interaction)

        if result.status == ApprovalStatus.APPROVED:
            return {"success": True, "answer": f"{agent_id}: approved and executed"}
        else:
            return {"success": False, "answer": f"{agent_id}: cancelled ({result.status.value})"}

    # Normal execution (no approval needed)
    await asyncio.sleep(0.05)
    return {"success": True, "answer": f"{agent_id}: completed"}


# ═══════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════

async def main():
    print("=" * 70)
    print("Phase E: 스트림 병합 방식 검증 테스트")
    print("=" * 70)

    all_pass = True

    # ═══════════════════════════════════════
    # Part A: 핵심 로직 검증
    # ═══════════════════════════════════════
    print("\n" + "─" * 50)
    print("Part A: 스트림 병합 핵심 로직")
    print("─" * 50)

    # ── A1: orchestrator 이벤트만 ──
    print("\n=== A1: orchestrator 이벤트만 (approval 없음) ===")
    ApprovalManager._instance = None

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": "internet_agent"},
        {"agent_id": "analysis_agent"},
    ]

    events = []
    async for event in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        events.append(event)

    event_types = [e["event"] for e in events]
    ok = ("planning_complete" in event_types and
          "final_result" in event_types and
          event_types.count("agent_started") == 2 and
          event_types.count("agent_complete") == 2)
    print(f"  이벤트: {event_types}")
    print(f"  {'✅' if ok else '❌'} orchestrator 이벤트만 정상 흐름")
    all_pass &= ok

    # ── A2: 병합 + approval 끼어들기 ──
    print("\n=== A2: 병합 + approval 이벤트 끼어들기 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": "scheduler_agent", "needs_approval": True,
         "action": "delete_schedule", "description": "Delete meeting", "timeout": 5},
    ]

    events = []

    async def approve_when_pending():
        """Frontend: wait for approval event to appear, then approve."""
        while True:
            pending = manager.get_pending()
            if pending:
                manager.respond(pending[0].id, approved=True)
                return
            await asyncio.sleep(0.05)

    frontend_task = asyncio.create_task(approve_when_pending())

    async for event in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        events.append(event)

    await frontend_task

    event_types = [e["event"] for e in events]
    has_approval = "approval_required" in event_types
    has_complete = "agent_complete" in event_types
    # Check the agent was approved
    agent_result = next((e for e in events if e["event"] == "agent_complete"), None)
    was_approved = agent_result and "approved" in str(agent_result.get("data", {}).get("result", {}).get("answer", ""))

    ok = has_approval and has_complete and was_approved
    print(f"  이벤트: {event_types}")
    print(f"  approval_required 포함: {has_approval}")
    print(f"  승인 후 실행 완료: {was_approved}")
    print(f"  {'✅' if ok else '❌'} approval 이벤트 병합 동작")
    all_pass &= ok

    # ── A3: 병합 + 거부 ──
    print("\n=== A3: 병합 + approval 거부 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": "scheduler_agent", "needs_approval": True,
         "action": "delete", "description": "Delete event", "timeout": 5},
    ]

    events = []

    async def reject_when_pending():
        while True:
            pending = manager.get_pending()
            if pending:
                manager.respond(pending[0].id, approved=False)
                return
            await asyncio.sleep(0.05)

    frontend_task = asyncio.create_task(reject_when_pending())

    async for event in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        events.append(event)

    await frontend_task

    agent_result = next((e for e in events if e["event"] == "agent_complete"), None)
    was_rejected = agent_result and "cancelled" in str(agent_result.get("data", {}).get("result", {}).get("answer", ""))

    ok = was_rejected
    print(f"  거부 후 취소 결과: {was_rejected}")
    print(f"  {'✅' if ok else '❌'} 거부 시 에이전트 취소")
    all_pass &= ok

    # ── A4: 병합 + 타임아웃 ──
    print("\n=== A4: 병합 + approval 타임아웃 ===")
    ApprovalManager._instance = None

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": "test_agent", "needs_approval": True,
         "action": "test", "description": "Timeout test", "timeout": 1},
    ]

    events = []
    t = time.time()

    async for event in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        events.append(event)

    elapsed = time.time() - t

    agent_result = next((e for e in events if e["event"] == "agent_complete"), None)
    was_timeout = agent_result and "timeout" in str(agent_result.get("data", {}).get("result", {}).get("answer", ""))

    ok = was_timeout and elapsed < 3.0
    print(f"  타임아웃 결과: {was_timeout}, {elapsed:.1f}s")
    print(f"  {'✅' if ok else '❌'} 타임아웃 처리")
    all_pass &= ok

    # ═══════════════════════════════════════
    # Part B: 실제 시나리오 시뮬레이션
    # ═══════════════════════════════════════
    print("\n" + "─" * 50)
    print("Part B: 실제 시나리오 시뮬레이션")
    print("─" * 50)

    # ── B1: 단일 에이전트 + 삭제 approval ──
    print("\n=== B1: 단일 에이전트 — 일정 삭제 승인 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": "scheduler_agent", "needs_approval": True,
         "action": "delete_schedule", "description": "일정 '팀 미팅' 삭제",
         "details": {"title": "팀 미팅", "event_id": 42}, "timeout": 5},
    ]

    frontend_events = []

    async def frontend_b1():
        while True:
            pending = manager.get_pending()
            if pending:
                manager.respond(pending[0].id, approved=True)
                return
            await asyncio.sleep(0.05)

    ft = asyncio.create_task(frontend_b1())
    async for event in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        frontend_events.append(event)
    await ft

    types = [e["event"] for e in frontend_events]
    approval_event = next((e for e in frontend_events if e["event"] == "approval_required"), None)
    has_details = approval_event and "팀 미팅" in str(approval_event)

    ok = "approval_required" in types and "final_result" in types and has_details
    print(f"  이벤트 순서: {types}")
    print(f"  다이얼로그 데이터 포함: {has_details}")
    print(f"  {'✅' if ok else '❌'} 단일 에이전트 삭제 승인")
    all_pass &= ok

    # ── B2: 멀티 에이전트 (2개) + 중간 approval ──
    print("\n=== B2: 멀티 에이전트 — 검색 + 이메일전송(approval) ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": "internet_agent"},  # 검색 (approval 불필요)
        {"agent_id": "mail_agent", "needs_approval": True,
         "action": "send_email", "description": "검색 결과를 이메일로 전송",
         "details": {"to": "user@example.com"}, "timeout": 5},
    ]

    frontend_events = []

    async def frontend_b2():
        while True:
            pending = manager.get_pending()
            if pending:
                manager.respond(pending[0].id, approved=True)
                return
            await asyncio.sleep(0.05)

    ft = asyncio.create_task(frontend_b2())
    async for event in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        frontend_events.append(event)
    await ft

    types = [e["event"] for e in frontend_events]
    # internet_agent는 approval 없이 완료, mail_agent는 approval 후 완료
    internet_complete = any(e["event"] == "agent_complete" and e["data"]["agent_id"] == "internet_agent" for e in frontend_events)
    mail_complete = any(e["event"] == "agent_complete" and e["data"]["agent_id"] == "mail_agent" for e in frontend_events)
    has_approval = "approval_required" in types

    ok = internet_complete and mail_complete and has_approval
    print(f"  이벤트 순서: {types}")
    print(f"  검색 완료: {internet_complete}, 이메일(approval후) 완료: {mail_complete}")
    print(f"  {'✅' if ok else '❌'} 멀티에이전트 중간 approval")
    all_pass &= ok

    # ── B3: 멀티 에이전트 (3개) + 2개 각각 approval ──
    print("\n=== B3: 멀티 에이전트 — 분석 + 일정삭제(approval) + 이메일(approval) ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": "analysis_agent"},
        {"agent_id": "scheduler_agent", "needs_approval": True,
         "action": "delete_schedule", "description": "일정 삭제", "timeout": 5},
        {"agent_id": "mail_agent", "needs_approval": True,
         "action": "send_email", "description": "이메일 전송", "timeout": 5},
    ]

    frontend_events = []
    approval_count = 0

    async def frontend_b3():
        nonlocal approval_count
        approved = set()
        while approval_count < 2:
            pending = manager.get_pending()
            for p in pending:
                if p.id not in approved:
                    manager.respond(p.id, approved=True)
                    approved.add(p.id)
                    approval_count += 1
            await asyncio.sleep(0.05)

    ft = asyncio.create_task(frontend_b3())
    async for event in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        frontend_events.append(event)
    await ft

    types = [e["event"] for e in frontend_events]
    approval_events = [e for e in frontend_events if e["event"] == "approval_required"]
    complete_events = [e for e in frontend_events if e["event"] == "agent_complete"]

    ok = len(approval_events) == 2 and len(complete_events) == 3
    print(f"  이벤트 순서: {types}")
    print(f"  approval 이벤트: {len(approval_events)}개, agent_complete: {len(complete_events)}개")
    print(f"  {'✅' if ok else '❌'} 2개 에이전트 각각 approval")
    all_pass &= ok

    # ── B4: approval 승인 후 에이전트 결과 검증 ──
    print("\n=== B4: approval 승인 → 에이전트 결과에 '승인됨' 반영 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": "scheduler_agent", "needs_approval": True,
         "action": "delete", "description": "Delete", "timeout": 5},
    ]

    async def frontend_b4():
        while True:
            pending = manager.get_pending()
            if pending:
                manager.respond(pending[0].id, approved=True)
                return
            await asyncio.sleep(0.05)

    ft = asyncio.create_task(frontend_b4())
    events = []
    async for event in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        events.append(event)
    await ft

    agent_result = next((e for e in events if e["event"] == "agent_complete"), None)
    answer = agent_result["data"]["result"]["answer"] if agent_result else ""
    ok = "approved" in answer
    print(f"  에이전트 답변: {answer}")
    print(f"  {'✅' if ok else '❌'} 승인 결과 반영")
    all_pass &= ok

    # ── B5: approval 거부 → 에이전트 '취소' 결과 ──
    print("\n=== B5: approval 거부 → 에이전트 '취소' 결과 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    queue = asyncio.Queue()
    tasks = [
        {"agent_id": "mail_agent", "needs_approval": True,
         "action": "send_email", "description": "Send", "timeout": 5},
    ]

    async def frontend_b5():
        while True:
            pending = manager.get_pending()
            if pending:
                manager.respond(pending[0].id, approved=False)
                return
            await asyncio.sleep(0.05)

    ft = asyncio.create_task(frontend_b5())
    events = []
    async for event in merged_event_stream(mock_orchestrator_stream(tasks, queue), queue):
        events.append(event)
    await ft

    agent_result = next((e for e in events if e["event"] == "agent_complete"), None)
    answer = agent_result["data"]["result"]["answer"] if agent_result else ""
    ok = "cancelled" in answer
    print(f"  에이전트 답변: {answer}")
    print(f"  {'✅' if ok else '❌'} 거부 → 취소 결과")
    all_pass &= ok

    # ═══════════════════════════════════════
    # Part C: 에지케이스
    # ═══════════════════════════════════════
    print("\n" + "─" * 50)
    print("Part C: 에지케이스")
    print("─" * 50)

    # ── C1: 빈 orchestrator + approval만 ──
    print("\n=== C1: 빈 orchestrator 스트림 ===")

    async def empty_gen():
        return
        yield  # make it a generator

    queue = asyncio.Queue()
    events = []
    async for event in merged_event_stream(empty_gen(), queue):
        events.append(event)

    ok = len(events) == 0
    print(f"  이벤트: {len(events)}개")
    print(f"  {'✅' if ok else '❌'} 빈 스트림 처리")
    all_pass &= ok

    # ── C2: Queue에 동시에 여러 이벤트 ──
    print("\n=== C2: Queue에 동시에 여러 이벤트 (drain 확인) ===")

    async def slow_gen():
        yield {"event": "start"}
        await asyncio.sleep(0.3)
        yield {"event": "end"}

    queue = asyncio.Queue()
    # Pre-fill queue with 3 events
    for i in range(3):
        await queue.put({"event": f"approval_{i}"})

    events = []
    async for event in merged_event_stream(slow_gen(), queue):
        events.append(event)

    types = [e["event"] for e in events]
    has_all_approvals = all(f"approval_{i}" in types for i in range(3))
    has_start_end = "start" in types and "end" in types

    ok = has_all_approvals and has_start_end
    print(f"  이벤트: {types}")
    print(f"  3개 approval + start/end 모두 수신: {ok}")
    print(f"  {'✅' if ok else '❌'} 큐 drain 정상")
    all_pass &= ok

    # ── C3: 성능 — 병합 오버헤드 측정 ──
    print("\n=== C3: 병합 오버헤드 측정 ===")

    async def fast_gen():
        for i in range(20):
            yield {"event": f"evt_{i}"}

    queue = asyncio.Queue()
    t = time.time()
    events = []
    async for event in merged_event_stream(fast_gen(), queue):
        events.append(event)
    elapsed = (time.time() - t) * 1000

    ok = len(events) == 20 and elapsed < 500  # 500ms 이내
    print(f"  20개 이벤트 병합: {elapsed:.0f}ms")
    print(f"  {'✅' if ok else '⚠️'} 오버헤드 {'허용범위' if ok else '큼'}")
    all_pass &= ok

    # ── Summary ──
    total = 12
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {'전체 통과 ✅' if all_pass else '일부 실패 ❌'}")
    print(f"Part A (핵심 로직): 4개 — 이벤트만/approval끼기/거부/타임아웃")
    print(f"Part B (실제 시나리오): 5개 — 단일삭제/멀티2개/멀티3개/승인결과/거부결과")
    print(f"Part C (에지케이스): 3개 — 빈스트림/큐drain/성능")
    print(f"Total: {total}개 테스트")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
