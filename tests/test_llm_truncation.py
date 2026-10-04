"""출력 한도 잘림이 보인다 — LLMClient 는 잘린 응답을 정상 응답처럼 돌려줬다.

종료 사유 모양은 2026-10-05 세 프로바이더 실측 (max_tokens=20):
  google    candidates[0].finish_reason = FinishReason.MAX_TOKENS
  openai    choices[0].finish_reason   = 'length'
  anthropic stop_reason                = 'max_tokens'
잘림을 감지하는 코드가 없어서 호출자는 끊긴 텍스트를 받았다 — SDK 플래너에선 JSON 이
중간에 끊겨 "파싱 실패"로만 보였다. 기본 한도(2000)는 바꾸지 않는다: 모든 호출의 출력
비용에 걸리는 결정이라, 먼저 잘림을 보이게 하고 데이터로 판단한다.
"""
import enum
import json
import types

import pytest

from logosai.utils import llm_client as LC
from logosai.utils.llm_client import LLMClient, LLMResponse, finish_reason_of


class _GoogleReason(enum.Enum):
    MAX_TOKENS = "MAX_TOKENS"
    STOP = "STOP"


def _google(reason):
    return types.SimpleNamespace(candidates=[types.SimpleNamespace(finish_reason=reason)])


def _openai(reason):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason=reason)])


def _anthropic(reason):
    return types.SimpleNamespace(stop_reason=reason)


@pytest.mark.parametrize("raw, expected", [
    (_google(_GoogleReason.MAX_TOKENS), "length"),
    (_openai("length"), "length"),
    (_anthropic("max_tokens"), "length"),
    (_google(_GoogleReason.STOP), "stop"),          # 대조군 — 정상 종료는 잘림이 아니다
    (_openai("stop"), "stop"),
    (_anthropic("end_turn"), "stop"),
])
def test_finish_reason_is_normalized(raw, expected):
    assert finish_reason_of(raw) == expected


@pytest.mark.parametrize("raw", [None, object(), _openai(None), types.SimpleNamespace(candidates=[])])
def test_unknown_finish_reason_is_none_not_a_guess(raw):
    """모름 ≠ 정상 — 근거가 없으면 None."""
    assert finish_reason_of(raw) is None


def _client(raw, metadata=None):
    client = LLMClient(provider="google", model="test-model", api_key="test-key")
    client._initialized = True

    async def fake_call(messages, **kwargs):
        return LLMResponse(content='{"cut', provider="google", model="test-model",
                           metadata=metadata, raw_response=raw)
    client._call_google = fake_call
    return client


async def test_truncated_response_is_marked_and_warned(monkeypatch):
    warned = []
    monkeypatch.setattr(LC.logger, "warning", lambda msg, *a, **k: warned.append(str(msg)))
    response = await _client(_google(_GoogleReason.MAX_TOKENS)).invoke("q")
    assert response.metadata["truncated"] is True and response.metadata["finish_reason"] == "length"
    assert any("잘렸" in w for w in warned)


async def test_normal_response_is_not_marked_truncated(monkeypatch):
    warned = []
    monkeypatch.setattr(LC.logger, "warning", lambda msg, *a, **k: warned.append(str(msg)))
    response = await _client(_google(_GoogleReason.STOP), metadata={"keep": 1}).invoke("q")
    assert response.metadata == {"keep": 1, "finish_reason": "stop", "truncated": False}
    assert not any("잘렸" in w for w in warned)


async def test_unknown_reason_leaves_truncated_unknown():
    response = await _client(object()).invoke("q")
    assert response.metadata["finish_reason"] is None and response.metadata["truncated"] is None


# ── SDK 플래너: 기본 LLM 경로의 한도와 잘림 보고 ────────────────────────

class _FakeClient:
    def __init__(self, text, truncated):
        self.text, self.truncated, self.kwargs = text, truncated, []

    async def invoke(self, prompt, **kwargs):
        self.kwargs.append(kwargs)
        return LLMResponse(content=self.text, provider="google", model="m",
                           metadata={"truncated": self.truncated})


def _planner(client):
    from logosai.orchestration import AgentRegistry, AgentRegistryEntry, AgentSchema
    from logosai.orchestration.planner import QueryPlanner
    reg = AgentRegistry()
    reg.register_agent(AgentRegistryEntry(agent_id="alpha_agent", name="a", description="d",
                                          capabilities=[], tags=[],
                                          schema=AgentSchema(input_type="query", output_type="text")))
    planner = QueryPlanner(registry=reg)
    planner._llm_client = client
    return planner


async def test_planner_asks_for_the_same_output_budget_as_the_logos_planner():
    plan = json.dumps({"workflow_strategy": "sequential", "stages": [{"stage_id": 1,
        "execution_type": "sequential", "agents": [{"agent_id": "alpha_agent", "sub_query": "x"}]}]})
    client = _FakeClient(plan, truncated=False)
    await _planner(client).create_plan("x")
    assert client.kwargs[0].get("max_tokens") == 4096


async def test_planner_names_truncation_instead_of_a_json_error():
    from logosai.orchestration.exceptions import PlanningError
    with pytest.raises(PlanningError, match="잘렸"):
        await _planner(_FakeClient('{"workflow_strategy": "seq', truncated=True)).create_plan("x")


# ── 호출별 max_tokens 가 모든 프로바이더에서 먹는가 ──────────────────────
# 실측: google 경로만 kwargs 의 max_tokens 를 읽고, openai·anthropic 은 생성자 값만
# 썼다. 플래너가 4096 을 넘겨도 그 두 프로바이더에선 조용히 2000 이었다.

class _Capture:
    def __init__(self, response):
        self.seen, self.response = {}, response

    async def create(self, **kwargs):
        self.seen.update(kwargs)
        return self.response


def _openai_client():
    msg = types.SimpleNamespace(content="ok")
    cap = _Capture(types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=msg, finish_reason="stop")], usage=None))
    client = LLMClient(provider="openai", model="gpt-test", api_key="k")
    client._initialized = True
    client._client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=cap))
    return client, cap


def _anthropic_client():
    cap = _Capture(types.SimpleNamespace(content=[types.SimpleNamespace(text="ok")],
                                         usage=None, stop_reason="end_turn"))
    client = LLMClient(provider="anthropic", model="claude-test", api_key="k")
    client._initialized = True
    client._client = types.SimpleNamespace(messages=cap)
    return client, cap


@pytest.mark.parametrize("make", [_openai_client, _anthropic_client])
async def test_per_call_max_tokens_reaches_the_provider(make):
    client, cap = make()
    await client.invoke("q", max_tokens=4096)
    assert cap.seen["max_tokens"] == 4096


@pytest.mark.parametrize("make", [_openai_client, _anthropic_client])
async def test_constructor_max_tokens_is_the_default(make):
    """대조군 — 인자를 안 주면 생성자 값(기본 2000)."""
    client, cap = make()
    await client.invoke("q")
    assert cap.seen["max_tokens"] == client.max_tokens == 2000


# ── 도구 호출 경로 (invoke_with_tools) ────────────────────────────────
# invoke_messages 를 거치지 않아 잘림 표시가 빠졌고, openai·anthropic 은 max_tokens
# 인자도 무시했다 — 같은 결함 형태의 두 번째 배출구.

TOOLS = [{"name": "calc", "description": "계산", "parameters": {}}]


async def _no_fallback(*a, **k):
    raise AssertionError("native 도구 경로가 실패해 프롬프트 폴백으로 내려갔다 — 가짜 응답 모양을 확인")


def _openai_tools_client(reason):
    msg = types.SimpleNamespace(content="부분", tool_calls=None)
    cap = _Capture(types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=msg, finish_reason=reason)], usage=None))
    client = LLMClient(provider="openai", model="gpt-test", api_key="k")
    client._initialized = True
    client._client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=cap))
    return client, cap


def _anthropic_tools_client(reason):
    cap = _Capture(types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="부분")],
                                         usage=None, stop_reason=reason))
    client = LLMClient(provider="anthropic", model="claude-test", api_key="k")
    client._initialized = True
    client._client = types.SimpleNamespace(messages=cap)
    return client, cap


@pytest.mark.parametrize("make, cut", [(_openai_tools_client, "length"),
                                       (_anthropic_tools_client, "max_tokens")])
async def test_tool_calls_honor_max_tokens_and_mark_truncation(make, cut):
    client, cap = make(cut)
    client._call_with_tools_fallback = _no_fallback        # native 경로로 통과해야 한다
    response = await client.invoke_with_tools([{"role": "user", "content": "q"}], TOOLS, max_tokens=4096)
    assert cap.seen["max_tokens"] == 4096
    assert response.metadata["truncated"] is True


@pytest.mark.parametrize("make, ok", [(_openai_tools_client, "stop"),
                                      (_anthropic_tools_client, "end_turn")])
async def test_tool_calls_normal_stop_is_not_truncated(make, ok):
    client, cap = make(ok)
    client._call_with_tools_fallback = _no_fallback
    response = await client.invoke_with_tools([{"role": "user", "content": "q"}], TOOLS)
    assert response.metadata["truncated"] is False


async def test_google_tool_calls_mark_truncation():
    """google 도구 경로는 원응답을 싣지 않아 잘림이 '모름'(None)이었다 (실측)."""
    part = types.SimpleNamespace(text="부분", function_call=None)
    raw = types.SimpleNamespace(
        candidates=[types.SimpleNamespace(content=types.SimpleNamespace(parts=[part]),
                                          finish_reason=_GoogleReason.MAX_TOKENS)],
        usage_metadata=None, text="부분")
    client = LLMClient(provider="google", model="g-test", api_key="k")
    client._initialized = True
    client._client = types.SimpleNamespace(models=types.SimpleNamespace(
        generate_content=lambda **kw: raw))
    client._call_with_tools_fallback = _no_fallback
    response = await client.invoke_with_tools([{"role": "user", "content": "q"}], TOOLS)
    assert response.metadata["truncated"] is True
