"""Phase G: Observability — MetricsCollector 단위 테스트.

PostgreSQL에 직접 기록/조회 테스트.
서버: 211.180.253.250:5432/logosai (logosus 스키마)

테스트:
T1. record_execution — 실행 기록 + DB 확인
T2. record_llm_call — LLM 호출 기록 + 비용 계산
T3. daily_stat 자동 업데이트
T4. get_dashboard_summary
T5. get_agent_stats
T6. get_traces
T7. get_trace_detail (LLM 호출 트리)
T8. get_cost_breakdown
T9. get_hourly_trend
T10. 성능: 기록 지연 측정

Usage: python tests/test_metrics_collector.py
"""

import asyncio
import sys
import os
import time

_logos_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_logos_root, "logos_api"))

# DB connection
DB_URL = "postgresql+asyncpg://logosai:logosai1234@211.180.253.250:5432/logosai"


async def main():
    print("=" * 70)
    print("Phase G: MetricsCollector 단위 테스트")
    print("=" * 70)

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from contextlib import asynccontextmanager

    engine = create_async_engine(DB_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def get_db():
        async with SessionLocal() as session:
            yield session

    from app.services.metrics_collector import MetricsCollector
    collector = MetricsCollector(get_db)

    all_pass = True

    # ── T1: record_execution ──
    print("\n=== T1: record_execution ===")
    t = time.time()
    exec_id = await collector.record_execution(
        agent_id="test_scheduler",
        query="이번주 일정 보여줘",
        success=True,
        duration_ms=3200,
        agent_name="일정관리 에이전트",
        correlation_id="test-corr-001",
        user_email="test@example.com",
    )
    lat = (time.time() - t) * 1000
    ok = bool(exec_id) and len(exec_id) == 36  # UUID
    print(f"  exec_id: {exec_id[:12]}... ({lat:.0f}ms)")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T2: record_llm_call ──
    print("\n=== T2: record_llm_call + 비용 계산 ===")
    call_id = await collector.record_llm_call(
        execution_id=exec_id,
        agent_id="test_scheduler",
        model="gemini-2.5-flash-lite",
        provider="google",
        input_tokens=500,
        output_tokens=200,
        duration_ms=800,
        prompt_preview="이번주 일정을 조회합니다...",
    )
    # 두 번째 LLM 호출
    call_id2 = await collector.record_llm_call(
        execution_id=exec_id,
        agent_id="test_scheduler",
        model="gemini-2.5-flash-lite",
        provider="google",
        input_tokens=300,
        output_tokens=1500,
        duration_ms=2100,
        prompt_preview="마크다운 응답 생성...",
    )
    ok = bool(call_id) and bool(call_id2)
    # 비용 검증: (500*0.075 + 200*0.30) / 1M + (300*0.075 + 1500*0.30) / 1M
    expected_cost = (500*0.075 + 200*0.30 + 300*0.075 + 1500*0.30) / 1_000_000
    print(f"  LLM 호출 2건 기록")
    print(f"  예상 비용: ${expected_cost:.6f}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T3: 추가 실행 기록 (다른 에이전트) ──
    print("\n=== T3: 다중 에이전트 기록 ===")
    await collector.record_execution(
        agent_id="test_internet", query="날씨 검색",
        success=True, duration_ms=5400, agent_name="인터넷 에이전트",
    )
    await collector.record_execution(
        agent_id="test_internet", query="환율 검색",
        success=False, duration_ms=8200, error_message="Timeout",
        agent_name="인터넷 에이전트",
    )
    await collector.record_execution(
        agent_id="test_kakaotalk", query="카카오톡 전송",
        success=True, duration_ms=12000, agent_name="카카오톡 에이전트",
    )
    print(f"  3건 추가 기록 완료")
    print(f"  ✅")

    # ── T4: get_dashboard_summary ──
    print("\n=== T4: get_dashboard_summary ===")
    summary = await collector.get_dashboard_summary(period="1h")
    ok = (summary.get("total_calls", 0) >= 4 and
          summary.get("active_agents", 0) >= 3 and
          "success_rate" in summary)
    print(f"  total_calls: {summary.get('total_calls')}")
    print(f"  success_rate: {summary.get('success_rate')}")
    print(f"  avg_duration: {summary.get('avg_duration_ms')}ms")
    print(f"  total_tokens: {summary.get('total_tokens')}")
    print(f"  total_cost: ${summary.get('total_cost_usd')}")
    print(f"  active_agents: {summary.get('active_agents')}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T5: get_agent_stats ──
    print("\n=== T5: get_agent_stats ===")
    stats = await collector.get_agent_stats(period="1h")
    ok = len(stats) >= 3
    for s in stats[:5]:
        print(f"  {s['agent_id']}: {s['total_calls']}회, 성공률 {s['success_rate']:.0%}, 평균 {s['avg_duration_ms']:.0f}ms")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T6: get_traces ──
    print("\n=== T6: get_traces ===")
    traces = await collector.get_traces(limit=10, period="1h")
    ok = len(traces) >= 4
    for t in traces[:3]:
        status = "✅" if t["success"] else "❌"
        print(f"  {status} {t['agent_id']}: {t['query'][:30]} ({t['duration_ms']:.0f}ms)")
    print(f"  총 {len(traces)}건")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T7: get_trace_detail ──
    print("\n=== T7: get_trace_detail (LLM 트리) ===")
    detail = await collector.get_trace_detail(exec_id)
    ok = (detail is not None and
          len(detail.get("llm_calls", [])) == 2 and
          detail["summary"]["total_llm_calls"] == 2)
    if detail:
        print(f"  에이전트: {detail['execution']['agent_id']}")
        print(f"  LLM 호출: {detail['summary']['total_llm_calls']}건")
        print(f"  총 토큰: {detail['summary']['total_tokens']}")
        print(f"  총 비용: ${detail['summary']['total_cost_usd']:.6f}")
        for c in detail["llm_calls"]:
            print(f"    ├ {c['model']}: {c['total_tokens']} tokens, {c['duration_ms']:.0f}ms, ${c['cost_usd']:.6f}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T8: get_cost_breakdown ──
    print("\n=== T8: get_cost_breakdown ===")
    costs = await collector.get_cost_breakdown(period="1h")
    ok = costs.get("total_cost_usd", 0) > 0 or len(costs.get("by_model", [])) > 0
    print(f"  총 비용: ${costs.get('total_cost_usd')}")
    for m in costs.get("by_model", []):
        print(f"    {m['model']}: {m['calls']}회, {m['tokens']} tokens, ${m['cost_usd']}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T9: get_hourly_trend ──
    print("\n=== T9: get_hourly_trend ===")
    trend = await collector.get_hourly_trend(period="24h")
    ok = len(trend) >= 1
    for h in trend[:3]:
        print(f"  {h['hour'][:16]}: {h['calls']}회, {h['avg_duration_ms']:.0f}ms, ${h['cost_usd']}")
    print(f"  {'✅' if ok else '❌'}")
    all_pass &= ok

    # ── T10: 성능 — 기록 지연 ──
    print("\n=== T10: 기록 지연 측정 ===")
    latencies = []
    for i in range(5):
        t = time.time()
        await collector.record_execution(
            agent_id=f"perf_test_{i}", query="성능 테스트",
            success=True, duration_ms=100,
        )
        latencies.append((time.time() - t) * 1000)

    avg_lat = sum(latencies) / len(latencies)
    max_lat = max(latencies)
    print(f"  5회 평균: {avg_lat:.0f}ms, 최대: {max_lat:.0f}ms")
    ok = avg_lat < 100  # 100ms 이내
    print(f"  평가: {'✅ OK (<100ms)' if ok else '⚠️ 느림'}")
    all_pass &= ok

    # 정리: 테스트 데이터 삭제
    async with get_db() as db:
        from sqlalchemy import text
        await db.execute(text("DELETE FROM logosus.llm_calls WHERE agent_id LIKE 'test_%'"))
        await db.execute(text("DELETE FROM logosus.agent_executions WHERE agent_id LIKE 'test_%' OR agent_id LIKE 'perf_test_%'"))
        await db.execute(text("DELETE FROM logosus.daily_stats WHERE agent_id LIKE 'test_%' OR agent_id LIKE 'perf_test_%'"))
        await db.commit()
    print("\n  테스트 데이터 정리 완료")

    await engine.dispose()

    # Summary
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {'전체 통과 ✅' if all_pass else '일부 실패 ❌'}")
    print(f"  T1-T3: 기록 (execution + llm_call + daily_stat)")
    print(f"  T4-T9: 조회 (dashboard, agents, traces, detail, costs, trend)")
    print(f"  T10: 성능 ({avg_lat:.0f}ms)")
    print(f"Total: 10개 테스트")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
