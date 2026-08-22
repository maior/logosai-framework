"""정밀도 감사 — 장부에 들어간 발견이 얼마나 맞는지 (관문 G2, 2026-08-22).

무엇을 재는가 (그리고 무엇을 못 재는가)
──────────────────────────────────────
전수 census 는 리뷰어가 **420번 틀렸고 장부에는 0건 들어갔다**는 것까지만
말해 준다. 장부에 *들어간* 2,239건이 얼마나 맞는지는 재본 적이 없다.

발견이 코드를 고치기 시작하는 순간(Phase 1) 오탐은 **잘못된 수정**이 된다.
그래서 주입할 권리는 측정으로 사야 한다.

이 모듈이 재는 것은 **정밀도뿐**이다. 사상 ⑥ 이 말한 대로 우리는 정밀도를
재현율로 샀고, 얼마나 놓치는지는 이 안에서 알 수 없다. 여기서 나온 숫자를
"리뷰어가 이만큼 잘한다"로 읽으면 안 된다 — "보고한 것 중 이만큼이 맞다"이다.

세 가지 규율
──────────
1. **판단과 산술의 분리** (사상 ③) — 모델은 "이게 결함인가"만 답한다.
   표본을 어떻게 뽑았고 거기서 모집단 정밀도를 어떻게 얻었는지는 전부 여기,
   재현 가능한 순수 함수다. 이 산술이 틀리면 Phase 1 허가가 틀린다.

2. **판정자는 리뷰어가 아니다** (사상 ⑨) — 다른 모델, 다른 과제 형태,
   그리고 **리뷰어의 message 를 보여주지 않는다**. 리뷰어의 문장을 주면
   "그럴듯한가"를 재게 되지 "코드가 실제로 그런가"를 재지 못한다.

3. **모름을 강제 배분하지 않는다** (사상 ⑦) — 판정 3종이고, 결과는 한 숫자가
   아니라 구간이다. 판정 불가 층은 점추정에서 빠지되 **빠졌다는 사실이 보인다**.
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .rules import RULES

#: 대조군을 담는 가짜 층. 정밀도 모집단이 아니므로 가중 집계에서 제외된다.
CONTROL_STRATUM: Tuple[str, str] = ("__control__", "")

#: 95% 정규 근사 z. 층화 표본의 표준오차에 곱한다.
_Z95 = 1.959963985


class Verdict(Enum):
    """판정 3종. 모름은 실패가 아니라 **정보**다."""

    TRUE = "맞다"
    FALSE = "틀렸다"
    UNKNOWN = "모름"


# ── 표본 추출 ────────────────────────────────────────────

def stratify(
    population: Sequence[Mapping[str, Any]],
    per_stratum: int = 15,
    seed: int = 20260822,
) -> List[Dict[str, Any]]:
    """층 = (rule_id, target). 층마다 최대 `per_stratum` 건을 뽑는다.

    왜 비례 배분이 아닌가 — R-013 은 3건, R-001 은 474건이다. 비례로 뽑으면
    작은 규칙은 표본이 0 이 되어 **그 규칙의 정밀도를 영원히 모른다**. 규칙별
    판정이 규칙 솎기(사상 ⑧)의 근거이므로 작은 층도 봐야 한다.
    모집단 비중은 뽑을 때가 아니라 **집계할 때** 가중치로 되돌린다.

    시드를 고정하는 이유: 감사도 감사받아야 한다. 재현할 수 없는 표본으로 낸
    숫자는 검증할 수 없다.
    """
    buckets: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for f in population:
        key = (str(f.get("rule_id", "")), str(f.get("target", "")))
        buckets.setdefault(key, []).append(f)

    out: List[Dict[str, Any]] = []
    for key in sorted(buckets):
        items = sorted(buckets[key], key=lambda f: str(f.get("finding_id", "")))
        rng = random.Random(f"{seed}|{key[0]}|{key[1]}")
        take = min(per_stratum, len(items))
        for f in rng.sample(items, take):
            out.append(dict(f))
    return out


def stratum_sizes(
    population: Sequence[Mapping[str, Any]]
) -> Dict[Tuple[str, str], int]:
    """층별 모집단 크기 — 가중치와 유한모집단 보정의 분모."""
    sizes: Dict[Tuple[str, str], int] = {}
    for f in population:
        key = (str(f.get("rule_id", "")), str(f.get("target", "")))
        sizes[key] = sizes.get(key, 0) + 1
    return sizes


# ── 층별 정밀도 ──────────────────────────────────────────

@dataclass(frozen=True)
class Precision:
    """한 층의 정밀도. `point` 가 None 이면 **판정된 것이 없다**(0 이 아니다)."""

    point: Optional[float]
    low: float          # 모름을 전부 오답으로 볼 때
    high: float         # 모름을 전부 정답으로 볼 때
    decided: int
    unknown: int
    n: int


def stratum_precision(verdicts: Sequence[Verdict]) -> Precision:
    """모름은 어느 쪽으로도 강제 배분하지 않는다.

    한 숫자로 뭉치면 "정밀도 75%" 가 실제로는 "판정된 8건 중 6건" 인지
    "10건 중 6건에 2건은 모른다" 인지 구분되지 않는다. 둘은 다른 상태다.
    """
    n = len(verdicts)
    t = sum(1 for v in verdicts if v is Verdict.TRUE)
    f = sum(1 for v in verdicts if v is Verdict.FALSE)
    u = n - t - f
    decided = t + f
    if n == 0:
        return Precision(None, 0.0, 1.0, 0, 0, 0)
    return Precision(
        point=(t / decided) if decided else None,
        low=t / n,
        high=(t + u) / n,
        decided=decided,
        unknown=u,
        n=n,
    )


# ── 층화 집계 ────────────────────────────────────────────

@dataclass(frozen=True)
class Aggregate:
    point: Optional[float]
    ci_low: float
    ci_high: float
    half_width: float
    low: float           # 모름=오답 가정의 하한
    high: float          # 모름=정답 가정의 상한
    sampled: int
    unknown: int
    population: int
    #: 점추정이 실제로 덮는 모집단 비중. 1.0 이 아니면 나머지는 판정 불가였다.
    covered_share: float
    undecided_strata: List[Tuple[str, str]]
    per_stratum: Dict[Tuple[str, str], Precision] = field(default_factory=dict)
    #: 대조군(발견되지 않은 행)에서 '맞다'가 나온 비율. **귀속하지 않는다** —
    #: 판정자 과잉동의일 수도, 리뷰어 누락일 수도 있다.
    control_flagged_rate: Optional[float] = None
    control_n: int = 0


def aggregate(strata: Mapping[Tuple[str, str], Mapping[str, Any]]) -> Aggregate:
    """층별 판정 → 모집단 정밀도.

    `strata[key] = {"N": 모집단크기, "verdicts": [Verdict, ...]}`

    가중치는 표본이 아니라 **모집단** 비중이다. 이게 없으면 3건짜리 R-013 이
    474건짜리 R-001 과 동등하게 전체를 흔든다.

    유한모집단 보정(FPC)을 넣는 이유: 18건 중 15건을 뽑는 층이 실제로 있다.
    보정 없이는 거의 전수 조사한 층의 불확실성이 무한 모집단인 양 과대평가되고,
    전수 조사한 층조차 신뢰구간을 갖게 된다.
    """
    control = strata.get(CONTROL_STRATUM)
    real = {k: v for k, v in strata.items() if k != CONTROL_STRATUM}

    per: Dict[Tuple[str, str], Precision] = {
        k: stratum_precision(list(v.get("verdicts", []))) for k, v in real.items()
    }
    total_N = sum(int(v.get("N", 0)) for v in real.values())
    if total_N == 0:
        return Aggregate(None, 0.0, 1.0, 0.0, 0.0, 1.0, 0, 0, 0, 0.0, [])

    decided_N = 0
    num = var = 0.0
    low = high = 0.0
    undecided: List[Tuple[str, str]] = []

    for key, v in real.items():
        N_h = int(v.get("N", 0))
        p = per[key]
        w = N_h / total_N
        # 모름 구간은 모든 층에서 성립한다 (판정 불가 층은 [0,1] 전체를 기여).
        low += w * p.low
        high += w * (p.high if p.n else 1.0)

        if p.point is None:
            undecided.append(key)
            continue
        decided_N += N_h
        num += N_h * p.point
        # 층화 표본 분산 + FPC. n_h == N_h 이면 보정이 0 → 불확실성 없음.
        n_h = p.decided
        if n_h > 1 and N_h > 1:
            fpc = max(0.0, (N_h - n_h) / (N_h - 1))
            var += (w ** 2) * (p.point * (1 - p.point) / n_h) * fpc

    point = (num / decided_N) if decided_N else None
    # 분산은 '판정된 모집단' 기준으로 계산됐으므로 그 비중으로 되돌린다.
    scale = (total_N / decided_N) if decided_N else 1.0
    half = _Z95 * math.sqrt(var) * scale if point is not None else 0.0

    c_rate = c_n = None
    if control:
        cv = list(control.get("verdicts", []))
        c_n = len(cv)
        c_rate = (sum(1 for v in cv if v is Verdict.TRUE) / c_n) if c_n else None

    return Aggregate(
        point=point,
        ci_low=max(0.0, (point - half)) if point is not None else 0.0,
        ci_high=min(1.0, (point + half)) if point is not None else 1.0,
        half_width=half,
        low=low,
        high=high,
        sampled=sum(p.n for p in per.values()),
        unknown=sum(p.unknown for p in per.values()),
        population=total_N,
        covered_share=decided_N / total_N,
        undecided_strata=sorted(undecided),
        per_stratum=per,
        control_flagged_rate=c_rate,
        control_n=c_n or 0,
    )


# ── 판정자 프롬프트 ──────────────────────────────────────

_AUDIT_HEADER = """\
당신은 코드 감사자다. 아래에 **하나의 주장**이 있다: 특정 파일의 특정 행이
특정 규칙을 위반한다는 주장. 당신의 일은 그 주장이 **이 코드에서 실제로
성립하는지** 판정하는 것이다.

주의: 주장이 제시됐다는 사실은 그것이 참이라는 증거가 아니다. 규칙에 해당하지
않는 코드에 규칙이 잘못 붙은 경우가 흔하며, 그것을 잡아내는 것이 당신의 일이다.
코드가 규칙이 말하는 상황에 해당하지 않으면 주저 없이 "틀렸다"를 낸다.

판정 3종 중 하나를 고른다:
  맞다    — 이 행은 규칙이 말하는 결함에 실제로 해당한다
  틀렸다  — 해당하지 않는다 (규칙 오적용, 문맥상 정당한 코드, 대상이 아님)
  모름    — 주변 문맥만으로는 판단할 수 없다

**모름을 고르는 것은 실패가 아니다.** 확신 없이 맞다/틀렸다를 고르는 것이 실패다.

근거로 **주어진 코드에서 실제로 보이는 문자열**을 인용한다. 인용할 수 없으면
모름이다.

출력은 JSON 객체 하나:
  {"verdict": "맞다|틀렸다|모름", "evidence": "코드에서 인용", "why": "한 문장"}
설명 문장을 덧붙이지 않는다.
"""


def build_audit_prompt(item: Mapping[str, Any], context: str) -> str:
    """한 건의 판정 프롬프트.

    두 가지를 **의도적으로 뺀다**:

    - `item["message"]` — 리뷰어의 설명. 주면 판정자가 그 문장의 그럴듯함을
      평가하게 되고, 그건 채점이지 독립 판정이 아니다 (사상 ⑨).
    - `Rule.incident` — 규칙을 낳은 실제 사고에는 **정답(파일·행)이 적혀 있다**.
      리뷰어에게 주지 않은 것을 판정자에게 주면 같은 규율을 우리가 어긴다 (R-006).

    `item["is_control"]` 도 프롬프트에 나타나지 않는다 — 대조군임이 드러나면
    자기 감사가 무의미해진다.
    """
    rule = next((r for r in RULES if r.id == str(item.get("rule_id"))), None)
    title = rule.title if rule else "(알 수 없는 규칙)"
    hint = rule.detect_hint if rule else ""
    return (
        f"{_AUDIT_HEADER}\n"
        f"[규칙] {item.get('rule_id')} — {title}\n"
        f"판정 지침: {hint}\n\n"
        f"[주장] {item.get('path')} 의 {item.get('line')}행이 위 규칙을 위반한다.\n"
        f"지목된 코드: {item.get('excerpt')}\n\n"
        f"[주변 코드]\n{context}\n"
    )


_LABELS = {
    "맞다": Verdict.TRUE,
    "틀렸다": Verdict.FALSE,
    "모름": Verdict.UNKNOWN,
}


def parse_verdict(raw: Any) -> Tuple[Verdict, str]:
    """판정 응답 → (Verdict, 사유). 해석할 수 없으면 **모름**이다.

    모르는 라벨을 맞다/틀렸다 중 하나에 배정하면 파싱 실패가 판정으로 둔갑한다.
    근거 없는 '맞다'도 모름으로 강등한다 — 증거 결착이 리뷰어에게 적용되는데
    판정자에게만 면제될 이유가 없다 (사상 ②·⑨).
    """
    text = str(getattr(raw, "content", raw) or "")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return Verdict.UNKNOWN, "JSON 없음"
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return Verdict.UNKNOWN, "JSON 파싱 실패"
    if not isinstance(obj, dict):
        return Verdict.UNKNOWN, "객체가 아님"

    label = str(obj.get("verdict", "")).strip()
    verdict = _LABELS.get(label)
    if verdict is None:
        return Verdict.UNKNOWN, f"알 수 없는 판정 라벨: {label!r}"
    if verdict is not Verdict.UNKNOWN and not str(obj.get("evidence", "")).strip():
        return Verdict.UNKNOWN, "근거 인용 없음 — 판정을 강등한다"
    return verdict, str(obj.get("why", "")).strip()
