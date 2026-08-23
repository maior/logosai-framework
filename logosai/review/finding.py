"""ReviewFinding 계약과 순수 함수 (2026-08-21).

판단은 LLM 이, 장부는 여기가 한다
────────────────────────────
리뷰어의 판정은 결정적으로 테스트할 수 없다. 그래서 판단만 LLM 에 남기고
증거 결착·계약 검증·소재지 판정·중복 제거를 전부 순수 함수로 내렸다.
리뷰어 모델을 바꿔도 이 파일의 동작은 바뀌지 않아야 한다.

증거가 이 설계 전체를 떠받친다
──────────────────────────
프롬프트 자동 주입은 과거에 "잘못된 학습 주입 → 연쇄 장애 위험"으로 보류됐다
(CLAUDE.md:659). 리뷰 발견이 그 위험을 피할 수 있는 이유는 하나뿐이다 —
행동 학습은 '세상에 대한 주장'이라 검증할 수 없지만, 리뷰 발견은 '존재하는
텍스트에 대한 주장'이라 **언제든 다시 읽어 확인할 수 있다**.

따라서 excerpt(발췌) 없는 발견은 만들 수 없고, 코드가 바뀌면 recheck 가
발견을 만료시킨다. 증거를 선택 항목으로 두는 순간 이 안전성은 사라진다.

이 모듈은 표준 라이브러리만 쓴다 — 오프라인 census 에서 프레임워크 전체를
끌고 오지 않기 위해서다.
"""

import hashlib
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Dict, List, Sequence

#: 심각도 어휘의 정본은 `rules.py` 다 — 규칙이 먼저 갖고 발견이 물려받는다.
#: 여기서 다시 정의하면 두 정의가 곧 갈린다. 재수입해 이름만 유지한다.
from .rules import SEVERITIES, get_rule  # noqa: F401  (SEVERITIES 는 재수출)

TARGETS = ("template", "block", "instance")

_WS = re.compile(r"\s+")


class EvidenceError(ValueError):
    """인용한 증거가 소스에서 확인되지 않는다 — 발견을 버린다."""


def _norm(text: str) -> str:
    """비교용 정규화. 들여쓰기·공백 차이로 같은 결함을 다른 것으로 세지 않는다."""
    return _WS.sub(" ", (text or "").strip()).lower()


def revision_of(source: str) -> str:
    """코드 개정 스탬프.

    Pulse 의 agent_executions 에는 버전 컬럼이 없어 오늘은 '나아졌다'가 상관일
    뿐 귀속이 아니다. 발견 단계에서부터 리비전을 박아 두면 나중에 조인할 수 있다.
    """
    return hashlib.sha256((source or "").encode("utf-8")).hexdigest()[:12]


def finding_id_for(rule_id: str, path: str, line: int, excerpt: str) -> str:
    """같은 결함이 항상 같은 id 를 받아야 재발을 셀 수 있다."""
    key = f"{rule_id}|{path}|{line}|{_norm(excerpt)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


@dataclass
class ReviewFinding:
    rule_id: str
    severity: str
    path: str
    line: int
    excerpt: str
    target: str
    message: str
    subject_agent: str = ""
    agent_revision: str = ""
    source_agent: str = "code_review_agent"
    observed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finding_id: str = ""

    def __post_init__(self):
        if not self.finding_id:
            self.finding_id = finding_id_for(
                self.rule_id, self.path, self.line, self.excerpt
            )

    def to_dict(self) -> Dict:
        return {
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "path": self.path,
            "line": self.line,
            "excerpt": self.excerpt,
            "target": self.target,
            "message": self.message,
            "subject_agent": self.subject_agent,
            "agent_revision": self.agent_revision,
            "source_agent": self.source_agent,
            "observed_at": self.observed_at,
        }


def validate_finding(f: ReviewFinding) -> List[str]:
    """계약 위반 목록을 돌려준다. 빈 목록이면 통과.

    예외가 아니라 목록인 이유: 리뷰어가 한 번에 수십 건을 내므로 첫 위반에서
    멈추면 나머지를 못 본다.
    """
    errs: List[str] = []
    if get_rule(f.rule_id) is None:
        errs.append(f"rule_id: 레지스트리에 없는 규칙 {f.rule_id!r}")
    if f.severity not in SEVERITIES:
        errs.append(f"severity: {f.severity!r} 는 {SEVERITIES} 중 하나여야 한다")
    if f.target not in TARGETS:
        errs.append(f"target: {f.target!r} 는 {TARGETS} 중 하나여야 한다")
    if not isinstance(f.line, int) or f.line < 1:
        errs.append(f"line: 1 이상이어야 한다 (받은 값 {f.line!r})")
    if not (f.excerpt or "").strip():
        errs.append("excerpt: 증거가 비어 있다 — 재검증 불가능한 발견은 저장하지 않는다")
    if not (f.path or "").strip():
        errs.append("path: 비어 있다")
    return errs


def bind_evidence(f: ReviewFinding, source: str, window: int = 3) -> ReviewFinding:
    """인용한 발췌가 실제로 그 근처에 있는지 대조하고, 행 번호를 교정한다.

    LLM 은 행 번호를 한두 줄 자주 틀린다. 그래서 위치에는 관대하되(window),
    **발췌 자체가 없으면 거부한다** — 그것이 환각과 오탐의 경계다.

    창 안에 여러 번 나오면 보고된 행에서 가장 가까운 것을 고른다. finding_id 가
    행을 포함하므로 여기서 흔들리면 재발 집계가 무너진다.
    """
    lines = (source or "").splitlines()
    if not lines:
        raise EvidenceError("소스가 비어 있다")
    if f.line < 1 or f.line > len(lines):
        raise EvidenceError(
            f"행 번호 {f.line} 이 소스 범위(1..{len(lines)}) 밖이다"
        )

    needle = _norm(f.excerpt)
    if not needle:
        raise EvidenceError("발췌가 비어 있다")

    lo = max(1, f.line - window)
    hi = min(len(lines), f.line + window)
    hits = [n for n in range(lo, hi + 1) if needle in _norm(lines[n - 1])]
    if not hits:
        raise EvidenceError(
            f"{f.path}:{f.line} 부근 ±{window} 행에서 발췌를 찾지 못했다: {f.excerpt!r}"
        )

    best = min(hits, key=lambda n: (abs(n - f.line), n))
    if best == f.line:
        return f
    return replace(f, line=best, finding_id="")


def recheck(f: ReviewFinding, current_source: str) -> bool:
    """발견이 아직 성립하는가.

    bind_evidence 와 달리 파일 전체를 본다 — 코드가 밀려 위치가 바뀌었다고 해서
    결함이 사라진 것은 아니기 때문이다. 발췌가 어디에도 없으면 만료다.
    """
    needle = _norm(f.excerpt)
    if not needle:
        return False
    return needle in _norm(current_source)


def dedupe(findings: Sequence[ReviewFinding]) -> List[ReviewFinding]:
    """같은 규칙·파일·행은 하나로 접는다. 설명이 달라도 같은 결함이다."""
    seen = set()
    out: List[ReviewFinding] = []
    for f in findings:
        key = (f.rule_id, f.path, f.line)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def classify_target(
    findings: Sequence[ReviewFinding], template_threshold: int = 3
) -> List[ReviewFinding]:
    """결함의 소재지를 판정한다 — 레버리지가 여기서 갈린다.

    318곳의 except Exception 은 74개의 결함이 아니라 템플릿 결함 하나가 74번
    복제된 것이다. 개체를 74번 고치는 것과 생성기를 한 번 고치는 것의 차이가
    이 판정에 달렸다.

    **서로 다른 파일** 수를 센다. 같은 파일에서 10번 터진 것은 그 파일의 문제이지
    템플릿의 증거가 아니다.

    승격만 하고 강등하지 않는다 — 리뷰어가 명시적으로 template 이라 판정한 것을
    빈도가 낮다는 이유로 뒤집지 않는다.
    """
    files_by_defect: Dict[tuple, set] = {}
    for f in findings:
        files_by_defect.setdefault((f.rule_id, _norm(f.excerpt)), set()).add(f.path)

    out: List[ReviewFinding] = []
    for f in findings:
        distinct_files = len(files_by_defect[(f.rule_id, _norm(f.excerpt))])
        if f.target != "template" and distinct_files >= template_threshold:
            out.append(replace(f, target="template"))
        else:
            out.append(f)
    return out
