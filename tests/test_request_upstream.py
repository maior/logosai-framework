"""MultiAgentMixin.request_upstream — 역방향 채널 (Agentic Upgrade Phase 4).

에이전트가 데이터 부족 시 상류 에이전트에 1회 구조화 재요청.
재귀 상한(depth 1)으로 무한 왕복 차단, 실패 시 None (호출측 폴백 판단).

직접 실행: .venv/bin/python logosai/tests/test_request_upstream.py
"""

import asyncio
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "logosai"))

from logosai.agent import LogosAIAgent  # noqa: E402


class FakeUpstream:
    def __init__(self, answer="7월 1일: 60000\n7월 2일: 60500", fail=False):
        self.answer = answer
        self.fail = fail
        self.calls = []

    async def process(self, query, context=None):
        self.calls.append({"query": query, "context": dict(context or {})})
        if self.fail:
            raise RuntimeError("upstream died")
        return {"answer": self.answer, "success": True}


def _agent(registry):
    a = LogosAIAgent.__new__(LogosAIAgent)
    a._agent_registry = registry
    import logging
    a.logger = logging.getLogger("test")
    a.id = "viz"
    return a


def main():
    fails = []

    def t(name, cond):
        print(("PASS  " if cond else "FAIL  ") + name)
        if not cond:
            fails.append(name)

    # U-1 정상 재요청 — 상류 응답 도착
    up = FakeUpstream()
    agent = _agent({"internet_agent": up})
    r = asyncio.run(agent.request_upstream(
        "internet_agent", "라벨-값 목록으로 다시", {"original_query": "주가"}))
    t("U-1 상류 재요청 성공 → 응답 dict", r is not None and "60000" in r.get("answer", ""))

    # U-2 재귀 상한 — depth 1 이상이면 호출 자체를 안 함
    up2 = FakeUpstream()
    agent2 = _agent({"internet_agent": up2})
    r2 = asyncio.run(agent2.request_upstream(
        "internet_agent", "다시", {"_upstream_depth": 1}))
    t("U-2 재귀 상한: depth≥1 이면 None + 미호출", r2 is None and len(up2.calls) == 0)

    # U-3 전달 context 에 depth 증가 주입 (상류가 또 재요청하면 U-2 로 차단)
    t("U-3 재요청 context 에 _upstream_depth=1 주입",
      up.calls and up.calls[0]["context"].get("_upstream_depth") == 1)

    # U-4 대용량 previous_results 는 재요청에 재전파하지 않음
    up4 = FakeUpstream()
    agent4 = _agent({"a": up4})
    asyncio.run(agent4.request_upstream("a", "다시", {"previous_results": {"x": {"big": "y" * 9000}}}))
    t("U-4 previous_results 재전파 차단", "previous_results" not in up4.calls[0]["context"])

    # U-5 상류 예외 → None (호출측 폴백)
    agent5 = _agent({"a": FakeUpstream(fail=True)})
    r5 = asyncio.run(agent5.request_upstream("a", "다시", {}))
    t("U-5 상류 실패 → None", r5 is None)

    # U-6 레지스트리 부재 (비 ACP 환경) → None, 크래시 없음
    agent6 = _agent(None)
    r6 = asyncio.run(agent6.request_upstream("a", "다시", {}))
    t("U-6 레지스트리 부재 → None", r6 is None)

    print("\nRESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
