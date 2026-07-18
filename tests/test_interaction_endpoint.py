"""V2 SSE Bidirectional — REST 엔드포인트 + SSE 연동 테스트.

InteractionEngine이 SSE를 보내고, REST로 응답을 받는 전체 플로우 검증.
미니 서버로 실제 HTTP 레벨 테스트.

테스트:
E1. POST /interaction/{id} — confirm 응답
E2. POST /interaction/{id} — select 응답
E3. POST /interaction/{id} — form 응답
E4. GET /interaction/pending — 대기 목록
E5. POST 존재하지 않는 ID → 404
E6. SSE → REST → Engine unblock 전체 플로우

Usage: python tests/test_interaction_endpoint.py
"""

import asyncio
import json
import sys
import os
import time

_logos_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_logos_root, "logos_api"))

from aiohttp import web
import aiohttp

from app.services.interaction_engine import (
    InteractionEngine, InteractionManager, InteractionRequest,
    InteractionType, InteractionOption,
)


def create_test_app():
    """Create mini aiohttp server with interaction endpoints."""
    app = web.Application()

    async def handle_respond(request):
        request_id = request.match_info["request_id"]
        body = await request.json()
        manager = InteractionManager.get()
        found = manager.respond(request_id, body.get("response"))
        if not found:
            return web.json_response({"error": "Not found"}, status=404)
        return web.json_response({"request_id": request_id, "status": "responded"})

    async def handle_pending(request):
        manager = InteractionManager.get()
        pending = manager.get_pending()
        return web.json_response([
            {"request_id": r.id, "type": r.type.value, "question": r.question}
            for r in pending
        ])

    app.router.add_post("/api/v1/interaction/{request_id}", handle_respond)
    app.router.add_get("/api/v1/interaction/pending", handle_pending)
    return app


async def main():
    print("=" * 70)
    print("V2 SSE Bidirectional — REST 엔드포인트 테스트")
    print("=" * 70)

    PORT = 19891
    URL = f"http://localhost:{PORT}"
    all_pass = True

    # Start mini server
    app = create_test_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", PORT)
    await site.start()
    print(f"  Mini server started on port {PORT}")

    try:
        # ── E1: confirm 응답 ──
        print("\n=== E1: POST confirm 응답 ===")
        InteractionManager._instance = None
        manager = InteractionManager.get()
        req = InteractionRequest(type=InteractionType.CONFIRM, question="삭제?", timeout=5)

        async def rest_confirm():
            await asyncio.sleep(0.1)
            async with aiohttp.ClientSession() as s:
                r = await s.post(f"{URL}/api/v1/interaction/{req.id}", json={"response": True})
                return r.status

        task = asyncio.create_task(rest_confirm())
        resp = await manager.wait_for_response(req)
        status = await task

        ok = resp is True and status == 200
        print(f"  response: {resp}, HTTP: {status}")
        print(f"  {'✅' if ok else '❌'}")
        all_pass &= ok

        # ── E2: select 응답 ──
        print("\n=== E2: POST select 응답 ===")
        InteractionManager._instance = None
        manager = InteractionManager.get()
        req = InteractionRequest(type=InteractionType.SELECT, question="언어?", timeout=5)

        async def rest_select():
            await asyncio.sleep(0.1)
            async with aiohttp.ClientSession() as s:
                r = await s.post(f"{URL}/api/v1/interaction/{req.id}", json={"response": "ja"})
                return r.status, await r.json()

        task = asyncio.create_task(rest_select())
        resp = await manager.wait_for_response(req)
        status, body = await task

        ok = resp == "ja" and status == 200 and body["status"] == "responded"
        print(f"  response: {resp}, HTTP: {status}")
        print(f"  {'✅' if ok else '❌'}")
        all_pass &= ok

        # ── E3: form 응답 ──
        print("\n=== E3: POST form 응답 ===")
        InteractionManager._instance = None
        manager = InteractionManager.get()
        req = InteractionRequest(type=InteractionType.FORM, question="이메일?", timeout=5)

        form_data = {"to": "user@example.com", "subject": "Report"}

        async def rest_form():
            await asyncio.sleep(0.1)
            async with aiohttp.ClientSession() as s:
                r = await s.post(f"{URL}/api/v1/interaction/{req.id}", json={"response": form_data})
                return r.status

        task = asyncio.create_task(rest_form())
        resp = await manager.wait_for_response(req)
        status = await task

        ok = resp == form_data and status == 200
        print(f"  response: {resp}")
        print(f"  {'✅' if ok else '❌'}")
        all_pass &= ok

        # ── E4: GET pending ──
        print("\n=== E4: GET pending 목록 ===")
        InteractionManager._instance = None
        manager = InteractionManager.get()
        # Create pending request
        req1 = InteractionRequest(type=InteractionType.CONFIRM, question="Q1", timeout=10)
        req2 = InteractionRequest(type=InteractionType.SELECT, question="Q2", timeout=10)
        manager._pending[req1.id] = req1
        manager._events[req1.id] = asyncio.Event()
        manager._pending[req2.id] = req2
        manager._events[req2.id] = asyncio.Event()

        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{URL}/api/v1/interaction/pending")
            body = await r.json()

        ok = r.status == 200 and len(body) == 2
        print(f"  pending count: {len(body)}")
        print(f"  types: {[p['type'] for p in body]}")
        print(f"  {'✅' if ok else '❌'}")
        all_pass &= ok

        # Cleanup
        manager.respond(req1.id, True)
        manager.respond(req2.id, "opt1")

        # ── E5: 존재하지 않는 ID → 404 ──
        print("\n=== E5: POST 존재하지 않는 ID → 404 ===")
        async with aiohttp.ClientSession() as s:
            r = await s.post(f"{URL}/api/v1/interaction/nonexistent_xyz", json={"response": True})

        ok = r.status == 404
        print(f"  HTTP: {r.status}")
        print(f"  {'✅' if ok else '❌'}")
        all_pass &= ok

        # ── E6: SSE → REST → Engine unblock 전체 플로우 ──
        print("\n=== E6: SSE → REST → Engine 전체 플로우 ===")
        InteractionManager._instance = None
        manager = InteractionManager.get()
        engine = InteractionEngine()
        sse_events = []

        async def sse_cb(event):
            sse_events.append(event)

        async def frontend_respond():
            """Simulate frontend: wait for pending, then POST response."""
            while True:
                pending = manager.get_pending()
                if pending:
                    req_id = pending[0].id
                    async with aiohttp.ClientSession() as s:
                        await s.post(f"{URL}/api/v1/interaction/{req_id}", json={"response": True})
                    return
                await asyncio.sleep(0.05)

        frontend_task = asyncio.create_task(frontend_respond())
        result = await engine.analyze_and_interact("메모 삭제해줘", {}, sse_callback=sse_cb)
        await frontend_task

        ok = (result.had_interaction and
              result.enriched_context.get("confirmed") is True and
              len(sse_events) == 1 and
              sse_events[0]["event"] == "interaction_required" and
              sse_events[0]["data"]["type"] == "confirm")
        print(f"  had_interaction: {result.had_interaction}")
        print(f"  confirmed: {result.enriched_context.get('confirmed')}")
        print(f"  SSE events: {len(sse_events)}")
        print(f"  SSE type: {sse_events[0]['data']['type']}")
        print(f"  {'✅' if ok else '❌'}")
        all_pass &= ok

    finally:
        await runner.cleanup()

    # ── Summary ──
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {'전체 통과 ✅' if all_pass else '일부 실패 ❌'}")
    print(f"  E1-E3: REST confirm/select/form 응답")
    print(f"  E4: pending 목록")
    print(f"  E5: 404 에러")
    print(f"  E6: SSE → REST → Engine 전체 플로우")
    print(f"Total: 6개 테스트")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
