"""리뷰 규칙 레지스트리 — 이 코드베이스의 헌법 (2026-08-21).

왜 범용 린터로 충분하지 않은가
──────────────────────────
ruff/mypy 가 아는 것은 파이썬 문법이다. 아래 규칙들은 **이 시스템이 실제로 겪은
사고**에서 나왔다. "200 OK 를 성공으로 읽어 메트릭을 3일 잃었다" 같은 것을 아는
린터는 없다.

규율은 개수 상한이 아니라 **증거 상한**이다
──────────────────────────────────────
규칙 수를 제한하면 정작 필요한 규칙이 빠지고, 제한하지 않으면 취향 목록이 되어
소음을 낳는다. 그래서 대신 모든 규칙에 `incident`(실제 사고)를 강제한다. 근거를
댈 수 없는 규칙은 등록할 수 없다. 이 규율은 test_every_rule_cites_a_real_incident
가 강제한다.

`not_covered_by` 는 ruff/mypy 와의 중복을 막는다. 이미 잡히는 것을 또 보고하면
리뷰어는 소음이 되고, 소음은 무시를 낳는다.

어느 규칙이 실제로 값진지는 Phase 0 census 가 알려준다 — 손으로 쓴 에이전트
101개에서 대량 발화하는 규칙은 규칙 쪽이 틀린 것이므로 그때 솎아낸다.
"""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    severity: str      # blocker | major | minor
    incident: str      # 이 규칙을 낳은 실제 사고 — 비어 있으면 등록 불가
    detect_hint: str   # 리뷰어 프롬프트에 실리는 판정 지침
    applies_when: str  # **선행 조건** — 무엇이 참이어야 이 규칙이 적용되는가
    excludes: str      # 제외 조항 — 감사에서 실제로 관측된 오탐 형태
    not_covered_by: str  # ruff/mypy 가 못 잡는 이유


RULES: Tuple[Rule, ...] = (
    Rule(
        id="R-001",
        title="껍데기 금지 — 동작하지 않는 구현을 동작하는 것처럼 등록하지 않는다",
        severity="blocker",
        incident=(
            "forge_generated_387dc0b3.py:76 이 자기 코드에 'A very basic, non-functional "
            "placeholder to demonstrate structure' 라고 써 놓고도 등록되어 라이브였다. "
            "예외 없이 문자열을 반환하므로 성공률 100%, shadow test 통과, 회로 미개방."
        ),
        detect_hint=(
            "구현부가 placeholder/simulated/non-functional/예시 임을 스스로 밝히거나, "
            "입력을 가공하지 않고 접두사만 붙여 되돌려주는 경우."
        ),
        applies_when='그 행이 에이전트의 **실제 구현부**(함수·메서드 본문) 안에 있고, 그 결과가 반환되거나 다음 단계 입력이 된다.',
        excludes='데이터 값·설정 리터럴, 문법상 필요한 단독 `pass`, 자연어 요청/주석 문자열은 대상이 아니다. 미구현을 예외로 알리는 코드와 추상 메서드도 호출자를 속이지 않으므로 제외한다.',
        not_covered_by="문법·타입 모두 정상이라 린터·타입체커가 볼 수 있는 신호가 없다.",
    ),
    Rule(
        id="R-002",
        title="침묵 실패 금지 — 예외를 로그 없이 삼키지 않는다",
        severity="major",
        incident=(
            "생성물 74개에 except Exception 318곳, 그중 41곳이 pass 로 통과. "
            "별개로 silent fallback 이 capabilities type 불일치를 ERROR 없이 가려 "
            "원인 추적에 시간을 소모한 사고가 있었다."
        ),
        detect_hint="except 절이 로그·재전파·상태반환 없이 통과하거나 하드코딩 기본값으로 대체하는 경우.",
        applies_when='예외를 잡는 `except` 절이 실제로 존재한다.',
        excludes='로그를 남기고 **실패 상태를 반환**하는 except(에러 응답·False·None 반환 포함)는 침묵이 아니므로 제외한다. 대상은 아무것도 남기지 않는 `pass`/빈 본문, 또는 실패를 성공으로 보고하는 경우다.',
        not_covered_by="ruff 의 BLE001 은 광범위 포착만 지적하고 '로그 없이 통과'는 구분하지 못한다.",
    ),
    Rule(
        id="R-003",
        title="하드코딩 라우팅 금지 — 키워드 분기로 의도·에이전트를 결정하지 않는다",
        severity="major",
        incident=(
            "CLAUDE.md 핵심 원칙. 키워드 분기는 표현이 조금만 달라져도 빗나가고, "
            "열거 목록은 굴절형·번역쌍에서 세 번 같은 방식으로 뚫렸다."
        ),
        detect_hint="if any(word in query for word in [...]) 류로 분기해 에이전트/의도/액션을 정하는 경우.",
        applies_when='그 분기가 **어느 에이전트·의도가 요청을 처리할지**를 결정한다.',
        excludes='이미 결정된 요청의 파라미터(테마·단위·표시형식 등)를 고르는 분기, 열거형 값 비교, 조건을 담지 않은 `else:` 는 대상이 아니다.',
        not_covered_by="정상적인 파이썬이며, 같은 구문이 정당한 곳(설정 파싱 등)도 있어 정적 규칙으로 못 나눈다.",
    ),
    Rule(
        id="R-004",
        title="description 과대광고 금지 — 선언한 능력과 구현이 일치해야 한다",
        severity="major",
        incident=(
            "description 이 라우팅을 결정하는데 과대광고 desc 가 진짜 능력자를 밀어냈다. "
            "FORGE 자동등록이 desc 를 오염시킨 사고도 별도로 있었다."
        ),
        detect_hint="클래스 docstring/description 이 코드에 없는 능력을 주장하는 경우.",
        applies_when='그 텍스트가 **능력을 선언하는 자리**다 — 클래스 docstring, 에이전트 description, 레지스트리 항목.',
        excludes='구현 코드의 조건문, 기능 이름 문자열, 실제 구현과 일치하는 설명은 대상이 아니다.',
        not_covered_by="문서와 구현의 의미 대조라 정적 분석의 사정거리 밖이다.",
    ),
    Rule(
        id="R-005",
        title="process() 반환 계약 — 표준 dict 형태를 지킨다",
        severity="blocker",
        incident="AGENT_TEMPLATE_DICT_CONTRACT_FIX — 생성 템플릿의 dict 계약 위반이 파이프라인을 깼다.",
        detect_hint="process() 가 dict 아닌 값을 반환하거나 success/response 키를 빠뜨리는 경로가 있는 경우.",
        applies_when='그 행이 **`process()` 의 반환 지점**이다.',
        excludes='`process()` 가 아닌 내부 헬퍼의 반환, 반환문이 아닌 생성자 인자·`else:` 같은 중간 행은 대상이 아니다.',
        not_covered_by="반환 타입 힌트가 없거나 Any 여서 mypy 가 판정하지 못한다.",
    ),
    Rule(
        id="R-006",
        title="검증 신호 누설 금지 — 테스트용 값이 생성 지시로 새지 않는다",
        severity="major",
        incident="스모크 테스트의 expected:'' 가 LLM 에 플레이스홀더를 학습시켰다. synthetic 표시로 분리했다.",
        detect_hint="테스트/검증용 빈 기대값·더미 값이 프롬프트나 생성 입력에 그대로 실리는 경우.",
        applies_when='테스트·검증용 값이 **프롬프트나 생성 입력으로 실제로 전달**된다.',
        excludes='테스트 케이스 정의 그 자체, 시각화·표시용 데이터 생성, 에이전트의 기본 결과 값은 대상이 아니다. 값이 생성 지시에 닿는 경로가 보여야 한다.',
        not_covered_by="데이터 흐름을 따라가야 보이는 결함이라 단일 파일 정적 검사로 안 잡힌다.",
    ),
    Rule(
        id="R-007",
        title="200 OK ≠ 성공 — 전송 결과를 확인한다",
        severity="major",
        incident=(
            "fire-and-forget 이 상태 코드를 안 봐서 llm_calls 의 422 거부가 3주간 성공으로 집계됐고, "
            "메트릭이 3일간 흔적 없이 유실됐다."
        ),
        detect_hint="HTTP 전송 후 status 를 확인하지 않거나, 내부 예외를 잡고 200/성공을 반환하는 경우.",
        applies_when='그 코드가 **HTTP 요청을 보내거나 응답을 받는다**.',
        excludes='로컬 명령 실행(`subprocess`)·파일 IO 등 HTTP 가 아닌 전송은 대상이 아니다. 인접 행에서 `status` 를 확인하거나 비-200 을 처리하면 제외한다.',
        not_covered_by="정상 코드이며, 예외를 전파하지 않는 것이 의도인 경우도 있어 문맥 판단이 필요하다.",
    ),
    Rule(
        id="R-008",
        title="모름 ≠ 0 — 확인 못 한 것을 정상·0으로 기본값 주지 않는다",
        severity="major",
        incident="미분류 span 을 agent 로 기본값 주자 계측 공백이 '에이전트 실행'으로 위장했다. unknown 버킷으로 분리했다.",
        detect_hint="읽기 실패·미확인 상태를 0/ok/정상으로 대체해 호출자가 구분할 수 없게 만드는 경우.",
        applies_when='그 값이 **확인에 실패했거나 확인하지 않은** 상태에서 나온다.',
        excludes='성공/실패가 명확히 판정된 결과의 대입, NaN 처럼 모름이 보존되는 값, 정의된 비율로 계산한 값은 대상이 아니다.',
        not_covered_by="타입은 맞고 값만 거짓이라 정적으로는 보이지 않는다.",
    ),
    Rule(
        id="R-009",
        title="열거 목록 하드코딩 주의 — 굴절형·번역쌍에서 샌다",
        severity="minor",
        incident="열거 목록 판정이 굴절형·번역쌍에서 세 번 뚫렸다. 목록을 늘리는 대신 판정 전 정규화로 고쳤다.",
        detect_hint="한국어/영어 표현을 리터럴 목록으로 열거해 분기하고, 정규화 단계가 없는 경우.",
        applies_when='**둘 이상의** 표현을 리터럴로 열거해 분기한다.',
        excludes='단일 문자열 리터럴, 접미사 하나 확인, 정규식 패턴 내부의 고정 단위 문자열은 열거 목록이 아니므로 제외한다.',
        not_covered_by="R-003 과 달리 라우팅이 아닌 곳에서도 나타나며, 문자열 리터럴 자체는 합법이다.",
    ),
    Rule(
        id="R-010",
        title="LLM 출력 형태는 소비하는 쪽에서 정규화한다",
        severity="major",
        incident="문자열 배열로 지시해도 객체 배열이 돌아온다. 프롬프트로 고치려다 실패했고 소비자 정규화로 해결했다.",
        detect_hint="LLM 응답의 형태를 검증·정규화 없이 인덱싱하거나 속성 접근하는 경우.",
        applies_when='인덱싱·속성 접근의 대상이 **LLM 응답에서 온 값**이다.',
        excludes='LLM 과 무관한 자료구조(그래프 설정·내부 dict 등)는 대상이 아니다. 선행 `isinstance` 검사 안이거나 기본값을 주는 `.get(k, default)` 접근은 제외한다.',
        not_covered_by="런타임 형태 문제라 정적 타입으로 표현되지 않는다.",
    ),
    Rule(
        id="R-011",
        title="자원·span 종료를 분기마다 손으로 부르지 않는다",
        severity="minor",
        incident="분기별 end() 호출이 4곳에서 누락돼 '계보는 완벽한데 ROOT 행만 없는' trace 가 생겼다.",
        detect_hint="early return/except 경로에서 start 한 span·자원을 닫지 않는 경우.",
        applies_when='그 경로가 **span·자원을 실제로 start/open 했다**.',
        excludes='자원을 열지 않는 코드(`pass`, 키 입력, 앱 활성화 등)는 대상이 아니다. 컨텍스트매니저로 감싼 경우도 제외한다.',
        not_covered_by="ruff 는 컨텍스트매니저 미사용을 결함으로 보지 않는다.",
    ),
    Rule(
        id="R-012",
        title="테스트가 프로덕션 이름으로 관측을 오염시키지 않는다",
        severity="major",
        incident="테스트가 프로덕션 span 이름으로 25건을 실제 DB 에 넣어 'ingress 유실'로 오독됐고 하루를 썼다.",
        detect_hint="테스트·프로브 코드가 프로덕션과 같은 이름으로 메트릭·span 을 전송하는 경우.",
        applies_when='테스트·프로브 코드가 **메트릭이나 span 을 전송한다**.',
        excludes='전송하지 않는 테스트, `test.`/`probe.` 접두를 쓰는 전송은 대상이 아니다.',
        not_covered_by="테스트 코드도 정상 코드라 린터가 볼 이유가 없다.",
    ),
    Rule(
        id="R-013",
        title="테스트에서 os.environ 을 직접 세우지 않는다",
        severity="minor",
        incident="import 시점에 env 를 세운 파일 3개가 다른 파일의 테스트 8건을 조용히 죽였다. 단독 실행은 통과해 오래 안 보였다.",
        detect_hint="테스트 파일이 monkeypatch 없이 os.environ 에 대입하는 경우.",
        applies_when='**테스트 파일**이 `os.environ` 에 **값을 대입**한다.',
        excludes='테스트가 아닌 스크립트·프로덕션 코드, 그리고 읽기(`os.getenv`/`os.environ.get`)는 대상이 아니다. `monkeypatch` 사용도 제외한다.',
        not_covered_by="프로세스 전역 부작용이라 파일 단위 정적 분석으로는 영향이 안 보인다.",
    ),
)

_BY_ID = {r.id: r for r in RULES}


def get_rule(rule_id: str) -> Optional[Rule]:
    """규칙을 찾는다. 없으면 None — 모르는 것을 지어내지 않는다."""
    return _BY_ID.get(rule_id)
