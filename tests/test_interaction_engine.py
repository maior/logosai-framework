"""V2 SSE Bidirectional — InteractionEngine 단위 테스트.

테스트:
T1. 규칙 기반 분석 — 삭제 쿼리 → confirm
T2. 규칙 기반 분석 — 번역 (언어 미지정) → select
T3. 규칙 기반 분석 — 이메일 (수신자 미지정) → form
T4. 규칙 기반 분석 — 일반 쿼리 → none
T5. InteractionManager — 응답 대기 + 수신
T6. InteractionManager — 타임아웃
T7. analyze_and_interact — confirm 승인 플로우
T8. analyze_and_interact — confirm 거부 플로우
T9. analyze_and_interact — select 선택 플로우
T10. analyze_and_interact — form 입력 플로우
T11. SSE 이벤트 형식 검증
T12. enriched context 검증

Usage: python tests/test_interaction_engine.py
"""

import asyncio
import sys
import os

_logos_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_logos_root, "logos_api"))

from app.services.interaction_engine import (
    InteractionEngine, InteractionManager, InteractionRequest,
    InteractionType, InteractionOption, InteractionField,
    QueryAnalysis, InteractionResult,
)


def reset():
    InteractionManager._instance = None
    return InteractionManager.get()


async def main():
    print("=" * 70)
    print("V2 SSE Bidirectional — InteractionEngine 단위 테스트")
    print("=" * 70)

    all_pass = True
    engine = InteractionEngine()  # No LLM → rule-based

    # ── T1: 삭제 쿼리 → confirm ──
    print("\n=== T1: 삭제 쿼리 → confirm ===")
    a = engine._analyze_with_rules("내일 팀 미팅 삭제해줘", {})
    ok = a.needs_interaction and a.interaction_type == InteractionType.CONFIRM
    print(f"  type: {a.interaction_type.value}, question: {a.question[:40]}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T2: 번역 (언어 미지정) → select ──
    print("\n=== T2: 번역 (언어 미지정) → select ===")
    a = engine._analyze_with_rules("안녕하세요 번역해줘", {})
    ok = a.needs_interaction and a.interaction_type == InteractionType.SELECT and len(a.options) >= 3
    print(f"  type: {a.interaction_type.value}, options: {[o.label for o in a.options[:3]]}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T3: 번역 (언어 지정됨) → none ──
    print("\n=== T3: 번역 (언어 지정됨) → none ===")
    a = engine._analyze_with_rules("안녕하세요를 영어로 번역해줘", {})
    ok = not a.needs_interaction
    print(f"  needs_interaction: {a.needs_interaction}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T4: 이메일 (수신자 미지정) → form ──
    print("\n=== T4: 이메일 (수신자 미지정) → form ===")
    a = engine._analyze_with_rules("이메일 보내줘", {})
    ok = a.needs_interaction and a.interaction_type == InteractionType.FORM and len(a.fields) >= 2
    print(f"  type: {a.interaction_type.value}, fields: {[f.id for f in a.fields]}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T5: 일반 쿼리 → none ──
    print("\n=== T5: 일반 쿼리 → none ===")
    a = engine._analyze_with_rules("오늘 날씨 알려줘", {})
    ok = not a.needs_interaction
    print(f"  needs_interaction: {a.needs_interaction}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T6: InteractionManager — 응답 대기 + 수신 ──
    print("\n=== T6: InteractionManager 응답 대기 ===")
    manager = reset()
    req = InteractionRequest(type=InteractionType.CONFIRM, question="삭제?", timeout=5)

    async def respond_later(rid, delay=0.1):
        await asyncio.sleep(delay)
        manager.respond(rid, True)

    task = asyncio.create_task(respond_later(req.id))
    resp = await manager.wait_for_response(req)
    await task

    ok = resp is True and len(manager.get_pending()) == 0
    print(f"  response: {resp}, pending: {len(manager.get_pending())}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T7: InteractionManager — 타임아웃 ──
    print("\n=== T7: InteractionManager 타임아웃 ===")
    manager = reset()
    req = InteractionRequest(type=InteractionType.CONFIRM, question="삭제?", timeout=1)

    import time
    t = time.time()
    resp = await manager.wait_for_response(req)
    elapsed = time.time() - t

    ok = resp is None and 0.9 < elapsed < 2.0
    print(f"  response: {resp}, elapsed: {elapsed:.1f}s")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T8: analyze_and_interact — confirm 승인 ──
    print("\n=== T8: analyze_and_interact — confirm 승인 ===")
    reset()
    manager = InteractionManager.get()
    engine2 = InteractionEngine()
    sse_events = []

    async def sse_cb(event):
        sse_events.append(event)

    async def approve():
        await asyncio.sleep(0.1)
        pending = manager.get_pending()
        if pending:
            manager.respond(pending[0].id, True)

    task = asyncio.create_task(approve())
    result = await engine2.analyze_and_interact("팀 미팅 삭제해줘", {}, sse_callback=sse_cb)
    await task

    ok = (result.had_interaction and
          result.enriched_context.get("confirmed") is True and
          len(sse_events) == 1 and
          sse_events[0]["event"] == "interaction_required")
    print(f"  had_interaction: {result.had_interaction}")
    print(f"  confirmed: {result.enriched_context.get('confirmed')}")
    print(f"  SSE event: {sse_events[0]['event'] if sse_events else 'none'}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T9: analyze_and_interact — confirm 거부 ──
    print("\n=== T9: analyze_and_interact — confirm 거부 ===")
    reset()
    manager = InteractionManager.get()
    engine3 = InteractionEngine()
    sse_events.clear()

    async def reject():
        await asyncio.sleep(0.1)
        pending = manager.get_pending()
        if pending:
            manager.respond(pending[0].id, False)

    task = asyncio.create_task(reject())
    result = await engine3.analyze_and_interact("메모 삭제해줘", {}, sse_callback=sse_cb)
    await task

    ok = result.had_interaction and result.enriched_context.get("confirmed") is False
    print(f"  confirmed: {result.enriched_context.get('confirmed')}")
    print(f"  query: {result.enriched_query}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T10: analyze_and_interact — select 선택 ──
    print("\n=== T10: analyze_and_interact — select 선택 ===")
    reset()
    manager = InteractionManager.get()
    engine4 = InteractionEngine()
    sse_events.clear()

    async def select_ja():
        await asyncio.sleep(0.1)
        pending = manager.get_pending()
        if pending:
            manager.respond(pending[0].id, "ja")

    task = asyncio.create_task(select_ja())
    result = await engine4.analyze_and_interact("안녕하세요 번역해줘", {}, sse_callback=sse_cb)
    await task

    ok = (result.had_interaction and
          result.enriched_context.get("target_lang") == "ja" and
          "일본어" in result.enriched_query)
    print(f"  target_lang: {result.enriched_context.get('target_lang')}")
    print(f"  enriched_query: {result.enriched_query}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T11: analyze_and_interact — form 입력 ──
    print("\n=== T11: analyze_and_interact — form 입력 ===")
    reset()
    manager = InteractionManager.get()
    engine5 = InteractionEngine()
    sse_events.clear()

    async def fill_form():
        await asyncio.sleep(0.1)
        pending = manager.get_pending()
        if pending:
            manager.respond(pending[0].id, {
                "to": "user@example.com",
                "subject": "보고서",
                "body": "내용입니다",
            })

    task = asyncio.create_task(fill_form())
    result = await engine5.analyze_and_interact("이메일 보내줘", {}, sse_callback=sse_cb)
    await task

    ok = (result.had_interaction and
          result.enriched_context.get("to") == "user@example.com" and
          result.enriched_context.get("subject") == "보고서")
    print(f"  to: {result.enriched_context.get('to')}")
    print(f"  subject: {result.enriched_context.get('subject')}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T12: SSE 이벤트 형식 검증 ──
    print("\n=== T12: SSE 이벤트 형식 검증 ===")
    req = InteractionRequest(
        type=InteractionType.SELECT,
        question="선택하세요",
        options=[InteractionOption("a", "옵션A"), InteractionOption("b", "옵션B")],
        timeout=30,
        step=1,
        total_steps=2,
    )
    sse = req.to_sse_event()
    checks = {
        "event == interaction_required": sse["event"] == "interaction_required",
        "request_id exists": bool(sse["data"]["request_id"]),
        "type == select": sse["data"]["type"] == "select",
        "question not empty": bool(sse["data"]["question"]),
        "options count == 2": len(sse["data"]["options"]) == 2,
        "step == 1": sse["data"]["step"] == 1,
        "total_steps == 2": sse["data"]["total_steps"] == 2,
        "timeout == 30": sse["data"]["timeout"] == 30,
    }
    for check, passed in checks.items():
        print(f"  {'✅' if passed else '❌'} {check}")
    ok = all(checks.values())
    all_pass &= ok

    # ── Summary ──
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {'전체 통과 ✅' if all_pass else '일부 실패 ❌'}")
    print(f"  규칙 분석: T1-T5 (confirm/select/form/none)")
    print(f"  Manager: T6-T7 (응답/타임아웃)")
    print(f"  Full flow: T8-T11 (confirm승인/거부, select, form)")
    print(f"  SSE 형식: T12")
    print(f"Total: 12개 테스트")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
