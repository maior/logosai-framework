"""LLMClient 온-프렘 OpenAI-호환 base_url 테스트 (2026-07-07).

사용자 요구: 온-프렘에서도 사용. vLLM/LMStudio/Ollama(/v1)/TGI/LocalAI 등은
OpenAI-호환 API 를 노출하므로, openai 프로바이더 + config-driven base_url 로
langchain 없이 온-프렘 서버를 가리킨다. 계약:
  - base_url 은 config(~/.logosai/config.json llm.base_url)/env
    (LOGOSAI_LLM_BASE_URL)에서 결정. 명시 인자 우선.
  - base_url 미설정 시 None(기존 클라우드 동작 불변).
  - base_url 설정 + provider=openai + api_key 없음 → 온-프렘 placeholder 키
    (AsyncOpenAI 가 None 키로 실패하지 않도록).
  - base_url 설정 시 initialize()가 langchain(ChatOpenAI) 건너뜀 → 온-프렘은
    langchain 불필요(네이티브 AsyncOpenAI 경로).
  - _call_openai 직접 경로가 base_url 로 AsyncOpenAI 생성.

직접 실행: python logosai/tests/test_llm_onprem_base_url.py
"""
import asyncio
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PKG)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def main():
    fails = []

    def t(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    from logosai.utils.llm_client import LLMClient
    from logosai.config import llm_defaults

    for k in ("LOGOSAI_LLM_PROVIDER", "LOGOSAI_LLM_MODEL", "LOGOSAI_LLM_BASE_URL"):
        os.environ.pop(k, None)
    llm_defaults.reload_config()

    # ── 기본: base_url None (클라우드 동작 불변) ──
    c0 = LLMClient(provider="openai")
    t("OB-1 base_url 미설정 → None(기존 동작 불변)", getattr(c0, "base_url", "x") is None)

    # ── env LOGOSAI_LLM_BASE_URL → base_url 반영 ──
    os.environ["LOGOSAI_LLM_BASE_URL"] = "http://onprem.local:8000/v1"
    llm_defaults.reload_config()
    c1 = LLMClient(provider="openai")
    t("OB-2 env base_url 반영", c1.base_url == "http://onprem.local:8000/v1")

    # ── base_url + api_key 없음 → 온-프렘 placeholder 키 ──
    c2 = LLMClient(provider="openai", api_key=None)
    t("OB-3 base_url 설정 + 키 없음 → placeholder(None 아님)",
      bool(c2.api_key))

    # ── base_url 설정 시 initialize() 가 langchain 건너뜀 ──
    c3 = LLMClient(provider="openai")
    try:
        run(c3.initialize())
        skipped = c3._langchain_client is None
    except Exception as e:  # noqa: BLE001
        skipped = False
        print("   init err:", e)
    t("OB-4 base_url 설정 → initialize langchain 건너뜀(온-프렘 네이티브)", skipped)
    t("OB-5 base_url 설정 → 네이티브 AsyncOpenAI 클라이언트 생성",
      c3._client is not None)

    os.environ.pop("LOGOSAI_LLM_BASE_URL", None)
    llm_defaults.reload_config()

    # ── 명시적 base_url 인자 우선 ──
    c4 = LLMClient(provider="openai", base_url="http://explicit:9000/v1")
    t("OB-6 명시적 base_url 인자 우선", c4.base_url == "http://explicit:9000/v1")

    # ── base_url 없으면 langchain 경로 유지(클라우드 회귀) ──
    c5 = LLMClient(provider="openai")
    t("OB-7 base_url 없음 → base_url None(클라우드 회귀)", c5.base_url is None)

    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
