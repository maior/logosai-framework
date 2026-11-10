"""LLMClient 프로바이더 config-driven 테스트 (2026-07-07).

사용자 요구: "llm_client 는 설정에 따라 모두 사용할 수 있도록". 현재 모델은
config(~/.logosai/config.json / env)에서 오지만 프로바이더는 __init__ 의
리터럴 "google" 로 하드코딩돼 config.llm.provider 가 무시됐다. 계약:
  - 프로바이더 미지정 시 config/env(_get_default_provider)에서 결정.
  - 명시적 provider 인자는 config 를 이긴다(오버라이드).
  - 모델도 계속 config-driven(회귀 잠금).
  - env LOGOSAI_LLM_PROVIDER 로 전환 가능(온-프렘 대비).

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가 0건을 수집했다.
  - 직접 실행: python tests/test_llm_provider_config.py  → 마지막 줄 `RESULT: GREEN`

예전 `main()` 은 LOGOSAI_LLM_PROVIDER / LOGOSAI_LLM_MODEL 을 os.environ 에서
**지우고 되돌리지 않았다**. 이제 환경은 monkeypatch/ScriptPatch 로만 바꾸고,
끝나면 되돌린 뒤 llm_defaults 캐시를 다시 읽힌다(`_teardown`).
"""
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":      # 스크립트 모드에서만 — pytest 는 pyproject 의 pythonpath 를 쓴다
    sys.path.insert(0, _PKG)

from _script_runner import block_pulse, run_tests, use_fake_api_keys  # noqa: E402


def _defaults():
    from logosai.config import llm_defaults
    return llm_defaults


def _LLMClient():
    from logosai.utils.llm_client import LLMClient
    return LLMClient


def _setup(mp):
    block_pulse(mp)
    use_fake_api_keys(mp)
    # 초기 상태(env 없음) — config.json 기준
    for k in ("LOGOSAI_LLM_PROVIDER", "LOGOSAI_LLM_MODEL"):
        mp.delenv(k, raising=False)
    _defaults().reload_config()


def _teardown():
    # 환경이 되돌려진 뒤에 불린다 — llm_defaults 의 캐시를 진짜 환경으로 되돌린다.
    _defaults().reload_config()


def test_p1_unspecified_provider_comes_from_config():
    """P-1 provider 미지정 → config 프로바이더 사용"""
    assert _LLMClient()().provider == _defaults().get_default_provider()


def test_p2_unspecified_model_comes_from_config():
    """P-2 model 미지정 → config 모델 사용 (회귀)"""
    assert _LLMClient()().model == _defaults().get_default_model()


def test_p3_env_provider_switches_provider(monkeypatch):
    """P-3 env LOGOSAI_LLM_PROVIDER → 프로바이더 전환"""
    # config 기본값과 다른 쪽으로 돌려야 '전환'을 잰다 (기본이 openai 면 openai 로는 아무것도 못 잰다).
    target = "anthropic" if _defaults().get_default_provider() == "openai" else "openai"
    assert _LLMClient()().provider != target       # 대조군: 전환 전에는 다르다
    monkeypatch.setenv("LOGOSAI_LLM_PROVIDER", target)
    _defaults().reload_config()
    assert _LLMClient()().provider == target


def test_p4_explicit_provider_argument_wins(monkeypatch):
    """P-4 명시적 provider 인자 우선"""
    assert _LLMClient()(provider="anthropic").provider == "anthropic"
    # env 가 다른 값을 말해도 인자가 이긴다.
    monkeypatch.setenv("LOGOSAI_LLM_PROVIDER", "openai")
    _defaults().reload_config()
    assert _LLMClient()(provider="anthropic").provider == "anthropic"


def test_p5_explicit_provider_still_uses_config_model():
    """P-5 명시적 provider + 모델은 여전히 config"""
    assert _LLMClient()(provider="anthropic").model == _defaults().get_default_model()


def test_p6_env_model_is_honored_regardless_of_provider(monkeypatch):
    """P-6 env 모델은 프로바이더 무관 존중(openai 하드코딩 금지)"""
    monkeypatch.setenv("LOGOSAI_LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct")
    _defaults().reload_config()
    # openai 여도 env 모델 존중(하드코딩 금지)
    assert _LLMClient()(provider="openai").model == "Qwen/Qwen2.5-72B-Instruct"


# ══ pytest 배선 ═══════════════════════════════════════════════════════════

if "pytest" in sys.modules:
    import pytest

    @pytest.fixture(autouse=True)
    def _env(monkeypatch):
        _setup(monkeypatch)
        yield
        monkeypatch.undo()
        _teardown()


def main():
    return run_tests(globals(), setup=_setup, teardown=_teardown)


if __name__ == "__main__":
    sys.exit(main())
