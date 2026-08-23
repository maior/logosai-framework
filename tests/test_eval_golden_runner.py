"""Phase 2 — Eval golden runner 테스트 (2026-07-07).

표준 준비도 진단 G7: self_evaluate 를 넘어 golden dataset 러너 — 회귀 측정·
점수 추이를 프레임워크가 제공. 정답 판정은 LLM-judge 중심(FORGE honest_eval
방법론), 단 judge 는 주입 가능(injectable)해 러너 로직은 stub 로 결정적 테스트.
계약:
  - load_golden(json) → GoldenCase 리스트.
  - GoldenRunner(judge).run(agent, cases) → EvalReport(집계: pass_rate/mean/
    weighted). judge 는 async callable(query, response_text, criteria)->Verdict.
  - 케이스별 agent.process 실행, 응답 텍스트를 judge 에 전달.
  - agent 예외/타임아웃 → 해당 케이스 실패(score 0)로 격리, 전체 run 안 죽음.
  - LLMJudge 는 LLMClient(mock) JSON 응답을 Verdict 로 파싱, threshold 로 passed.

직접 실행: python logosai/tests/test_eval_golden_runner.py
"""
import asyncio
import json
import os
import sys
import tempfile

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

    from logosai.eval import GoldenCase, GoldenRunner, EvalReport, LLMJudge, Verdict
    from logosai.eval.golden import load_golden
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse

    # ── load_golden ──
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "golden.json")
        json.dump([
            {"id": "c1", "query": "2+2?", "criteria": "정답 4 를 포함", "weight": 2.0},
            {"id": "c2", "query": "수도?", "criteria": "서울 언급"},
        ], open(p, "w"))
        cases = load_golden(p)
    t("E-1 load_golden → GoldenCase 리스트", len(cases) == 2 and isinstance(cases[0], GoldenCase))
    t("E-2 weight/criteria 파싱", cases[0].weight == 2.0 and "4" in cases[0].criteria)

    # ── 스텁 judge (결정적): 응답에 'good' 있으면 1.0 pass, 아니면 0.0 fail ──
    seen = []

    async def stub_judge(query, response_text, criteria):
        seen.append((query, response_text, criteria))
        good = "good" in response_text
        return Verdict(score=1.0 if good else 0.0, passed=good,
                       reason="ok" if good else "miss")

    class MixedAgent(SimpleAgent):
        async def process(self, query, context=None):
            # "pass" 쿼리는 good, 아니면 bad
            return AgentResponse.success(content={"answer": "good result" if "pass" in query else "bad"})

    cases2 = [
        GoldenCase(id="a", query="pass one", criteria="x", weight=1.0),
        GoldenCase(id="b", query="fail one", criteria="y", weight=3.0),
    ]
    report = run(GoldenRunner(stub_judge).run(MixedAgent(), cases2))
    t("E-3 EvalReport 반환", isinstance(report, EvalReport))
    t("E-4 pass_rate 집계(1/2)", abs(report.pass_rate - 0.5) < 1e-9)
    t("E-5 mean_score 집계((1+0)/2)", abs(report.mean_score - 0.5) < 1e-9)
    # weighted: (1*1.0 + 0*3.0)/(1+3) = 0.25
    t("E-6 weighted_score 가중 집계(0.25)", abs(report.weighted_score - 0.25) < 1e-9)
    t("E-7 judge 에 응답 텍스트 전달", any("good result" in s[1] for s in seen))

    # ── agent 예외 격리 ──
    class BoomAgent(SimpleAgent):
        async def process(self, query, context=None):
            raise ValueError("boom")

    rep2 = run(GoldenRunner(stub_judge).run(BoomAgent(), [GoldenCase(id="z", query="q", criteria="c")]))
    t("E-8 agent 예외 → 케이스 실패로 격리(run 안 죽음)",
      isinstance(rep2, EvalReport) and rep2.total == 1 and rep2.passed_count == 0)

    # ── LLMJudge: mock LLMClient JSON → Verdict ──
    class _MockResp:
        def __init__(self, content):
            self.content = content

    class _MockLLM:
        async def invoke_messages(self, messages, **kw):
            return _MockResp('{"score": 0.9, "reason": "정확함"}')

    judge = LLMJudge(llm_client=_MockLLM(), threshold=0.7)
    v = run(judge("2+2?", "4 입니다", "정답 4 포함"))
    t("E-9 LLMJudge score 파싱", abs(v.score - 0.9) < 1e-9)
    t("E-10 LLMJudge threshold → passed", v.passed is True)

    class _MockLLMLow:
        async def invoke_messages(self, messages, **kw):
            return _MockResp('점수: {"score": 0.3, "reason": "부정확"}')  # 앞뒤 잡음 포함

    v2 = run(LLMJudge(llm_client=_MockLLMLow(), threshold=0.7)("q", "틀림", "c"))
    t("E-11 LLMJudge JSON 추출(잡음 내성) + threshold 미달 fail",
      abs(v2.score - 0.3) < 1e-9 and v2.passed is False)

    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
