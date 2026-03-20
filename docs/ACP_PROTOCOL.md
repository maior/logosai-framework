# ACP (Agent Communication Protocol) — LogosAI

ACP is the communication protocol for LogosAI's multi-agent system. It enables agent execution, inter-agent calls, and real-time streaming.

## Architecture

```
Frontend (logos_web:8010)
    ↓ HTTP/SSE
Backend (logos_api:8090)
    ↓ HTTP/SSE
ACP Server (:8888)
    ├── JSON-RPC   — Agent discovery (list_agents)
    ├── SSE Stream — Single/multi agent execution
    ├── REST API   — Auto Reports management
    └── Agents     — 50+ agents with call_agent() support
```

## Endpoints

### JSON-RPC: `/jsonrpc` (POST)

```bash
# List all registered agents
curl -X POST http://localhost:8888/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "list_agents", "id": 1}'
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "agents": [
      {"name": "Internet Agent", "id": "internet_agent", "description": "..."},
      {"name": "Desktop Agent", "id": "desktop_agent", "description": "..."}
    ]
  }
}
```

### SSE Stream: `/stream` (POST)

Execute a single agent with Server-Sent Events streaming.

```bash
curl -X POST http://localhost:8888/stream \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "desktop_agent",
    "query": "Search Bitcoin price and send to John via KakaoTalk",
    "sessionid": "session-123",
    "email": "user@example.com"
  }'
```

**SSE Events:**
```
event: agent_selected
data: {"agent_id": "desktop_agent", "confidence": 1.0}

event: start
data: {"agent_id": "desktop_agent", "query": "..."}

event: progress
data: {"stage": "processing", "message": "..."}

event: chunk
data: {"content": "...", "index": 0}

event: complete
data: {"result": {"answer": "Message sent successfully."}}
```

### Multi-Agent Stream: `/stream/multi` (POST)

Execute multiple agents in a workflow.

```bash
curl -X POST http://localhost:8888/stream/multi \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Analyze Q4 sales data",
    "agents": [{"agent_id": "analysis_agent"}, {"agent_id": "report_generator_agent"}],
    "sessionid": "session-123",
    "email": "user@example.com"
  }'
```

### Auto Reports REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/auto-reports` | List all reports |
| POST | `/api/auto-reports` | Create new report |
| PUT | `/api/auto-reports/{id}` | Update report |
| DELETE | `/api/auto-reports/{id}` | Delete report |
| POST | `/api/auto-reports/{id}/run` | Run immediately |

**Create Report:**
```json
{
  "name": "Morning Weather",
  "search_query": "Seoul weather today",
  "deliver_via": "telegram",
  "recipient": "1633619663",
  "hour": 8,
  "minute": 0,
  "days": "매일",
  "condition": "temperature < 0",
  "summarize": true,
  "recipients": [
    {"via": "kakaotalk", "name": "John"},
    {"via": "email", "email": "user@gmail.com"},
    {"via": "telegram", "name": "1633619663"}
  ]
}
```

## Agent-to-Agent Communication

### Built-in: `self.call_agent()`

Every agent registered with the ACP server automatically gets `call_agent()` — no imports needed.

```python
class MyAgent(LogosAIAgent):
    async def process(self, query, context=None):
        # Call another agent
        result = await self.call_agent("internet_agent", "Bitcoin price")
        answer = result["answer"]

        # List available agents
        agents = self.available_agents()
        # ['internet_agent', 'calculator_agent', 'desktop_agent', ...]

        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": answer},
        )
```

### How It Works

1. ACP Server registers agents: `server.agents[agent_id] = agent`
2. Server injects registry: `agent._agent_registry = server.agents`
3. `LogosAIAgent.call_agent()` looks up target in `_agent_registry` and calls `target.process()`
4. No network overhead — direct in-process call

### Response Format

```python
result = await self.call_agent("internet_agent", "query")
# {
#     "success": True,
#     "answer": "The current Bitcoin price is ...",
#     "agent_id": "internet_agent"
# }
```

## Agent Registration

### In ACP Server (production)

Agents are loaded from `configs/agents.json` and registered automatically:

```python
# server.py
server.agents[agent.id] = agent
agent._agent_registry = server.agents  # Enable call_agent()
```

### In Sample Server (development)

```python
# sample_acp_server.py
AGENTS = {}
for agent in [LLMChatAgent(), CalculatorAgent(), ...]:
    await agent.initialize()
    AGENTS[agent_id] = agent

# Inject registry for call_agent()
for agent in AGENTS.values():
    agent._agent_registry = AGENTS
```

## Desktop Agent Sub-Agents

The Desktop Agent routes requests to specialized sub-agents:

| Sub-Agent | Capabilities | Platform |
|-----------|-------------|----------|
| `kakaotalk_agent` | Send KakaoTalk messages | macOS |
| `mail_agent` | Gmail read/compose/reply/send | Cross-platform |
| `auto_report_agent` | Scheduled search + delivery | Cross-platform |
| `app_launcher` | Launch apps, screenshots, automation | Cross-platform |

## Platform Support

| Feature | macOS | Ubuntu |
|---------|-------|--------|
| KakaoTalk | AppleScript Accessibility + Peekaboo | N/A |
| Gmail | Chrome AppleScript JS | Chrome CDP |
| Desktop automation | Peekaboo + pyautogui | xdotool + pyautogui |
| Screenshots | screencapture | scrot |
| Clipboard | pbcopy | xclip |

## Security

- **CORS**: Configured for cross-origin requests
- **Session-based**: `sessionid` parameter for request tracking
- **No auth by default**: Set `require_auth=True` for production
- **Telegram pairing**: Bot messages require user verification

## Configuration

### Environment Variables

```bash
GOOGLE_API_KEY=...          # Gemini LLM
OPENAI_API_KEY=...          # OpenAI LLM
TAVILY_API_KEY=...          # Internet search
TELEGRAM_BOT_TOKEN=...      # Telegram delivery
```

### ACP Server Start

```bash
python standalone_acp_server.py --port 8888
```

Options:
- `--port`: Server port (default: 8888)
- `--enable-auto-agent-selection`: Enable query-based agent routing
