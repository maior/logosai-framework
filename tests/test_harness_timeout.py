"""P0-2 하네스 기본 적용 — 타임아웃 테스트 (2026-07-06).

표준 준비도 진단 G2: 안전이 default. base process() 에 실행 타임아웃을 기본으로
걸어, 폭주 에이전트가 무한정 매달리지 않게 한다. 계약:
  - 기본 타임아웃(default) 초과 시 process 가 매달리지 않고 AgentResponse.error 반환.
  - 정상(빠른) process 는 영향 없음.
  - opt-out: agent._harness=False 또는 env LOGOSAI_HARNESS=off → 타임아웃 미적용.
  - env LOGOSAI_HARNESS_TIMEOUT 로 초 조정.
  - 타임아웃도 관측(success=False)으로 기록.
  - 관측·하네스 공존.

직접 실행: python logosai/tests/test_harness_timeout.py
"""
import asyncio
import os
import sys
import time

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PKG)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def main():
    fails = []

    def t(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    os.environ.pop("LOGOSAI_AUTO_OBSERVE", None)
    os.environ.pop("LOGOSAI_HARNESS", None)
    os.environ["LOGOSAI_HARNESS_TIMEOUT"] = "0.15"  # 테스트용 짧은 기본

    import logosai.observability as obs
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse, AgentResponseType

    # 관측 emit 은 레코더로 (하네스와 무관하게 관측 검증)
    rec = {"exec": []}
    obs.emit_agent_execution = lambda agent_id, query, success, duration_ms, output="", error=None: \
        rec["exec"].append({"success": success})
    obs.start_agent_span = lambda agent_id, query: type("S", (), {"end": lambda self, *a, **k: None})()

    class SlowAgent(SimpleAgent):
        async def process(self, query, context=None):
            await asyncio.sleep(1.0)  # 기본 타임아웃(0.15s) 초과
            return AgentResponse.success(content={"answer": "late"})

    class FastAgent(SimpleAgent):
        async def process(self, query, context=None):
            return AgentResponse.success(content={"answer": "quick:" + query})

    # ── 타임아웃 발동: 매달리지 않고 error 반환 ──
    slow = SlowAgent()
    t0 = time.monotonic()
    res = run(slow.process("x"))
    elapsed = time.monotonic() - t0
    t("H-1 타임아웃 초과 시 매달리지 않음(<0.5s)", elapsed < 0.5)
    t("H-2 AgentResponse.error 반환",
      getattr(res, "type", None) == AgentResponseType.ERROR)

    # ── 정상 process 영향 없음 ──
    fast = FastAgent()
    res2 = run(fast.process("hi"))
    t("H-3 빠른 process 정상", getattr(res2, "content", {}).get("answer") == "quick:hi")

    # ── opt-out: _harness=False → 타임아웃 미적용(느린 것도 완료) ──
    slow2 = SlowAgent()
    slow2._harness = False
    r3 = run(slow2.process("y"))
    t("H-4 _harness=False → 타임아웃 미적용(완료)",
      getattr(r3, "content", {}).get("answer") == "late")

    # ── opt-out: env LOGOSAI_HARNESS=off ──
    os.environ["LOGOSAI_HARNESS"] = "off"
    slow3 = SlowAgent()
    r4 = run(slow3.process("z"))
    t("H-5 env HARNESS=off → 타임아웃 미적용",
      getattr(r4, "content", {}).get("answer") == "late")
    os.environ.pop("LOGOSAI_HARNESS", None)

    # ── env 타임아웃 조정: 크게 하면 완료 ──
    os.environ["LOGOSAI_HARNESS_TIMEOUT"] = "2.0"
    slow4 = SlowAgent()
    r5 = run(slow4.process("w"))
    t("H-6 env TIMEOUT 상향 → 완료",
      getattr(r5, "content", {}).get("answer") == "late")
    os.environ["LOGOSAI_HARNESS_TIMEOUT"] = "0.15"

    # ── 타임아웃도 관측 success=False ──
    rec["exec"].clear()
    slow5 = SlowAgent()
    run(slow5.process("obs"))
    t("H-7 타임아웃도 관측(success False)",
      len(rec["exec"]) == 1 and rec["exec"][0]["success"] is False)

    os.environ.pop("LOGOSAI_HARNESS_TIMEOUT", None)
    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
