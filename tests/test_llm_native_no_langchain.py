"""LLMClient native-only 검증 — langchain 없이 전 프로바이더 동작 (2026-07-07).

배경: openai/anthropic/ollama 경로가 langchain 래퍼(ChatOpenAI 등)로 남아
있었고, import 가드가 native SDK 와 langchain 을 한 try 에 묶어서
native-only 설치(logosai[llm])에서 프로바이더가 통째로 불가용 처리됐다.
사용자 설계 의도 = langchain 미사용, 직접 구현.

핵심 기법: sys.meta_path 에 langchain* import 차단 finder 를 꽂고
llm_client 를 리로드 → langchain 이 아예 설치 안 된 환경을 재현.

실행: .venv/bin/python logosai/tests/test_llm_native_no_langchain.py
"""
import asyncio
import importlib
import os
import sys
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "logosai"))


class _BlockLangchain:
    """langchain* 모듈 import 를 ImportError 로 차단하는 meta path finder."""

    def find_module(self, fullname, path=None):
        if fullname.startswith("langchain"):
            return self
        return None

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("langchain"):
            raise ImportError(f"blocked for test: {fullname}")
        return None

    def load_module(self, fullname):
        raise ImportError(f"blocked for test: {fullname}")


def _reload_without_langchain():
    """langchain 이 없는 환경을 재현해 llm_client 리로드."""
    blocker = _BlockLangchain()
    # 이미 로드된 langchain 모듈 제거 + 차단
    removed = {k: v for k, v in list(sys.modules.items()) if k.startswith("langchain")}
    for k in removed:
        del sys.modules[k]
    sys.meta_path.insert(0, blocker)
    try:
        import logosai.utils.llm_client as m
        return importlib.reload(m), blocker, removed
    except Exception:
        sys.meta_path.remove(blocker)
        sys.modules.update(removed)
        raise


def _restore(blocker, removed):
    sys.meta_path.remove(blocker)
    sys.modules.update(removed)
    import logosai.utils.llm_client as m
    importlib.reload(m)


class _FakeCompletionMsg:
    def __init__(self, content):
        self.message = types.SimpleNamespace(content=content)


class _FakeChatResponse:
    def __init__(self, content):
        self.choices = [_FakeCompletionMsg(content)]
        self.usage = None


def main():
    fails = []

    def t(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    mod, blocker, removed = _reload_without_langchain()
    try:
        # ── N-1 모듈 자체가 langchain 없이 import 가능 + 가용성 플래그 ──
        t("N-1 langchain 차단 상태에서 모듈 로드 성공", mod is not None)
        t("N-2 openai 가용 (native SDK 만으로)", mod._PROVIDERS_AVAILABLE.get("openai") is True)
        t("N-3 anthropic 가용 (native SDK 만으로)", mod._PROVIDERS_AVAILABLE.get("anthropic") is True)
        t("N-4 ollama 가용 (OpenAI-호환 /v1, langchain_community 불필요)",
          mod._PROVIDERS_AVAILABLE.get("ollama") is True)

        # ── openai: native 초기화 + 호출 ──
        c = mod.LLMClient(provider="openai", model="gpt-test", api_key="sk-dummy")
        ok = asyncio.run(c.initialize())
        t("N-5 openai initialize 성공 (langchain 클라이언트 없음)",
          ok and c._langchain_client is None and c._client is not None)

        async def fake_create(**kw):
            assert kw["model"] == "gpt-test"
            assert kw["messages"][0]["role"] == "user"
            return _FakeChatResponse("native-openai-ok")

        c._client.chat.completions.create = fake_create
        r = asyncio.run(c.invoke("hi"))
        t("N-6 openai 호출이 native chat.completions 경로", r.content == "native-openai-ok")

        # ── anthropic: native 초기화 + system 분리 호출 ──
        a = mod.LLMClient(provider="anthropic", model="claude-test", api_key="sk-ant-dummy")
        ok_a = asyncio.run(a.initialize())
        t("N-7 anthropic initialize 성공 (langchain 클라이언트 없음)",
          ok_a and a._langchain_client is None and a._client is not None)

        seen = {}

        async def fake_msgs_create(**kw):
            seen.update(kw)
            block = types.SimpleNamespace(text="native-anthropic-ok")
            return types.SimpleNamespace(content=[block], usage=None)

        a._client.messages.create = fake_msgs_create
        r_a = asyncio.run(a.invoke_messages([
            {"role": "system", "content": "너는 검증봇"},
            {"role": "user", "content": "hi"},
        ]))
        t("N-8 anthropic native 호출 + system 파라미터 분리",
          r_a.content == "native-anthropic-ok"
          and seen.get("system") == "너는 검증봇"
          and all(m["role"] != "system" for m in seen.get("messages", [])))

        # ── ollama: OpenAI-호환 native ──
        o = mod.LLMClient(provider="ollama", model="llama3.1")
        ok_o = asyncio.run(o.initialize())
        base = str(getattr(o._client, "base_url", ""))
        t("N-9 ollama initialize → OpenAI-호환 클라이언트 (기본 11434/v1)",
          ok_o and o._langchain_client is None and "11434" in base and "/v1" in base)

        o._client.chat.completions.create = fake_create_ollama = None

        async def fake_create2(**kw):
            return _FakeChatResponse("native-ollama-ok")

        o._client.chat.completions.create = fake_create2
        r_o = asyncio.run(o.invoke("hi"))
        t("N-10 ollama 호출이 native 경로", r_o.content == "native-ollama-ok")

        # ── ollama base_url 커스텀 (온-프렘 일관) ──
        o2 = mod.LLMClient(provider="ollama", model="m", base_url="http://gpu-node:11434/v1")
        asyncio.run(o2.initialize())
        t("N-11 ollama base_url 커스텀 반영", "gpu-node" in str(getattr(o2._client, "base_url", "")))
    finally:
        _restore(blocker, removed)

    # ── N-12 소스 정적 검사: langchain 챗 래퍼 사용 잔존 금지 ──
    src = open(os.path.join(_ROOT, "logosai", "logosai", "utils", "llm_client.py")).read()
    for marker in ("ChatOpenAI", "ChatAnthropic", "ChatOllama", "langchain_openai",
                   "langchain_anthropic", "langchain_community", "langchain_core"):
        t(f"N-12 소스에 {marker} 잔존 없음", marker not in src)

    print("\nRESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
