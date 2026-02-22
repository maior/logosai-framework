# LogosAI

[![Version](https://img.shields.io/badge/version-0.9.0-blue.svg)](https://github.com/maior/logosai-framework)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A Python framework for building, orchestrating, and evolving AI agents.

## Installation

```bash
pip install logosai
```

With LLM provider support:

```bash
pip install logosai[llm]   # OpenAI, Anthropic, Google Gemini, LangChain
pip install logosai[all]   # All optional dependencies
```

Or install from source:

```bash
git clone https://github.com/maior/logosai-framework.git
cd logosai-framework
pip install -e .
```

## Quick Start

### The Easiest Way (v0.9.0)

```python
from logosai import quick_llm

answer = await quick_llm("What is the capital of France?")
# → "Paris"
```

### SimpleAgent — Zero Boilerplate

```python
import asyncio
from logosai import SimpleAgent, AgentResponse

class GreetingAgent(SimpleAgent):
    agent_name = "Greeting Agent"
    agent_description = "Generates friendly greetings"

    async def handle(self, query, context=None):
        greeting = await self.ask_llm(f"Generate a greeting for: {query}")
        return AgentResponse.success(content={"answer": greeting})

async def main():
    agent = GreetingAgent()
    result = await agent.process("Alice")
    print(result.content["answer"])

asyncio.run(main())
```

### @agent Decorator — Even Simpler

```python
from logosai import agent, AgentResponse

@agent(name="Joke Agent", description="Tells jokes")
async def joke_agent(query, context=None, llm=None):
    response = await llm.invoke(f"Tell a joke about: {query}")
    return AgentResponse.success(content={"answer": response.content})

instance = joke_agent()
result = await instance.process("cats")
```

### Classic LogosAIAgent

```python
import asyncio
from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType

class MyAgent(LogosAIAgent):
    def __init__(self):
        config = AgentConfig(
            name="My Agent",
            agent_type=AgentType.CUSTOM,
            description="A simple custom agent",
        )
        super().__init__(config)

    async def process(self, query: str, context=None) -> AgentResponse:
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": f"Processed: {query}"},
            message="Done",
        )

async def main():
    agent = MyAgent()
    await agent.initialize()
    result = await agent.process("Hello, world!")
    print(result.content["answer"])

if __name__ == "__main__":
    asyncio.run(main())
```

See the [samples/](samples/) directory for more examples.

## Documentation

| Guide | Description |
|-------|-------------|
| [Building Agentic AI](docs/BUILDING_AGENTIC_AI.md) | Complete guide to creating intelligent agents with LLM, collaboration, debate, and evolution |
| [Building an ACP Server](docs/BUILDING_ACP_SERVER.md) | How to build and deploy ACP servers that host and orchestrate agents |
| [Samples](samples/) | Minimal working examples — SimpleAgent, @agent decorator, quick_llm, and more |

## Features

### SimpleAgent & Utilities (v0.9.0)

Zero-boilerplate agent development:

- **`SimpleAgent`** — Subclass with just `agent_name`, `agent_description`, and `handle()`. Auto-manages init, LLM setup, error handling, and ACP compatibility
- **`@agent` decorator** — Convert an async function into a full agent in 4 lines
- **`quick_llm()`** — One-shot LLM call with no setup: `await quick_llm("question")`
- **`ask_llm()` / `ask_llm_json()`** — Convenience methods on SimpleAgent for LLM calls
- **Text utilities** — `parse_llm_json()`, `clean_markdown_code()`, `extract_code_block()`, `truncate_for_prompt()`

### Core Agent Framework

- **LogosAIAgent** base class with async lifecycle management (`initialize`, `process`, `shutdown`)
- **AgentConfig** for flexible, config-driven agent behavior
- **AgentResponse** with typed results (`SUCCESS`, `ERROR`, `PARTIAL`)
- Multi-provider LLM client (OpenAI, Anthropic, Google Gemini, Ollama)

### Multi-Agent Orchestration

- **Message Bus** — pub/sub messaging with topic routing, priorities, and correlation IDs
- **Workflow Engine** — sequential, parallel, and hybrid execution strategies
- **Agent Router** — request routing with fallback chains
- **Agent Collaboration** — coordinated multi-agent task execution

### Agent Debate System (v0.5.0)

Autonomous multi-agent negotiation for workflow decisions:

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

### Agent Self-Evolution (v0.7.0)

Agents that learn and improve autonomously:

```python
from logosai.evolution import EvolutionSystem, EvolutionConfig

config = EvolutionConfig(enabled=True, llm_provider="google")
evolution = EvolutionSystem(agent, config)
await evolution.enable()

result = await evolution.evolve(query="Convert 100 USD to KRW", response="Not supported")
# result.improvements → suggested fixes
```

**Capabilities**: Self-Healing (auto-fix errors) · Self-Growing (add features) · Self-Evaluation (quality scoring)

**Safety**: Circuit Breaker (3 failures → 1h cooldown) · Confidence Gates (4-tier validation) · Fix History (cycle prevention)

### Agentic AI Modules

Advanced reasoning and memory for agents:

```python
from logosai.agentic import AgenticCore, AgenticReasoning, AgenticMemory

reasoning = AgenticReasoning()
chain = await reasoning.create_chain("Complex multi-step task...")
```

| Module | Purpose |
|--------|---------|
| `AgenticCore` | Core reasoning engine |
| `AgenticReasoning` | Chain-of-thought planning |
| `AgenticTools` | Tool registration and execution |
| `AgenticMemory` | Short-term and long-term memory |
| `AgenticLearning` | Learning from interactions |

### ACP (Agent Communication Protocol)

Standard protocol for agent-to-agent communication:

- **JSON-RPC** endpoint for agent discovery and invocation
- **SSE streaming** for real-time processing events
- **WebSocket** for bidirectional communication

```python
from logosai.acp import ACPClient

client = ACPClient(endpoint="http://localhost:8888")
agents = await client.list_agents()
result = await client.query("calculator_agent", "What is 42 * 17?")
```

### Template Engine

Generate agent code from templates:

```python
from logosai.template_engine import TemplateEngine

engine = TemplateEngine()
code = engine.render("basic_agent", name="WeatherAgent", description="Fetches weather data")
```

Built-in templates: `basic_agent`, `async_agent`, `workflow_agent`, `database_agent`, `singleton_agent`

## Package Structure

```
logosai/
├── agent.py              # LogosAIAgent base class
├── simple_agent.py       # SimpleAgent, @agent decorator (v0.9.0)
├── agent_types.py        # Type definitions and enums
├── config/               # Configuration management
├── utils/                # LLM client, text utilities, helpers
├── agents/               # Built-in agent implementations
├── workflow/             # Workflow orchestration engine
├── message_bus/          # Pub/sub messaging system
├── debate/               # Agent Debate System
├── evolution/            # Self-Evolution System
│   └── safety/           # Circuit breaker, confidence gates
├── agentic/              # Agentic AI modules
├── acp/                  # ACP client library
├── template_engine/      # Code generation templates
├── cli/                  # Command-line tools
├── market/               # Agent marketplace client
└── generation/           # LLM-powered code generation
```

## LLM Client

Unified client supporting multiple providers (requires `pip install logosai[llm]`):

```python
# Quick one-liner (v0.9.0)
from logosai import quick_llm
answer = await quick_llm("Explain async/await in Python")

# Full client for advanced usage
from logosai import LLMClient

client = LLMClient(provider="google", model="gemini-2.5-flash-lite")
await client.initialize()

# Single prompt
response = await client.invoke("Explain async/await in Python")

# Chat messages
response = await client.invoke_messages([
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is Python?"},
])
```

Supported providers: `openai`, `anthropic`, `google` (Gemini), `ollama`

## Requirements

**Core** (installed automatically):

- Python 3.8+
- `aiohttp`, `requests`, `websocket-client`
- `pydantic`, `loguru`, `python-dotenv`

**Optional** (install with `pip install logosai[llm]`):

- `openai`, `anthropic`, `google-generativeai`
- `langchain`, `langchain-openai`, `langchain-community`

## License

[MIT](LICENSE)

## Links

- [GitHub](https://github.com/maior/logosai-framework)
- [Issues](https://github.com/maior/logosai-framework/issues)
- [Samples](samples/)
