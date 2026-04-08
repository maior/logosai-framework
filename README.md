# LogosAI

[![PyPI](https://img.shields.io/pypi/v/logosai.svg)](https://pypi.org/project/logosai/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Build AI agents in 4 lines. Orchestrate 63+ agents. Self-evolving. Observable.**

LogosAI is a Python framework for building, orchestrating, and evolving AI agents. Create a single agent with minimal code, or build a multi-agent system where agents collaborate, debate, learn from each other, and improve themselves autonomously — with full observability via LogosPulse.

```bash
pip install logosai
```

## Architecture

<p align="center">
  <img src="https://raw.githubusercontent.com/maior/logosai-framework/main/docs/architecture-overview.svg" alt="LogosAI System Architecture" width="100%"/>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/maior/logosai-framework/main/docs/self-evolution-flow.svg" alt="Self-Evolution Flow" width="100%"/>
</p>

## Why LogosAI?

| | LogosAI | LangGraph | CrewAI | OpenAI SDK | OpenClaw | Claude Agent SDK | Google ADK |
|---|---------|-----------|--------|------------|----------|-----------------|------------|
| **Agent creation** | 4 lines | 30+ lines | 15+ lines | 10+ lines | — | 10+ lines | 10+ lines |
| **Tool Use (function calling)** | ✅ Auto-inject | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **ReAct (Think→Act→Observe)** | ✅ `react()` | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| **Persistent Memory** | ✅ PostgreSQL/SQLite + embedding search | ✅ | ✅ | Limited | Local | Limited | Limited |
| **LLM Streaming** | ✅ Token-by-token | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| **Structured Output** | ✅ Pydantic schema | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| **Error Recovery** | ✅ @retry + re-prompt | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| **Self-evolution** | ✅ Auto-fix + deploy | — | — | — | — | — | — |
| **Observability** | ✅ LogosPulse (OTel-style traces) | Partial | — | — | — | — | ✅ OTel native |
| **Desktop control** | ✅ Gmail, KakaoTalk, Notion | — | — | — | ✅ 20+ channels | — | — |
| **Browser search** | ✅ Real Chrome | — | — | — | ✅ | — | — |
| **Agent-to-agent** | ✅ `call_agent()` built-in | Manual | Manual | — | — | ✅ | ✅ |
| **Agent debate** | ✅ 5-phase voting | — | — | — | — | — | — |
| **Sub-agent spawn** | ✅ `spawn_agent()` | ✅ | ✅ | — | — | ✅ | ✅ |
| **Mixin architecture** | ✅ Composable mixins | — | — | — | — | — | — |
| **Ontology-based routing** | ✅ GNN+RL+KG | — | — | — | — | — | — |
| **LLM providers** | OpenAI, Anthropic, Gemini, Ollama | OpenAI-centric | OpenAI-centric | OpenAI only | Multiple | Claude only | Google-centric |

## Quick Start

### 1. One-Line LLM Call

```python
import asyncio
from logosai import quick_llm

async def main():
    answer = await quick_llm("What is the capital of France?")
    print(answer)  # "The capital of France is Paris."

asyncio.run(main())
```

### 2. Build an Agent (4 Lines)

```python
from logosai import agent, AgentResponse

@agent(name="Joke Agent", description="Tells jokes about any topic")
async def joke_agent(query, context=None, llm=None):
    response = await llm.invoke(f"Tell a short joke about: {query}")
    return AgentResponse.success(content={"answer": response.content})
```

### 3. Build an Agent (Class-Based)

```python
from logosai import SimpleAgent, AgentResponse

class TranslatorAgent(SimpleAgent):
    agent_name = "Translator"
    agent_description = "Translates text between languages"

    async def handle(self, query, context=None):
        translation = await self.ask_llm(f"Translate to English: {query}")
        return AgentResponse.success(content={"answer": translation})
```

### 4. Run a Multi-Agent Server

```python
from logosai import SimpleAgent, AgentResponse
from logosai.acp import SimpleACPServer

class MathAgent(SimpleAgent):
    agent_name = "Math Agent"
    agent_description = "Solves math problems"

    async def handle(self, query, context=None):
        answer = await self.ask_llm(f"Calculate: {query}")
        return AgentResponse.success(content={"answer": answer})

server = SimpleACPServer(port=9000)
server.add(MathAgent())
server.run()
```

```bash
# List agents
curl localhost:9000/jsonrpc -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"list_agents"}'

# SSE streaming
curl -N "localhost:9000/stream?query=3+5&agent_id=math_agent"
```

### 5. LLM Client (Multi-Provider)

```python
from logosai import LLMClient

client = LLMClient(provider="google", model="gemini-2.5-flash-lite")
await client.initialize()

response = await client.invoke("Explain async/await in Python")
print(response.content)
```

Supported: `openai`, `anthropic`, `google` (Gemini), `ollama`

## Installation

```bash
pip install logosai          # Core framework
pip install logosai[llm]     # + LLM providers (OpenAI, Anthropic, Gemini)
pip install logosai[all]     # + All optional dependencies
```

## Features

### Core
- **`@agent` decorator** — 4-line agent creation
- **`SimpleAgent`** — Class-based with `ask_llm()` helper
- **`quick_llm()`** — One-shot LLM call
- **`LLMClient`** — Unified multi-provider client (OpenAI, Anthropic, Gemini, Ollama)
- **`LogosAIAgent`** — Full-featured base with async lifecycle and mixin composition

### Multi-Agent Orchestration
- **SimpleACPServer** — Host agents with JSON-RPC + SSE streaming
- **Message Bus** — Pub/sub with topic routing and priorities
- **Workflow Engine** — Sequential, parallel, hybrid with enriched data pipeline
- **Dynamic Routing** — Tag-based auto-discovery, no hardcoded routes
- **Data Flow** — Previous agent results automatically injected into next agent's query
- **Document Search** — Semantic search across project docs (LLM-indexed, "where is this info?")

### Agent Communication (4 Levels)

```
L1: call_agent()      — Data passing (query → result)
L2: Debate System     — 5-phase workflow negotiation (propose → vote → consensus)
L3: Collaboration     — ask_opinion(), share_finding(), request_help()
L4: Learning          — share_learning(), get_learnings() (persisted across sessions)
```

```python
# L1: Call another agent
result = await self.call_agent("internet_agent", "Seoul weather")

# L3: Ask for opinion (not just data — shares reasoning)
opinion = await self.ask_opinion("analysis_agent",
    "Is this a seasonal pattern?",
    my_analysis={"pattern": "March spike", "confidence": 0.6})

# L4: Share what you learned (persisted for all agents)
await self.share_learning(
    pattern="Gmail compose overlay breaks JS selectors",
    solution="Add &fs=1 to compose URL",
    tags=["gmail", "chrome"])

# L4: Learn from others
learnings = await self.get_learnings(tags=["gmail"])
```

### Agentic AI (v0.12) — Mixin Architecture

`LogosAIAgent` is built from five composable mixins, each independently usable:

| Mixin | File | Capabilities |
|-------|------|--------------|
| **ToolUseMixin** | `mixins/tool_use.py` | `register_tool()`, `run_with_tools()`, `register_tool_object()` |
| **MemoryMixin** | `mixins/memory.py` | `memorize()`, `recall()`, `forget()` — embedding hybrid search |
| **ReactMixin** | `mixins/react.py` | `react()` — Think→Act→Observe loop |
| **PlanningMixin** | `mixins/planning.py` | `plan()`, `plan_stream()` — Goal decomposition tree |
| **MultiAgentMixin** | `mixins/multi_agent.py` | `call_agent()`, `delegate()`, `spawn_agent()` |

```python
# Tool Use — 3 ways to register tools
agent.register_tool("calc", "Calculator", calc_func, params)          # existing
agent.register_tool_object(Tool(name="calc", category="math", ...))   # new: Tool dataclass
agent.register_tool_object(@tool_decorator(...))                       # new: auto-parse signature

# ReAct — Think → Act → Observe loop
result = await agent.react(
    "Calculate compound interest: $10K at 8% for 5 years, then convert to KRW",
    tools=BUILTIN_TOOLS, tool_executors=BUILTIN_EXECUTORS,
)
# → Thought: "Need to calculate compound interest"
# → Action: calculator(10000 * 1.08**5) → $14,693
# → Thought: "Now convert to KRW"
# → Action: calculator(14693 * 1380) → ₩20,276,340
# → Final Answer: "₩20,276,340"

# Persistent Memory — embedding hybrid search
await agent.memorize("user_pref", "User prefers Korean", importance=0.9)
memories = await agent.recall("user")  # Auto-injected into LLM context
# Semantic: query "수도 날씨" finds memory "서울 기온" via cosine similarity

# Goal Decomposition
plan = await agent.plan("Build a web scraper for news articles")
# → Sub-goals: fetch → parse → store → deduplicate → schedule
async for step in agent.plan_stream("Build a web scraper"):
    print(step)  # Streams decomposition steps in real-time

# Structured Output — enforce JSON schema
from pydantic import BaseModel
class Weather(BaseModel):
    city: str
    temperature: float

result = await agent.ask_llm_structured("Seoul weather", Weather)
# → Weather(city="Seoul", temperature=22.5)

# Dynamic Sub-Agent — create specialists at runtime
translator = agent.spawn_agent("translator", "Translates text", my_func)
results = await agent.delegate([
    {"agent_id": "translator", "query": "Hello"},
    {"agent_id": "calculator", "query": "1+1"},
], parallel=True)

# LLM Streaming — token-by-token
async for chunk in agent.ask_llm_stream("Tell me about AI"):
    print(chunk, end="")
```

**Capabilities**: Tool Use · ReAct · Memory (embedding search) · Goal Decomposition · Streaming · Structured Output · Error Recovery · Context Management

### Document Generation — Desktop Native

Generate professional documents through natural language:

```
"SpaceX 회사 정보를 PPT로 만들어줘"
→ internet_agent (search) → pptx_generator_agent (generate)
→ PowerPoint opens and builds slides in real-time

"Docker 매뉴얼을 워드로 만들어줘"
→ docx_generator_agent → Word document with tables, charts, metrics
```

| Feature | Details |
|---------|---------|
| **PPT Generation** | 101 themes × 15 layouts, Desktop Native (AppleScript) + python-pptx fallback |
| **DOCX Generation** | 8 doc_types × 8 themes, Hybrid mode (python-docx tables + Desktop Native text) |
| **Google Maps** | Place search + directions + interactive map rendering |
| **File Search** | Spotlight + find + grep — local filesystem search with content matching |
| **Capability Protocol** | Agent auto-composition via DAG (Level B composite + Level C autonomous) |

### Observability — LogosPulse

OpenTelemetry-style tracing and metrics for every agent execution:

```
Root Span (agent.process)
├── LLM Span (llm.gemini-2.5-flash-lite) — intent extraction      ~120ms
└── LLM Span (llm.gemini-2.5-flash-lite) — response generation    ~1.8s
```

```python
from logosai.utils.pulse_client import PulseClient

# Fire-and-forget — zero overhead (~0.01ms/span)
pulse = PulseClient(endpoint="http://localhost:8095")
await pulse.record_execution(agent_id, query, result, duration_ms)
await pulse.record_llm_call(model, tokens_in, tokens_out, latency_ms)
await pulse.record_span(trace_id, parent_id, name, metadata)
```

**Dashboard** (port 8096): Execution history · LLM cost tracking · Span tree visualization · User feedback (👍/👎) · Adaptive learning loop

### Self-Evolution

```python
from logosai.evolution import EvolutionSystem, EvolutionConfig

config = EvolutionConfig(enabled=True, llm_provider="google")
evolution = EvolutionSystem(agent, config)
await evolution.enable()
```

**Capabilities**: Self-Healing · Self-Growing · Self-Evaluation

**Safety**: Circuit Breaker (3 failures → 1h cooldown) · Confidence Gates · Fix History

### FORGE Agent Builder (Optional)

```bash
pip install logosai-forge
```

```python
from logosai_forge import ForgeClient

forge = ForgeClient()
result = await forge.create_agent("Calculate BMI from weight and height")
result = await forge.improve_agent(code, failure_log)      # Fix bugs
result = await forge.enhance_agent(code, "add caching")    # Add features
```

Autonomous evolution loop:
```
Agent fails → FailureLogger → 30% threshold → FORGE improves
→ Confidence Gate (≥0.95) → RollbackManager backup
→ hot_register (zero-downtime deploy) → EvolutionMonitor tracks
```

### Desktop Agent

Control your desktop through natural language — 63+ agents, each independent:

```
desktop_agent (dynamic LLM router — no hardcoded routes)
├── call_agent("kakaotalk_agent")       → KakaoTalk messaging
├── call_agent("mail_desktop_agent")    → Gmail read/compose/attach
├── call_agent("notion_desktop_agent")  → Notion pages/todos
├── call_agent("multi_ai_inquiry_agent") → ChatGPT/Claude/Gemini compare
├── call_agent("auto_report_agent")     → Scheduled search + delivery
└── screen_analyzer (lightweight 0.1s + Vision 3s fallback)
```

| Feature | macOS | Ubuntu |
|---------|-------|--------|
| Gmail read/compose/reply/attach | ✅ | ✅ Chrome CDP |
| KakaoTalk messaging | ✅ AppleScript | ❌ |
| Notion read/create/todos | ✅ Keyboard + Vision | ✅ |
| Multi-AI Inquiry | ✅ App + Chrome | ✅ Chrome |
| Auto Reports (scheduled) | ✅ | ✅ |
| ScreenAnalyzer (lightweight + Vision) | ✅ | ✅ |
| Intent Verification | ✅ | ✅ |

**ScreenAnalyzer**: Lightweight check first (~0.1s AppleScript/JS) → Vision fallback only when needed (~3s). **Intent Verification**: verifies all preconditions before irreversible actions. **No Trace**: closes windows and restores previous app after completion (Cmd+W, not Cmd+Q).

### Auto Reports

```
"Every morning at 8am, search Seoul weather and send via KakaoTalk"
"If Bitcoin exceeds $80,000, notify me by email"
```

Conditional execution · AI summary · Multi-channel (KakaoTalk/Gmail/Telegram)

Web management: `http://localhost:8010/auto-reports`

## Testing

54 tests across framework core, Agentic AI, and observability:

```bash
pytest logosai/tests/ -v           # Framework + Agentic AI tests
pytest logos_pulse/tests/ -v      # Observability + tracing tests
```

Key coverage: Tool Use · ReAct · Persistent Memory · Goal Decomposition · Span Tracing · Feedback API · Learning Loop · SSE Bidirectional · Interaction Engine (31 tests + 7 evaluations)

## Documentation

| Guide | Description |
|-------|-------------|
| [ACP Protocol](docs/ACP_PROTOCOL.md) | Agent Communication Protocol — endpoints, call_agent(), Auto Reports |
| [Building Agentic AI](docs/BUILDING_AGENTIC_AI.md) | LLM integration, collaboration, debate, evolution |
| [Building an ACP Server](docs/BUILDING_ACP_SERVER.md) | Deploy multi-agent servers with JSON-RPC + SSE |
| [Samples](samples/) | Runnable examples — ResearchAgent, calculator, hello world |

## Full Stack Quick Start

**macOS:**
```bash
curl -fsSL https://raw.githubusercontent.com/maior/logosai-framework/main/install-macos.sh | bash
```

**Ubuntu / Debian:**
```bash
curl -fsSL https://raw.githubusercontent.com/maior/logosai-framework/main/install-ubuntu.sh | bash
```

```bash
cd ~/logosai
./start.sh       # Start all services
./stop.sh        # Stop all services
./status.sh      # Check what's running
```

| Service | Port | Description |
|---------|------|-------------|
| logos_web | 8010 | Next.js frontend — chat, [admin](/admin), auto reports, [architecture](/architecture) |
| logos_api | 8090 | FastAPI backend — auth, streaming, memory, Telegram bot |
| ACP Server | 8888 | Agent runtime — 63+ agents, self-evolution, L3/L4, Desktop Native |
| LogosPulse API | 8095 | Observability backend — execution traces, LLM metrics, costs |
| LogosPulse UI | 8096 | Observability dashboard — span tree, feedback, learning loop |
| PostgreSQL | 5432 | Database |

## Requirements

**Core**: Python 3.11+, aiohttp, pydantic, loguru

**LLM** (`pip install logosai[llm]`): openai, anthropic, google-genai, langchain

**Desktop Agent**: macOS: Peekaboo + Accessibility · Ubuntu: xdotool, xclip, scrot

**Full Stack**: Node.js 18+, PostgreSQL 14+

## Related Repositories

| Repository | Description |
|-----------|-------------|
| [logosai-ontology](https://github.com/maior/logosai-ontology) | Multi-agent orchestration (GNN+RL+KG+LLM) |
| [logosai-api](https://github.com/maior/logosai-api) | FastAPI backend server |
| [logosai-web](https://github.com/maior/logosai-web) | Next.js frontend |
| [logosai-pulse](https://github.com/maior/logosai-pulse) | Agent Observability (traces, metrics, feedback) |

## License

[MIT](LICENSE) — Copyright (c) 2023-2026 LogosAI

---

[PyPI](https://pypi.org/project/logosai/) · [GitHub](https://github.com/maior/logosai-framework) · [Issues](https://github.com/maior/logosai-framework/issues) · [Samples](samples/)
