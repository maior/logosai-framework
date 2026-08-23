"""코드 리뷰 발견의 계약 계층 (2026-08-21).

리뷰어(에이전트)는 ACP 에, 저장소는 런타임에, 소비는 FORGE 에 있다. 여기에는
**계약과 순수 함수만** 둔다 — 모든 에이전트가 이미 import 하는 유일한 층이기
때문이다.

FORGE 에 두지 않은 이유: FORGE 는 코드 자판기이며 축적물을 프로세스 밖에서
읽을 수단이 없다(grown_slices.json HTTP 노출 0, Stage 7.5 lesson 은 인메모리).
게다가 2026-08-11~17 에 5일 18시간 죽어 있었고 아무도 몰랐다. 그 위에 집단
학습을 올리면 그 5일 동안 조직 전체가 조용히 퇴화한다.

이 서브패키지는 표준 라이브러리만 쓴다.
"""

from .finding import (
    SEVERITIES,
    TARGETS,
    EvidenceError,
    ReviewFinding,
    bind_evidence,
    classify_target,
    dedupe,
    finding_id_for,
    recheck,
    revision_of,
    validate_finding,
)
from .rules import Rule, RuleSet, get_rule
from .rules_logos import RULES, DEFAULT_RULES

__all__ = [
    "SEVERITIES",
    "TARGETS",
    "EvidenceError",
    "ReviewFinding",
    "bind_evidence",
    "classify_target",
    "dedupe",
    "finding_id_for",
    "recheck",
    "revision_of",
    "validate_finding",
    "RULES",
    "DEFAULT_RULES",
    "Rule",
    "RuleSet",
    "get_rule",
]
