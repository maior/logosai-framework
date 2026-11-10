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

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가 0건을 수집했다.
  - 직접 실행: python tests/test_g8_extras_reorg.py  → 마지막 줄 `RESULT: GREEN`
"""
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from _script_runner import run_tests  # noqa: E402


def _pyproject():
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # py<3.11

    with open(os.path.join(_PKG, "pyproject.toml"), "rb") as f:
        return tomllib.load(f)


def _core():
    return " ".join(_pyproject()["project"]["dependencies"])


def _extras():
    return _pyproject()["project"]["optional-dependencies"]


def _joined(key):
    return " ".join(_extras().get(key, []))


def test_g8_1_core_has_no_llm_langchain_desktop_deps():
    """G8-1 core 에 LLM/langchain/desktop deps 없음"""
    core_str = _core()
    # 대조군: core 목록을 실제로 읽었다 (빈 문자열이면 아래 검사는 공허하게 참).
    assert "aiohttp" in core_str
    leaked = [x for x in ["openai", "anthropic", "langchain", "google-genai", "pyautogui"]
              if x in core_str]
    assert not leaked, f"core 로 샌 의존성: {leaked}"


def test_g8_2_llm_extra_has_native_sdks():
    """G8-2 llm extra 에 native SDK 포함(openai/anthropic/google-genai)"""
    llm = _joined("llm")
    assert "openai" in llm
    assert "anthropic" in llm
    assert "google-genai" in llm


def test_g8_3_llm_extra_has_no_langchain():
    """G8-3 llm extra 에 langchain 없음(lean 기본)"""
    llm = _joined("llm")
    assert "openai" in llm      # 대조군: llm extra 가 비어 있지 않다
    assert "langchain" not in llm


def test_g8_4_langchain_extra_exists_separately():
    """G8-4 langchain extra 존재 + langchain 패키지 포함"""
    lc = _joined("langchain")
    assert "langchain" in lc
    assert "langchain-openai" in lc


def test_g8_5_desktop_extra_has_pyautogui():
    """G8-5 desktop extra 에 pyautogui"""
    assert "pyautogui" in _joined("desktop")


def test_g8_6_agentic_extra_has_google_genai():
    """G8-6 agentic extra 에 google-genai(메모리 임베딩)"""
    assert "google-genai" in _joined("agentic")


def test_g8_7_monitoring_extra_declared():
    """G8-7 monitoring extra 선언됨(경량, 추가 의존성 없음)"""
    # 빈 리스트 허용 — 선언만 본다.
    assert "monitoring" in _extras()


def test_g8_8_all_includes_llm_and_desktop():
    """G8-8 all 에 llm·desktop 포함"""
    allx = _joined("all")
    assert "logosai[llm]" in allx
    assert "logosai[desktop]" in allx


def test_g8_9_all_excludes_legacy_langchain():
    """G8-9 all 에 langchain(레거시) 미포함(opt-in 전용)"""
    allx = _joined("all")
    assert "logosai[llm]" in allx       # 대조군: all 이 비어 있지 않다
    assert "langchain" not in allx


def main():
    return run_tests(globals())


if __name__ == "__main__":
    sys.exit(main())
