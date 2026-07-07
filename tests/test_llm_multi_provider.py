"""LLMClient 진화 — OpenAI-호환 프로바이더 레지스트리 테스트 (2026-07-07).

목표: langchain 의 잔여 장점(프로바이더 폭)을 LLMClient 가 흡수하되
장점(native·관측·config-driven·얇음)은 유지.

계약:
  - 내장 레지스트리 `_COMPAT_PROVIDERS`: groq/deepseek/together/fireworks/
    openrouter/mistral/xai/perplexity/ollama — {base_url, api_key_env}.
    전부 OpenAI-호환 /v1 이므로 AsyncOpenAI 하나로 소화.
  - config 확장: llm.providers.<name> (llm_defaults.get_extra_providers) —
    코드 수정 없이 신규 프로바이더 (config-driven 장점 유지).
  - base_url 단독으로도 generic 호환 서버 사용 가능 (온-프렘 설계의 일반화).
  - 미지의 프로바이더 + base_url 없음 → 가용 목록을 담은 명확한 에러.
  - 스트리밍/native tool calling 이 openai·compat 경로에서 동작
    (기존: 둘 다 google 전용, 나머지는 폴백).
  - ANTHROPIC_API_KEY env 해석 (기존 갭).

실행: .venv/bin/python logosai/tests/test_llm_multi_provider.py
"""
import asyncio
import json
import os
import sys
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "logosai"))


class _FakeChatResponse:
    def __init__(self, content, tool_calls=None):
        msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
        self.choices = [types.SimpleNamespace(message=msg)]
        self.usage = None


def main():
    fails = []

    def t(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    import logosai.utils.llm_client as m
    LLMClient = m.LLMClient

    # ── M-1 내장 레지스트리 해석 ──
    os.environ["GROQ_API_KEY"] = "gsk-test-123"
    c = LLMClient(provider="groq", model="llama-3.3-70b")
    ok = asyncio.run(c.initialize())
    base = str(getattr(c._client, "base_url", ""))
    t("M-1 groq: 레지스트리 base_url + env 키 해석",
      ok and "api.groq.com" in base and c.api_key == "gsk-test-123")

    # ── M-2 미지 프로바이더 → 가용 목록 에러 ──
    try:
        LLMClient(provider="no_such_llm")
        t("M-2 미지 프로바이더 → 명확한 에러", False)
    except ValueError as e:
        t("M-2 미지 프로바이더 → 명확한 에러(가용 목록 포함)",
          "no_such_llm" in str(e) and "groq" in str(e))

    # ── M-3 config 확장 프로바이더 ──
    _orig_extra = m._get_extra_providers
    m._get_extra_providers = lambda: {
        "our_gpu_farm": {"base_url": "http://gpu-farm:8000/v1", "api_key_env": "FARM_KEY"}
    }
    try:
        os.environ["FARM_KEY"] = "farm-key-1"
        c3 = LLMClient(provider="our_gpu_farm", model="qwen3")
        asyncio.run(c3.initialize())
        t("M-3 config llm.providers 확장 프로바이더 동작",
          "gpu-farm" in str(getattr(c3._client, "base_url", "")) and c3.api_key == "farm-key-1")
    finally:
        m._get_extra_providers = _orig_extra

    # ── M-4 compat 호출이 chat.completions 경유 + 관측 경로(invoke_messages) ──
    async def fake_create(**kw):
        assert kw["model"] == "llama-3.3-70b"
        return _FakeChatResponse("groq-ok")

    c._client.chat.completions.create = fake_create
    r = asyncio.run(c.invoke("hi"))
    t("M-4 compat invoke → native chat.completions", r.content == "groq-ok" and r.provider == "groq")

    # ── M-5 anthropic env 키 해석 (기존 갭) ──
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-env-1"
    a = LLMClient(provider="anthropic", model="claude-test")
    t("M-5 ANTHROPIC_API_KEY env 해석", a.api_key == "sk-ant-env-1")

    # ── M-6 compat 진짜 토큰 스트리밍 ──
    async def fake_stream_create(**kw):
        assert kw.get("stream") is True

        async def gen():
            for piece in ["안", "녕", "하세요"]:
                delta = types.SimpleNamespace(content=piece)
                yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])

        return gen()

    c._client.chat.completions.create = fake_stream_create
    chunks = []

    async def collect():
        async for ch in c.invoke_stream("인사해줘"):
            chunks.append(ch)

    asyncio.run(collect())
    t("M-6 compat invoke_stream → 토큰 단위 스트리밍", chunks == ["안", "녕", "하세요"])

    # ── M-7 openai/compat native tool calling ──
    seen = {}

    async def fake_tools_create(**kw):
        seen.update(kw)
        tc = types.SimpleNamespace(
            id="call_1",
            function=types.SimpleNamespace(
                name="calculator", arguments='{"expression": "1+1"}'
            ),
        )
        return _FakeChatResponse("", tool_calls=[tc])

    c._client.chat.completions.create = fake_tools_create
    r_t = asyncio.run(c.invoke_with_tools(
        [{"role": "user", "content": "1+1 계산해"}],
        tools=[{
            "name": "calculator",
            "description": "수학 계산",
            "parameters": {"expression": {"type": "string", "description": "수식"}},
        }],
    ))
    sent_tools = seen.get("tools") or []
    t("M-7a tools 가 OpenAI function 포맷으로 전달",
      len(sent_tools) == 1 and sent_tools[0]["type"] == "function"
      and sent_tools[0]["function"]["name"] == "calculator"
      and "expression" in sent_tools[0]["function"]["parameters"]["properties"])
    t("M-7b tool_calls 가 ToolCall 로 파싱",
      r_t.has_tool_calls and r_t.tool_calls[0].name == "calculator"
      and r_t.tool_calls[0].args == {"expression": "1+1"} and r_t.tool_calls[0].id == "call_1")

    # ── M-8 ollama 하위호환 (레지스트리 통합 후에도) ──
    o = LLMClient(provider="ollama", model="llama3.1")
    asyncio.run(o.initialize())
    ob = str(getattr(o._client, "base_url", ""))
    t("M-8 ollama: 기본 11434/v1 + 키 불요 동작 유지", "11434" in ob and "/v1" in ob)

    # ── M-9 base_url 단독 generic 호환 서버 ──
    g = LLMClient(provider="openai", model="m", base_url="http://edge-box:9000/v1", api_key="k")
    asyncio.run(g.initialize())
    t("M-9 base_url 단독 generic 호환", "edge-box" in str(getattr(g._client, "base_url", "")))

    # ── M-10 기존 1군 프로바이더 validation 불변 ──
    okc = 0
    for p in ("openai", "google", "anthropic", "ollama"):
        try:
            LLMClient(provider=p, model="x", api_key="k")
            okc += 1
        except Exception:
            pass
    t("M-10 기존 4 프로바이더 생성 여전히 통과", okc == 4)

    print("\nRESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
