"""리뷰어 프롬프트 구성 (2026-08-21).

한 가지만 기억하면 된다: **`incident` 는 절대 프롬프트에 넣지 않는다.**

레지스트리의 incident 필드에는 "forge_generated_387dc0b3.py:76 이 non-functional
placeholder 라고 써 놓고도 등록되어 라이브였다" 처럼 **정답이 적혀 있다**. 이걸
모델에 주고 그 파일을 리뷰시키면 발견이 아니라 받아적기가 되고, 다른 파일에서는
같은 문장을 환각할 근거가 된다.

R-006 이 정확히 그 사고에서 나온 규칙이다 — 스모크 테스트의 expected:'' 가 LLM 에
플레이스홀더를 학습시켰던 일. 리뷰어가 자기 규칙을 어기면 이 도구는 신뢰를 잃는다.

incident 는 **사람이 규칙의 정당성을 감사하는 필드**이지 모델 입력이 아니다.
test_review_prompt.py 가 이 경계를 강제한다.
"""

from typing import Optional, Sequence

from .rules import RULES

_HEADER = """\
당신은 이 코드베이스의 에이전트 코드를 검토한다. 목적은 문법 오류 찾기가 아니다 —
ruff·mypy 가 이미 그 일을 한다. 당신은 **실행은 성공하는데 결과가 틀린** 종류의
결함, 즉 도구가 볼 수 없고 사람이 읽어야 보이는 것을 찾는다.

아래 규칙 목록에 있는 것만 보고한다. 목록에 없는 문제를 발견해도 보고하지 않는다
(레지스트리 밖 rule_id 는 버려진다).

각 발견마다 반드시 다음을 낸다:
  rule_id   목록의 id (예: R-001)
  severity  blocker | major | minor
  line      결함이 있는 행 번호
  excerpt   **그 행에 실제로 있는 문자열을 그대로** 옮긴 것
  message   왜 결함인지 한 문장

excerpt 가 실제 소스와 대조되지 않으면 그 발견은 버려진다. 기억으로 쓰지 말고 보이는 대로 옮긴다. 확신이 없으면 보고하지
않는다 — 놓치는 것보다 지어내는 것이 훨씬 나쁘다.

결함이 없으면 빈 목록을 낸다. 억지로 채우지 않는다.

출력은 JSON 배열 하나. 설명 문장을 덧붙이지 않는다.
"""

_RULE_LINE = "  {id}  [{severity}] {title}\n        판정: {hint}\n"


def build_review_prompt(rule_ids: Optional[Sequence[str]] = None) -> str:
    """리뷰어 시스템 프롬프트를 만든다.

    Args:
        rule_ids: 사용할 규칙 id. None 이면 전부.
                  Phase 0 census 이후 값 없는 규칙을 솎아낼 때 쓴다.

    incident 필드는 의도적으로 제외한다 — 모듈 docstring 참조.
    """
    wanted = list(rule_ids) if rule_ids else None
    lines = [_HEADER, "\n[규칙]\n"]
    for rule in RULES:
        if wanted is not None and rule.id not in wanted:
            continue
        lines.append(
            _RULE_LINE.format(
                id=rule.id,
                severity=rule.severity,
                title=rule.title,
                hint=rule.detect_hint,
            )
        )
    return "".join(lines)
