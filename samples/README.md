# LogosAI SDK Samples

Minimal examples for the LogosAI agent framework. No external API keys, databases, or credentials required.

## Files

| File | Description |
|------|-------------|
| `hello_agent.py` | Minimal agent (~20 lines of logic) |
| `calculator_agent.py` | Math expression evaluator |
| `sample_acp_server.py` | Mini ACP server hosting 2 agents |
| `agents.json` | Sample agent configuration |

## Quick Start

```bash
# Install SDK
pip install logosai aiohttp

# Run a single agent
python hello_agent.py

# Run calculator
python calculator_agent.py

# Start a mini ACP server
python sample_acp_server.py
# Test:
curl http://localhost:9000/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"list_agents","id":1}'
```

## Creating Your Own Agent

```python
from logosai.agent import LogosAIAgent
from logosai.config import AgentConfig
from logosai.types import AgentType, AgentResponse, AgentResponseType

class MyAgent(LogosAIAgent):
    def __init__(self):
        config = AgentConfig(
            name="My Agent",
            agent_type=AgentType.CUSTOM,
            description="What my agent does",
            version="1.0.0",
        )
        super().__init__(config)

    async def process(self, query: str, context=None) -> AgentResponse:
        # Your logic here
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": "result"},
            message="Done",
        )
```

See the [LogosAI documentation](../docs/) for more details.
