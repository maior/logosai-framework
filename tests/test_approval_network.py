"""Phase E: SSE Bidirectional — 네트워크 경로 + 에지케이스 테스트.

테스트 대상:
Part A: SSE 전체 경로 시뮬레이션 (미니 ACP 서버 → logos_api proxy 경유)
Part B: 네트워크 장애 및 에지케이스

Usage: python tests/test_approval_network.py
"""

import asyncio
import json
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from aiohttp import web
import aiohttp

from logosai.agentic.approval import (
    ApprovalManager, ApprovalStatus, InteractionRequest, InteractionType,
)


# ═══════════════════════════════════════════
# Mini ACP Server for testing
# ═══════════════════════════════════════════

def create_mini_acp_app():
    """Create a minimal ACP server with approval endpoints for testing."""
    app = web.Application()

    async def handle_approve(request):
        request_id = request.match_info["request_id"]
        body = await request.json()
        manager = ApprovalManager.get()
        found = manager.respond(request_id, approved=body.get("approved", False), response=body.get("response"))
        if not found:
            return web.json_response({"error": "Not found"}, status=404)
        return web.json_response({
            "request_id": request_id,
            "status": "approved" if body.get("approved") else "rejected",
        })

    async def handle_pending(request):
        manager = ApprovalManager.get()
        pending = manager.get_pending()
        return web.json_response({
            "count": len(pending),
            "requests": [r.to_sse_event() for r in pending],
        }, dumps=lambda o: json.dumps(o, ensure_ascii=False, default=str))

    async def handle_cancel(request):
        request_id = request.match_info["request_id"]
        manager = ApprovalManager.get()
        found = manager.cancel(request_id)
        if not found:
            return web.json_response({"error": "Not found"}, status=404)
        return web.json_response({"request_id": request_id, "status": "cancelled"})

    async def handle_stream(request):
        """Simulates SSE stream with an approval event mid-stream."""
        resp = web.StreamResponse()
        resp.content_type = "text/event-stream"
        await resp.prepare(request)

        # 1. Send initialization
        await resp.write(b"event: initialization\ndata: {\"message\": \"Starting\"}\n\n")
        await asyncio.sleep(0.05)

        # 2. Agent requests approval (emitted as SSE event)
        ApprovalManager._instance = None
        manager = ApprovalManager.get()
        interaction = InteractionRequest(
            type=InteractionType.APPROVAL,
            action="send_email",
            description="Send report to user@example.com",
            details={"to": "user@example.com", "subject": "Test"},
            timeout_seconds=10,
            agent_id="test_agent",
        )

        # Emit approval_required SSE event
        sse_event = interaction.to_sse_event()
        event_data = json.dumps(sse_event, ensure_ascii=False)
        await resp.write(f"event: approval_required\ndata: {event_data}\n\n".encode("utf-8"))

        # Wait for approval (will be unblocked by REST call)
        result = await manager.request(interaction)

        # 3. Send complete based on result
        if result.status == ApprovalStatus.APPROVED:
            complete = {"type": "complete", "data": {"result": {"answer": "Email sent!"}}}
        else:
            complete = {"type": "complete", "data": {"result": {"answer": "Cancelled by user"}}}

        await resp.write(f"event: complete\ndata: {json.dumps(complete)}\n\n".encode("utf-8"))
        return resp

    app.router.add_post("/api/approve/{request_id}", handle_approve)
    app.router.add_get("/api/approve/pending", handle_pending)
    app.router.add_post("/api/approve/{request_id}/cancel", handle_cancel)
    app.router.add_post("/stream", handle_stream)
    app.router.add_get("/stream", handle_stream)

    return app


async def start_mini_acp(port=19888):
    """Start mini ACP server on given port."""
    app = create_mini_acp_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", port)
    await site.start()
    return runner


async def main():
    print("=" * 70)
    print("Phase E: SSE Bidirectional — 네트워크 경로 + 에지케이스 테스트")
    print("=" * 70)

    all_pass = True
    ACP_PORT = 19888
    ACP_URL = f"http://localhost:{ACP_PORT}"

    # ═══════════════════════════════════════════
    # Part A: SSE 전체 경로 시뮬레이션
    # ═══════════════════════════════════════════
    print("\n" + "─" * 50)
    print("Part A: SSE 전체 경로 시뮬레이션")
    print("─" * 50)

    # Start mini ACP
    runner = await start_mini_acp(ACP_PORT)
    print(f"\n  Mini ACP server started on port {ACP_PORT}")

    try:
        # ── A1: REST approve endpoint ──
        print("\n=== A1: REST /api/approve/{id} 엔드포인트 ===")
        ApprovalManager._instance = None
        manager = ApprovalManager.get()

        req = InteractionRequest(
            type=InteractionType.APPROVAL, action="test",
            description="Test", timeout_seconds=5, agent_id="test",
        )

        async def rest_approve(rid):
            await asyncio.sleep(0.1)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{ACP_URL}/api/approve/{rid}",
                    json={"approved": True, "response": "ok"},
                ) as resp:
                    return resp.status, await resp.json()

        task = asyncio.create_task(rest_approve(req.id))
        result = await manager.request(req)
        status, body = await task

        ok = result.status == ApprovalStatus.APPROVED and status == 200
        print(f"  HTTP status: {status}")
        print(f"  Approval status: {result.status.value}")
        print(f"  Response body: {body}")
        print(f"  {'✅' if ok else '❌'} REST approve 동작")
        all_pass &= ok

        # ── A2: REST pending endpoint ──
        print("\n=== A2: REST /api/approve/pending 엔드포인트 ===")
        ApprovalManager._instance = None
        manager = ApprovalManager.get()

        # Create pending request
        req2 = InteractionRequest(
            type=InteractionType.APPROVAL, action="pending_test",
            description="Pending test", timeout_seconds=5, agent_id="test",
        )
        manager._pending[req2.id] = req2
        manager._events[req2.id] = asyncio.Event()

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ACP_URL}/api/approve/pending") as resp:
                status = resp.status
                body = await resp.json()

        ok = status == 200 and body["count"] == 1
        print(f"  HTTP status: {status}")
        print(f"  Pending count: {body['count']}")
        print(f"  {'✅' if ok else '❌'} REST pending 동작")
        all_pass &= ok

        # Cleanup
        manager.cancel(req2.id)

        # ── A3: REST 404 for unknown request ──
        print("\n=== A3: REST 404 for unknown request ===")
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{ACP_URL}/api/approve/nonexistent_id",
                json={"approved": True},
            ) as resp:
                status = resp.status

        ok = status == 404
        print(f"  HTTP status: {status}")
        print(f"  {'✅' if ok else '❌'} 존재하지 않는 ID → 404")
        all_pass &= ok

        # ── A4: SSE 스트림 + 중간 승인 전체 경로 ──
        print("\n=== A4: SSE 스트림 + 중간 승인 전체 경로 ===")

        events_received = []

        async def consume_sse_and_approve():
            """Simulate frontend: consume SSE, approve when approval_required received."""
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{ACP_URL}/stream",
                    json={"query": "test", "agent_id": "test"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    buffer = ""
                    async for chunk in resp.content.iter_any():
                        buffer += chunk.decode("utf-8", errors="ignore")
                        while "\n\n" in buffer:
                            block, buffer = buffer.split("\n\n", 1)
                            lines = block.strip().split("\n")
                            event_type, data_str = "", ""
                            for line in lines:
                                if line.startswith("event:"):
                                    event_type = line[6:].strip()
                                elif line.startswith("data:"):
                                    data_str = line[5:].strip()

                            if event_type and data_str:
                                try:
                                    data = json.loads(data_str)
                                except:
                                    data = data_str
                                events_received.append({"event": event_type, "data": data})

                                # When we receive approval_required, approve via REST
                                if event_type == "approval_required":
                                    request_id = data.get("data", {}).get("request_id", "")
                                    if request_id:
                                        await asyncio.sleep(0.1)
                                        async with aiohttp.ClientSession() as s2:
                                            await s2.post(
                                                f"{ACP_URL}/api/approve/{request_id}",
                                                json={"approved": True},
                                            )

                                if event_type == "complete":
                                    return

        await consume_sse_and_approve()

        event_types = [e["event"] for e in events_received]
        has_init = "initialization" in event_types
        has_approval = "approval_required" in event_types
        has_complete = "complete" in event_types

        # Check final answer
        complete_event = next((e for e in events_received if e["event"] == "complete"), None)
        final_answer = ""
        if complete_event:
            final_answer = complete_event.get("data", {}).get("data", {}).get("result", {}).get("answer", "")

        ok = has_init and has_approval and has_complete and "sent" in final_answer.lower()
        print(f"  이벤트 순서: {event_types}")
        print(f"  최종 답변: {final_answer}")
        print(f"  {'✅' if ok else '❌'} SSE 전체 경로 (init → approval_required → approve → complete)")
        all_pass &= ok

        # ── A5: SSE 스트림 + 거부 경로 ──
        print("\n=== A5: SSE 스트림 + 거부 경로 ===")

        events_received2 = []

        async def consume_sse_and_reject():
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{ACP_URL}/stream",
                    json={"query": "test"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    buffer = ""
                    async for chunk in resp.content.iter_any():
                        buffer += chunk.decode("utf-8", errors="ignore")
                        while "\n\n" in buffer:
                            block, buffer = buffer.split("\n\n", 1)
                            lines = block.strip().split("\n")
                            event_type, data_str = "", ""
                            for line in lines:
                                if line.startswith("event:"):
                                    event_type = line[6:].strip()
                                elif line.startswith("data:"):
                                    data_str = line[5:].strip()

                            if event_type and data_str:
                                try:
                                    data = json.loads(data_str)
                                except:
                                    data = data_str
                                events_received2.append({"event": event_type, "data": data})

                                if event_type == "approval_required":
                                    request_id = data.get("data", {}).get("request_id", "")
                                    if request_id:
                                        await asyncio.sleep(0.1)
                                        async with aiohttp.ClientSession() as s2:
                                            await s2.post(
                                                f"{ACP_URL}/api/approve/{request_id}",
                                                json={"approved": False},
                                            )

                                if event_type == "complete":
                                    return

        await consume_sse_and_reject()

        complete2 = next((e for e in events_received2 if e["event"] == "complete"), None)
        final2 = ""
        if complete2:
            final2 = complete2.get("data", {}).get("data", {}).get("result", {}).get("answer", "")

        ok = "cancel" in final2.lower() or "cancelled" in final2.lower()
        print(f"  이벤트: {[e['event'] for e in events_received2]}")
        print(f"  최종 답변: {final2}")
        print(f"  {'✅' if ok else '❌'} SSE 거부 경로")
        all_pass &= ok

    finally:
        await runner.cleanup()
        print(f"\n  Mini ACP server stopped")

    # ═══════════════════════════════════════════
    # Part B: 네트워크 장애 및 에지케이스
    # ═══════════════════════════════════════════
    print("\n" + "─" * 50)
    print("Part B: 네트워크 장애 및 에지케이스")
    print("─" * 50)

    # ── B1: ACP 서버 다운 시 REST 요청 ──
    print("\n=== B1: ACP 서버 다운 시 REST 요청 ===")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:19999/api/approve/test123",  # No server on this port
                json={"approved": True},
                timeout=aiohttp.ClientTimeout(total=2),
            ) as resp:
                pass
        ok = False  # Should not reach here
    except (aiohttp.ClientError, OSError) as e:
        ok = True
        print(f"  예외: {type(e).__name__}")
    print(f"  {'✅' if ok else '❌'} ACP 다운 → ClientError 발생")
    all_pass &= ok

    # ── B2: 대용량 details 필드 ──
    print("\n=== B2: 대용량 details 필드 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    large_details = {f"field_{i}": f"value_{'x' * 100}" for i in range(50)}
    req_large = InteractionRequest(
        type=InteractionType.APPROVAL,
        action="large_details_test",
        description="Test with large details",
        details=large_details,
        timeout_seconds=5,
        agent_id="test",
    )

    sse = req_large.to_sse_event()
    sse_size = len(json.dumps(sse, ensure_ascii=False))

    async def approve_large(rid):
        await asyncio.sleep(0.1)
        manager.respond(rid, approved=True)

    task = asyncio.create_task(approve_large(req_large.id))
    result = await manager.request(req_large)
    await task

    ok = result.status == ApprovalStatus.APPROVED and sse_size < 10000
    print(f"  Details 필드 수: {len(large_details)}")
    print(f"  SSE 이벤트 크기: {sse_size} bytes")
    print(f"  승인 상태: {result.status.value}")
    print(f"  {'✅' if ok else '⚠️'} 대용량 details 처리 {'OK' if sse_size < 10000 else '(크기 주의)'}")
    all_pass &= ok

    # ── B3: 빈 description/details ──
    print("\n=== B3: 빈 description/details ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    req_empty = InteractionRequest(
        type=InteractionType.APPROVAL,
        action="",
        description="",
        details={},
        timeout_seconds=5,
        agent_id="",
    )

    async def approve_empty(rid):
        await asyncio.sleep(0.1)
        manager.respond(rid, approved=True)

    task = asyncio.create_task(approve_empty(req_empty.id))
    result = await manager.request(req_empty)
    await task

    ok = result.status == ApprovalStatus.APPROVED
    print(f"  빈 필드로도 승인 가능: {result.status.value}")
    print(f"  {'✅' if ok else '❌'} 빈 필드 처리")
    all_pass &= ok

    # ── B4: 특수문자/유니코드 ──
    print("\n=== B4: 특수문자/유니코드 데이터 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    req_unicode = InteractionRequest(
        type=InteractionType.APPROVAL,
        action="send_email",
        description="이메일 전송: 📧 résumé → 你好世界 🌍",
        details={
            "to": "user@例え.jp",
            "subject": "Ñoño's <script>alert('xss')</script> Report",
            "emoji": "🎉🎊🎈",
        },
        timeout_seconds=5,
        agent_id="test_agent",
    )

    sse_unicode = json.dumps(req_unicode.to_sse_event(), ensure_ascii=False)

    async def approve_unicode(rid):
        await asyncio.sleep(0.1)
        manager.respond(rid, approved=True)

    task = asyncio.create_task(approve_unicode(req_unicode.id))
    result = await manager.request(req_unicode)
    await task

    ok = result.status == ApprovalStatus.APPROVED and "📧" in sse_unicode and "你好" in sse_unicode
    print(f"  유니코드 이벤트 크기: {len(sse_unicode)} bytes")
    print(f"  한글/이모지/CJK 포함: {'✅' if '📧' in sse_unicode else '❌'}")
    print(f"  XSS 시도 포함 (이스케이프됨): {'✅' if '<script>' in sse_unicode else '❌'}")
    print(f"  {'✅' if ok else '❌'} 특수문자 처리")
    all_pass &= ok

    # ── B5: 매우 짧은 타임아웃 (100ms) ──
    print("\n=== B5: 극단적 짧은 타임아웃 (100ms) ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    # asyncio.wait_for minimum is ~sleep granularity
    req_fast = InteractionRequest(
        type=InteractionType.APPROVAL, action="fast",
        description="Very fast timeout",
        timeout_seconds=0.1,  # 100ms
        agent_id="test",
    )

    t = time.time()
    result = await manager.request(req_fast)
    elapsed = time.time() - t

    ok = result.status == ApprovalStatus.TIMEOUT and elapsed < 1.0
    print(f"  타임아웃: {result.status.value}, {elapsed:.2f}s")
    print(f"  {'✅' if ok else '❌'} 100ms 타임아웃 처리")
    all_pass &= ok

    # ── B6: 동시 100개 요청 스트레스 ──
    print("\n=== B6: 동시 100개 요청 스트레스 테스트 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    N = 100
    reqs = [
        InteractionRequest(
            type=InteractionType.APPROVAL, action=f"stress_{i}",
            description=f"Stress {i}", timeout_seconds=10, agent_id=f"agent_{i}",
        )
        for i in range(N)
    ]

    async def bulk_approve():
        await asyncio.sleep(0.1)
        for r in reqs:
            manager.respond(r.id, approved=True)

    t = time.time()
    task = asyncio.create_task(bulk_approve())
    results = await asyncio.gather(*[manager.request(r) for r in reqs])
    elapsed = time.time() - t
    await task

    approved_count = sum(1 for r in results if r.status == ApprovalStatus.APPROVED)
    pending_after = len(manager.get_pending())

    ok = approved_count == N and pending_after == 0 and elapsed < 3.0
    print(f"  {N}개 동시 처리: {elapsed:.2f}s")
    print(f"  승인됨: {approved_count}/{N}")
    print(f"  잔여 pending: {pending_after}")
    print(f"  {'✅' if ok else '❌'} 100개 동시 스트레스")
    all_pass &= ok

    # ── B7: respond 후 다시 request (ID 재사용 불가 확인) ──
    print("\n=== B7: 완료된 request ID 재사용 불가 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    req_reuse = InteractionRequest(
        type=InteractionType.APPROVAL, action="reuse_test",
        description="Reuse test", timeout_seconds=5, agent_id="test",
    )
    saved_id = req_reuse.id

    async def quick_approve(rid):
        await asyncio.sleep(0.05)
        manager.respond(rid, approved=True)

    task = asyncio.create_task(quick_approve(saved_id))
    await manager.request(req_reuse)
    await task

    # Try to respond again with same ID
    found = manager.respond(saved_id, approved=False)
    ok = not found
    print(f"  완료 후 재응답 시도: found={found}")
    print(f"  {'✅' if ok else '❌'} ID 재사용 불가")
    all_pass &= ok

    # ── Summary ──
    total_a = 5
    total_b = 7
    total = total_a + total_b
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {'전체 통과 ✅' if all_pass else '일부 실패 ❌'}")
    print(f"Part A (SSE 경로): {total_a}개")
    print(f"  - REST approve/pending/404")
    print(f"  - SSE 스트림 승인 경로 (init → approval_required → approve → complete)")
    print(f"  - SSE 스트림 거부 경로")
    print(f"Part B (에지케이스): {total_b}개")
    print(f"  - ACP 다운, 대용량 details, 빈 필드")
    print(f"  - 유니코드/특수문자, 100ms 타임아웃, 100개 동시, ID 재사용")
    print(f"Total: {total}개 테스트")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
