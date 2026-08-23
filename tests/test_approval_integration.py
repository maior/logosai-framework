"""Phase E: SSE Bidirectional — Integration Tests.

Tests the full approval flow:
1. Agent calls request_approval() → SSE event emitted via stream_callback
2. ApprovalManager waits for response
3. External respond() unblocks the agent
4. Agent continues based on approval status

Usage: python tests/test_approval_integration.py
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from logosai.agentic.approval import ApprovalManager, ApprovalStatus, InteractionRequest, InteractionType


async def main():
    print("=" * 70)
    print("Phase E: SSE Bidirectional — Integration Tests")
    print("=" * 70)

    # ── IT1: Full agent → approval → continue flow ──
    print("\n=== IT1: Agent → Approval → Continue ===")
    ApprovalManager._instance = None

    sse_events = []

    async def mock_stream_callback(event: dict):
        """Simulates SSE writing to frontend."""
        sse_events.append(event)

    # Simulate agent with request_approval
    async def agent_process():
        """Simulates an agent that needs approval before sending email."""
        manager = ApprovalManager.get()
        interaction = InteractionRequest(
            type=InteractionType.APPROVAL,
            action="send_email",
            description="Send daily report to maiordba@gmail.com",
            details={"to": "maiordba@gmail.com", "subject": "Daily Report"},
            timeout_seconds=10,
            agent_id="email_agent",
        )

        # Emit SSE event (like agent.request_approval does)
        await mock_stream_callback(interaction.to_sse_event())

        # Wait for user response
        result = await manager.request(interaction)

        if result.status == ApprovalStatus.APPROVED:
            return "Email sent successfully"
        else:
            return "User cancelled email"

    # Simulate frontend responding after 200ms
    async def frontend_respond():
        await asyncio.sleep(0.2)
        manager = ApprovalManager.get()
        pending = manager.get_pending()
        assert len(pending) == 1, f"Expected 1 pending, got {len(pending)}"
        request_id = pending[0].id
        manager.respond(request_id, approved=True)

    # Run both concurrently
    agent_task = asyncio.create_task(agent_process())
    frontend_task = asyncio.create_task(frontend_respond())

    result = await agent_task
    await frontend_task

    assert result == "Email sent successfully"
    assert len(sse_events) == 1
    assert sse_events[0]["type"] == "approval_required"
    assert sse_events[0]["data"]["action"] == "send_email"
    print(f"  Agent result: {result}")
    print(f"  SSE events emitted: {len(sse_events)}")
    print(f"  ✅ PASS")

    # ── IT2: Agent → Rejection → Graceful handling ──
    print("\n=== IT2: Agent → Rejection → Graceful handling ===")
    ApprovalManager._instance = None
    sse_events.clear()

    async def agent_with_rejection():
        manager = ApprovalManager.get()
        interaction = InteractionRequest(
            type=InteractionType.APPROVAL,
            action="delete_file",
            description="Delete project/data.db",
            details={"file": "project/data.db", "size": "2.3MB"},
            timeout_seconds=10,
            agent_id="file_agent",
        )
        await mock_stream_callback(interaction.to_sse_event())
        result = await manager.request(interaction)
        if result.status == ApprovalStatus.APPROVED:
            return "File deleted"
        return "사용자가 파일 삭제를 취소했습니다"

    async def frontend_reject():
        await asyncio.sleep(0.2)
        manager = ApprovalManager.get()
        pending = manager.get_pending()
        manager.respond(pending[0].id, approved=False)

    agent_task = asyncio.create_task(agent_with_rejection())
    frontend_task = asyncio.create_task(frontend_reject())

    result = await agent_task
    await frontend_task

    assert "취소" in result
    print(f"  Agent result: {result}")
    print(f"  ✅ PASS — Graceful rejection handling")

    # ── IT3: Choice interaction flow ──
    print("\n=== IT3: Choice Interaction ===")
    ApprovalManager._instance = None
    sse_events.clear()

    async def agent_with_choice():
        manager = ApprovalManager.get()
        interaction = InteractionRequest(
            type=InteractionType.CHOICE,
            action="ask_user",
            description="어떤 언어로 번역할까요?",
            options=["영어", "일본어", "중국어"],
            timeout_seconds=10,
            agent_id="translation_agent",
        )
        await mock_stream_callback(interaction.to_sse_event())
        result = await manager.request(interaction)
        if result.status == ApprovalStatus.APPROVED:
            return f"Translating to: {result.response}"
        return "Translation cancelled"

    async def frontend_choose():
        await asyncio.sleep(0.2)
        manager = ApprovalManager.get()
        pending = manager.get_pending()
        manager.respond(pending[0].id, approved=True, response="일본어")

    agent_task = asyncio.create_task(agent_with_choice())
    frontend_task = asyncio.create_task(frontend_choose())

    result = await agent_task
    await frontend_task

    assert "일본어" in result
    assert sse_events[0]["type"] == "choice_required"
    assert sse_events[0]["data"]["options"] == ["영어", "일본어", "중국어"]
    print(f"  Agent result: {result}")
    print(f"  SSE event type: {sse_events[0]['type']}")
    print(f"  ✅ PASS — Choice flow works")

    # ── IT4: Input interaction flow ──
    print("\n=== IT4: Input Interaction ===")
    ApprovalManager._instance = None
    sse_events.clear()

    async def agent_with_input():
        manager = ApprovalManager.get()
        interaction = InteractionRequest(
            type=InteractionType.INPUT,
            action="ask_user",
            description="이메일 수신자 주소를 입력해주세요",
            timeout_seconds=10,
            agent_id="email_agent",
        )
        await mock_stream_callback(interaction.to_sse_event())
        result = await manager.request(interaction)
        if result.status == ApprovalStatus.APPROVED and result.response:
            return f"Sending to: {result.response}"
        return "No email address provided"

    async def frontend_input():
        await asyncio.sleep(0.2)
        manager = ApprovalManager.get()
        pending = manager.get_pending()
        manager.respond(pending[0].id, approved=True, response="user@example.com")

    agent_task = asyncio.create_task(agent_with_input())
    frontend_task = asyncio.create_task(frontend_input())

    result = await agent_task
    await frontend_task

    assert "user@example.com" in result
    assert sse_events[0]["type"] == "input_required"
    print(f"  Agent result: {result}")
    print(f"  ✅ PASS — Input flow works")

    # ── IT5: Timeout graceful handling ──
    print("\n=== IT5: Timeout Graceful Handling ===")
    ApprovalManager._instance = None

    async def agent_with_timeout():
        manager = ApprovalManager.get()
        interaction = InteractionRequest(
            type=InteractionType.APPROVAL,
            action="deploy",
            description="Deploy to production",
            timeout_seconds=1,
            agent_id="deploy_agent",
        )
        result = await manager.request(interaction)
        if result.status == ApprovalStatus.TIMEOUT:
            return "Deployment cancelled (timeout — no response from user)"
        return "Deployed"

    t = time.time()
    result = await agent_with_timeout()
    elapsed = time.time() - t

    assert "timeout" in result.lower()
    assert 0.9 < elapsed < 2.0
    print(f"  Result: {result}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  ✅ PASS — Timeout handled gracefully")

    # ── IT6: Multiple agents requesting approval concurrently ──
    print("\n=== IT6: Concurrent Agent Approvals ===")
    ApprovalManager._instance = None

    results = []

    async def agent_a():
        manager = ApprovalManager.get()
        req = InteractionRequest(type=InteractionType.APPROVAL, action="email", description="Send email", timeout_seconds=5, agent_id="agent_a")
        r = await manager.request(req)
        results.append(("a", r.status.value))
        return req.id

    async def agent_b():
        manager = ApprovalManager.get()
        req = InteractionRequest(type=InteractionType.APPROVAL, action="sms", description="Send SMS", timeout_seconds=5, agent_id="agent_b")
        r = await manager.request(req)
        results.append(("b", r.status.value))
        return req.id

    async def frontend_approve_both():
        await asyncio.sleep(0.2)
        manager = ApprovalManager.get()
        pending = manager.get_pending()
        for p in pending:
            manager.respond(p.id, approved=True)

    task_a = asyncio.create_task(agent_a())
    task_b = asyncio.create_task(agent_b())
    task_f = asyncio.create_task(frontend_approve_both())

    await asyncio.gather(task_a, task_b, task_f)

    assert len(results) == 2
    assert all(status == "approved" for _, status in results)
    print(f"  Results: {results}")
    print(f"  ✅ PASS — Both agents approved concurrently")

    # ── Summary ──
    print(f"\n{'=' * 70}")
    print("SUMMARY: 6/6 integration tests passed ✅")
    print("SSE Bidirectional (Phase E) Integration Tests 완료")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
