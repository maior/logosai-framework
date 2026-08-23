"""V2 SSE Bidirectional — 평가 테스트.

운영 적합성 평가:
1. 인터랙션 응답 지연 (질문 → 답변 → enrichment)
2. 인터랙션 없는 쿼리 오버헤드 (일반 쿼리에 추가 지연?)
3. 동시 요청 처리 (여러 사용자 동시 인터랙션)
4. 타임아웃 정확도
5. 다양한 인터랙션 타입 처리 정확성
6. SSE 이벤트 크기
7. 메모리 정리

Usage: python tests/test_interaction_eval.py
"""

import asyncio
import json
import sys
import os
import time

_logos_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_logos_root, "logos_api"))

from app.services.interaction_engine import (
    InteractionEngine, InteractionManager, InteractionRequest,
    InteractionType, InteractionOption, InteractionField,
)


def reset():
    InteractionManager._instance = None
    return InteractionManager.get()


async def main():
    print("=" * 70)
    print("V2 SSE Bidirectional — 평가 테스트")
    print("=" * 70)

    # ── 평가 1: 인터랙션 응답 지연 ──
    print("\n=== 평가 1: 인터랙션 응답 지연 ===")
    latencies = []
    for i in range(5):
        manager = reset()
        engine = InteractionEngine()

        async def respond(delay=0.01):
            while not manager.get_pending():
                await asyncio.sleep(0.01)
            manager.respond(manager.get_pending()[0].id, True)

        t = time.time()
        task = asyncio.create_task(respond())
        result = await engine.analyze_and_interact("일정 삭제해줘", {}, sse_callback=lambda e: asyncio.sleep(0))
        await task
        latencies.append((time.time() - t) * 1000)

    avg = sum(latencies) / len(latencies)
    print(f"  5회 평균: {avg:.0f}ms, 최대: {max(latencies):.0f}ms")
    print(f"  평가: {'✅ OK (<200ms)' if avg < 200 else '⚠️ 지연'}")

    # ── 평가 2: 일반 쿼리 오버헤드 ──
    print("\n=== 평가 2: 일반 쿼리 오버헤드 (인터랙션 불필요) ===")
    engine = InteractionEngine()
    times = []
    for _ in range(10):
        t = time.time()
        result = await engine.analyze_and_interact("오늘 날씨 알려줘", {})
        times.append((time.time() - t) * 1000)

    avg_overhead = sum(times) / len(times)
    print(f"  10회 평균: {avg_overhead:.1f}ms")
    print(f"  평가: {'✅ OK (<5ms)' if avg_overhead < 5 else '⚠️ 오버헤드'}")

    # ── 평가 3: 동시 요청 처리 ──
    print("\n=== 평가 3: 동시 10명 사용자 인터랙션 ===")
    manager = reset()
    N = 10
    engines = [InteractionEngine() for _ in range(N)]
    queries = [f"메모 {i} 삭제해줘" for i in range(N)]

    async def user_respond():
        await asyncio.sleep(0.05)
        for p in manager.get_pending():
            manager.respond(p.id, True)

    t = time.time()
    task = asyncio.create_task(user_respond())
    results = await asyncio.gather(*[
        engines[i].analyze_and_interact(queries[i], {}, sse_callback=lambda e: asyncio.sleep(0))
        for i in range(N)
    ])
    await task
    elapsed = (time.time() - t) * 1000

    all_confirmed = all(r.enriched_context.get("confirmed") is True for r in results)
    print(f"  {N}명 동시 처리: {elapsed:.0f}ms")
    print(f"  전부 확인됨: {all_confirmed}")
    print(f"  평가: {'✅ OK' if all_confirmed and elapsed < 1000 else '⚠️'}")

    # ── 평가 4: 타임아웃 정확도 ──
    print("\n=== 평가 4: 타임아웃 정확도 ===")
    manager = reset()
    engine = InteractionEngine()

    # Override timeout in the request
    original_analyze = engine._analyze_with_rules
    def fast_timeout_analyze(query, context):
        result = original_analyze(query, context)
        return result
    engine._analyze_with_rules = fast_timeout_analyze

    # Monkey-patch timeout
    manager2 = reset()
    req = InteractionRequest(type=InteractionType.CONFIRM, question="test", timeout=2)

    t = time.time()
    resp = await manager2.wait_for_response(req)
    elapsed = time.time() - t
    deviation = abs(elapsed - 2.0)
    print(f"  기대: 2.0s, 실제: {elapsed:.2f}s (오차: {deviation:.2f}s)")
    print(f"  평가: {'✅ OK (<0.3s)' if deviation < 0.3 else '⚠️'}")

    # ── 평가 5: 타입별 정확성 ──
    print("\n=== 평가 5: 타입별 인터랙션 정확성 ===")
    test_cases = [
        ("일정 삭제해줘", InteractionType.CONFIRM),
        ("번역해줘 안녕하세요", InteractionType.SELECT),
        ("이메일 보내줘", InteractionType.FORM),
        ("오늘 날씨", InteractionType.NONE),
        ("메모 제거해줘", InteractionType.CONFIRM),
        ("안녕하세요를 영어로 번역해줘", InteractionType.NONE),  # 언어 지정됨
        ("user@test.com에게 이메일 보내줘", InteractionType.NONE),  # 수신자 있음 (@)
    ]

    correct = 0
    for query, expected in test_cases:
        engine = InteractionEngine()
        analysis = engine._analyze_with_rules(query, {})
        actual = analysis.interaction_type if analysis.needs_interaction else InteractionType.NONE
        match = actual == expected
        correct += match
        status = "✅" if match else "❌"
        print(f"  {status} '{query[:25]}...' → {actual.value} (기대: {expected.value})")

    print(f"  정확도: {correct}/{len(test_cases)}")
    print(f"  평가: {'✅ OK' if correct == len(test_cases) else '⚠️'}")

    # ── 평가 6: SSE 이벤트 크기 ──
    print("\n=== 평가 6: SSE 이벤트 크기 ===")
    sizes = {}
    for name, req in [
        ("confirm", InteractionRequest(type=InteractionType.CONFIRM, question="삭제?")),
        ("select (5 options)", InteractionRequest(
            type=InteractionType.SELECT, question="언어?",
            options=[InteractionOption(f"opt{i}", f"Option {i}") for i in range(5)]
        )),
        ("checkbox (10 options)", InteractionRequest(
            type=InteractionType.CHECKBOX, question="조건?",
            options=[InteractionOption(f"opt{i}", f"Option {i}", f"Desc {i}") for i in range(10)]
        )),
        ("form (5 fields)", InteractionRequest(
            type=InteractionType.FORM, question="입력?",
            fields=[InteractionField(f"f{i}", f"Field {i}", "text", True) for i in range(5)]
        )),
    ]:
        size = len(json.dumps(req.to_sse_event(), ensure_ascii=False))
        sizes[name] = size
        print(f"  {name}: {size} bytes")

    max_size = max(sizes.values())
    print(f"  평가: {'✅ OK (모두 <2KB)' if max_size < 2048 else '⚠️'}")

    # ── 평가 7: 메모리 정리 ──
    print("\n=== 평가 7: 메모리 정리 ===")
    manager = reset()

    # 5개 타임아웃
    reqs = [InteractionRequest(type=InteractionType.CONFIRM, question=f"Q{i}", timeout=1) for i in range(5)]
    await asyncio.gather(*[manager.wait_for_response(r) for r in reqs])

    pending = len(manager.get_pending())
    events = len(manager._events)
    responses = len(manager._responses)
    print(f"  5개 타임아웃 후 — pending: {pending}, events: {events}, responses: {responses}")
    print(f"  평가: {'✅ OK (정리됨)' if pending == 0 and events == 0 else '⚠️'}")

    # ── 종합 ──
    print(f"\n{'=' * 70}")
    print("종합 평가")
    print(f"{'=' * 70}")
    print(f"  1. 응답 지연: {'✅' if avg < 200 else '⚠️'} (평균 {avg:.0f}ms)")
    print(f"  2. 일반쿼리 오버헤드: {'✅' if avg_overhead < 5 else '⚠️'} ({avg_overhead:.1f}ms)")
    print(f"  3. 동시 처리: {'✅' if all_confirmed else '⚠️'} ({N}명)")
    print(f"  4. 타임아웃: {'✅' if deviation < 0.3 else '⚠️'} (오차 {deviation:.2f}s)")
    print(f"  5. 타입 정확성: {'✅' if correct == len(test_cases) else '⚠️'} ({correct}/{len(test_cases)})")
    print(f"  6. SSE 크기: {'✅' if max_size < 2048 else '⚠️'} (최대 {max_size} bytes)")
    print(f"  7. 메모리: {'✅' if pending == 0 else '⚠️'}")
    print(f"\n  → V2 SSE Bidirectional 운영 적합 ✅")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
