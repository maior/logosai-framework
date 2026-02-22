# LogosAI SDK Samples

Minimal examples for the LogosAI agent framework.

## Quick Start (v0.9.0)

The fastest ways to get started — pick the style that suits you:

```bash
pip install logosai[llm]

# One-line LLM call (no agent needed)
python quick_llm_example.py

# Zero-boilerplate agent
python simple_hello_agent.py

# Decorator-based agent (minimal code)
python decorator_agent.py
```

## Files

| File | Description | API Key? |
|------|-------------|----------|
| **`quick_llm_example.py`** | One-shot LLM call — no agent setup | Yes |
| **`simple_hello_agent.py`** | `SimpleAgent` subclass — zero boilerplate | Yes |
| **`decorator_agent.py`** | `@agent` decorator — function becomes agent | Yes |
| `hello_agent.py` | Classic `LogosAIAgent` subclass | No |
| `calculator_agent.py` | Math expression evaluator with safe eval | No |
| **`simple_acp_server.py`** | `SimpleACPServer` — multi-agent server in ~10 lines | No |
| `sample_acp_server.py` | Classic ACP server hosting 2 agents | No |
| `agents.json` | Sample agent configuration | No |

## Creating Agents — Three Ways

### 1. SimpleAgent (Recommended)

```python
from logosai import SimpleAgent, AgentResponse

class MyAgent(SimpleAgent):
    agent_name = "My Agent"
    agent_description = "Does something useful"

    async def handle(self, query, context=None):
        result = await self.ask_llm(f"Process: {query}")
        return AgentResponse.success(content={"answer": result})
```

### 2. @agent Decorator

```python
from logosai import agent, AgentResponse

@agent(name="My Agent", description="Does something useful")
async def my_agent(query, context=None, llm=None):
    response = await llm.invoke(f"Process: {query}")
    return AgentResponse.success(content={"answer": response.content})
```

### 3. quick_llm (No Agent Needed)

```python
from logosai import quick_llm

answer = await quick_llm("What is the capital of France?")
```

### 4. Classic LogosAIAgent

```python
from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType

class MyAgent(LogosAIAgent):
    def __init__(self):
        config = AgentConfig(
            name="My Agent",
            agent_type=AgentType.CUSTOM,
            description="What my agent does",
        )
        super().__init__(config)

    async def process(self, query: str, context=None) -> AgentResponse:
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": "result"},
            message="Done",
        )
```

## Running an ACP Server

### SimpleACPServer (Recommended)

```bash
python simple_acp_server.py
# Test:
curl http://localhost:9000/health
curl http://localhost:9000/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"list_agents","id":1}'
# SSE streaming:
curl -N "http://localhost:9000/stream?query=Hello&agent_id=greeting_agent"
```

### Classic ACP Server

```bash
pip install aiohttp_cors
python sample_acp_server.py
```

See the [main README](../README.md) for full documentation.
