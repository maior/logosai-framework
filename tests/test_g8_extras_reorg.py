"""Phase 2 — G8 extras 재구성 테스트 (2026-07-07).

표준 준비도 진단 G8: 경량 코어 + 필요 기능만 opt-in. 실사 결과 agentic·
monitoring 은 이미 core(aiohttp/requests)로 동작(추가 의존성 없음)이 강점.
유일한 실질 optional 은 llm(providers)·desktop·메모리 임베딩(google-genai).
계약:
  - core dependencies 는 경량 유지(LLM/langchain/desktop deps 누출 금지).
  - llm extra 는 native SDK(openai/anthropic/google-genai)만 — langchain 없음
    (lean 기본 + G6 hang 위험 격리).
  - langchain extra 가 별도 존재(레거시 프로바이더 opt-in, 잃지 않음).
  - desktop extra 는 pyautogui.
  - agentic extra 는 google-genai(메모리 임베딩).
  - all 은 추천 기능(llm+desktop) 포함, langchain(레거시)은 미포함(opt-in).

직접 실행: python logosai/tests/test_g8_extras_reorg.py
"""
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    fails = []

    def t(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # py<3.11

    with open(os.path.join(_PKG, "pyproject.toml"), "rb") as f:
        pp = tomllib.load(f)

    core = pp["project"]["dependencies"]
    extras = pp["project"]["optional-dependencies"]

    def joined(key):
        return " ".join(extras.get(key, []))

    # ── core 경량 (LLM/langchain/desktop 누출 금지) ──
    core_str = " ".join(core)
    t("G8-1 core 에 LLM/langchain/desktop deps 없음",
      not any(x in core_str for x in ["openai", "anthropic", "langchain", "google-genai", "pyautogui"]))

    # ── llm 은 native SDK 만, langchain 없음 ──
    llm = joined("llm")
    t("G8-2 llm extra 에 native SDK 포함(openai/anthropic/google-genai)",
      "openai" in llm and "anthropic" in llm and "google-genai" in llm)
    t("G8-3 llm extra 에 langchain 없음(lean 기본)", "langchain" not in llm)

    # ── langchain 별도 extra (레거시 opt-in, 잃지 않음) ──
    lc = joined("langchain")
    t("G8-4 langchain extra 존재 + langchain 패키지 포함",
      "langchain" in lc and "langchain-openai" in lc)

    # ── desktop / agentic ──
    t("G8-5 desktop extra 에 pyautogui", "pyautogui" in joined("desktop"))
    t("G8-6 agentic extra 에 google-genai(메모리 임베딩)", "google-genai" in joined("agentic"))

    # ── monitoring extra 존재(경량 문서화 — 빈 리스트 허용) ──
    t("G8-7 monitoring extra 선언됨(경량, 추가 의존성 없음)", "monitoring" in extras)

    # ── all: 추천 기능(llm+desktop) 포함, langchain 레거시 미포함 ──
    allx = joined("all")
    t("G8-8 all 에 llm·desktop 포함", "logosai[llm]" in allx and "logosai[desktop]" in allx)
    t("G8-9 all 에 langchain(레거시) 미포함(opt-in 전용)", "langchain" not in allx)

    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
