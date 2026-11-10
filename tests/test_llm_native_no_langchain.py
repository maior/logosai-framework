"""LLMClient native-only 검증 — langchain 없이 전 프로바이더 동작 (2026-07-07).

배경: openai/anthropic/ollama 경로가 langchain 래퍼(ChatOpenAI 등)로 남아
있었고, import 가드가 native SDK 와 langchain 을 한 try 에 묶어서
native-only 설치(logosai[llm])에서 프로바이더가 통째로 불가용 처리됐다.
사용자 설계 의도 = langchain 미사용, 직접 구현.

핵심 기법: sys.meta_path 에 langchain* import 차단 finder 를 꽂고 llm_client
소스를 **별도 이름의 사본 모듈**로 적재 → langchain 이 아예 설치 안 된 환경을 재현.

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가 0건을 수집했다.
  - 직접 실행: python tests/test_llm_native_no_langchain.py  → 마지막 줄 `RESULT: GREEN`

예전에는 `importlib.reload(logosai.utils.llm_client)` 로 정본 모듈을 제자리에서
갈아끼웠다. 스크립트로 혼자 돌 때는 무해했지만, pytest 세션 안에서는 이미
`from logosai.utils.llm_client import LLMClient` 로 클래스를 쥐고 있는 다른 모듈과
정본이 서로 다른 클래스를 가리키게 된다. 그래서 정본은 건드리지 않고 사본을 쓴다
(`test_n1` 이 정본이 그대로임을 확인한다).
"""
import asyncio
import contextlib
import importlib
import importlib.util
import os
import sys
import types

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":      # 스크립트 모드에서만 — pytest 는 pyproject 의 pythonpath 를 쓴다
    sys.path.insert(0, _PKG)

from _script_runner import (  # noqa: E402
    block_pulse, generate_tests, run_tests, use_fake_api_keys,
)

_PROBE_NAME = "logosai.utils._llm_client_no_langchain_probe"

# N-12: 소스에 남아 있으면 안 되는 langchain 챗 래퍼 흔적.
_PARAMS = {
    "marker": ["ChatOpenAI", "ChatAnthropic", "ChatOllama", "langchain_openai",
               "langchain_anthropic", "langchain_community", "langchain_core"],
}


class _BlockLangchain:
    """langchain* 모듈 import 를 ImportError 로 차단하는 meta path finder."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("langchain"):
            raise ImportError(f"blocked for test: {fullname}")
        return None


@contextlib.contextmanager
def _native_module():
    """langchain 이 없는 환경에서 적재한 llm_client 사본. 나가면 전부 되돌린다."""
    import logosai.utils.llm_client as canonical

    blocker = _BlockLangchain()
    removed = {k: v for k, v in list(sys.modules.items()) if k.startswith("langchain")}
    for k in removed:
        del sys.modules[k]
    sys.meta_path.insert(0, blocker)
    try:
        spec = importlib.util.spec_from_file_location(_PROBE_NAME, canonical.__file__)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_PROBE_NAME] = mod      # dataclass 가 sys.modules[cls.__module__] 을 본다
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(_PROBE_NAME, None)
        sys.meta_path.remove(blocker)
        sys.modules.update(removed)


class _FakeCompletionMsg:
    def __init__(self, content):
        self.message = types.SimpleNamespace(content=content)


class _FakeChatResponse:
    def __init__(self, content):
        self.choices = [_FakeCompletionMsg(content)]
        self.usage = None


def _setup(mp):
    block_pulse(mp)
    use_fake_api_keys(mp)


def _teardown():
    pass


def _source():
    return open(os.path.join(_PKG, "logosai", "utils", "llm_client.py"), encoding="utf-8").read()


def test_n1_module_loads_with_langchain_blocked():
    """N-1 langchain 차단 상태에서 모듈 로드 성공"""
    import logosai.utils.llm_client as canonical
    canonical_cls = canonical.LLMClient
    meta_before = list(sys.meta_path)

    with _native_module() as mod:
        assert mod is not None
        assert hasattr(mod, "LLMClient")
        # 대조군: 차단이 실제로 걸려 있다 — 이게 없으면 "langchain 없이"가 빈말이다.
        blocked = False
        try:
            importlib.import_module("langchain_core")
        except ImportError as e:
            blocked = "blocked for test" in str(e)
        assert blocked, "langchain import 가 차단되지 않았다"
        # 사본이지 정본이 아니다.
        assert mod is not canonical
        assert mod.LLMClient is not canonical_cls

    # 정본과 import 기계장치는 그대로다.
    assert sys.modules["logosai.utils.llm_client"] is canonical
    assert canonical.LLMClient is canonical_cls
    assert _PROBE_NAME not in sys.modules
    assert sys.meta_path == meta_before


def test_n2_openai_available_with_native_sdk_only():
    """N-2 openai 가용 (native SDK 만으로)"""
    with _native_module() as mod:
        assert mod._PROVIDERS_AVAILABLE.get("openai") is True


def test_n3_anthropic_available_with_native_sdk_only():
    """N-3 anthropic 가용 (native SDK 만으로)"""
    with _native_module() as mod:
        assert mod._PROVIDERS_AVAILABLE.get("anthropic") is True


def test_n4_ollama_available_without_langchain_community():
    """N-4 ollama 가용 (OpenAI-호환 /v1, langchain_community 불필요)"""
    with _native_module() as mod:
        assert mod._PROVIDERS_AVAILABLE.get("ollama") is True


def test_n5_openai_initializes_without_langchain_client():
    """N-5 openai initialize 성공 (langchain 클라이언트 없음)"""
    with _native_module() as mod:
        c = mod.LLMClient(provider="openai", model="gpt-test", api_key="sk-dummy")
        ok = asyncio.run(c.initialize())
        assert ok
        assert c._langchain_client is None
        assert c._client is not None


def test_n6_openai_call_uses_native_chat_completions():
    """N-6 openai 호출이 native chat.completions 경로"""
    with _native_module() as mod:
        c = mod.LLMClient(provider="openai", model="gpt-test", api_key="sk-dummy")
        asyncio.run(c.initialize())
        calls = []

        async def fake_create(**kw):
            calls.append(kw)
            assert kw["model"] == "gpt-test"
            assert kw["messages"][0]["role"] == "user"
            return _FakeChatResponse("native-openai-ok")

        c._client.chat.completions.create = fake_create
        r = asyncio.run(c.invoke("hi"))
        assert len(calls) == 1
        assert r.content == "native-openai-ok"


def test_n7_anthropic_initializes_without_langchain_client():
    """N-7 anthropic initialize 성공 (langchain 클라이언트 없음)"""
    with _native_module() as mod:
        a = mod.LLMClient(provider="anthropic", model="claude-test", api_key="sk-ant-dummy")
        ok_a = asyncio.run(a.initialize())
        assert ok_a
        assert a._langchain_client is None
        assert a._client is not None


def test_n8_anthropic_native_call_separates_system_param():
    """N-8 anthropic native 호출 + system 파라미터 분리"""
    with _native_module() as mod:
        a = mod.LLMClient(provider="anthropic", model="claude-test", api_key="sk-ant-dummy")
        asyncio.run(a.initialize())
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
        assert r_a.content == "native-anthropic-ok"
        assert seen.get("system") == "너는 검증봇"
        sent = seen.get("messages", [])
        # 대조군: 메시지는 실제로 전달됐다 (빈 목록이면 아래 all() 은 공허하게 참).
        assert [m["role"] for m in sent] == ["user"]
        assert all(m["role"] != "system" for m in sent)


def test_n9_ollama_initializes_openai_compat_client():
    """N-9 ollama initialize → OpenAI-호환 클라이언트 (기본 11434/v1)"""
    with _native_module() as mod:
        o = mod.LLMClient(provider="ollama", model="llama3.1")
        ok_o = asyncio.run(o.initialize())
        base = str(getattr(o._client, "base_url", ""))
        assert ok_o
        assert o._langchain_client is None
        assert "11434" in base
        assert "/v1" in base


def test_n10_ollama_call_uses_native_path():
    """N-10 ollama 호출이 native 경로"""
    with _native_module() as mod:
        o = mod.LLMClient(provider="ollama", model="llama3.1")
        asyncio.run(o.initialize())
        calls = []

        async def fake_create2(**kw):
            calls.append(kw)
            return _FakeChatResponse("native-ollama-ok")

        o._client.chat.completions.create = fake_create2
        r_o = asyncio.run(o.invoke("hi"))
        assert len(calls) == 1
        assert r_o.content == "native-ollama-ok"


def test_n11_ollama_custom_base_url_is_used():
    """N-11 ollama base_url 커스텀 반영"""
    with _native_module() as mod:
        o2 = mod.LLMClient(provider="ollama", model="m", base_url="http://gpu-node:11434/v1")
        asyncio.run(o2.initialize())
        assert "gpu-node" in str(getattr(o2._client, "base_url", ""))


def test_n12_source_has_no_langchain_chat_wrapper(marker):
    """N-12 소스에 {marker} 잔존 없음"""
    src = _source()
    # 대조군: 읽은 것이 진짜 llm_client 소스다 (빈 문자열이면 아래 검사는 공허하게 참).
    assert "class LLMClient" in src
    assert "AsyncOpenAI" in src
    assert marker not in src


# ══ pytest 배선 ═══════════════════════════════════════════════════════════

if "pytest" in sys.modules:
    import pytest

    @pytest.fixture(autouse=True)
    def _env(monkeypatch):
        _setup(monkeypatch)
        yield
        monkeypatch.undo()
        _teardown()


def pytest_generate_tests(metafunc):
    generate_tests(metafunc, _PARAMS)


def main():
    return run_tests(globals(), setup=_setup, teardown=_teardown, params=_PARAMS,
                     blank_before_result=True)


if __name__ == "__main__":
    sys.exit(main())
