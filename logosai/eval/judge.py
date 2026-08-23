"""LLM-judge — 응답을 기준(criteria)으로 채점 (Phase 2, 2026-07-07).

FORGE honest_eval 방법론(rubric 채점)을 단순화: LLM 이 (query, response,
criteria)를 보고 0~1 점수 + 이유를 JSON 으로 반환. threshold 이상이면 passed.

judge 는 GoldenRunner 에 주입되는 async callable — 이 클래스는 LLM 기반 기본
구현이며, 테스트/오프라인에서는 임의의 async callable 로 대체할 수 있다.
LLMClient 는 주입 가능(기본은 지연 생성)해 mock 테스트가 쉽다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class Verdict:
    """judge 판정 결과."""
    score: float          # 0.0 ~ 1.0
    passed: bool
    reason: str = ""


_JUDGE_SYSTEM = (
    "당신은 엄정한 평가자입니다. 에이전트 응답이 주어진 기준을 충족하는지 "
    "0.0~1.0 점수로 채점하세요. 관대하지 말고 근거에 기반해 평가합니다. "
    '반드시 JSON 만 출력: {"score": <0~1 실수>, "reason": "<간단한 근거>"}'
)


def _extract_json(text: str) -> dict:
    """LLM 출력에서 첫 JSON 객체를 관대하게 추출."""
    if not text:
        return {}
    # 코드펜스 제거
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        # score 만이라도 정규식으로
        sm = re.search(r'"score"\s*:\s*([0-9.]+)', text)
        rm = re.search(r'"reason"\s*:\s*"([^"]*)"', text)
        out = {}
        if sm:
            out["score"] = float(sm.group(1))
        if rm:
            out["reason"] = rm.group(1)
        return out


class LLMJudge:
    """LLM 기반 기본 judge. async callable(query, response, criteria)->Verdict."""

    def __init__(self, llm_client=None, threshold: float = 0.7, model: str = None):
        self._llm = llm_client
        self.threshold = threshold
        self.model = model

    def _get_llm(self):
        if self._llm is None:
            from logosai.utils.llm_client import LLMClient
            self._llm = LLMClient(model=self.model) if self.model else LLMClient()
        return self._llm

    async def __call__(self, query: str, response: str, criteria: str) -> Verdict:
        prompt = (
            f"[사용자 쿼리]\n{query}\n\n"
            f"[에이전트 응답]\n{response}\n\n"
            f"[판정 기준]\n{criteria}\n\n"
            "위 기준을 얼마나 충족하는지 채점하세요."
        )
        messages = [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        try:
            resp = await self._get_llm().invoke_messages(messages)
            content = getattr(resp, "content", "") or ""
        except Exception as e:  # noqa: BLE001 — judge 실패는 0점 처리(회귀 러너 안 죽임)
            return Verdict(score=0.0, passed=False, reason=f"judge error: {e}")
        data = _extract_json(content)
        try:
            score = float(data.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))
        return Verdict(
            score=score,
            passed=score >= self.threshold,
            reason=str(data.get("reason", "")),
        )
