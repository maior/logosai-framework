"""P0-2 확장 — 하네스 LLM 호출/비용 상한 (2026-07-06).

표준 준비도 진단 G2 완전 밀봉: 타임아웃에 더해 base process() 실행당
LLM 호출 수·토큰(비용) 상한을 기본 적용. 폭주 에이전트가 무한 LLM 호출로
비용을 태우지 않게 한다. 계약:
  - per-execution 격리(ContextVar) — 동시 실행이 서로 카운터를 오염하지 않음.
  - 호출 상한 초과 → HarnessBudgetExceeded, 하네스가 graceful AgentResponse.error 로.
  - 토큰 상한 누적 초과 → 다음 호출 precheck 에서 차단.
  - 예산 미활성(하네스 off / caps None) → precheck/record no-op(비하네스 경로 불변).
  - reset 로 실행 간 카운터 격리.
  - opt-out: _harness=False / env LOGOSAI_HARNESS=off → 예산 미적용.

직접 실행: python logosai/tests/test_harness_budget.py
"""
import asyncio
import os
import sys

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
    os.environ["LOGOSAI_HARNESS_TIMEOUT"] = "5"       # 타임아웃은 넉넉히
    os.environ["LOGOSAI_HARNESS_MAX_CALLS"] = "3"     # 테스트용 낮은 상한
    os.environ["LOGOSAI_HARNESS_MAX_TOKENS"] = "100"

    import logosai.observability as obs
    from logosai.utils import guardrails as gr
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse, AgentResponseType

    # 관측 emit/span 은 무해화(예산만 검증)
    obs.emit_agent_execution = lambda *a, **k: None
    obs.start_agent_span = lambda agent_id, query: type("S", (), {"end": lambda self, *a, **k: None})()

    # ── 프리미티브: 예산 없이 no-op ──
    gr.precheck_llm_call()  # caps None → raise 안 함
    gr.record_llm_tokens(9999, 9999)
    t("B-1 예산 미활성 → precheck/record no-op", True)

    # ── 프리미티브: 호출 상한 ──
    tok = gr.begin_execution_budget(max_calls=3, max_tokens=None)
    raised = False
    try:
        for _ in range(3):
            gr.precheck_llm_call()  # 1,2,3 OK
        gr.precheck_llm_call()      # 4번째 → 초과
    except gr.HarnessBudgetExceeded:
        raised = True
    gr.reset_execution_budget(tok)
    t("B-2 호출 상한 초과 → HarnessBudgetExceeded", raised)

    # ── 프리미티브: 토큰 상한 ──
    tok = gr.begin_execution_budget(max_calls=None, max_tokens=100)
    gr.precheck_llm_call()           # 1번째 OK (누적 0)
    gr.record_llm_tokens(80, 40)     # 누적 120 >= 100
    raised = False
    try:
        gr.precheck_llm_call()       # 다음 호출 차단
    except gr.HarnessBudgetExceeded:
        raised = True
    gr.reset_execution_budget(tok)
    t("B-3 토큰 상한 누적 초과 → 다음 precheck 차단", raised)

    # ── 프리미티브: reset 격리 ──
    tok = gr.begin_execution_budget(max_calls=2, max_tokens=None)
    gr.precheck_llm_call()
    gr.reset_execution_budget(tok)
    # reset 후 새 예산 → 카운터 0 부터
    tok2 = gr.begin_execution_budget(max_calls=2, max_tokens=None)
    ok = True
    try:
        gr.precheck_llm_call()
        gr.precheck_llm_call()
    except gr.HarnessBudgetExceeded:
        ok = False
    gr.reset_execution_budget(tok2)
    t("B-4 reset 후 카운터 격리(0부터)", ok)

    # ── 통합: process() 가 호출 상한 초과 → graceful error ──
    class BurstAgent(SimpleAgent):
        async def process(self, query, context=None):
            for _ in range(10):            # 상한(3) 훨씬 초과하는 LLM 호출 시뮬
                gr.precheck_llm_call()
            return AgentResponse.success(content={"answer": "done"})

    res = run(BurstAgent().process("x"))
    t("B-5 호출 상한 초과 시 graceful AgentResponse.error",
      getattr(res, "type", None) == AgentResponseType.ERROR)

    # ── 통합: 상한 이내면 정상 ──
    class LightAgent(SimpleAgent):
        async def process(self, query, context=None):
            gr.precheck_llm_call()
            gr.record_llm_tokens(10, 10)
            return AgentResponse.success(content={"answer": "ok:" + query})

    res2 = run(LightAgent().process("hi"))
    t("B-6 상한 이내 → 정상 완료",
      getattr(res2, "content", {}).get("answer") == "ok:hi")

    # ── opt-out: _harness=False → 예산 미적용(초과해도 완료) ──
    burst2 = BurstAgent()
    burst2._harness = False
    res3 = run(burst2.process("y"))
    t("B-7 _harness=False → 예산 미적용(완료)",
      getattr(res3, "content", {}).get("answer") == "done")

    os.environ.pop("LOGOSAI_HARNESS_TIMEOUT", None)
    os.environ.pop("LOGOSAI_HARNESS_MAX_CALLS", None)
    os.environ.pop("LOGOSAI_HARNESS_MAX_TOKENS", None)
    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
