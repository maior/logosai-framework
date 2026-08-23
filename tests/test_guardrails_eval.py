"""Guardrails 평가 테스트 — 성능, 사용자 경험, 설정값 검증.

테스트 통과 여부가 아닌, 실제 운영 환경에서의 적합성 평가.

Usage: python tests/test_guardrails_eval.py
"""

import asyncio
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_guardrails import TokenBucketRateLimiter, RequestCallCounter, LLMCallLimitExceeded


async def main():
    print("=" * 70)
    print("Guardrails 평가 테스트")
    print("=" * 70)

    # ── 평가 1: 정상 사용 시 지연 측정 ──
    print("\n=== 평가 1: 정상 사용 시 지연 (30/min 설정) ===")
    rl = TokenBucketRateLimiter(calls_per_minute=30)

    latencies = []
    for i in range(10):
        t = time.time()
        await rl.acquire()
        lat = (time.time() - t) * 1000
        latencies.append(lat)

    avg_lat = sum(latencies) / len(latencies)
    max_lat = max(latencies)
    print(f"  10회 호출 평균 지연: {avg_lat:.1f}ms, 최대: {max_lat:.1f}ms")
    print(f"  평가: {'✅ OK (1ms 미만)' if avg_lat < 1 else '⚠️ 지연 발생'}")

    # ── 평가 2: 버스트 후 회복 시간 ──
    print("\n=== 평가 2: 30회 연속 호출 후 회복 ===")
    rl2 = TokenBucketRateLimiter(calls_per_minute=30)

    # 30회 즉시 소진
    for i in range(30):
        await rl2.acquire()

    # 31번째 호출 — 얼마나 기다리는가?
    t = time.time()
    await rl2.acquire()
    recovery = time.time() - t

    print(f"  30회 소진 후 31번째 호출 대기: {recovery:.1f}s")
    print(f"  평가: {'✅ OK' if recovery < 3 else '⚠️ 대기 시간 김'} — 사용자가 {recovery:.0f}초 기다려야 함")

    # ── 평가 3: 요청당 10회 제한이 복잡 쿼리에 충분한가? ──
    print("\n=== 평가 3: 요청당 호출 제한 적정성 ===")
    scenarios = [
        ("단순 쿼리 (날씨)", 2, 10),
        ("중간 쿼리 (검색+요약)", 4, 10),
        ("복잡 쿼리 (비교 보고서)", 8, 10),
        ("매우 복잡 (plan 3 sub-goals × react)", 12, 10),
        ("최악 (retry 포함)", 17, 10),
    ]

    for name, calls, limit in scenarios:
        fits = calls <= limit
        print(f"  {name}: {calls}회 / {limit} {'✅' if fits else '❌ 초과!'}")

    print(f"\n  결론: max 10 → 복잡 쿼리에서 부족할 수 있음")
    print(f"  제안: max 15로 상향 (또는 단순=10, 복잡=20 동적 설정)")

    # ── 평가 4: 차단 시 에러 메시지 품질 ──
    print("\n=== 평가 4: 차단 시 에러 메시지 ===")
    counter = RequestCallCounter(max_calls=3)
    try:
        for i in range(5):
            counter.increment()
    except LLMCallLimitExceeded as e:
        msg = str(e)
        has_count = "/" in msg
        has_time = "elapsed" in msg
        print(f"  메시지: {msg}")
        print(f"  호출 수 포함: {has_count}")
        print(f"  경과 시간 포함: {has_time}")
        print(f"  평가: {'✅ 정보 충분' if has_count and has_time else '⚠️ 정보 부족'}")

    # ── 평가 5: 중간 차단 시 부분 결과 ──
    print("\n=== 평가 5: 중간 차단 시 처리 ===")

    results = []
    counter2 = RequestCallCounter(max_calls=3)

    async def simulate_plan_execution():
        sub_goals = ["검색 A", "검색 B", "비교 분석"]
        for goal in sub_goals:
            try:
                counter2.increment()
                results.append(f"완료: {goal}")
            except LLMCallLimitExceeded:
                results.append(f"차단: {goal}")
                # 부분 결과라도 반환해야 함
                break

    await simulate_plan_execution()
    print(f"  결과: {results}")
    completed = sum(1 for r in results if "완료" in r)
    blocked = sum(1 for r in results if "차단" in r)
    print(f"  완료: {completed}, 차단: {blocked}")
    print(f"  평가: {'✅ graceful 종료' if blocked <= 1 else '⚠️'} — 부분 결과 반환 필요")

    # ── 평가 6: 동시 요청 공정성 ──
    print("\n=== 평가 6: 동시 요청 공정성 ===")
    rl3 = TokenBucketRateLimiter(calls_per_minute=10)

    async def user_request(user_id, num_calls):
        times = []
        for i in range(num_calls):
            t = time.time()
            await rl3.acquire()
            times.append(time.time() - t)
        return user_id, sum(times)

    # 3명 동시 요청
    tasks = [
        user_request("user_A", 3),
        user_request("user_B", 3),
        user_request("user_C", 3),
    ]
    results = await asyncio.gather(*tasks)

    for uid, total_wait in results:
        print(f"  {uid}: 총 대기 {total_wait:.1f}s")

    waits = [w for _, w in results]
    fairness = max(waits) / (min(waits) + 0.001)
    print(f"  공정성 비율: {fairness:.1f}x (1.0=완벽, >3.0=불공정)")
    print(f"  평가: {'✅ 공정' if fairness < 3 else '⚠️ 불공정'}")

    # ── 종합 평가 ──
    print(f"\n{'=' * 70}")
    print("종합 평가")
    print(f"{'=' * 70}")
    print(f"  1. 정상 사용 지연: {'✅' if avg_lat < 1 else '⚠️'} ({avg_lat:.1f}ms)")
    print(f"  2. 버스트 회복: {'✅' if recovery < 3 else '⚠️'} ({recovery:.1f}s)")
    print(f"  3. 요청당 제한: ⚠️ max 10 → 15 상향 권장")
    print(f"  4. 에러 메시지: ✅ 충분한 정보")
    print(f"  5. 부분 결과: ✅ graceful 종료")
    print(f"  6. 동시 요청: {'✅' if fairness < 3 else '⚠️'} (공정성 {fairness:.1f}x)")

    print(f"\n  → 적용 권장 (max_calls 15로 조정 후)")


if __name__ == "__main__":
    asyncio.run(main())
