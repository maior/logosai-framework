"""GoldenRunner — 에이전트를 golden dataset 으로 돌려 회귀 점수 집계 (2026-07-07).

judge 는 주입(async callable(query, response, criteria)->Verdict). agent 예외/
빈 응답은 케이스 실패(score 0)로 격리해 전체 run 을 죽이지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List

from .golden import GoldenCase
from .judge import Verdict


def _response_text(resp: Any) -> str:
    """AgentResponse/문자열/dict 에서 judge 에 넘길 텍스트 추출."""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    # AgentResponse: message + content 결합
    msg = getattr(resp, "message", None)
    content = getattr(resp, "content", None)
    parts = []
    if msg:
        parts.append(str(msg))
    if content is not None:
        parts.append(content if isinstance(content, str) else str(content))
    if parts:
        return "\n".join(parts)
    return str(resp)


@dataclass
class CaseResult:
    case: GoldenCase
    response: str
    verdict: Verdict


@dataclass
class EvalReport:
    """회귀 실행 요약."""
    results: List[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.verdict.passed)

    @property
    def pass_rate(self) -> float:
        return (self.passed_count / self.total) if self.total else 0.0

    @property
    def mean_score(self) -> float:
        if not self.total:
            return 0.0
        return sum(r.verdict.score for r in self.results) / self.total

    @property
    def weighted_score(self) -> float:
        wsum = sum(r.case.weight for r in self.results)
        if wsum <= 0:
            return 0.0
        return sum(r.verdict.score * r.case.weight for r in self.results) / wsum

    def summary(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed_count,
            "pass_rate": round(self.pass_rate, 4),
            "mean_score": round(self.mean_score, 4),
            "weighted_score": round(self.weighted_score, 4),
        }


JudgeFn = Callable[[str, str, str], Awaitable[Verdict]]


class GoldenRunner:
    """golden dataset 러너. judge 를 주입받아 케이스별 채점·집계."""

    def __init__(self, judge: JudgeFn):
        if not callable(judge):
            raise TypeError("judge 는 async callable 이어야 합니다")
        self.judge = judge

    async def run(self, agent, cases: List[GoldenCase]) -> EvalReport:
        report = EvalReport()
        for case in cases:
            try:
                resp = await agent.process(case.query, case.context)
                text = _response_text(resp)
            except Exception as e:  # noqa: BLE001 — 케이스 격리
                report.results.append(CaseResult(
                    case=case, response="",
                    verdict=Verdict(score=0.0, passed=False,
                                    reason=f"agent error: {e}"),
                ))
                continue
            try:
                verdict = await self.judge(case.query, text, case.criteria)
            except Exception as e:  # noqa: BLE001 — judge 실패도 격리
                verdict = Verdict(score=0.0, passed=False, reason=f"judge error: {e}")
            report.results.append(CaseResult(case=case, response=text, verdict=verdict))
        return report
