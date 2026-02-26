# LogosAI

[![PyPI](https://img.shields.io/pypi/v/logosai.svg)](https://pypi.org/project/logosai/)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Build AI agents in 4 lines. Orchestrate them in 10.**

LogosAI is a Python framework for building, orchestrating, and evolving AI agents. Create a single agent with minimal code, or build a multi-agent server with built-in communication, debate, and self-evolution capabilities.

```python
pip install logosai
```

## Why LogosAI?

| | LogosAI | LangGraph | CrewAI |
|---|---------|-----------|--------|
| **Agent creation** | 4 lines (`@agent` decorator) | 30+ lines | 15+ lines |
| **Built-in server** | `SimpleACPServer` — add agents & run | Manual setup | Manual setup |
| **Agent debate** | Agents negotiate workflows via voting | — | — |
| **Self-evolution** | Agents auto-fix errors & learn | — | — |
| **LLM providers** | OpenAI, Anthropic, Gemini, Ollama | OpenAI-centric | OpenAI-centric |
| **Streaming** | SSE + WebSocket built-in | Custom | Custom |

## Quick Start

### 1. One-Line LLM Call

No agent, no setup — just ask:

```python
import asyncio
from logosai import quick_llm

async def main():
    answer = await quick_llm("What is the capital of France?")
    print(answer)  # "The capital of France is Paris."

    # With system prompt
    result = await quick_llm(
        "Hello, how are you?",
        system_prompt="Translate to Korean.",
    )
    print(result)  # "안녕하세요, 어떻게 지내세요?"

asyncio.run(main())
```

> Requires `GOOGLE_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` in your environment.

### 2. Build an Agent (4 Lines)

The `@agent` decorator turns any async function into a full agent:

```python
import asyncio
from logosai import agent, AgentResponse

@agent(name="Joke Agent", description="Tells jokes about any topic")
async def joke_agent(query, context=None, llm=None):
    response = await llm.invoke(f"Tell a short joke about: {query}")
    return AgentResponse.success(content={"answer": response.content})

async def main():
    bot = joke_agent()
    result = await bot.process("programming")
    print(result.content["answer"])

asyncio.run(main())
```

### 3. Build an Agent (Class-Based)

`SimpleAgent` gives you more control with `ask_llm()` helper and class attributes:

```python
import asyncio
from logosai import SimpleAgent, AgentResponse

class TranslatorAgent(SimpleAgent):
    agent_name = "Translator"
    agent_description = "Translates text between languages"

    async def handle(self, query, context=None):
        translation = await self.ask_llm(f"Translate to English: {query}")
        return AgentResponse.success(content={"answer": translation})

async def main():
    agent = TranslatorAgent()
    result = await agent.process("안녕하세요, 반갑습니다")
    print(result.content["answer"])

asyncio.run(main())
```

### 4. Run a Multi-Agent Server

Host multiple agents with JSON-RPC + SSE streaming in ~10 lines:

```python
from logosai import SimpleAgent, AgentResponse
from logosai.acp import SimpleACPServer

class GreetingAgent(SimpleAgent):
    agent_name = "Greeting Agent"
    agent_description = "Greets users"

    async def handle(self, query, context=None):
        return AgentResponse.success(content={"answer": f"Hello! You said: {query}"})

class MathAgent(SimpleAgent):
    agent_name = "Math Agent"
    agent_description = "Solves math problems"
    llm_temperature = 0.0

    async def handle(self, query, context=None):
        answer = await self.ask_llm(f"Calculate and return ONLY the result: {query}")
        return AgentResponse.success(content={"answer": answer})

server = SimpleACPServer(port=9000)
server.add(GreetingAgent())
server.add(MathAgent())
server.run()
```

Test it:

```bash
# List agents
curl localhost:9000/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"list_agents"}'

# Query an agent
curl localhost:9000/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"process","params":{"query":"3+5","agent_id":"math_agent"}}'

# SSE streaming
curl -N "localhost:9000/stream?query=Hello&agent_id=greeting_agent"
```

### 5. Use the LLM Client Directly

Unified client for multiple providers:

```python
import asyncio
from logosai import LLMClient

async def main():
    client = LLMClient(provider="google", model="gemini-2.5-flash-lite")
    await client.initialize()

    # Single prompt
    response = await client.invoke("Explain async/await in Python")
    print(response.content)

    # Chat-style messages
    response = await client.invoke_messages([
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is Python?"},
    ])
    print(response.content)

asyncio.run(main())
```

Supported providers: `openai`, `anthropic`, `google` (Gemini), `ollama`

## Installation

```bash
pip install logosai          # Core framework
pip install logosai[llm]     # + LLM providers (OpenAI, Anthropic, Gemini)
pip install logosai[all]     # + All optional dependencies
```

From source:

```bash
git clone https://github.com/maior/logosai-framework.git
cd logosai-framework
pip install -e ".[llm]"
```

## Features

### Core

- **`SimpleAgent`** — Subclass with `agent_name`, `agent_description`, and `handle()`. Auto-manages init, LLM, errors, and ACP compatibility
- **`@agent` decorator** — Turn an async function into a full agent in 4 lines
- **`quick_llm()`** — One-shot LLM call with no setup
- **`LLMClient`** — Unified client for OpenAI, Anthropic, Google Gemini, Ollama
- **`LogosAIAgent`** — Full-featured base class with async lifecycle (`initialize`, `process`, `shutdown`)

### Multi-Agent Orchestration

- **SimpleACPServer** — Host agents with JSON-RPC + SSE streaming
- **Message Bus** — Pub/sub messaging with topic routing and priorities
- **Workflow Engine** — Sequential, parallel, and hybrid execution strategies
- **Agent Collaboration** — Coordinated multi-agent task execution

### Agent Debate System

Agents autonomously negotiate and decide on workflows through voting:

```python
from logosai.debate import SimpleDebateSystem

debate = SimpleDebateSystem()
result = await debate.start_debate(
    query="Analyze Q4 sales data and generate a forecast report.",
    agents=my_agents,
)
print(result.workflow)  # Agreed-upon execution plan
```

**5-phase process**: Query Analysis → Role Proposal → Discussion → Voting → Consensus

### Agent Self-Evolution

Agents that learn, heal, and improve autonomously:

```python
from logosai.evolution import EvolutionSystem, EvolutionConfig

config = EvolutionConfig(enabled=True, llm_provider="google")
evolution = EvolutionSystem(agent, config)
await evolution.enable()

result = await evolution.evolve(
    query="Convert 100 USD to KRW",
    response="Not supported",
)
# result.improvements → suggested code fixes
```

**Capabilities**: Self-Healing · Self-Growing · Self-Evaluation

**Safety**: Circuit Breaker (3 failures → 1h cooldown) · Confidence Gates (4-tier validation) · Fix History (cycle prevention)

### Agentic AI Modules

| Module | Purpose |
|--------|---------|
| `AgenticReasoning` | Chain-of-thought planning |
| `AgenticTools` | Tool registration and execution |
| `AgenticMemory` | Short-term and long-term memory |
| `AgenticLearning` | Learning from interactions |

### Template Engine

Generate agent code from built-in templates:

```python
from logosai.template_engine import TemplateEngine

engine = TemplateEngine()
code = engine.render("basic_agent", name="WeatherAgent", description="Fetches weather data")
```

Templates: `basic_agent`, `async_agent`, `workflow_agent`, `database_agent`, `singleton_agent`

## Documentation

| Guide | Description |
|-------|-------------|
| [Building Agentic AI](docs/BUILDING_AGENTIC_AI.md) | Complete guide — LLM integration, collaboration, debate, evolution |
| [Building an ACP Server](docs/BUILDING_ACP_SERVER.md) | Deploy multi-agent servers with JSON-RPC + SSE |
| [Samples](samples/) | Runnable examples for every feature |

## Requirements

**Core** (installed automatically): Python 3.8+, aiohttp, pydantic, loguru

**Optional** (`pip install logosai[llm]`): openai, anthropic, google-generativeai, langchain

## License

[MIT](LICENSE) — Copyright (c) 2023-2026 LogosAI

## Links

- [PyPI](https://pypi.org/project/logosai/)
- [GitHub](https://github.com/maior/logosai-framework)
- [Issues](https://github.com/maior/logosai-framework/issues)
- [Samples](samples/)
