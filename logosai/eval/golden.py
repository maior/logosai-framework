"""Golden dataset — 회귀 측정용 케이스 정의·로딩 (Phase 2, 2026-07-07).

GoldenCase 는 (query, criteria) 쌍. criteria 는 LLM-judge 가 채점할 자연어
판정 기준이다. weight 로 케이스별 중요도를 가중 집계에 반영한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GoldenCase:
    """단일 회귀 케이스."""
    query: str
    criteria: str                      # LLM-judge 가 채점하는 자연어 기준
    context: Optional[Dict[str, Any]] = None
    weight: float = 1.0
    id: str = ""


def load_golden(path: str) -> List[GoldenCase]:
    """JSON 파일(케이스 리스트)에서 GoldenCase 들을 로드한다.

    형식: [{"query": ..., "criteria": ..., "weight"?: ..., "context"?: {...},
            "id"?: ...}, ...]
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError("golden dataset 은 케이스 리스트여야 합니다")
    cases: List[GoldenCase] = []
    for i, item in enumerate(raw):
        cases.append(GoldenCase(
            query=item["query"],
            criteria=item.get("criteria", ""),
            context=item.get("context"),
            weight=float(item.get("weight", 1.0)),
            id=str(item.get("id", f"case_{i}")),
        ))
    return cases
