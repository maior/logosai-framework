"""V2 SSE Bidirectional — Orchestrator 통합 시뮬레이션 테스트.

stream_with_orchestrator에서 InteractionEngine이 올바르게 동작하는지 검증.
실제 orchestrator 대신 mock으로 시뮬레이션.

테스트:
O1. 일반 쿼리 → 인터랙션 없이 통과
O2. 삭제 쿼리 → confirm → 승인 → 에이전트 실행
O3. 삭제 쿼리 → confirm → 거부 → 에이전트 미실행
O4. 번역 쿼리 → select → 선택 → enriched query로 에이전트 실행
O5. 이메일 쿼리 → form → 입력 → context에 정보 포함
O6. SSE 이벤트 순서 검증 (interaction_required → interaction_complete → agent events)

Usage: python tests/test_interaction_orchestrator.py
"""

import asyncio
import sys
import os
import time

_logos_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_logos_root, "logos_api"))

from app.services.interaction_engine import (
    InteractionEngine, InteractionManager, InteractionType,
)


async def simulate_orchestrator_flow(query, frontend_action=None, frontend_response=None):
    """Simulate the orchestrator flow with interaction.

    Returns (events, final_query, final_context).
    """
    InteractionManager._instance = None
    manager = InteractionManager.get()
    engine = InteractionEngine()

    events = []
    _interaction_queue = asyncio.Queue()

    async def sse_cb(event):
        await _interaction_queue.put(event)

    # Frontend simulator
    async def frontend():
        if frontend_action is None:
            return
        while True:
            pending = manager.get_pending()
            if pending:
                manager.respond(pending[0].id, frontend_response)
                return
            await asyncio.sleep(0.05)

    # Run interaction
    ft = asyncio.create_task(frontend())
    interaction_task = asyncio.create_task(
        engine.analyze_and_interact(query, {}, sse_callback=sse_cb)
    )

    # Drain interaction events
    while not interaction_task.done():
        try:
            event = await asyncio.wait_for(_interaction_queue.get(), timeout=0.1)
            events.append(event)
        except asyncio.TimeoutError:
            pass

    result = interaction_task.result()
    await ft

    # Simulate agent execution (only if not cancelled)
    if not result.enriched_context.get("confirmed") == False and not result.enriched_context.get("interaction_timeout"):
        events.append({"event": "agent_started", "data": {"query": result.enriched_query}})
        events.append({"event": "agent_complete", "data": {"result": "done", "context": result.enriched_context}})

    if result.had_interaction:
        events.append({"event": "interaction_complete", "data": {}})

    return events, result.enriched_query, result.enriched_context


async def main():
    print("=" * 70)
    print("V2 SSE Bidirectional — Orchestrator 통합 시뮬레이션")
    print("=" * 70)

    all_pass = True

    # ── O1: 일반 쿼리 → 인터랙션 없이 통과 ──
    print("\n=== O1: 일반 쿼리 — 인터랙션 없음 ===")
    events, query, ctx = await simulate_orchestrator_flow("오늘 날씨 알려줘")

    has_interaction = any(e["event"] == "interaction_required" for e in events)
    has_agent = any(e["event"] == "agent_started" for e in events)
    ok = not has_interaction and has_agent
    print(f"  인터랙션: {has_interaction}, 에이전트 실행: {has_agent}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── O2: 삭제 → confirm 승인 → 에이전트 실행 ──
    print("\n=== O2: 삭제 → confirm 승인 → 에이전트 실행 ===")
    events, query, ctx = await simulate_orchestrator_flow(
        "팀 미팅 삭제해줘", frontend_action="confirm", frontend_response=True
    )

    has_interaction = any(e["event"] == "interaction_required" for e in events)
    has_agent = any(e["event"] == "agent_started" for e in events)
    confirmed = ctx.get("confirmed")
    ok = has_interaction and has_agent and confirmed is True
    print(f"  인터랙션: {has_interaction}, 에이전트 실행: {has_agent}, confirmed: {confirmed}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── O3: 삭제 → confirm 거부 → 에이전트 미실행 ──
    print("\n=== O3: 삭제 → confirm 거부 → 에이전트 미실행 ===")
    events, query, ctx = await simulate_orchestrator_flow(
        "메모 삭제해줘", frontend_action="reject", frontend_response=False
    )

    has_interaction = any(e["event"] == "interaction_required" for e in events)
    has_agent = any(e["event"] == "agent_started" for e in events)
    confirmed = ctx.get("confirmed")
    ok = has_interaction and not has_agent and confirmed is False
    print(f"  인터랙션: {has_interaction}, 에이전트 실행: {has_agent}, confirmed: {confirmed}")
    print(f"  query: {query}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── O4: 번역 → select → enriched query ──
    print("\n=== O4: 번역 → select → enriched query ===")
    events, query, ctx = await simulate_orchestrator_flow(
        "안녕하세요 번역해줘", frontend_action="select", frontend_response="ja"
    )

    has_interaction = any(e["event"] == "interaction_required" for e in events)
    target = ctx.get("target_lang")
    ok = has_interaction and target == "ja" and "일본어" in query
    print(f"  target_lang: {target}, query: {query}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── O5: 이메일 → form → context 포함 ──
    print("\n=== O5: 이메일 → form → context 포함 ===")
    events, query, ctx = await simulate_orchestrator_flow(
        "이메일 보내줘", frontend_action="form",
        frontend_response={"to": "boss@company.com", "subject": "Report"}
    )

    has_interaction = any(e["event"] == "interaction_required" for e in events)
    has_to = ctx.get("to") == "boss@company.com"
    ok = has_interaction and has_to
    print(f"  to: {ctx.get('to')}, subject: {ctx.get('subject')}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── O6: SSE 이벤트 순서 ──
    print("\n=== O6: SSE 이벤트 순서 검증 ===")
    events, _, _ = await simulate_orchestrator_flow(
        "일정 삭제해줘", frontend_action="confirm", frontend_response=True
    )
    types = [e["event"] for e in events]

    # Expected: interaction_required → agent_started → agent_complete → interaction_complete
    idx_ir = types.index("interaction_required") if "interaction_required" in types else -1
    idx_as = types.index("agent_started") if "agent_started" in types else -1
    correct_order = idx_ir < idx_as and idx_ir >= 0
    ok = correct_order
    print(f"  이벤트 순서: {types}")
    print(f"  interaction_required({idx_ir}) < agent_started({idx_as}): {correct_order}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── Summary ──
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {'전체 통과 ✅' if all_pass else '일부 실패 ❌'}")
    print(f"  O1: 일반쿼리 통과, O2: 삭제승인, O3: 삭제거부")
    print(f"  O4: 번역선택, O5: 이메일폼, O6: 이벤트순서")
    print(f"Total: 6개 테스트")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
