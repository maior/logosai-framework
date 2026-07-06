"""LLMClient 프로바이더 config-driven 테스트 (2026-07-07).

사용자 요구: "llm_client 는 설정에 따라 모두 사용할 수 있도록". 현재 모델은
config(~/.logosai/config.json / env)에서 오지만 프로바이더는 __init__ 의
리터럴 "google" 로 하드코딩돼 config.llm.provider 가 무시됐다. 계약:
  - 프로바이더 미지정 시 config/env(_get_default_provider)에서 결정.
  - 명시적 provider 인자는 config 를 이긴다(오버라이드).
  - 모델도 계속 config-driven(회귀 잠금).
  - env LOGOSAI_LLM_PROVIDER 로 전환 가능(온-프렘 대비).

직접 실행: python logosai/tests/test_llm_provider_config.py
"""
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PKG)


def main():
    fails = []

    def t(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    from logosai.utils.llm_client import LLMClient
    from logosai.config import llm_defaults

    # 초기 상태(env 없음) — config.json 기준
    os.environ.pop("LOGOSAI_LLM_PROVIDER", None)
    os.environ.pop("LOGOSAI_LLM_MODEL", None)
    llm_defaults.reload_config()

    cfg_provider = llm_defaults.get_default_provider()
    cfg_model = llm_defaults.get_default_model()

    # ── 프로바이더 미지정 → config 값 ──
    c = LLMClient()
    t("P-1 provider 미지정 → config 프로바이더 사용",
      c.provider == cfg_provider)
    t("P-2 model 미지정 → config 모델 사용 (회귀)",
      c.model == cfg_model)

    # ── env 오버라이드로 전환 (온-프렘 대비) ──
    os.environ["LOGOSAI_LLM_PROVIDER"] = "openai"  # 가용 프로바이더
    llm_defaults.reload_config()
    c2 = LLMClient()
    t("P-3 env LOGOSAI_LLM_PROVIDER → 프로바이더 전환",
      c2.provider == "openai")
    os.environ.pop("LOGOSAI_LLM_PROVIDER", None)
    llm_defaults.reload_config()

    # ── 명시적 provider 는 config 를 이긴다 ──
    c3 = LLMClient(provider="anthropic")
    t("P-4 명시적 provider 인자 우선", c3.provider == "anthropic")

    # ── 명시적 provider + config 모델 조합 ──
    c4 = LLMClient(provider="anthropic")
    t("P-5 명시적 provider + 모델은 여전히 config", c4.model == cfg_model)

    # ── 모델도 프로바이더 무관 config-driven (온-프렘 Qwen 등) ──
    os.environ["LOGOSAI_LLM_MODEL"] = "Qwen/Qwen2.5-72B-Instruct"
    llm_defaults.reload_config()
    c6 = LLMClient(provider="openai")  # openai 여도 env 모델 존중(하드코딩 금지)
    t("P-6 env 모델은 프로바이더 무관 존중(openai 하드코딩 금지)",
      c6.model == "Qwen/Qwen2.5-72B-Instruct")
    os.environ.pop("LOGOSAI_LLM_MODEL", None)
    llm_defaults.reload_config()

    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
