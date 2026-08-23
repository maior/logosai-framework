"""Anthropic 스트리밍 · native tools 갭 메우기 테스트 (2026-07-19).

배경: LLMClient 는 "어떤 생성형AI 든 호출" 이 설계 목표인데, 실측 결과
anthropic 만 2등 시민이었다 — 스트리밍은 non-streaming 폴백(전문 1회 yield),
도구 호출은 프롬프트 폴백. google/openai 는 둘 다 native.

이 테스트는 네트워크 없이 SDK 를 가짜 객체로 대체해 계약을 검증한다.
직접 실행: python3 logosai/tests/test_anthropic_stream_tools.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


async def main():
    fails = []

    def t(name, cond):
        print(("PASS  " if cond else "FAIL  ") + name)
        if not cond:
            fails.append(name)

    # ── 스트리밍 ──────────────────────────────────────────────────────────
    rec = {}
    c = _client(rec, chunks=["안녕", "하세", "요"])
    got = [chunk async for chunk in c.invoke_stream("인사해줘", system_prompt="너는 비서다")]
    t("S-1 토큰 단위 청크 (전문 1회 아님)", got == ["안녕", "하세", "요"])
    t("S-2 messages.stream 사용 (native 경로)", "stream_kwargs" in rec)
    sk = rec.get("stream_kwargs", {})
    t("S-3 system 은 top-level 파라미터", sk.get("system") == "너는 비서다")
    t("S-4 system 이 messages 배열에 섞이지 않음",
      all(m.get("role") != "system" for m in sk.get("messages", [])))
    t("S-5 model/temperature/max_tokens 전달",
      sk.get("model") == "claude-sonnet-5" and "max_tokens" in sk)

    # system 없는 경우
    rec2 = {}
    c2 = _client(rec2, chunks=["a", "b"])
    got2 = [x async for x in c2.invoke_stream("hi")]
    t("S-6 system 없으면 파라미터 미포함",
      got2 == ["a", "b"] and "system" not in rec2.get("stream_kwargs", {}))

    # ── native tools ─────────────────────────────────────────────────────
    blocks = [
        _FakeTextBlock("날씨를 조회하겠습니다."),
        _FakeToolUseBlock("tu_01", "get_weather", {"city": "서울"}),
    ]
    rec3 = {}
    c3 = _client(rec3, blocks=blocks)
    tools = [{
        "name": "get_weather",
        "description": "도시의 날씨를 조회",
        "parameters": {"city": {"type": "string", "description": "도시명"}},
    }]
    resp = await c3.invoke_with_tools(
        [LLMMessage(role="system", content="너는 비서다"),
         LLMMessage(role="user", content="서울 날씨")],
        tools,
    )
    t("T-1 tool_calls 파싱됨", resp.has_tool_calls and len(resp.tool_calls) == 1)
    tc = resp.tool_calls[0] if resp.tool_calls else None
    t("T-2 name/args/id 매핑", tc and tc.name == "get_weather"
      and tc.args == {"city": "서울"} and tc.id == "tu_01")
    t("T-3 텍스트 블록도 content 로 보존", "날씨를 조회" in resp.content)

    ck = rec3.get("create_kwargs", {})
    sent = (ck.get("tools") or [{}])[0]
    t("T-4 Anthropic 스키마로 변환 (input_schema, parameters 아님)",
      "input_schema" in sent and "parameters" not in sent)
    t("T-5 input_schema 가 JSON Schema 형태",
      sent.get("input_schema", {}).get("type") == "object"
      and "city" in sent.get("input_schema", {}).get("properties", {}))
    t("T-6 도구 호출에서도 system 은 top-level", ck.get("system") == "너는 비서다")

    # 도구 호출 없이 텍스트만 반환하는 경우
    rec4 = {}
    c4 = _client(rec4, blocks=[_FakeTextBlock("도구 없이 답합니다")])
    resp4 = await c4.invoke_with_tools([LLMMessage(role="user", content="안녕")], tools)
    t("T-7 도구 미사용 시 tool_calls=None", resp4.tool_calls is None
      and "도구 없이" in resp4.content)

    # ── 실패 시 폴백 (native 예외 → 프롬프트 폴백으로 강등) ────────────────
    class _BoomMessages(_FakeMessages):
        async def create(self, **kwargs):
            if "tools" in kwargs:
                raise RuntimeError("tools unsupported by this endpoint")
            return _FakeResponse([_FakeTextBlock('{"tool": null, "answer": "폴백 응답"}')])

    rec5 = {}
    c5 = _client(rec5)
    c5._client.messages = _BoomMessages(rec5)
    try:
        resp5 = await c5.invoke_with_tools([LLMMessage(role="user", content="x")], tools)
        t("F-1 native 실패 시 예외 대신 폴백 응답", resp5 is not None)
    except Exception as e:
        t(f"F-1 native 실패 시 예외 대신 폴백 응답 (raised {type(e).__name__})", False)

    print("\nRESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
