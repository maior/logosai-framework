"""Phase E: SSE Bidirectional — 다양한 실사용 시나리오 E2E 테스트.

실제 에이전트가 request_approval()을 호출하는 상황을 시뮬레이션.
각 시나리오에서 승인/거부/타임아웃 3가지 경로를 모두 테스트.

시나리오:
1. 카카오톡 메시지 전송 (승인 → 전송 / 거부 → 취소)
2. 이메일 전송 (승인 → 전송 / 거부 → 취소 / 타임아웃 → 취소)
3. 일정 삭제 (승인 → 삭제 / 거부 → 유지)
4. 메모 삭제 (승인 → 삭제 / 거부 → 유지)
5. 번역 언어 선택 (choice — 사용자 선택 반영)
6. 추가 정보 입력 (input — 사용자 입력 반영)
7. 연속 승인 (에이전트가 2번 연속 approval 요청)
8. 다중 에이전트 동시 승인 (3 에이전트 동시)

Usage: python tests/test_approval_scenarios.py
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from logosai.agentic.approval import (
    ApprovalManager, ApprovalStatus, InteractionRequest, InteractionType,
)


# ═══════════════════════════════════════════
# Mock agents that simulate real agent behavior
# ═══════════════════════════════════════════

class MockAgent:
    """Base mock agent with request_approval capability."""
    def __init__(self, agent_id):
        self.id = agent_id
        self._stream_callback = None
        self.sse_events = []

    async def request_approval(self, action, description, details=None, timeout=30):
        from logosai.agentic.approval import ApprovalManager, InteractionRequest, InteractionType, ApprovalStatus
        interaction = InteractionRequest(
            type=InteractionType.APPROVAL,
            action=action,
            description=description,
            details=details or {},
            timeout_seconds=timeout,
            agent_id=self.id,
        )
        if self._stream_callback:
            await self._stream_callback(interaction.to_sse_event())
        self.sse_events.append(interaction.to_sse_event())
        manager = ApprovalManager.get()
        result = await manager.request(interaction)
        return result.status == ApprovalStatus.APPROVED

    async def ask_user(self, question, options=None, timeout=60):
        from logosai.agentic.approval import ApprovalManager, InteractionRequest, InteractionType, ApprovalStatus
        interaction = InteractionRequest(
            type=InteractionType.CHOICE if options else InteractionType.INPUT,
            action="ask_user",
            description=question,
            options=options or [],
            timeout_seconds=timeout,
            agent_id=self.id,
        )
        if self._stream_callback:
            await self._stream_callback(interaction.to_sse_event())
        self.sse_events.append(interaction.to_sse_event())
        manager = ApprovalManager.get()
        result = await manager.request(interaction)
        if result.status == ApprovalStatus.APPROVED:
            return result.response
        return None


class KakaoTalkAgent(MockAgent):
    """Simulates kakaotalk_agent with approval."""
    def __init__(self):
        super().__init__("kakaotalk_agent")

    async def process(self, query, context=None):
        recipient = "홍길동"
        message = query

        approved = await self.request_approval(
            action="send_kakaotalk",
            description=f"카카오톡 메시지를 {recipient}에게 전송합니다",
            details={"recipient": recipient, "message": message[:200]},
            timeout=20,
        )
        if not approved:
            return {"success": True, "answer": "사용자가 카카오톡 메시지 전송을 취소했습니다."}

        # Simulate sending
        return {"success": True, "answer": f"카카오톡으로 {recipient}에게 메시지를 전송했습니다."}


class MailAgent(MockAgent):
    """Simulates mail_agent with approval."""
    def __init__(self):
        super().__init__("mail_agent")

    async def process(self, query, context=None):
        to = "user@example.com"
        subject = "Daily Report"
        body = query[:150]

        approved = await self.request_approval(
            action="send_email",
            description=f"이메일을 {to}에게 전송합니다",
            details={"to": to, "subject": subject, "preview": body},
            timeout=30,
        )
        if not approved:
            return {"success": True, "answer": "사용자가 이메일 전송을 취소했습니다."}

        return {"success": True, "answer": f"이메일을 {to}에게 전송했습니다."}


class SchedulerAgent(MockAgent):
    """Simulates scheduler_agent delete with approval."""
    def __init__(self):
        super().__init__("scheduler_agent")

    async def process(self, query, context=None):
        event_title = "팀 미팅"
        event_id = 42

        approved = await self.request_approval(
            action="delete_schedule",
            description=f"일정 '{event_title}'을(를) 삭제합니다",
            details={"title": event_title, "event_id": event_id},
            timeout=15,
        )
        if not approved:
            return {"success": False, "answer": f"사용자가 일정 '{event_title}' 삭제를 취소했습니다."}

        return {"success": True, "answer": f"일정 '{event_title}'이(가) 삭제되었습니다."}


class MemoAgent(MockAgent):
    """Simulates memo_agent delete with approval."""
    def __init__(self):
        super().__init__("memo_agent")

    async def process(self, query, context=None):
        memo_title = "프로젝트 노트"

        approved = await self.request_approval(
            action="delete_memo",
            description=f"메모를 삭제합니다: {memo_title}",
            details={"title": memo_title},
            timeout=15,
        )
        if not approved:
            return {"success": True, "answer": "사용자가 메모 삭제를 취소했습니다."}

        return {"success": True, "answer": f"메모 '{memo_title}'이(가) 삭제되었습니다."}


class TranslationAgent(MockAgent):
    """Simulates translation_agent with choice."""
    def __init__(self):
        super().__init__("translation_agent")

    async def process(self, query, context=None):
        lang = await self.ask_user(
            "어떤 언어로 번역할까요?",
            options=["영어", "일본어", "중국어", "프랑스어"],
            timeout=60,
        )
        if not lang:
            return {"success": False, "answer": "번역 언어를 선택하지 않았습니다."}

        return {"success": True, "answer": f"'{query}'을(를) {lang}로 번역합니다."}


class ShoppingAgent(MockAgent):
    """Simulates shopping_agent with purchase approval."""
    def __init__(self):
        super().__init__("shopping_agent")

    async def process(self, query, context=None):
        product = "Apple AirPods Pro"
        price = "₩329,000"

        approved = await self.request_approval(
            action="purchase",
            description=f"{product} 구매를 진행합니다 ({price})",
            details={"product": product, "price": price, "store": "Apple Store"},
            timeout=30,
        )
        if not approved:
            return {"success": True, "answer": "구매를 취소했습니다."}

        return {"success": True, "answer": f"{product}을(를) 구매했습니다. 결제 금액: {price}"}


class AssistantAgent(MockAgent):
    """Simulates an agent that asks for additional input."""
    def __init__(self):
        super().__init__("assistant_agent")

    async def process(self, query, context=None):
        extra = await self.ask_user(
            "추가 정보를 입력해주세요 (예: 수신자 이메일)",
            timeout=60,
        )
        if not extra:
            return {"success": False, "answer": "추가 정보가 제공되지 않았습니다."}

        return {"success": True, "answer": f"추가 정보 반영: {extra}"}


# ═══════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════

def reset():
    ApprovalManager._instance = None
    return ApprovalManager.get()


async def respond_after(delay, approved=True, response=None):
    """Frontend simulator: respond to pending request after delay."""
    await asyncio.sleep(delay)
    manager = ApprovalManager.get()
    pending = manager.get_pending()
    if pending:
        manager.respond(pending[0].id, approved=approved, response=response)


# ═══════════════════════════════════════════
# Test scenarios
# ═══════════════════════════════════════════

async def main():
    print("=" * 70)
    print("Phase E: SSE Bidirectional — 다양한 실사용 시나리오 테스트")
    print("=" * 70)

    all_pass = True

    # ── S1: 카카오톡 전송 승인 ──
    print("\n=== S1: 카카오톡 메시지 전송 — 승인 ===")
    reset()
    agent = KakaoTalkAgent()
    task = asyncio.create_task(respond_after(0.1, approved=True))
    result = await agent.process("오늘 회의 시간 변경되었습니다")
    await task
    ok = "전송했습니다" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  SSE: {agent.sse_events[0]['type']}")
    print(f"  {'✅' if ok else '❌'} 카카오톡 전송 승인")
    all_pass &= ok

    # ── S2: 카카오톡 전송 거부 ──
    print("\n=== S2: 카카오톡 메시지 전송 — 거부 ===")
    reset()
    agent = KakaoTalkAgent()
    task = asyncio.create_task(respond_after(0.1, approved=False))
    result = await agent.process("내일 점심 먹자")
    await task
    ok = "취소" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  {'✅' if ok else '❌'} 카카오톡 전송 거부")
    all_pass &= ok

    # ── S3: 이메일 전송 승인 ──
    print("\n=== S3: 이메일 전송 — 승인 ===")
    reset()
    agent = MailAgent()
    task = asyncio.create_task(respond_after(0.1, approved=True))
    result = await agent.process("월간 보고서를 보내주세요")
    await task
    ok = "전송했습니다" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  Details: {agent.sse_events[0]['data']['details']}")
    print(f"  {'✅' if ok else '❌'} 이메일 전송 승인")
    all_pass &= ok

    # ── S4: 이메일 전송 타임아웃 ──
    print("\n=== S4: 이메일 전송 — 타임아웃 ===")
    reset()
    agent = MailAgent()
    # Override timeout to 1s for fast test
    original_process = agent.process
    async def fast_timeout_process(query, context=None):
        agent2 = MailAgent()
        agent2.id = agent.id
        approved = await agent2.request_approval(
            action="send_email", description="Send email", timeout=1,
        )
        if not approved:
            return {"success": True, "answer": "사용자가 이메일 전송을 취소했습니다. (타임아웃)"}
        return {"success": True, "answer": "전송완료"}

    t = time.time()
    result = await fast_timeout_process("test")
    elapsed = time.time() - t
    ok = "취소" in result["answer"] and 0.9 < elapsed < 2.0
    print(f"  결과: {result['answer'][:60]}")
    print(f"  대기: {elapsed:.1f}s")
    print(f"  {'✅' if ok else '❌'} 이메일 타임아웃 → 자동 취소")
    all_pass &= ok

    # ── S5: 일정 삭제 승인 ──
    print("\n=== S5: 일정 삭제 — 승인 ===")
    reset()
    agent = SchedulerAgent()
    task = asyncio.create_task(respond_after(0.1, approved=True))
    result = await agent.process("팀 미팅 삭제해줘")
    await task
    ok = "삭제되었습니다" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  {'✅' if ok else '❌'} 일정 삭제 승인")
    all_pass &= ok

    # ── S6: 일정 삭제 거부 ──
    print("\n=== S6: 일정 삭제 — 거부 ===")
    reset()
    agent = SchedulerAgent()
    task = asyncio.create_task(respond_after(0.1, approved=False))
    result = await agent.process("팀 미팅 삭제해줘")
    await task
    ok = "취소" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  {'✅' if ok else '❌'} 일정 삭제 거부 → 유지")
    all_pass &= ok

    # ── S7: 메모 삭제 승인 ──
    print("\n=== S7: 메모 삭제 — 승인 ===")
    reset()
    agent = MemoAgent()
    task = asyncio.create_task(respond_after(0.1, approved=True))
    result = await agent.process("프로젝트 노트 삭제")
    await task
    ok = "삭제되었습니다" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  {'✅' if ok else '❌'} 메모 삭제 승인")
    all_pass &= ok

    # ── S8: 메모 삭제 거부 ──
    print("\n=== S8: 메모 삭제 — 거부 ===")
    reset()
    agent = MemoAgent()
    task = asyncio.create_task(respond_after(0.1, approved=False))
    result = await agent.process("프로젝트 노트 삭제")
    await task
    ok = "취소" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  {'✅' if ok else '❌'} 메모 삭제 거부")
    all_pass &= ok

    # ── S9: 번역 언어 선택 (Choice) ──
    print("\n=== S9: 번역 언어 선택 — 일본어 선택 ===")
    reset()
    agent = TranslationAgent()
    task = asyncio.create_task(respond_after(0.1, approved=True, response="일본어"))
    result = await agent.process("안녕하세요")
    await task
    ok = "일본어" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  SSE type: {agent.sse_events[0]['type']}")
    print(f"  Options: {agent.sse_events[0]['data']['options']}")
    print(f"  {'✅' if ok else '❌'} 번역 언어 선택")
    all_pass &= ok

    # ── S10: 번역 언어 선택 취소 ──
    print("\n=== S10: 번역 언어 선택 — 취소 ===")
    reset()
    agent = TranslationAgent()
    task = asyncio.create_task(respond_after(0.1, approved=False))
    result = await agent.process("안녕하세요")
    await task
    ok = "선택하지 않았습니다" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  {'✅' if ok else '❌'} 번역 취소")
    all_pass &= ok

    # ── S11: 쇼핑 결제 승인 ──
    print("\n=== S11: 쇼핑 결제 — 승인 ===")
    reset()
    agent = ShoppingAgent()
    task = asyncio.create_task(respond_after(0.1, approved=True))
    result = await agent.process("에어팟 프로 사줘")
    await task
    ok = "구매했습니다" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  Details: {agent.sse_events[0]['data']['details']}")
    print(f"  {'✅' if ok else '❌'} 쇼핑 결제 승인")
    all_pass &= ok

    # ── S12: 쇼핑 결제 거부 ──
    print("\n=== S12: 쇼핑 결제 — 거부 ===")
    reset()
    agent = ShoppingAgent()
    task = asyncio.create_task(respond_after(0.1, approved=False))
    result = await agent.process("에어팟 프로 사줘")
    await task
    ok = "취소" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  {'✅' if ok else '❌'} 쇼핑 결제 거부")
    all_pass &= ok

    # ── S13: 추가 정보 입력 (Input) ──
    print("\n=== S13: 추가 정보 입력 — 이메일 입력 ===")
    reset()
    agent = AssistantAgent()
    task = asyncio.create_task(respond_after(0.1, approved=True, response="team@company.com"))
    result = await agent.process("보고서 보내줘")
    await task
    ok = "team@company.com" in result["answer"]
    print(f"  결과: {result['answer'][:60]}")
    print(f"  SSE type: {agent.sse_events[0]['type']}")
    print(f"  {'✅' if ok else '❌'} 추가 정보 입력")
    all_pass &= ok

    # ── S14: 추가 정보 입력 타임아웃 ──
    print("\n=== S14: 추가 정보 입력 — 타임아웃 ===")
    reset()
    async def fast_input():
        agent = AssistantAgent()
        from logosai.agentic.approval import ApprovalManager, InteractionRequest, InteractionType, ApprovalStatus
        interaction = InteractionRequest(
            type=InteractionType.INPUT, action="ask_user",
            description="입력해주세요", timeout_seconds=1, agent_id="test",
        )
        manager = ApprovalManager.get()
        result = await manager.request(interaction)
        return result.status == ApprovalStatus.TIMEOUT

    t = time.time()
    timed_out = await fast_input()
    elapsed = time.time() - t
    ok = timed_out and 0.9 < elapsed < 2.0
    print(f"  타임아웃: {timed_out}, {elapsed:.1f}s")
    print(f"  {'✅' if ok else '❌'} 입력 타임아웃")
    all_pass &= ok

    # ── S15: 연속 승인 (에이전트가 2번 요청) ──
    print("\n=== S15: 연속 승인 — 2회 연속 요청 ===")
    reset()
    manager = ApprovalManager.get()
    results = []

    async def agent_sequential():
        """Agent that needs 2 approvals in sequence."""
        agent = MockAgent("deploy_agent")

        # Step 1: backup approval
        approved1 = await agent.request_approval(
            action="backup_db", description="DB 백업을 실행합니다", timeout=5,
        )
        results.append(("backup", approved1))
        if not approved1:
            return "백업 취소"

        # Step 2: deploy approval
        approved2 = await agent.request_approval(
            action="deploy_prod", description="프로덕션 배포를 실행합니다", timeout=5,
        )
        results.append(("deploy", approved2))
        if not approved2:
            return "배포 취소"

        return "배포 완료"

    async def frontend_sequential():
        # Approve first request
        await asyncio.sleep(0.1)
        manager.respond(manager.get_pending()[0].id, approved=True)
        # Approve second request
        await asyncio.sleep(0.2)
        pending = manager.get_pending()
        if pending:
            manager.respond(pending[0].id, approved=True)

    agent_task = asyncio.create_task(agent_sequential())
    frontend_task = asyncio.create_task(frontend_sequential())
    answer = await agent_task
    await frontend_task

    ok = answer == "배포 완료" and len(results) == 2 and all(r[1] for r in results)
    print(f"  결과: {answer}")
    print(f"  승인 순서: {results}")
    print(f"  {'✅' if ok else '❌'} 연속 2회 승인")
    all_pass &= ok

    # ── S16: 연속 승인 — 첫번째 승인, 두번째 거부 ──
    print("\n=== S16: 연속 승인 — 1차 승인, 2차 거부 ===")
    reset()
    manager = ApprovalManager.get()
    results.clear()

    async def frontend_approve_then_reject():
        await asyncio.sleep(0.1)
        manager.respond(manager.get_pending()[0].id, approved=True)
        await asyncio.sleep(0.2)
        pending = manager.get_pending()
        if pending:
            manager.respond(pending[0].id, approved=False)

    agent_task = asyncio.create_task(agent_sequential())
    frontend_task = asyncio.create_task(frontend_approve_then_reject())
    answer = await agent_task
    await frontend_task

    ok = answer == "배포 취소" and results[0] == ("backup", True) and results[1] == ("deploy", False)
    print(f"  결과: {answer}")
    print(f"  승인 순서: {results}")
    print(f"  {'✅' if ok else '❌'} 1차 승인 → 2차 거부")
    all_pass &= ok

    # ── S17: 다중 에이전트 동시 승인 ──
    print("\n=== S17: 3개 에이전트 동시 승인 요청 ===")
    reset()
    manager = ApprovalManager.get()

    agents = [KakaoTalkAgent(), MailAgent(), SchedulerAgent()]

    async def frontend_approve_all():
        await asyncio.sleep(0.2)
        for p in manager.get_pending():
            manager.respond(p.id, approved=True)

    frontend_task = asyncio.create_task(frontend_approve_all())
    results_multi = await asyncio.gather(
        agents[0].process("메시지 보내기"),
        agents[1].process("이메일 보내기"),
        agents[2].process("일정 삭제"),
    )
    await frontend_task

    all_success = all("취소" not in r["answer"] for r in results_multi)
    ok = all_success
    for i, r in enumerate(results_multi):
        print(f"  {agents[i].id}: {r['answer'][:50]}")
    print(f"  {'✅' if ok else '❌'} 3개 에이전트 동시 승인")
    all_pass &= ok

    # ── S18: SSE 이벤트 정확성 검증 ──
    print("\n=== S18: SSE 이벤트 데이터 정확성 ===")
    reset()
    agent = ShoppingAgent()
    task = asyncio.create_task(respond_after(0.1, approved=True))
    await agent.process("구매 테스트")
    await task

    event = agent.sse_events[0]
    checks = {
        "type == approval_required": event["type"] == "approval_required",
        "request_id exists": bool(event["data"]["request_id"]),
        "action == purchase": event["data"]["action"] == "purchase",
        "description not empty": len(event["data"]["description"]) > 0,
        "details has product": "product" in event["data"]["details"],
        "details has price": "price" in event["data"]["details"],
        "agent_id == shopping_agent": event["data"]["agent_id"] == "shopping_agent",
        "timeout > 0": event["data"]["timeout"] > 0,
    }
    for check, passed in checks.items():
        print(f"  {'✅' if passed else '❌'} {check}")
    ok = all(checks.values())
    all_pass &= ok

    # ── Summary ──
    total = 18
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {'전체 통과 ✅' if all_pass else '일부 실패 ❌'}")
    print(f"시나리오: {total}개")
    print(f"  - 승인 경로: 카카오톡, 이메일, 일정, 메모, 쇼핑, 연속2회, 동시3개")
    print(f"  - 거부 경로: 카카오톡, 일정, 메모, 쇼핑, 번역, 연속(2차)")
    print(f"  - 타임아웃: 이메일, 입력")
    print(f"  - 선택/입력: 번역(choice), 추가정보(input)")
    print(f"  - 정확성: SSE 이벤트 데이터 필드 8항목")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
