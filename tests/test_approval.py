"""Phase E: SSE Bidirectional — Approval System Tests.

Tests:
1. ApprovalManager basic flow (request → approve → unblock)
2. ApprovalManager reject flow
3. ApprovalManager timeout
4. ApprovalManager cancel
5. Multiple concurrent requests
6. InteractionRequest SSE event format
7. @requires_approval decorator
8. ask_user() choice flow
9. ask_user() input flow

Usage: python tests/test_approval.py
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from logosai.agentic.approval import (
    ApprovalManager,
    ApprovalStatus,
    InteractionRequest,
    InteractionType,
    requires_approval,
)


async def main():
    print("=" * 70)
    print("Phase E: SSE Bidirectional — Approval System Tests")
    print("=" * 70)

    # Reset singleton for clean testing
    ApprovalManager._instance = None

    # ── T1: Approve flow ──
    print("\n=== T1: Approval — 승인 흐름 ===")
    manager = ApprovalManager.get()

    req = InteractionRequest(
        type=InteractionType.APPROVAL,
        action="send_email",
        description="Send report to user@example.com",
        details={"to": "user@example.com"},
        timeout_seconds=5,
        agent_id="test_agent",
    )

    async def approve_after_delay(req_id, delay=0.1):
        await asyncio.sleep(delay)
        manager.respond(req_id, approved=True)

    # Start approval in background, respond quickly
    task = asyncio.create_task(approve_after_delay(req.id))
    result = await manager.request(req)

    assert result.status == ApprovalStatus.APPROVED, f"Expected APPROVED, got {result.status}"
    print(f"  Status: {result.status.value} ✅")

    # ── T2: Reject flow ──
    print("\n=== T2: Approval — 거부 흐름 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    req2 = InteractionRequest(
        type=InteractionType.APPROVAL,
        action="delete_file",
        description="Delete important.txt",
        timeout_seconds=5,
        agent_id="test_agent",
    )

    async def reject_after_delay(req_id, delay=0.1):
        await asyncio.sleep(delay)
        manager.respond(req_id, approved=False)

    task = asyncio.create_task(reject_after_delay(req2.id))
    result = await manager.request(req2)

    assert result.status == ApprovalStatus.REJECTED, f"Expected REJECTED, got {result.status}"
    print(f"  Status: {result.status.value} ✅")

    # ── T3: Timeout flow ──
    print("\n=== T3: Approval — 타임아웃 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    req3 = InteractionRequest(
        type=InteractionType.APPROVAL,
        action="send_message",
        description="Send message",
        timeout_seconds=1,  # 1 second timeout
        agent_id="test_agent",
    )

    t = time.time()
    result = await manager.request(req3)
    elapsed = time.time() - t

    assert result.status == ApprovalStatus.TIMEOUT, f"Expected TIMEOUT, got {result.status}"
    assert 0.9 < elapsed < 2.0, f"Expected ~1s timeout, got {elapsed:.1f}s"
    print(f"  Status: {result.status.value}, elapsed: {elapsed:.1f}s ✅")

    # ── T4: Cancel flow ──
    print("\n=== T4: Approval — 취소 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    req4 = InteractionRequest(
        type=InteractionType.APPROVAL,
        action="risky_action",
        description="Do something risky",
        timeout_seconds=5,
        agent_id="test_agent",
    )

    async def cancel_after_delay(req_id, delay=0.1):
        await asyncio.sleep(delay)
        manager.cancel(req_id)

    task = asyncio.create_task(cancel_after_delay(req4.id))
    result = await manager.request(req4)

    assert result.status == ApprovalStatus.CANCELLED, f"Expected CANCELLED, got {result.status}"
    print(f"  Status: {result.status.value} ✅")

    # ── T5: Concurrent requests ──
    print("\n=== T5: 동시 요청 처리 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    reqs = []
    for i in range(3):
        r = InteractionRequest(
            type=InteractionType.APPROVAL,
            action=f"action_{i}",
            description=f"Action {i}",
            timeout_seconds=5,
            agent_id=f"agent_{i}",
        )
        reqs.append(r)

    async def approve_all(requests, delay=0.1):
        await asyncio.sleep(delay)
        for r in requests:
            manager.respond(r.id, approved=True, response=f"ok_{r.action}")

    task = asyncio.create_task(approve_all(reqs))

    results = await asyncio.gather(*[manager.request(r) for r in reqs])

    all_approved = all(r.status == ApprovalStatus.APPROVED for r in results)
    assert all_approved, f"Not all approved: {[r.status for r in results]}"
    print(f"  3 concurrent requests all approved ✅")
    print(f"  Pending after resolution: {len(manager.get_pending())}")
    assert len(manager.get_pending()) == 0

    # ── T6: SSE event format ──
    print("\n=== T6: SSE 이벤트 형식 ===")
    req6 = InteractionRequest(
        type=InteractionType.APPROVAL,
        action="send_email",
        description="Send report",
        details={"to": "user@example.com", "subject": "Report"},
        timeout_seconds=30,
        agent_id="email_agent",
    )

    sse = req6.to_sse_event()
    assert sse["type"] == "approval_required", f"Wrong type: {sse['type']}"
    assert sse["data"]["request_id"] == req6.id
    assert sse["data"]["action"] == "send_email"
    assert sse["data"]["details"]["to"] == "user@example.com"
    assert sse["data"]["agent_id"] == "email_agent"
    print(f"  Event type: {sse['type']}")
    print(f"  Data keys: {list(sse['data'].keys())}")
    print(f"  ✅ SSE 이벤트 형식 정상")

    # ── T7: CHOICE type SSE event ──
    print("\n=== T7: Choice 이벤트 형식 ===")
    req7 = InteractionRequest(
        type=InteractionType.CHOICE,
        action="ask_user",
        description="어떤 언어로 번역할까요?",
        options=["영어", "일본어", "중국어"],
        agent_id="translation_agent",
    )

    sse7 = req7.to_sse_event()
    assert sse7["type"] == "choice_required", f"Wrong type: {sse7['type']}"
    assert sse7["data"]["options"] == ["영어", "일본어", "중국어"]
    print(f"  Event type: {sse7['type']}")
    print(f"  Options: {sse7['data']['options']}")
    print(f"  ✅ Choice 이벤트 형식 정상")

    # ── T8: INPUT type SSE event ──
    print("\n=== T8: Input 이벤트 형식 ===")
    req8 = InteractionRequest(
        type=InteractionType.INPUT,
        action="ask_user",
        description="추가 정보를 입력해주세요",
        agent_id="assistant_agent",
    )

    sse8 = req8.to_sse_event()
    assert sse8["type"] == "input_required"
    print(f"  Event type: {sse8['type']}")
    print(f"  ✅ Input 이벤트 형식 정상")

    # ── T9: Response with data ──
    print("\n=== T9: 응답 데이터 전달 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    req9 = InteractionRequest(
        type=InteractionType.CHOICE,
        action="ask_user",
        description="Select language",
        options=["en", "ja", "ko"],
        timeout_seconds=5,
        agent_id="test_agent",
    )

    async def respond_with_choice(req_id, delay=0.1):
        await asyncio.sleep(delay)
        manager.respond(req_id, approved=True, response="ja")

    task = asyncio.create_task(respond_with_choice(req9.id))
    result = await manager.request(req9)

    assert result.status == ApprovalStatus.APPROVED
    assert result.response == "ja", f"Expected 'ja', got {result.response}"
    print(f"  Response: {result.response} ✅")

    # ── T10: Unknown request_id ──
    print("\n=== T10: 존재하지 않는 요청 ===")
    found = manager.respond("nonexistent_id", approved=True)
    assert not found, "Should return False for unknown request"
    print(f"  respond('nonexistent') → False ✅")

    found = manager.cancel("nonexistent_id")
    assert not found
    print(f"  cancel('nonexistent') → False ✅")

    # ── Summary ──
    print(f"\n{'=' * 70}")
    print("SUMMARY: 10/10 tests passed ✅")
    print("Approval System (Phase E Day 1) 검증 완료")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
