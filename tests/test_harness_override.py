"""하네스 에이전트별 재정의 훅 (2026-08-03).

왜 필요한가 — 30일 실측에서 한도에 근접한 상위 4개가 전부 데스크톱·문서 계열이다
(desktop_agent 101.8s = 한도의 84.8%, docx_generator 94.0s, file_agent 81.7s).
PowerPoint 를 몰고 Word 를 만드는 일은 **본성상 느리다.** 반면 calculator 는 1초에
끝나면서 같은 120초를 배정받는다. 성격이 다른 121개가 한 개의 전역 한도를 공유하는
것이 문제였고, 그래서 **에이전트별 재정의 계층**을 연다.

계약 (docs/tracks.md §1·§2 동결):

    agent._harness is False   → 미적용        (코드 opt-out 이 절대 우선)
    env LOGOSAI_HARNESS=off   → 미적용
    agent._harness 값          → 그 값         ← 코드가 왕
    ★ override resolver        → 그 값         ← 운영자 계층 (이번에 신설)
    env LOGOSAI_HARNESS_*     → 그 값
    기본값 120s / 25호출 / 200000토큰

`logosai` 는 저장소도 HTTP 도 모른다. 훅만 노출하고, 호스트(ACP)가 자기 저장소로
구현을 꽂는다 — 이 저장소의 확립된 "Judge ABC = 교체 이음새" 패턴과 같다.

⚠️ 이 훅은 **절대 실행을 막지 않는다.** resolver 가 죽으면 재정의만 없던 일이
되고 실행은 그대로 간다. 저장소 장애가 에이전트를 멈추면 안 된다.

직접 실행: python logosai/tests/test_harness_override.py
"""
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PKG)

# 관측 DB 에 테스트 흔적을 남기지 않는다 (이 저장소의 확립된 규칙).
# 2026-08-09: pytest 하에서는 세우지 않는다 — os.environ 은 프로세스 전역이라
# 되돌려지지 않고 남아, 전송 경로를 검증하는 다른 파일의 테스트를 조용히 죽인다.
# pytest 하에서는 pulse_client 가 스스로 막으므로 보호는 유지된다.
if "pytest" not in sys.modules:
    os.environ["LOGOS_PULSE_DISABLED"] = "1"


class _Agent:
    """최소 에이전트 — resolve_* 가 보는 것은 `_harness` 와 `id` 뿐이다."""

    def __init__(self, agent_id="test_agent", harness=None):
        self.id = agent_id
        if harness is not None:
            self._harness = harness


def _clean_env():
    for k in ("LOGOSAI_HARNESS", "LOGOSAI_HARNESS_TIMEOUT",
              "LOGOSAI_HARNESS_MAX_CALLS", "LOGOSAI_HARNESS_MAX_TOKENS"):
        os.environ.pop(k, None)


def main():
    from logosai.observability import (
        resolve_harness, resolve_harness_budget,
        set_harness_override_resolver, harness_agent_id,
    )

    fails = []

    def t(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # ── 1. 미등록 = 현재 동작 그대로 (회귀 0) ───────────────────
    _clean_env()
    set_harness_override_resolver(None)
    t("미등록이면 기본 120초", resolve_harness(_Agent()) == (True, 120.0))
    t("미등록이면 기본 예산 25/200000",
      resolve_harness_budget(_Agent()) == (25, 200000))

    # ── 2. 재정의가 env·기본값을 이긴다 ─────────────────────────
    set_harness_override_resolver(lambda aid: {"timeout_s": 300})
    t("재정의 300초가 기본값을 이김", resolve_harness(_Agent()) == (True, 300.0))

    os.environ["LOGOSAI_HARNESS_TIMEOUT"] = "60"
    t("재정의가 env(60) 를 이김", resolve_harness(_Agent()) == (True, 300.0))
    _clean_env()

    # ── 3. 코드가 왕 — _harness 가 재정의를 이긴다 ───────────────
    set_harness_override_resolver(lambda aid: {"timeout_s": 300})
    t("코드 _harness=90 이 재정의 300 을 이김",
      resolve_harness(_Agent(harness=90)) == (True, 90.0))
    t("코드 _harness dict 도 재정의를 이김",
      resolve_harness(_Agent(harness={"timeout_s": 45})) == (True, 45.0))

    # ── 4. opt-out 은 재정의로 뚫리지 않는다 ────────────────────
    # 재정의로 하네스를 되살릴 수 있으면 코드의 명시적 거부가 무의미해진다.
    t("_harness=False 는 재정의가 있어도 미적용",
      resolve_harness(_Agent(harness=False)) == (False, 0.0))

    os.environ["LOGOSAI_HARNESS"] = "off"
    t("env off 는 재정의가 있어도 미적용",
      resolve_harness(_Agent()) == (False, 0.0))
    _clean_env()

    # ── 5. resolver 가 죽어도 실행은 간다 (fail-open, 재정의만 무시) ──
    def _boom(aid):
        raise RuntimeError("저장소 장애")

    set_harness_override_resolver(_boom)
    t("resolver 예외 → 삼키고 기본값", resolve_harness(_Agent()) == (True, 120.0))
    t("resolver 예외 → 예산도 기본값",
      resolve_harness_budget(_Agent()) == (25, 200000))

    set_harness_override_resolver(lambda aid: None)
    t("resolver None → 기본값", resolve_harness(_Agent()) == (True, 120.0))

    # ── 6. 예산도 같은 우선순위 ─────────────────────────────────
    set_harness_override_resolver(
        lambda aid: {"max_llm_calls": 40, "max_tokens": 400000})
    t("재정의 예산 40/400000", resolve_harness_budget(_Agent()) == (40, 400000))

    os.environ["LOGOSAI_HARNESS_MAX_CALLS"] = "10"
    t("재정의 예산이 env(10) 를 이김",
      resolve_harness_budget(_Agent())[0] == 40)
    _clean_env()

    set_harness_override_resolver(lambda aid: {"max_llm_calls": 40})
    t("코드 _harness 예산이 재정의를 이김",
      resolve_harness_budget(_Agent(harness={"max_llm_calls": 5}))[0] == 5)

    # ── 7. 부분 재정의 — 준 것만 바뀐다 ─────────────────────────
    set_harness_override_resolver(lambda aid: {"timeout_s": 300})
    t("timeout 만 재정의하면 예산은 기본값",
      resolve_harness_budget(_Agent()) == (25, 200000))
    set_harness_override_resolver(lambda aid: {"max_tokens": 400000})
    t("예산만 재정의하면 timeout 은 기본값",
      resolve_harness(_Agent()) == (True, 120.0))

    # ── 8. 쓰레기 값은 무시하고 다음 단계로 ─────────────────────
    # 저장소가 오염돼도 실행 한도가 이상해지면 안 된다.
    for bad in ({"timeout_s": 0}, {"timeout_s": -5}, {"timeout_s": "삼백"},
                {"timeout_s": None}, {}, "문자열", 42, []):
        set_harness_override_resolver(lambda aid, b=bad: b)
        ok = resolve_harness(_Agent()) == (True, 120.0)
        t(f"쓰레기 재정의 {bad!r} 는 무시", ok)

    for bad in ({"max_llm_calls": 0}, {"max_llm_calls": -1},
                {"max_llm_calls": "다섯"}, {"max_tokens": None}):
        set_harness_override_resolver(lambda aid, b=bad: b)
        ok = resolve_harness_budget(_Agent()) == (25, 200000)
        t(f"쓰레기 예산 재정의 {bad!r} 는 무시", ok)

    # ── 9. resolver 가 받는 id = span 에 기록되는 id ────────────
    # 이게 어긋나면 운영자는 'desktop_agent' 에 재정의를 걸고, resolver 는
    # 'DesktopAgent' 를 찾다 못 찾는다. 조용히 안 먹는 가장 나쁜 실패다.
    seen = []
    set_harness_override_resolver(lambda aid: seen.append(aid) or None)

    resolve_harness(_Agent(agent_id="desktop_agent"))
    t("resolver 는 agent.id 를 받는다", seen and seen[-1] == "desktop_agent")

    class DesktopAgent:  # id 속성이 없는 경우
        pass

    a = DesktopAgent()
    resolve_harness(a)
    t("id 없으면 클래스명", seen[-1] == "DesktopAgent")
    t("resolver 가 받는 id == harness_agent_id() 결과",
      seen[-1] == harness_agent_id(a))

    # ── 10. 해제 가능 (테스트·운영 모두 필요) ───────────────────
    set_harness_override_resolver(None)
    t("해제하면 기본 동작 복귀", resolve_harness(_Agent()) == (True, 120.0))

    _clean_env()
    print()
    if fails:
        print(f"❌ {len(fails)} FAILED: {fails}")
        return 1
    print("✅ 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
