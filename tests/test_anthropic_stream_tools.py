"""Anthropic 스트리밍 · native tools 갭 메우기 테스트 (2026-07-19).

배경: LLMClient 는 "어떤 생성형AI 든 호출" 이 설계 목표인데, 실측 결과
anthropic 만 2등 시민이었다 — 스트리밍은 non-streaming 폴백(전문 1회 yield),
도구 호출은 프롬프트 폴백. google/openai 는 둘 다 native.

이 테스트는 네트워크 없이 SDK 를 가짜 객체로 대체해 계약을 검증한다.

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `async def main()` 하나뿐이라 pytest 가 0건을 수집했다.
  - 직접 실행: python3 tests/test_anthropic_stream_tools.py  → 마지막 줄 `RESULT: GREEN`
"""
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":      # 스크립트 모드에서만 — pytest 는 pyproject 의 pythonpath 를 쓴다
    sys.path.insert(0, _PKG)

from _script_runner import block_pulse, run, run_tests, use_fake_api_keys  # noqa: E402

from logosai.utils.llm_client import LLMClient, LLMMessage  # noqa: E402


# ── 가짜 Anthropic SDK ────────────────────────────────────────────────────
class _FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, id, name, input):
        self.id, self.name, self.input = id, name, input


class _FakeUsage:
    input_tokens = 11
    output_tokens = 22


class _FakeResponse:
    def __init__(self, blocks):
        self.content = blocks
        self.usage = _FakeUsage()
        self.stop_reason = "tool_use"


class _FakeStreamCtx:
    """messages.stream(...) 이 반환하는 async context manager."""

    def __init__(self, chunks, recorder):
        self._chunks = chunks
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    @property
    def text_stream(self):
        chunks = self._chunks

        async def _gen():
            for c in chunks:
                yield c
        return _gen()


class _FakeMessages:
    def __init__(self, recorder, blocks=None, chunks=None):
        self._recorder = recorder
        self._blocks = blocks or [_FakeTextBlock("ok")]
        self._chunks = chunks or ["안녕", "하세", "요"]

    async def create(self, **kwargs):
        self._recorder["create_kwargs"] = kwargs
        return _FakeResponse(self._blocks)

    def stream(self, **kwargs):
        self._recorder["stream_kwargs"] = kwargs
        return _FakeStreamCtx(self._chunks, self._recorder)


class _FakeAnthropic:
    def __init__(self, recorder, blocks=None, chunks=None):
        self.messages = _FakeMessages(recorder, blocks, chunks)


def _client(recorder, blocks=None, chunks=None):
    c = LLMClient(provider="anthropic", model="claude-sonnet-5", api_key="test-key")
    c._client = _FakeAnthropic(recorder, blocks, chunks)
    c._initialized = True
    return c


_TOOLS = [{
    "name": "get_weather",
    "description": "도시의 날씨를 조회",
    "parameters": {"city": {"type": "string", "description": "도시명"}},
}]


def _setup(mp):
    block_pulse(mp)
    use_fake_api_keys(mp)


def _teardown():
    pass


def _stream_with_system():
    """스트리밍 한 번 (system 있음) → (받은 청크, messages.stream 에 넘어간 kwargs 기록)"""
    rec = {}
    c = _client(rec, chunks=["안녕", "하세", "요"])

    async def go():
        return [chunk async for chunk in c.invoke_stream("인사해줘", system_prompt="너는 비서다")]

    return run(go()), rec


def _tool_call():
    """도구 호출 한 번 → (응답, messages.create 에 넘어간 kwargs)"""
    blocks = [
        _FakeTextBlock("날씨를 조회하겠습니다."),
        _FakeToolUseBlock("tu_01", "get_weather", {"city": "서울"}),
    ]
    rec = {}
    c = _client(rec, blocks=blocks)
    resp = run(c.invoke_with_tools(
        [LLMMessage(role="system", content="너는 비서다"),
         LLMMessage(role="user", content="서울 날씨")],
        _TOOLS,
    ))
    return resp, rec.get("create_kwargs", {})


# ── 스트리밍 ──────────────────────────────────────────────────────────────

def test_s1_stream_yields_token_chunks_not_one_blob():
    """S-1 토큰 단위 청크 (전문 1회 아님)"""
    got, _ = _stream_with_system()
    assert got == ["안녕", "하세", "요"]


def test_s2_stream_uses_native_messages_stream():
    """S-2 messages.stream 사용 (native 경로)"""
    _, rec = _stream_with_system()
    assert "stream_kwargs" in rec
    # non-streaming 폴백(messages.create)으로 새지 않았다.
    assert "create_kwargs" not in rec


def test_s3_stream_system_is_top_level_param():
    """S-3 system 은 top-level 파라미터"""
    _, rec = _stream_with_system()
    assert rec.get("stream_kwargs", {}).get("system") == "너는 비서다"


def test_s4_stream_system_not_mixed_into_messages():
    """S-4 system 이 messages 배열에 섞이지 않음"""
    _, rec = _stream_with_system()
    sent = rec.get("stream_kwargs", {}).get("messages", [])
    # 대조군: 메시지는 실제로 갔다 (빈 목록이면 아래 all() 은 공허하게 참).
    assert any(m.get("role") == "user" for m in sent)
    assert all(m.get("role") != "system" for m in sent)


def test_s5_stream_passes_model_and_max_tokens():
    """S-5 model/temperature/max_tokens 전달"""
    _, rec = _stream_with_system()
    sk = rec.get("stream_kwargs", {})
    assert sk.get("model") == "claude-sonnet-5"
    assert "max_tokens" in sk


def test_s6_stream_without_system_omits_the_param():
    """S-6 system 없으면 파라미터 미포함"""
    rec2 = {}
    c2 = _client(rec2, chunks=["a", "b"])

    async def go():
        return [x async for x in c2.invoke_stream("hi")]

    assert run(go()) == ["a", "b"]
    assert "system" not in rec2.get("stream_kwargs", {})
    # 대조군: system 을 주면 같은 자리에 나타난다.
    _, rec = _stream_with_system()
    assert "system" in rec.get("stream_kwargs", {})


# ── native tools ─────────────────────────────────────────────────────────

def test_t1_tool_calls_are_parsed():
    """T-1 tool_calls 파싱됨"""
    resp, _ = _tool_call()
    assert resp.has_tool_calls
    assert len(resp.tool_calls) == 1


def test_t2_tool_call_name_args_id_are_mapped():
    """T-2 name/args/id 매핑"""
    resp, _ = _tool_call()
    tc = resp.tool_calls[0] if resp.tool_calls else None
    assert tc is not None
    assert tc.name == "get_weather"
    assert tc.args == {"city": "서울"}
    assert tc.id == "tu_01"


def test_t3_text_block_is_kept_as_content():
    """T-3 텍스트 블록도 content 로 보존"""
    resp, _ = _tool_call()
    assert "날씨를 조회" in resp.content


def test_t4_tools_converted_to_anthropic_schema():
    """T-4 Anthropic 스키마로 변환 (input_schema, parameters 아님)"""
    _, ck = _tool_call()
    sent = (ck.get("tools") or [{}])[0]
    assert "input_schema" in sent
    assert "parameters" not in sent


def test_t5_input_schema_is_json_schema():
    """T-5 input_schema 가 JSON Schema 형태"""
    _, ck = _tool_call()
    sent = (ck.get("tools") or [{}])[0]
    assert sent.get("input_schema", {}).get("type") == "object"
    assert "city" in sent.get("input_schema", {}).get("properties", {})


def test_t6_tool_call_system_is_top_level():
    """T-6 도구 호출에서도 system 은 top-level"""
    _, ck = _tool_call()
    assert ck.get("system") == "너는 비서다"


def test_t7_no_tool_use_means_tool_calls_none():
    """T-7 도구 미사용 시 tool_calls=None"""
    rec4 = {}
    c4 = _client(rec4, blocks=[_FakeTextBlock("도구 없이 답합니다")])
    resp4 = run(c4.invoke_with_tools([LLMMessage(role="user", content="안녕")], _TOOLS))
    assert resp4.tool_calls is None
    assert "도구 없이" in resp4.content
    # 대조군: tool_use 블록이 있으면 같은 경로가 tool_calls 를 채운다.
    resp, _ = _tool_call()
    assert resp.tool_calls


# ── 실패 시 폴백 (native 예외 → 프롬프트 폴백으로 강등) ────────────────────

def test_f1_native_failure_falls_back_instead_of_raising():
    """F-1 native 실패 시 예외 대신 폴백 응답"""
    native_attempts = []

    class _BoomMessages(_FakeMessages):
        async def create(self, **kwargs):
            if "tools" in kwargs:
                native_attempts.append(kwargs)
                raise RuntimeError("tools unsupported by this endpoint")
            return _FakeResponse([_FakeTextBlock('{"tool": null, "answer": "폴백 응답"}')])

    rec5 = {}
    c5 = _client(rec5)
    c5._client.messages = _BoomMessages(rec5)
    # 예외가 새면 그대로 실패한다 (예전엔 잡아서 FAIL 줄로 바꿨다).
    resp5 = run(c5.invoke_with_tools([LLMMessage(role="user", content="x")], _TOOLS))
    assert resp5 is not None
    # 대조군: native 시도가 실제로 있었고 실패했다 — 폴백을 탄 것이지 처음부터 폴백이 아니다.
    assert native_attempts, "native tools 경로를 시도하지 않았다"


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
    return run_tests(globals(), setup=_setup, teardown=_teardown,
                     pass_prefix="PASS  ", fail_prefix="FAIL  ", blank_before_result=True)


if __name__ == "__main__":
    sys.exit(main())
