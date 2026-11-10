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

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가 0건을 수집했다.
  - 직접 실행: python tests/test_llm_multi_provider.py  → 마지막 줄 `RESULT: GREEN`

예전 `main()` 은 GROQ_API_KEY·FARM_KEY·ANTHROPIC_API_KEY 를 os.environ 에 세우고
되돌리지 않았다(진짜 ANTHROPIC_API_KEY 를 덮어쓴 채로 남았다). 이제 전부
monkeypatch/ScriptPatch 를 거쳐 테스트가 끝나면 되돌려진다.
"""
import asyncio
import os
import sys
import types

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":      # 스크립트 모드에서만 — pytest 는 pyproject 의 pythonpath 를 쓴다
    sys.path.insert(0, _PKG)

from _script_runner import block_pulse, run_tests, use_fake_api_keys  # noqa: E402


class _FakeChatResponse:
    def __init__(self, content, tool_calls=None):
        msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
        self.choices = [types.SimpleNamespace(message=msg)]
        self.usage = None


def _setup(mp):
    block_pulse(mp)
    use_fake_api_keys(mp)


def _teardown():
    pass


def _m():
    import logosai.utils.llm_client as m
    return m


def _groq(mp):
    """초기화된 groq 클라이언트 (키는 가짜, 네트워크 호출 없음)."""
    mp.setenv("GROQ_API_KEY", "gsk-test-123")
    c = _m().LLMClient(provider="groq", model="llama-3.3-70b")
    ok = asyncio.run(c.initialize())
    return c, ok


def _tool_call(mp):
    """M-7 공용 — 가짜 chat.completions 로 도구 호출 한 번. (보낸 kwargs, 응답)"""
    c, _ = _groq(mp)
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
    return seen, r_t


def test_m1_groq_resolves_registry_base_url_and_env_key(monkeypatch):
    """M-1 groq: 레지스트리 base_url + env 키 해석"""
    c, ok = _groq(monkeypatch)
    assert ok
    assert "api.groq.com" in str(getattr(c._client, "base_url", ""))
    assert c.api_key == "gsk-test-123"


def test_m2_unknown_provider_raises_with_available_list(monkeypatch):
    """M-2 미지 프로바이더 → 명확한 에러(가용 목록 포함)"""
    LLMClient = _m().LLMClient
    raised = None
    try:
        LLMClient(provider="no_such_llm")
    except ValueError as e:
        raised = e
    assert raised is not None, "미지 프로바이더가 에러 없이 생성됐다"
    assert "no_such_llm" in str(raised)
    assert "groq" in str(raised)
    # 대조군: 아는 프로바이더는 같은 생성자가 받아들인다.
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-123")
    assert LLMClient(provider="groq", model="x").provider == "groq"


def test_m3_config_extra_provider_works(monkeypatch):
    """M-3 config llm.providers 확장 프로바이더 동작"""
    m = _m()
    monkeypatch.setenv("FARM_KEY", "farm-key-1")
    # 대조군: config 에 없으면 이 이름은 미지의 프로바이더다.
    unknown = False
    try:
        m.LLMClient(provider="our_gpu_farm", model="qwen3")
    except ValueError:
        unknown = True
    assert unknown, "config 확장 없이도 our_gpu_farm 이 생성됐다 — 아래 검사가 아무것도 재지 않는다"

    monkeypatch.setattr(m, "_get_extra_providers", lambda: {
        "our_gpu_farm": {"base_url": "http://gpu-farm:8000/v1", "api_key_env": "FARM_KEY"}
    })
    c3 = m.LLMClient(provider="our_gpu_farm", model="qwen3")
    asyncio.run(c3.initialize())
    assert "gpu-farm" in str(getattr(c3._client, "base_url", ""))
    assert c3.api_key == "farm-key-1"


def test_m4_compat_invoke_goes_through_chat_completions(monkeypatch):
    """M-4 compat invoke → native chat.completions"""
    c, _ = _groq(monkeypatch)
    calls = []

    async def fake_create(**kw):
        calls.append(kw)
        assert kw["model"] == "llama-3.3-70b"
        return _FakeChatResponse("groq-ok")

    c._client.chat.completions.create = fake_create
    r = asyncio.run(c.invoke("hi"))
    assert len(calls) == 1
    assert r.content == "groq-ok"
    assert r.provider == "groq"


def test_m5_anthropic_api_key_env_is_resolved(monkeypatch):
    """M-5 ANTHROPIC_API_KEY env 해석"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-1")
    a = _m().LLMClient(provider="anthropic", model="claude-test")
    assert a.api_key == "sk-ant-env-1"


def test_m6_compat_invoke_stream_yields_token_chunks(monkeypatch):
    """M-6 compat invoke_stream → 토큰 단위 스트리밍"""
    c, _ = _groq(monkeypatch)

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
    assert chunks == ["안", "녕", "하세요"]


def test_m7a_tools_are_sent_in_openai_function_format(monkeypatch):
    """M-7a tools 가 OpenAI function 포맷으로 전달"""
    seen, _ = _tool_call(monkeypatch)
    sent_tools = seen.get("tools") or []
    assert len(sent_tools) == 1
    assert sent_tools[0]["type"] == "function"
    assert sent_tools[0]["function"]["name"] == "calculator"
    assert "expression" in sent_tools[0]["function"]["parameters"]["properties"]


def test_m7b_tool_calls_are_parsed_into_toolcall(monkeypatch):
    """M-7b tool_calls 가 ToolCall 로 파싱"""
    _, r_t = _tool_call(monkeypatch)
    assert r_t.has_tool_calls
    assert r_t.tool_calls[0].name == "calculator"
    assert r_t.tool_calls[0].args == {"expression": "1+1"}
    assert r_t.tool_calls[0].id == "call_1"


def test_m8_ollama_keeps_default_port_and_needs_no_key():
    """M-8 ollama: 기본 11434/v1 + 키 불요 동작 유지"""
    o = _m().LLMClient(provider="ollama", model="llama3.1")
    asyncio.run(o.initialize())
    ob = str(getattr(o._client, "base_url", ""))
    assert "11434" in ob
    assert "/v1" in ob


def test_m9_base_url_alone_is_a_generic_compat_server():
    """M-9 base_url 단독 generic 호환"""
    g = _m().LLMClient(provider="openai", model="m", base_url="http://edge-box:9000/v1", api_key="k")
    asyncio.run(g.initialize())
    assert "edge-box" in str(getattr(g._client, "base_url", ""))


def test_m10_first_class_providers_still_construct():
    """M-10 기존 4 프로바이더 생성 여전히 통과"""
    LLMClient = _m().LLMClient
    failed = {}
    for p in ("openai", "google", "anthropic", "ollama"):
        try:
            LLMClient(provider=p, model="x", api_key="k")
        except Exception as e:  # noqa: BLE001
            failed[p] = repr(e)
    assert not failed, f"생성에 실패한 1군 프로바이더: {failed}"


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
    return run_tests(globals(), setup=_setup, teardown=_teardown, blank_before_result=True)


if __name__ == "__main__":
    sys.exit(main())
