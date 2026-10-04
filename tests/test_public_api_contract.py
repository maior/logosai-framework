"""공개 API 계약 — README 가 약속한 사용법이 그대로 동작하는가.

왜 있나: 오케스트레이터를 SDK 로 옮기는 작업(orchestrator-unify) 동안
"설치해서 쓰는 사용자 코드는 한 줄도 바뀌지 않는다"를 보증하는 안전망이다.
그리고 README 가 이미 한 번 어긋났다 — 존재하지 않는 `PulseClient` 를
광고하고 있었다(2026-10-04). 문서의 코드는 실행되지 않으면 조용히 낡는다.

원칙: LLM·네트워크를 부르지 않는다(가짜 LLM, 프로세스 안 서버).
내부 구현이 아니라 이름·호출 모양·관찰 가능한 결과만 본다.
"""
import importlib
import inspect
import json
import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parents[1] / "README.md"

#: README 에 등장하지만 logosai 가 아닌 별도 패키지 — 이 계약의 대상이 아니다
EXTERNAL_PACKAGES = {"logosai_forge"}


def _python_blocks():
    return re.findall(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), re.S)


def _readme_imports():
    out = []
    for i, block in enumerate(_python_blocks(), 1):
        for mod, names in re.findall(
            r"^\s*from\s+(logosai[\w\.]*)\s+import\s+([^\n#]+)", block, re.M
        ):
            if mod.split(".")[0] in EXTERNAL_PACKAGES:
                continue
            for name in names.replace("(", "").replace(")", "").split(","):
                name = name.strip().split(" as ")[0]
                if name:
                    out.append((i, mod, name))
    return out


class FakeLLM:
    """LLMClient 대역 — 받은 프롬프트를 기록하고 고정 답을 돌려준다."""

    _initialized = True

    def __init__(self, answer="FAKE-ANSWER"):
        self.answer = answer
        self.prompts = []

    async def invoke(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return type("Resp", (), {"content": self.answer})()

    async def invoke_messages(self, messages, **kwargs):
        self.prompts.append(messages[-1]["content"])
        return type("Resp", (), {"content": self.answer})()


# ── 1. README 의 import 가 전부 실재한다 ─────────────────────────────

def test_readme_parser_finds_what_it_should():
    """대조군 — 파서가 고장 나 0개를 찾으면 아래 검사는 공허하게 통과한다."""
    assert len(_python_blocks()) >= 8
    assert len(_readme_imports()) >= 10


@pytest.mark.parametrize("block,module,name", _readme_imports())
def test_readme_imports_resolve(block, module, name):
    assert _resolves(module, name), f"README 블록 {block}: {module}.{name} 이 존재하지 않는다"


def _resolves(module, name):
    """`from module import name` 과 같은 규칙 — 속성이거나 하위 모듈이면 된다."""
    if hasattr(importlib.import_module(module), name):
        return True
    try:
        importlib.import_module(f"{module}.{name}")
        return True
    except ModuleNotFoundError:
        return False


def test_resolver_rejects_missing_names():
    """대조군 — 판정기가 없는 이름을 통과시키면 위 검사는 공허하다."""
    assert _resolves("logosai.utils", "pulse_client")
    assert not _resolves("logosai.utils.pulse_client", "PulseClient")


@pytest.mark.parametrize("fn,kwargs", [
    ("send_execution", {"agent_id": "my_agent", "query": "q", "success": True, "duration_ms": 120}),
    ("send_llm_call", {"agent_id": "my_agent", "model": "m", "input_tokens": 1,
                       "output_tokens": 1, "duration_ms": 1}),
    ("send_span", {"trace_id": "t", "parent_id": "p", "name": "tool.search", "duration_ms": 40}),
])
def test_readme_pulse_call_shapes(fn, kwargs):
    from logosai.utils import pulse_client
    inspect.signature(getattr(pulse_client, fn)).bind(**kwargs)


# ── 2. 에이전트 정의 — README 블록 2·3 ────────────────────────────────

async def test_agent_decorator_readme_shape():
    from logosai import AgentResponse, agent

    @agent(name="Joke Agent", description="Tells jokes about any topic")
    async def joke_agent(query, context=None, llm=None):
        response = await llm.invoke(f"Tell a short joke about: {query}")
        return AgentResponse.success(content={"answer": response.content})

    instance = joke_agent()
    fake = FakeLLM("a cat joke")
    instance.llm_client = fake

    result = await instance.process("cats")

    assert isinstance(result, AgentResponse)
    assert result.content["answer"] == "a cat joke"
    assert any("cats" in p for p in fake.prompts), "데코레이트된 함수가 query 를 받지 못했다"


async def test_simple_agent_readme_shape():
    from logosai import AgentResponse, SimpleAgent

    class TranslatorAgent(SimpleAgent):
        agent_name = "Translator"
        agent_description = "Translates text between languages"

        async def handle(self, query, context=None):
            translation = await self.ask_llm(f"Translate to English: {query}")
            return AgentResponse.success(content={"answer": translation})

    instance = TranslatorAgent()
    fake = FakeLLM("hello")
    instance.llm_client = fake

    result = await instance.process("안녕")

    assert result.content["answer"] == "hello"
    assert fake.prompts == ["Translate to English: 안녕"]


# ── 3. ACP 서버 — README 블록 4 + logos_api 가 읽는 응답 모양 ──────────

async def test_simple_acp_server_contract():
    from aiohttp.test_utils import TestClient, TestServer

    from logosai import AgentResponse, SimpleAgent
    from logosai.acp import SimpleACPServer

    class EchoAgent(SimpleAgent):
        agent_name = "Echo Agent"
        agent_description = "Uppercases the query (no LLM)"

        async def handle(self, query, context=None):
            return AgentResponse.success(content={"answer": str(query).upper()})

    server = SimpleACPServer(port=0)
    agent_id = server.add(EchoAgent())
    client = TestClient(TestServer(server._create_app()))
    await client.start_server()
    try:
        r = await client.post(
            "/jsonrpc", json={"jsonrpc": "2.0", "id": 1, "method": "list_agents"}
        )
        listed = (await r.json())["result"]["agents"]
        assert agent_id in [a["agent_id"] for a in listed]

        # logos_api `_execute_agent_via_acp` 와 같은 요청·같은 파싱
        r = await client.post(
            "/stream", json={"query": "hello", "agent_id": agent_id, "context": {}}
        )
        assert r.status == 200
        completes = []
        for chunk in (await r.text()).split("\n\n"):
            event = data = None
            for line in chunk.splitlines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:])
            if (event or (data or {}).get("type")) in ("complete", "final_result"):
                completes.append(data.get("data", data))
        assert completes, "logos_api 가 결과로 읽는 complete 이벤트가 없다"
        assert completes[-1]["result"]["answer"] == "HELLO"
    finally:
        await client.close()


# ── 4. mixin 메서드 — README 블록 6·7 의 호출 모양 그대로 ─────────────

_README_CALLS = [
    # (메서드, 위치 인자, 키워드 인자) — README 에 적힌 그대로
    ("call_agent", ("internet_agent", "Seoul weather"), {}),
    ("ask_opinion", ("analysis_agent", "Is this a seasonal pattern?"),
     {"my_analysis": {"pattern": "March spike"}}),
    ("share_learning", (), {"pattern": "p", "solution": "s", "tags": ["gmail"]}),
    ("get_learnings", (), {"tags": ["gmail"]}),
    ("react", ("Calculate compound interest",), {"tools": [], "tool_executors": {}}),
    ("memorize", ("user_pref", "User prefers Korean"), {"importance": 0.9}),
    ("recall", ("user",), {}),
    ("plan", ("Build a web scraper",), {}),
    ("plan_stream", ("Build a web scraper",), {}),
    ("ask_llm_structured", ("Seoul weather", dict), {}),
    ("spawn_agent", ("translator", "Translates text", lambda q: q), {}),
    ("delegate", ([{"agent_id": "translator", "query": "Hello"}],), {"parallel": True}),
    ("ask_llm_stream", ("Tell me about AI",), {}),
    ("register_tool", ("calc", "Calculator", lambda: 0, {}), {}),
    ("forget", ("user_pref",), {}),
]


@pytest.fixture(scope="module")
def readme_agent():
    from logosai import SimpleAgent

    class Probe(SimpleAgent):
        agent_name = "Probe"

    return Probe()


@pytest.mark.parametrize("method,args,kwargs", _README_CALLS, ids=[c[0] for c in _README_CALLS])
def test_mixin_call_shape_matches_readme(readme_agent, method, args, kwargs):
    fn = getattr(readme_agent, method, None)
    assert callable(fn), f"README 가 쓰는 {method}() 가 없다"
    inspect.signature(fn).bind(*args, **kwargs)  # 호출 모양이 안 맞으면 TypeError


def test_call_shape_check_rejects_wrong_shape(readme_agent):
    """대조군 — bind 가 아무거나 통과시키면 위 검사는 공허하다."""
    with pytest.raises(TypeError):
        inspect.signature(readme_agent.memorize).bind(no_such_keyword=1)
