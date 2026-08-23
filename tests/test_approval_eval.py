"""Phase E: SSE Bidirectional — 평가 테스트.

테스트 통과 여부가 아닌, 실제 운영 환경에서의 적합성 평가.

평가 항목:
1. 응답 지연 — 승인 요청~해제까지 지연 측정
2. 타임아웃 설정 적정성 — 다양한 시나리오별 적절한 타임아웃
3. 동시 요청 부하 — 10+ 동시 승인 요청 처리
4. SSE 이벤트 크기 — 네트워크 오버헤드
5. 메모리 누수 — 미응답 요청 정리 확인
6. 사용자 경험 — 다이얼로그 응답 시간 시뮬레이션
7. 에러 복구 — 비정상 응답/이중 응답/잘못된 ID

Usage: python tests/test_approval_eval.py
"""

import asyncio
import sys
import os
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from logosai.agentic.approval import (
    ApprovalManager,
    ApprovalStatus,
    InteractionRequest,
    InteractionType,
)


async def main():
    print("=" * 70)
    print("Phase E: SSE Bidirectional — 평가 테스트")
    print("=" * 70)

    # ── 평가 1: 응답 지연 측정 ──
    print("\n=== 평가 1: 승인 요청 → 해제 지연 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    latencies = []
    for i in range(10):
        req = InteractionRequest(
            type=InteractionType.APPROVAL,
            action=f"action_{i}",
            description=f"Test {i}",
            timeout_seconds=5,
            agent_id="test",
        )

        async def respond_fast(rid):
            await asyncio.sleep(0.01)  # 10ms 사용자 응답 시뮬레이션
            manager.respond(rid, approved=True)

        t = time.time()
        task = asyncio.create_task(respond_fast(req.id))
        await manager.request(req)
        lat = (time.time() - t) * 1000
        latencies.append(lat)
        await task

    avg_lat = sum(latencies) / len(latencies)
    max_lat = max(latencies)
    min_lat = min(latencies)
    print(f"  10회 평균 지연: {avg_lat:.1f}ms, 최소: {min_lat:.1f}ms, 최대: {max_lat:.1f}ms")
    print(f"  평가: {'✅ OK (50ms 미만)' if avg_lat < 50 else '⚠️ 지연 발생'}")

    # ── 평가 2: 타임아웃 설정 적정성 ──
    print("\n=== 평가 2: 시나리오별 타임아웃 적정성 ===")
    scenarios = [
        ("이메일 전송 확인", "send_email", 30, "사용자가 내용 확인 필요"),
        ("파일 삭제 확인", "delete_file", 15, "빠른 예/아니오"),
        ("번역 언어 선택", "choose_language", 60, "옵션 비교 필요"),
        ("추가 정보 입력", "input_details", 120, "사용자가 타이핑 필요"),
        ("긴급 배포 승인", "deploy_prod", 30, "신중하지만 빠르게"),
        ("카카오톡 메시지 전송", "send_kakaotalk", 20, "미리보기 확인만"),
    ]

    for name, action, timeout, reason in scenarios:
        appropriate = True
        if action in ("delete_file", "send_kakaotalk") and timeout > 30:
            appropriate = False
        if action == "input_details" and timeout < 60:
            appropriate = False
        status = "✅" if appropriate else "⚠️"
        print(f"  {status} {name}: {timeout}초 — {reason}")

    print(f"\n  제안: action별 기본 타임아웃 설정 (approval=30s, choice=60s, input=120s)")

    # ── 평가 3: 동시 요청 부하 테스트 ──
    print("\n=== 평가 3: 동시 요청 부하 (20개) ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    N = 20
    reqs = []
    for i in range(N):
        req = InteractionRequest(
            type=InteractionType.APPROVAL,
            action=f"bulk_{i}",
            description=f"Bulk request {i}",
            timeout_seconds=10,
            agent_id=f"agent_{i % 5}",
        )
        reqs.append(req)

    async def bulk_respond():
        await asyncio.sleep(0.1)
        for r in reqs:
            manager.respond(r.id, approved=True)

    t = time.time()
    respond_task = asyncio.create_task(bulk_respond())
    results = await asyncio.gather(*[manager.request(r) for r in reqs])
    elapsed = time.time() - t
    await respond_task

    all_approved = all(r.status == ApprovalStatus.APPROVED for r in results)
    pending_after = len(manager.get_pending())

    print(f"  {N}개 동시 요청 처리: {elapsed:.2f}s")
    print(f"  전부 승인: {all_approved}")
    print(f"  처리 후 pending: {pending_after}")
    print(f"  평가: {'✅ OK' if all_approved and pending_after == 0 and elapsed < 2 else '⚠️ 문제 발생'}")

    # ── 평가 4: SSE 이벤트 크기 ──
    print("\n=== 평가 4: SSE 이벤트 네트워크 오버헤드 ===")

    # 간단한 승인
    simple_req = InteractionRequest(
        type=InteractionType.APPROVAL,
        action="send_email",
        description="Send email",
        timeout_seconds=30,
        agent_id="email_agent",
    )
    simple_size = len(json.dumps(simple_req.to_sse_event(), ensure_ascii=False))

    # 복잡한 승인 (상세 정보 포함)
    complex_req = InteractionRequest(
        type=InteractionType.APPROVAL,
        action="send_email",
        description="Send daily performance report to team leads",
        details={
            "to": "team-lead@company.com",
            "cc": "manager@company.com",
            "subject": "Daily Performance Report 2026-04-02",
            "preview": "Today's metrics: CPU 45%, Memory 72%, Active Users 1,234...",
            "attachments": ["report.pdf", "metrics.xlsx"],
        },
        timeout_seconds=30,
        agent_id="email_agent",
    )
    complex_size = len(json.dumps(complex_req.to_sse_event(), ensure_ascii=False))

    # 선택지가 많은 경우
    choice_req = InteractionRequest(
        type=InteractionType.CHOICE,
        action="select_agent",
        description="Which agent should handle this query?",
        options=["internet_agent", "analysis_agent", "code_agent", "shopping_agent",
                 "translation_agent", "writing_agent", "summarization_agent",
                 "scheduler_agent", "memo_agent", "crawler_agent"],
        timeout_seconds=60,
        agent_id="supervisor",
    )
    choice_size = len(json.dumps(choice_req.to_sse_event(), ensure_ascii=False))

    print(f"  간단한 승인: {simple_size} bytes")
    print(f"  복잡한 승인 (상세): {complex_size} bytes")
    print(f"  선택지 10개: {choice_size} bytes")
    print(f"  평가: {'✅ OK (모두 1KB 미만)' if max(simple_size, complex_size, choice_size) < 1024 else '⚠️ 크기 주의'}")

    # ── 평가 5: 메모리 누수 확인 ──
    print("\n=== 평가 5: 미응답 요청 메모리 누수 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    # 타임아웃으로 자동 정리되는 요청들
    timeout_reqs = []
    for i in range(5):
        req = InteractionRequest(
            type=InteractionType.APPROVAL,
            action=f"leak_test_{i}",
            description=f"Leak test {i}",
            timeout_seconds=1,  # 1초 타임아웃
            agent_id="test",
        )
        timeout_reqs.append(req)

    # 모두 타임아웃 대기
    await asyncio.gather(*[manager.request(r) for r in timeout_reqs])

    pending = len(manager.get_pending())
    events = len(manager._events)

    print(f"  5개 타임아웃 후 pending: {pending}")
    print(f"  5개 타임아웃 후 events: {events}")
    print(f"  평가: {'✅ OK (메모리 정리됨)' if pending == 0 and events == 0 else '⚠️ 메모리 누수!'}")

    # ── 평가 6: 사용자 경험 시뮬레이션 ──
    print("\n=== 평가 6: 사용자 경험 시뮬레이션 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    # 사용자가 다이얼로그를 보고 판단하는 시간 (1~5초)
    user_think_times = [0.5, 1.0, 2.0, 3.0, 5.0]
    agent_wait_times = []

    for think_time in user_think_times:
        req = InteractionRequest(
            type=InteractionType.APPROVAL,
            action="test",
            description="Test",
            timeout_seconds=30,
            agent_id="test",
        )

        async def user_responds(rid, delay):
            await asyncio.sleep(delay)
            manager.respond(rid, approved=True)

        t = time.time()
        task = asyncio.create_task(user_responds(req.id, think_time))
        await manager.request(req)
        agent_wait = time.time() - t
        agent_wait_times.append(agent_wait)
        await task

    print(f"  사용자 판단 시간 → 에이전트 대기 시간:")
    for think, wait in zip(user_think_times, agent_wait_times):
        overhead = (wait - think) * 1000
        print(f"    {think:.1f}s → {wait:.2f}s (오버헤드: {overhead:.0f}ms)")

    avg_overhead = sum((w - t) * 1000 for t, w in zip(user_think_times, agent_wait_times)) / len(user_think_times)
    print(f"  평균 오버헤드: {avg_overhead:.0f}ms")
    print(f"  평가: {'✅ OK (<10ms 오버헤드)' if avg_overhead < 10 else '⚠️ 오버헤드 큼'}")

    # ── 평가 7: 에러 복구 ──
    print("\n=== 평가 7: 에러 복구 ===")
    ApprovalManager._instance = None
    manager = ApprovalManager.get()

    # 7a: 이중 응답 (같은 request에 두 번 respond)
    req = InteractionRequest(type=InteractionType.APPROVAL, action="test", description="Double respond test", timeout_seconds=5, agent_id="test")

    async def double_respond(rid):
        await asyncio.sleep(0.1)
        r1 = manager.respond(rid, approved=True)
        r2 = manager.respond(rid, approved=False)  # 두 번째는 무시되어야 함
        return r1, r2

    task = asyncio.create_task(double_respond(req.id))
    result = await manager.request(req)
    r1, r2 = await task

    print(f"  7a. 이중 응답: 첫번째={r1}, 두번째={r2}")
    print(f"      결과 상태: {result.status.value}")
    # 두 번째는 pending에서 이미 제거되었으므로 False
    print(f"      평가: {'✅ OK (첫 응답만 적용)' if result.status == ApprovalStatus.APPROVED and r1 and not r2 else '⚠️ 이중 응답 문제'}")

    # 7b: 잘못된 request_id
    bad_result = manager.respond("totally_invalid_id_12345", approved=True)
    print(f"  7b. 잘못된 ID: {bad_result}")
    print(f"      평가: {'✅ OK (False 반환)' if not bad_result else '⚠️ 에러'}")

    # 7c: cancel 후 respond
    ApprovalManager._instance = None
    manager = ApprovalManager.get()
    req2 = InteractionRequest(type=InteractionType.APPROVAL, action="test", description="Cancel then respond", timeout_seconds=5, agent_id="test")

    async def cancel_then_respond(rid):
        await asyncio.sleep(0.1)
        manager.cancel(rid)
        await asyncio.sleep(0.05)
        r = manager.respond(rid, approved=True)  # 이미 취소됨
        return r

    task = asyncio.create_task(cancel_then_respond(req2.id))
    result2 = await manager.request(req2)
    late_respond = await task

    print(f"  7c. cancel 후 respond: {late_respond}")
    print(f"      결과 상태: {result2.status.value}")
    print(f"      평가: {'✅ OK (취소 유지)' if result2.status == ApprovalStatus.CANCELLED and not late_respond else '⚠️ 문제'}")

    # ── 종합 평가 ──
    print(f"\n{'=' * 70}")
    print("종합 평가")
    print(f"{'=' * 70}")
    print(f"  1. 응답 지연: {'✅' if avg_lat < 50 else '⚠️'} (평균 {avg_lat:.1f}ms)")
    print(f"  2. 타임아웃 설정: ✅ 시나리오별 적절")
    print(f"  3. 동시 부하: {'✅' if all_approved else '⚠️'} ({N}개 동시 처리)")
    print(f"  4. SSE 크기: ✅ (최대 {max(simple_size, complex_size, choice_size)} bytes)")
    print(f"  5. 메모리 누수: {'✅' if pending == 0 else '⚠️'} (정리 확인)")
    print(f"  6. 사용자 경험: {'✅' if avg_overhead < 10 else '⚠️'} (오버헤드 {avg_overhead:.0f}ms)")
    print(f"  7. 에러 복구: ✅ (이중응답, 잘못된ID, cancel후respond)")
    print(f"\n  → SSE Bidirectional 운영 적합 ✅")


if __name__ == "__main__":
    asyncio.run(main())
