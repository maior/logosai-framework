"""리뷰 규칙의 **메커니즘** — 계약 · 증거 강제 · 규칙셋 (2026-08-21, 분리 2026-08-23).

이 모듈에는 규칙이 없다. 규칙을 **만들 수 있는 조건**만 있다.
Logos 가 실제로 쓰는 13개는 `rules_logos.py` 에 있고, 그것은 이 메커니즘의
한 인스턴스일 뿐이다 — 다른 조직은 자기 사고로 자기 규칙셋을 만든다.

왜 범용 린터로 충분하지 않은가
──────────────────────────
ruff/mypy 가 아는 것은 파이썬 문법이다. 이 계층이 겨냥하는 것은 **실행은
성공하는데 결과가 틀린** 부류다. "200 OK 를 성공으로 읽어 메트릭을 3일 잃었다"
같은 것을 아는 린터는 없다.

규율은 개수 상한이 아니라 **증거 상한**이다
──────────────────────────────────────
규칙 수를 제한하면 정작 필요한 규칙이 빠지고, 제한하지 않으면 취향 목록이 되어
소음을 낳는다. 그래서 대신 모든 규칙에 `incident`(실제 사고)와 적용 범위를
강제한다. **근거를 댈 수 없는 규칙은 생성 자체가 실패한다.**

2026-08-23 까지 이 강제는 문서에만 있었다 — 내장 튜플을 훑는 테스트 하나가
전부였고 `Rule()` 은 빈 incident 로도 만들어졌다. 즉 게이트가 우리 경로에만
있고 외부 채택자의 경로에는 없었다. `__post_init__` 로 옮긴 이유가 그것이다.

`not_covered_by` 는 ruff/mypy 와의 중복을 막는다. 이미 잡히는 것을 또 보고하면
리뷰어는 소음이 되고, 소음은 무시를 낳는다.

이 모듈은 표준 라이브러리만 쓴다.
"""

from dataclasses import dataclass
from typing import Iterator, Optional, Sequence, Tuple

#: 심각도 어휘. 규칙이 먼저 갖고 발견이 물려받으므로 아래 층인 여기가 정본이다
#: (`finding.py` 가 이 이름을 재수입한다 — 정의가 둘이면 곧 갈린다).
SEVERITIES: Tuple[str, ...] = ("blocker", "major", "minor")

#: 비어 있으면 규칙을 만들 수 없는 필드. 증거 상한이 규율이라는 말의 실체.
_REQUIRED_EVIDENCE: Tuple[str, ...] = ("incident", "applies_when", "excludes")


@dataclass(frozen=True)
class Rule:
    """하나의 리뷰 규칙.

    `incident` 는 **사람이 규칙의 정당성을 감사하는 필드**이지 모델 입력이
    아니다 — 거기에는 정답(파일·행)이 적혀 있어 주면 발견이 아니라 받아적기가
    된다. 프롬프트 구성기가 이 경계를 지킨다 (`prompt.py`, `audit.py`).
    """

    id: str
    title: str
    severity: str      # blocker | major | minor
    incident: str      # 이 규칙을 낳은 실제 사고 — 비어 있으면 생성 불가
    detect_hint: str   # 리뷰어 프롬프트에 실리는 판정 지침
    applies_when: str  # **선행 조건** — 무엇이 참이어야 이 규칙이 적용되는가
    excludes: str      # 제외 조항 — 감사에서 실제로 관측된 오탐 형태
    not_covered_by: str  # ruff/mypy 가 못 잡는 이유

    def __post_init__(self) -> None:
        if not (self.id or "").strip():
            raise ValueError("Rule.id 가 비어 있다")
        for field in _REQUIRED_EVIDENCE:
            if not (getattr(self, field) or "").strip():
                raise ValueError(
                    f"{self.id}: {field} 가 비어 있다 — 근거를 댈 수 없는 규칙은 등록할 수 없다"
                )
        if self.severity not in SEVERITIES:
            raise ValueError(f"{self.id}: severity {self.severity!r} 는 {SEVERITIES} 중 하나여야 한다")


class RuleSet:
    """한 조직이 실제로 쓰는 규칙 목록.

    전역 레지스트리를 두지 않는 이유: 프로세스 전역 가변 상태는 R-013 이 기록한
    사고와 같은 부류다(import 시점 env 설정이 다른 파일의 테스트를 조용히 죽였고,
    단독 실행은 통과해 오래 안 보였다). 대신 소비자에게 **주입**한다.
    """

    __slots__ = ("_rules", "_by_id")

    def __init__(self, rules: Sequence[Rule]) -> None:
        self._rules: Tuple[Rule, ...] = tuple(rules)
        by_id = {}
        for rule in self._rules:
            if rule.id in by_id:
                raise ValueError(f"중복된 규칙 id: {rule.id}")
            by_id[rule.id] = rule
        self._by_id = by_id

    @classmethod
    def of(cls, *rules: Rule) -> "RuleSet":
        """규칙을 나열해 규칙셋을 만든다. 이것이 '등록'이다."""
        return cls(rules)

    @property
    def rules(self) -> Tuple[Rule, ...]:
        return self._rules

    @property
    def ids(self) -> Tuple[str, ...]:
        return tuple(r.id for r in self._rules)

    def get(self, rule_id: str) -> Optional[Rule]:
        """규칙을 찾는다. 없으면 None — 모르는 것을 지어내지 않는다."""
        return self._by_id.get(rule_id)

    def subset(self, rule_ids: Sequence[str]) -> "RuleSet":
        """일부만 남긴다 — 측정상 정밀도를 올린 유일한 지렛대가 솎기였다.

        모르는 id 는 거절한다. 오타 하나에 조용히 0개가 되면 "규칙을 좁혔다"와
        "규칙이 사라졌다"를 구분할 수 없다 (모름 ≠ 없음).
        """
        unknown = [i for i in rule_ids if i not in self._by_id]
        if unknown:
            raise ValueError(f"모르는 규칙 id: {unknown}")
        wanted = set(rule_ids)
        return RuleSet([r for r in self._rules if r.id in wanted])

    def __iter__(self) -> Iterator[Rule]:
        return iter(self._rules)

    def __len__(self) -> int:
        return len(self._rules)

    def __repr__(self) -> str:  # pragma: no cover - 진단용
        return f"RuleSet({len(self._rules)} rules: {', '.join(self.ids)})"


def get_rule(rule_id: str) -> Optional[Rule]:
    """기본 규칙셋(Logos 참조 인스턴스)에서 찾는다. 없으면 None.

    다른 규칙셋을 쓴다면 `RuleSet.get()` 을 직접 부른다.
    """
    from .rules_logos import DEFAULT_RULES

    return DEFAULT_RULES.get(rule_id)


def __getattr__(name: str):
    """`RULES` 하위호환 — 기존 코드가 `from .rules import RULES` 를 쓴다.

    모듈 상수로 두면 `rules_logos` 를 import 하게 되어 메커니즘이 인스턴스에
    의존한다. 지연 조회로 그 방향을 뒤집지 않는다.
    """
    if name == "RULES":
        from .rules_logos import DEFAULT_RULES

        return DEFAULT_RULES.rules
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
