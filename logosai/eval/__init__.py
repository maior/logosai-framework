"""logosai.eval — Golden dataset 회귀 러너 (Phase 2, 2026-07-07).

self_evaluate 를 넘어 프레임워크가 회귀 측정·점수 추이를 제공. 정답 판정은
LLM-judge 중심(FORGE honest_eval 방법론)이며 judge 는 주입 가능해 결정적
테스트가 쉽다.

사용 예:
    from logosai.eval import GoldenRunner, LLMJudge
    from logosai.eval.golden import load_golden

    cases = load_golden("golden.json")
    report = await GoldenRunner(LLMJudge()).run(my_agent, cases)
    print(report.summary())   # {'pass_rate': ..., 'weighted_score': ...}
"""
from .golden import GoldenCase, load_golden
from .judge import LLMJudge, Verdict
from .runner import CaseResult, EvalReport, GoldenRunner

__all__ = [
    "GoldenCase",
    "load_golden",
    "LLMJudge",
    "Verdict",
    "CaseResult",
    "EvalReport",
    "GoldenRunner",
]
