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

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가 0건을 수집했다.
  - 직접 실행: python tests/test_eval_golden_runner.py  → 마지막 줄 `RESULT: GREEN`

예전 스크립트는 에이전트를 실제로 돌리면서 Pulse 전송을 막지 않았다 — span 이
관측 서버로 나가려다 루프가 닫혀 "Task was destroyed but it is pending" 이 쏟아졌고,
그 경고가 `RESULT: GREEN` 뒤에 찍혀 마지막 줄을 차지했다. 이제 `_setup` 이 막는다.
"""
import json
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":      # 스크립트 모드에서만 — pytest 는 pyproject 의 pythonpath 를 쓴다
    sys.path.insert(0, _PKG)

from _script_runner import block_pulse, run, run_tests  # noqa: E402


def _setup(mp):
    block_pulse(mp)     # 에이전트 process() 는 하네스·관측을 탄다 — 전송만 막는다


def _teardown():
    pass


def _golden_cases(tmp_path):
    from logosai.eval.golden import load_golden
    p = os.path.join(str(tmp_path), "golden.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump([
            {"id": "c1", "query": "2+2?", "criteria": "정답 4 를 포함", "weight": 2.0},
            {"id": "c2", "query": "수도?", "criteria": "서울 언급"},
        ], f)
    return load_golden(p)


def _stub_judge(seen):
    """스텁 judge (결정적): 응답에 'good' 있으면 1.0 pass, 아니면 0.0 fail"""
    from logosai.eval import Verdict

    async def stub_judge(query, response_text, criteria):
        seen.append((query, response_text, criteria))
        good = "good" in response_text
        return Verdict(score=1.0 if good else 0.0, passed=good,
                       reason="ok" if good else "miss")

    return stub_judge


def _mixed_report():
    """pass 1건(weight 1) + fail 1건(weight 3) → (report, judge 가 본 것)"""
    from logosai.eval import GoldenCase, GoldenRunner
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse

    class MixedAgent(SimpleAgent):
        async def process(self, query, context=None):
            # "pass" 쿼리는 good, 아니면 bad
            return AgentResponse.success(content={"answer": "good result" if "pass" in query else "bad"})

    cases2 = [
        GoldenCase(id="a", query="pass one", criteria="x", weight=1.0),
        GoldenCase(id="b", query="fail one", criteria="y", weight=3.0),
    ]
    seen = []
    report = run(GoldenRunner(_stub_judge(seen)).run(MixedAgent(), cases2))
    return report, seen


class _MockResp:
    def __init__(self, content):
        self.content = content


def _llm_judge_verdict(raw, query="2+2?", response="4 입니다", criteria="정답 4 포함"):
    from logosai.eval import LLMJudge

    class _MockLLM:
        async def invoke_messages(self, messages, **kw):
            return _MockResp(raw)

    return run(LLMJudge(llm_client=_MockLLM(), threshold=0.7)(query, response, criteria))


# ── load_golden ──

def test_e1_load_golden_returns_goldencase_list(tmp_path):
    """E-1 load_golden → GoldenCase 리스트"""
    from logosai.eval import GoldenCase
    cases = _golden_cases(tmp_path)
    assert len(cases) == 2
    assert isinstance(cases[0], GoldenCase)


def test_e2_weight_and_criteria_parsed(tmp_path):
    """E-2 weight/criteria 파싱"""
    cases = _golden_cases(tmp_path)
    assert cases[0].weight == 2.0
    assert "4" in cases[0].criteria


# ── 러너 집계 ──

def test_e3_run_returns_evalreport():
    """E-3 EvalReport 반환"""
    from logosai.eval import EvalReport
    report, _ = _mixed_report()
    assert isinstance(report, EvalReport)


def test_e4_pass_rate_aggregated():
    """E-4 pass_rate 집계(1/2)"""
    report, _ = _mixed_report()
    assert abs(report.pass_rate - 0.5) < 1e-9


def test_e5_mean_score_aggregated():
    """E-5 mean_score 집계((1+0)/2)"""
    report, _ = _mixed_report()
    assert abs(report.mean_score - 0.5) < 1e-9


def test_e6_weighted_score_aggregated():
    """E-6 weighted_score 가중 집계(0.25)"""
    # weighted: (1*1.0 + 0*3.0)/(1+3) = 0.25
    report, _ = _mixed_report()
    assert abs(report.weighted_score - 0.25) < 1e-9


def test_e7_judge_receives_response_text():
    """E-7 judge 에 응답 텍스트 전달"""
    _, seen = _mixed_report()
    assert len(seen) == 2
    assert any("good result" in s[1] for s in seen)


# ── agent 예외 격리 ──

def test_e8_agent_exception_is_isolated_as_case_failure():
    """E-8 agent 예외 → 케이스 실패로 격리(run 안 죽음)"""
    from logosai.eval import EvalReport, GoldenCase, GoldenRunner
    from logosai.simple_agent import SimpleAgent

    class BoomAgent(SimpleAgent):
        async def process(self, query, context=None):
            raise ValueError("boom")

    rep2 = run(GoldenRunner(_stub_judge([])).run(
        BoomAgent(), [GoldenCase(id="z", query="q", criteria="c")]))
    assert isinstance(rep2, EvalReport)
    assert rep2.total == 1
    assert rep2.passed_count == 0
    # 대조군: 같은 러너·judge 가 멀쩡한 에이전트에는 통과를 센다 (0 이 '항상 0'이 아님).
    report, _ = _mixed_report()
    assert report.passed_count == 1


# ── LLMJudge: mock LLMClient JSON → Verdict ──

def test_e9_llmjudge_parses_score():
    """E-9 LLMJudge score 파싱"""
    v = _llm_judge_verdict('{"score": 0.9, "reason": "정확함"}')
    assert abs(v.score - 0.9) < 1e-9


def test_e10_llmjudge_threshold_sets_passed():
    """E-10 LLMJudge threshold → passed"""
    v = _llm_judge_verdict('{"score": 0.9, "reason": "정확함"}')
    assert v.passed is True


def test_e11_llmjudge_extracts_json_from_noise_and_fails_below_threshold():
    """E-11 LLMJudge JSON 추출(잡음 내성) + threshold 미달 fail"""
    # 앞뒤 잡음 포함
    v2 = _llm_judge_verdict('점수: {"score": 0.3, "reason": "부정확"}', "q", "틀림", "c")
    assert abs(v2.score - 0.3) < 1e-9
    assert v2.passed is False
    # 대조군: 같은 잡음이어도 점수가 threshold 를 넘으면 통과한다.
    assert _llm_judge_verdict('점수: {"score": 0.8, "reason": "ok"}', "q", "맞음", "c").passed is True


# ══ pytest 배선 ═══════════════════════════════════════════════════════════

if "pytest" in sys.modules:
    import pytest

    @pytest.fixture(autouse=True)
    def _env(monkeypatch):
        _setup(monkeypatch)
        yield
        monkeypatch.undo()
        _teardown()


def main():
    return run_tests(globals(), setup=_setup, teardown=_teardown)


if __name__ == "__main__":
    sys.exit(main())
