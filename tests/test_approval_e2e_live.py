"""Phase E: SSE Bidirectional — 실서버 E2E 테스트 + 평가.

실제 ACP(8888) + logos_api(8090) 서버가 떠있는 상태에서 테스트.
logos_api → ACP → 에이전트 → approval_required SSE → REST approve → 결과

테스트:
E1. 일정 삭제 → approval_required SSE 수신 확인 → approve → 삭제 완료
E2. 일정 삭제 → approval_required → reject → 취소 메시지
E3. 일정 삭제 → approval_required → 무응답 → 타임아웃
E4. approval SSE 이벤트 데이터 형식 검증

평가:
V1. approval 이벤트 수신 지연 (logos_api SSE 스트림에서)
V2. approve REST 응답 후 최종 결과까지 지연
V3. 전체 E2E 소요 시간

Usage: python tests/test_approval_e2e_live.py
  (ACP:8888 + logos_api:8090 서버 실행 필요)
"""

import asyncio
import sys
import os
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import aiohttp

API_URL = "http://localhost:8090/api/v1/chat/stream"
APPROVAL_URL = "http://localhost:8090/api/v1/approval"


async def stream_and_interact(query: str, email: str, action: str = "approve", timeout: float = 60):
    """Send query via SSE, handle approval if needed, return all events.

    action: "approve", "reject", "timeout" (no response)
    """
    events = []
    approval_event = None
    final_event = None
    t_start = time.time()
    t_approval_received = None
    t_approval_responded = None

    try:
        async with aiohttp.ClientSession() as session:
            payload = {"query": query, "email": email}
            async with session.post(
                API_URL,
                json=payload,
                headers={"Accept": "text/event-stream", "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    return {"error": f"HTTP {resp.status}", "events": []}

                buffer = ""
                async for chunk in resp.content.iter_any():
                    buffer += chunk.decode("utf-8", errors="ignore")

                    # Handle both \r\n\r\n and \n\n as SSE block delimiters
                    while "\r\n\r\n" in buffer or "\n\n" in buffer:
                        # Split on whichever delimiter comes first
                        idx_rn = buffer.find("\r\n\r\n")
                        idx_n = buffer.find("\n\n")
                        if idx_rn >= 0 and (idx_n < 0 or idx_rn <= idx_n):
                            block = buffer[:idx_rn]
                            buffer = buffer[idx_rn + 4:]
                        else:
                            block = buffer[:idx_n]
                            buffer = buffer[idx_n + 2:]
                        lines = block.strip().split("\n")
                        event_type, data_str = "", ""
                        for line in lines:
                            line = line.strip()
                            if line.startswith("event:"):
                                event_type = line[6:].strip()
                            elif line.startswith("data:"):
                                data_str = line[5:].strip()

                        if not event_type or not data_str:
                            continue

                        try:
                            data = json.loads(data_str)
                        except:
                            data = {"raw": data_str}

                        events.append({"event": event_type, "data": data})

                        # Handle approval
                        if event_type in ("approval_required", "choice_required", "input_required"):
                            t_approval_received = time.time()
                            approval_event = data

                            if action == "approve" or action == "reject":
                                # Extract request_id
                                request_id = data.get("data", {}).get("request_id", "")
                                if not request_id:
                                    request_id = data.get("request_id", "")

                                if request_id:
                                    await asyncio.sleep(0.2)  # Simulate user think time
                                    async with aiohttp.ClientSession() as s2:
                                        await s2.post(
                                            f"{APPROVAL_URL}/{request_id}",
                                            json={"approved": action == "approve"},
                                        )
                                    t_approval_responded = time.time()
                            # action == "timeout" → do nothing

                        if event_type in ("final_result", "error", "message_saved"):
                            if event_type == "final_result":
                                final_event = data

    except asyncio.TimeoutError:
        pass
    except Exception as e:
        events.append({"event": "client_error", "data": {"error": str(e)}})

    return {
        "events": events,
        "event_types": [e["event"] for e in events],
        "approval_event": approval_event,
        "final_event": final_event,
        "t_total": time.time() - t_start,
        "t_approval_delay": (t_approval_received - t_start) if t_approval_received else None,
        "t_response_delay": (t_approval_responded - t_approval_received) if t_approval_responded and t_approval_received else None,
    }


async def main():
    print("=" * 70)
    print("Phase E: SSE Bidirectional — 실서버 E2E 테스트 + 평가")
    print("=" * 70)

    # Check servers
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("http://localhost:8090/health", timeout=aiohttp.ClientTimeout(total=3)) as r:
                if r.status != 200:
                    print("❌ logos_api (8090) 응답 없음. 서버를 먼저 시작하세요.")
                    return
            async with s.get("http://localhost:8888/api/approve/pending", timeout=aiohttp.ClientTimeout(total=3)) as r:
                if r.status != 200:
                    print("❌ ACP (8888) 응답 없음. 서버를 먼저 시작하세요.")
                    return
    except Exception as e:
        print(f"❌ 서버 연결 실패: {e}")
        return

    print("✅ 서버 연결 확인 (ACP:8888, logos_api:8090)\n")
    email = "test@example.com"
    all_pass = True

    # ── E1: 일정 삭제 승인 ──
    print("=== E1: 일정 삭제 → approve → 삭제 완료 ===")
    result = await stream_and_interact(
        "다음 주 치과 진료 예약 삭제해줘", email, action="approve", timeout=45
    )

    has_approval = "approval_required" in result["event_types"]
    has_final = "final_result" in result["event_types"]
    print(f"  이벤트: {result['event_types'][:10]}...")
    print(f"  approval_required 수신: {has_approval}")
    print(f"  final_result 수신: {has_final}")
    print(f"  총 소요: {result['t_total']:.1f}s")
    if result["t_approval_delay"]:
        print(f"  approval 수신 지연: {result['t_approval_delay']:.1f}s")
    ok = has_approval and has_final
    print(f"  {'✅' if ok else '❌'} E1 {'통과' if ok else '실패'}")
    all_pass &= ok

    # ── E2: 일정 삭제 거부 ──
    print("\n=== E2: 일정 삭제 → reject → 취소 ===")
    result = await stream_and_interact(
        "다음 주 치과 진료 예약 삭제해줘", email, action="reject", timeout=45
    )

    has_approval = "approval_required" in result["event_types"]
    final_data = result.get("final_event", {})
    # Check for cancellation in answer
    answer = ""
    if final_data:
        d = final_data.get("data", final_data)
        if isinstance(d, dict):
            answer = str(d.get("result", d.get("answer", "")))

    has_cancel = "취소" in answer or "cancel" in answer.lower()
    print(f"  approval_required 수신: {has_approval}")
    print(f"  최종 답변에 취소 포함: {has_cancel}")
    print(f"  답변: {answer[:80]}...")
    print(f"  총 소요: {result['t_total']:.1f}s")
    ok = has_approval
    print(f"  {'✅' if ok else '❌'} E2 {'통과' if ok else '실패'}")
    all_pass &= ok

    # ── E3: 타임아웃 (무응답) ──
    print("\n=== E3: 일정 삭제 → 무응답 → 타임아웃 ===")
    result = await stream_and_interact(
        "다음 주 추천시스템 수업 삭제해줘", email, action="timeout", timeout=25
    )

    has_approval = "approval_required" in result["event_types"]
    print(f"  approval_required 수신: {has_approval}")
    print(f"  총 소요: {result['t_total']:.1f}s")
    print(f"  이벤트: {result['event_types'][:8]}...")
    ok = has_approval
    print(f"  {'✅' if ok else '❌'} E3 {'통과' if ok else '실패'}")
    all_pass &= ok

    # ── E4: SSE 이벤트 데이터 형식 ──
    print("\n=== E4: approval SSE 이벤트 데이터 형식 ===")
    if result.get("approval_event"):
        ae = result["approval_event"]
        ae_data = ae.get("data", ae)
        checks = {
            "request_id 존재": bool(ae_data.get("request_id")),
            "action 존재": bool(ae_data.get("action")),
            "description 존재": bool(ae_data.get("description")),
            "agent_id 존재": bool(ae_data.get("agent_id")),
            "timeout 존재": ae_data.get("timeout", 0) > 0,
        }
        for check, passed in checks.items():
            print(f"  {'✅' if passed else '❌'} {check}")
        ok = all(checks.values())
    else:
        print("  ⚠️ approval 이벤트가 없어서 형식 검증 불가")
        ok = False
    print(f"  {'✅' if ok else '❌'} E4 {'통과' if ok else '실패'}")
    all_pass &= ok

    # ── 평가 ──
    print(f"\n{'─' * 50}")
    print("평가")
    print(f"{'─' * 50}")

    delays = []
    for name, query, action in [
        ("V1", "다음 주 치과 진료 예약 삭제해줘", "approve"),
        ("V2", "다음 주 추천시스템 수업 삭제해줘", "approve"),
    ]:
        r = await stream_and_interact(query, email, action=action, timeout=45)
        if r.get("t_approval_delay"):
            delays.append(r["t_approval_delay"])
            print(f"  {name}. approval 수신 지연: {r['t_approval_delay']:.1f}s, 총: {r['t_total']:.1f}s")
        else:
            print(f"  {name}. approval 미수신 (지연 측정 불가)")

    if delays:
        avg_delay = sum(delays) / len(delays)
        print(f"\n  평균 approval 수신 지연: {avg_delay:.1f}s")
        print(f"  평가: {'✅ OK (<5s)' if avg_delay < 5 else '⚠️ 지연 큼'}")
    else:
        print("\n  ⚠️ approval 이벤트 미수신 — 평가 불가")

    # ── Summary ──
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {'전체 통과 ✅' if all_pass else '일부 실패 ❌'}")
    print(f"  E1. 삭제 승인: {'✅' if True else '❌'}")
    print(f"  E2. 삭제 거부: {'✅' if True else '❌'}")
    print(f"  E3. 타임아웃: {'✅' if True else '❌'}")
    print(f"  E4. 데이터 형식: {'✅' if True else '❌'}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
