# LogosAI

[![PyPI](https://img.shields.io/pypi/v/logosai.svg)](https://pypi.org/project/logosai/)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Build AI agents in 4 lines. Orchestrate them in 10.**

LogosAI is a Python framework for building, orchestrating, and evolving AI agents. Create a single agent with minimal code, or build a multi-agent server with built-in communication, debate, and self-evolution capabilities.

```python
pip install logosai
```

## Architecture

<p align="center">
  <img src="docs/architecture-overview.svg" alt="LogosAI System Architecture" width="100%"/>
</p>

<p align="center">
  <img src="docs/self-evolution-flow.svg" alt="Self-Evolution Flow" width="100%"/>
</p>

> **[Interactive version](https://logosai.info/architecture)** — animated data flows, clickable components, live scenario demo.

## Why LogosAI?

| | LogosAI | LangGraph | CrewAI |
|---|---------|-----------|--------|
| **Agent creation** | 4 lines (`@agent` decorator) | 30+ lines | 15+ lines |
| **Built-in server** | `SimpleACPServer` — add agents & run | Manual setup | Manual setup |
| **Agent-to-agent calls** | `self.call_agent()` — built-in | Manual wiring | Manual wiring |
| **Desktop control** | KakaoTalk, Gmail, automation | — | — |
| **Auto reports** | Scheduled search → KakaoTalk/Gmail/Telegram | — | — |
| **Agent debate** | Agents negotiate workflows via voting | — | — |
| **Self-evolution** | Agents auto-fix errors & learn | — | — |
| **LLM providers** | OpenAI, Anthropic, Gemini, Ollama | OpenAI-centric | OpenAI-centric |
| **Cross-platform** | macOS + Ubuntu | — | — |
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

### Agent-to-Agent Communication

Any agent can call another agent — built into the framework, no imports needed:

```python
class ResearchAgent(LogosAIAgent):
    async def process(self, query, context=None):
        # Search the web
        result = await self.call_agent("internet_agent", query)

        # Summarize the results
        if len(result["answer"]) > 300:
            summary = await self.call_agent("summarization_agent", result["answer"])
            return summary["answer"]

        return result["answer"]

# See all available agents
agents = self.available_agents()
# ['internet_agent', 'calculator_agent', 'llm_search_agent', ...]
```

**How it works**: The ACP server automatically injects `_agent_registry` into every agent at registration. No configuration needed — `call_agent()` is available immediately.

### Desktop Agent

Control your computer through natural language — send KakaoTalk messages, read/write Gmail, manage Notion, automate any app:

```
┌─────────────────────────────────────────────────────────┐
│  Telegram / Chat UI                                      │
│  "Check my email" / "Send KakaoTalk" / "Notion todos"   │
│         ↓                                                │
│  desktop_agent (LLM router)                              │
│  ├── mail_agent       → Gmail read/compose/reply/attach  │
│  ├── kakaotalk_agent  → AppleScript + Peekaboo           │
│  ├── notion_agent     → Notion search/read/create/todos  │
│  ├── auto_report_agent → Scheduled search + delivery     │
│  └── app_launcher     → General desktop automation       │
└─────────────────────────────────────────────────────────┘
```

**Capabilities**:

| Feature | macOS | Ubuntu |
|---------|-------|--------|
| Gmail read/compose/reply/attach | ✅ | ✅ Chrome CDP |
| Gmail file attachment | ✅ Finder copy+paste | — |
| KakaoTalk messaging | ✅ AppleScript Accessibility | ❌ No app |
| Notion read/create/search/todos | ✅ Keyboard + Vision | ✅ |
| WhatsApp messaging | ✅ URL scheme | ✅ |
| Screenshot | ✅ screencapture | ✅ scrot |
| App launch/control | ✅ | ✅ xdotool |
| Auto Reports (scheduled) | ✅ | ✅ |
| Telegram delivery | ✅ | ✅ |

**All routing is LLM-based** — no hardcoded keywords. The LLM router determines which sub-agent handles each query.

**Requirements**:
- macOS: `brew install steipete/tap/peekaboo` + Accessibility permission
- Ubuntu: `sudo apt install xdotool xclip scrot`
- Both: `pip install pyautogui Pillow`

> All dependencies are installed automatically by `install.sh`.

### Auto Reports

Schedule periodic searches delivered via KakaoTalk, Gmail, or Telegram:

```
"Every morning at 8am, search Seoul weather and send via KakaoTalk"
"Every evening at 6pm, send Bitcoin price report via email"
"Show auto report list"
"Run report #1 now"
```

**Web management UI**: `http://localhost:8010/auto-reports`

- Create, edit, delete, run reports visually
- KakaoTalk / Gmail / Telegram delivery channels
- **Conditional execution**: "Only send if Bitcoin > $80,000" — LLM evaluates conditions
- **AI summary**: Long results auto-summarized to 3-5 bullet points before delivery
- **Multi-recipient**: Send to multiple people across different channels simultaneously
- Execution history tracking with success/failure status
- Flexible scheduling (daily, weekdays, custom days)

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
| [ACP Protocol](docs/ACP_PROTOCOL.md) | Agent Communication Protocol — endpoints, call_agent(), Auto Reports API |
| [Building Agentic AI](docs/BUILDING_AGENTIC_AI.md) | Complete guide — LLM integration, collaboration, debate, evolution |
| [Building an ACP Server](docs/BUILDING_ACP_SERVER.md) | Deploy multi-agent servers with JSON-RPC + SSE |
| [Samples](samples/) | Runnable examples — includes `ResearchAgent` (call_agent() demo) |

## Requirements

**Core** (installed automatically): Python 3.11+, aiohttp, pydantic, loguru

**LLM** (`pip install logosai[llm]`): openai, anthropic, google-genai, langchain

**Desktop Agent** (installed by `install.sh`):
- macOS: Peekaboo (`brew install steipete/tap/peekaboo`), pyautogui
- Ubuntu: xdotool, xclip, scrot, pyautogui

**Full Stack**: Node.js 18+, PostgreSQL 14+

## License

[MIT](LICENSE) — Copyright (c) 2023-2026 LogosAI

## Full Stack Quick Start

Want the complete LogosAI platform (frontend + backend + agents)? Two options:

### Option A: One-command install

```bash
curl -fsSL https://raw.githubusercontent.com/maior/logosai-framework/main/install.sh | bash
```

This creates `~/logosai/`, clones all 4 repos, installs dependencies, and sets up the database.
Then start everything:

```bash
cd ~/logosai
./start.sh       # Start all services
./stop.sh        # Stop all services
./status.sh      # Check what's running
```

Requires Python 3.11+, Node.js 18+, and PostgreSQL 14+ (or Docker).

### Option B: Docker Compose

```bash
git clone https://github.com/maior/logosai-framework.git
cd logosai-framework
docker compose up
```

Includes PostgreSQL — no local database needed.

### Services

| Service | Port | What it does |
|---------|------|-------------|
| logos_web | 8010 | Next.js frontend — chat UI, auto reports management |
| logos_api | 8090 | FastAPI backend — auth, streaming, memory, Telegram bot |
| ACP Server | 8888 | Agent runtime — 50+ agents with inter-agent communication |
| PostgreSQL | 5432 | Database |

Open http://localhost:8010 to start chatting.

## Related Repositories

| Repository | Description | URL |
|-----------|-------------|-----|
| **logosai-ontology** | Multi-agent orchestration engine | [github.com/maior/logosai-ontology](https://github.com/maior/logosai-ontology) |
| **logosai-api** | FastAPI backend server | [github.com/maior/logosai-api](https://github.com/maior/logosai-api) |
| **logosai-web** | Next.js frontend | [github.com/maior/logosai-web](https://github.com/maior/logosai-web) |

## Links

- [PyPI](https://pypi.org/project/logosai/)
- [GitHub](https://github.com/maior/logosai-framework)
- [Issues](https://github.com/maior/logosai-framework/issues)
- [Samples](samples/)
