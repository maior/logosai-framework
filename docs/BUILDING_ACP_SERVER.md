# Building an ACP Server

A comprehensive guide to creating Agent Communication Protocol (ACP) servers that host and orchestrate LogosAI agents.

## Table of Contents

1. [Overview](#overview)
2. [What is ACP?](#what-is-acp)
3. [Quick Start: Minimal ACP Server](#quick-start-minimal-acp-server)
4. [ACP Protocol Specification](#acp-protocol-specification)
5. [Adding SSE Streaming](#adding-sse-streaming)
6. [Agent Registration](#agent-registration)
7. [Agent Collaboration Service](#agent-collaboration-service)
8. [Production ACP Server](#production-acp-server)
9. [Configuration with agents.json](#configuration-with-agentsjson)
10. [Deployment](#deployment)
11. [API Reference](#api-reference)

---

## Overview

An ACP (Agent Communication Protocol) server is a runtime environment that:

- **Hosts agents**: Loads, initializes, and manages agent lifecycles
- **Exposes JSON-RPC**: Standard endpoint for agent discovery and invocation
- **Streams responses**: SSE (Server-Sent Events) for real-time processing
- **Enables collaboration**: Agents can invoke other agents within the same server
- **Scales horizontally**: Multiple ACP servers can be federated

> **Tip (v0.9.0)**: Use `SimpleAgent` for new agents — it auto-manages init, error handling, publish_status, and ACP compatibility. See [Building Agentic AI](BUILDING_AGENTIC_AI.md#quick-start-with-simpleagent-v090) for details.

## What is ACP?

ACP is a protocol for agent-to-agent and client-to-agent communication:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/jsonrpc` | POST | Agent discovery (`list_agents`) and direct invocation (`process`) |
| `/stream` | GET | SSE streaming for single-agent queries |
| `/stream/multi` | GET | SSE streaming for multi-agent orchestrated queries |
| `/health` | GET | Server health check |

---

## Quick Start: Minimal ACP Server

A working ACP server in ~70 lines:

```python
"""
Minimal ACP Server — hosts two agents on port 9000.

Run:
    python my_acp_server.py

Test:
    curl http://localhost:9000/jsonrpc \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","method":"list_agents","id":1}'
"""

import asyncio
import json
from aiohttp import web

from logosai import SimpleAgent, AgentResponse
from logosai.agent_types import AgentResponseType


# ---- Define Agents ----

class GreetingAgent(SimpleAgent):
    agent_name = "Greeting Agent"
    agent_description = "A friendly greeting agent"

    async def handle(self, query, context=None):
        return AgentResponse.success(
            content={"answer": f"Hello! You said: {query}"},
            message=f"Greeted: {query}",
        )


class CalculatorAgent(SimpleAgent):
    agent_name = "Calculator Agent"
    agent_description = "Evaluates mathematical expressions safely"

    async def handle(self, query, context=None):
        import ast
        try:
            tree = ast.parse(query, mode='eval')
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp,
                                         ast.Constant, ast.Add, ast.Sub,
                                         ast.Mult, ast.Div, ast.Pow, ast.Mod,
                                         ast.USub)):
                    raise ValueError("Unsafe expression")
            result = eval(compile(tree, '<expr>', 'eval'))
            return AgentResponse.success(
                content={"answer": str(result)},
                message=str(result),
            )
        except Exception as e:
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": str(e)},
                message=f"Calculation error: {e}",
            )


# ---- Agent Registry ----

AGENTS = {}

async def load_agents():
    agents = [GreetingAgent(), CalculatorAgent()]
    for agent in agents:
        agent_id = agent.config.name.lower().replace(" ", "_")
        AGENTS[agent_id] = agent
    print(f"Loaded {len(AGENTS)} agents: {list(AGENTS.keys())}")


# ---- JSON-RPC Handler ----

async def jsonrpc_handler(request: web.Request) -> web.Response:
    body = await request.json()
    method = body.get("method", "")
    params = body.get("params", {})
    req_id = body.get("id", 1)

    if method == "list_agents":
        agent_list = [
            {
                "agent_id": aid,
                "name": agent.config.name,
                "description": agent.config.description,
            }
            for aid, agent in AGENTS.items()
        ]
        return web.json_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"agents": agent_list},
        })

    if method == "process":
        agent_id = params.get("agent_id", "")
        query = params.get("query", "")
        agent = AGENTS.get(agent_id)
        if not agent:
            return web.json_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Unknown agent: {agent_id}"},
            })
        result = await agent.process(query)
        return web.json_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result.content,
        })

    return web.json_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    })


# ---- Application Setup ----

async def init_app():
    await load_agents()
    app = web.Application()
    app.router.add_post("/jsonrpc", jsonrpc_handler)
    return app


if __name__ == "__main__":
    print("Starting ACP server on http://localhost:9000")
    web.run_app(init_app(), port=9000)
```

**Test it:**

```bash
# List agents
curl http://localhost:9000/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"list_agents","id":1}'

# Invoke an agent
curl http://localhost:9000/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"process","params":{"agent_id":"calculator_agent","query":"42 * 17"},"id":2}'
```

---

## ACP Protocol Specification

### JSON-RPC Methods

#### `list_agents`

Returns all registered agents.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "list_agents",
  "id": 1
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "agents": [
      {
        "agent_id": "calculator_agent",
        "name": "Calculator Agent",
        "description": "Evaluates mathematical expressions"
      }
    ]
  }
}
```

#### `process`

Invoke an agent with a query.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "process",
  "params": {
    "agent_id": "calculator_agent",
    "query": "42 * 17",
    "context": {}
  },
  "id": 2
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "answer": "714"
  }
}
```

---

## Adding SSE Streaming

For real-time UIs, add SSE (Server-Sent Events) streaming.

```python
async def stream_handler(request: web.Request) -> web.StreamResponse:
    """SSE streaming endpoint for agent queries."""
    query = request.query.get("query", "")
    agent_id = request.query.get("agent_id", "")
    session_id = request.query.get("sessionid", "default")

    agent = AGENTS.get(agent_id)
    if not agent:
        return web.json_response({"error": f"Unknown agent: {agent_id}"}, status=404)

    # Set up SSE response
    response = web.StreamResponse()
    response.headers["Content-Type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["Access-Control-Allow-Origin"] = "*"
    await response.prepare(request)

    async def send_event(event_type: str, data: dict):
        payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
        await response.write(f"data: {payload}\n\n".encode("utf-8"))

    try:
        # Initialization event
        await send_event("initialization", {
            "message": f"Processing with {agent.config.name}",
            "agent_id": agent_id,
        })

        # Process query
        result = await agent.process(query, {"sessionid": session_id})

        # Result event
        content = result.content
        answer = content.get("answer", str(content)) if isinstance(content, dict) else str(content)

        await send_event("chunk", {"content": answer})

        # Final result
        await send_event("complete", {
            "result": content,
            "message": result.message,
        })

    except Exception as e:
        await send_event("error", {"message": str(e)})

    return response


# Add to app setup:
# app.router.add_get("/stream", stream_handler)
```

### SSE Event Sequence

A typical SSE session produces events in this order:

```
data: {"type":"initialization","message":"Processing with Calculator Agent","agent_id":"calculator_agent"}

data: {"type":"chunk","content":"714"}

data: {"type":"complete","result":{"answer":"714"},"message":"714"}
```

### Multi-Agent Streaming

For orchestrated multi-agent queries with progress tracking:

```python
async def multi_stream_handler(request: web.Request) -> web.StreamResponse:
    query = request.query.get("query", "")
    session_id = request.query.get("sessionid", "default")

    response = web.StreamResponse()
    response.headers["Content-Type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Access-Control-Allow-Origin"] = "*"
    await response.prepare(request)

    async def send_event(event_type: str, data: dict):
        payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
        await response.write(f"data: {payload}\n\n".encode("utf-8"))

    try:
        await send_event("initialization", {"message": "Starting multi-agent processing"})

        # Select agent(s) for the query
        selected_agent_id, selected_agent = select_best_agent(query)

        await send_event("agent_selected", {
            "agent_id": selected_agent_id,
            "agent_name": selected_agent.config.name,
        })

        # Process
        result = await selected_agent.process(query, {"sessionid": session_id})

        content = result.content
        answer = content.get("answer", str(content)) if isinstance(content, dict) else str(content)

        await send_event("final_result", {
            "result": answer,
            "agent_id": selected_agent_id,
        })

    except Exception as e:
        await send_event("error", {"message": str(e)})

    return response
```

---

## Agent Registration

### Dynamic Agent Loading from agents.json

```python
import json
import importlib
import os

async def load_agents_from_config(config_path: str = "agents.json"):
    """Load agents dynamically from a JSON configuration file."""
    with open(config_path, 'r') as f:
        config = json.load(f)

    agents = {}
    for agent_def in config.get("agents", []):
        agent_id = agent_def["agent_id"]
        module_path = agent_def.get("module", "")
        class_name = agent_def.get("class_name", "")

        if not module_path or not class_name:
            continue

        try:
            # Dynamic import
            module = importlib.import_module(module_path)
            agent_class = getattr(module, class_name)
            agent = agent_class()
            await agent.initialize()
            agents[agent_id] = agent
            print(f"  Loaded: {agent_id} ({class_name})")
        except Exception as e:
            print(f"  FAILED: {agent_id} — {e}")

    return agents
```

### agents.json Format

```json
{
  "agents": [
    {
      "agent_id": "greeting_agent",
      "name": "Greeting Agent",
      "description": "A friendly greeting agent",
      "module": "agents.greeting_agent",
      "class_name": "GreetingAgent",
      "keywords": ["hello", "greeting", "hi"]
    },
    {
      "agent_id": "calculator_agent",
      "name": "Calculator Agent",
      "description": "Mathematical expression evaluator",
      "module": "agents.calculator_agent",
      "class_name": "CalculatorAgent",
      "keywords": ["calculate", "math", "compute"]
    }
  ]
}
```

---

## Agent Collaboration Service

Enable agents hosted on the same ACP server to invoke each other.

### Setting Up Collaboration

```python
from logosai.collaboration import (
    CollaborationService,
    AgentCapability,
    CollaborationResult,
    CollaborationStatus,
)


class SimpleCollaborationService(CollaborationService):
    """In-process collaboration service for a single ACP server."""

    def __init__(self, agents: dict):
        super().__init__()
        self.agents = agents  # {agent_id: agent_instance}
        self._capabilities = {}  # {agent_id: AgentCapability}
        self._capability_index = {}  # {capability: [agent_ids]}
        self._build_index()

    def _build_index(self):
        """Build capability index from loaded agents."""
        for agent_id, agent in self.agents.items():
            name = getattr(agent, 'name', agent_id)
            description = getattr(agent.config, 'description', '')

            # Auto-detect capabilities from agent_id and description
            capabilities = self._detect_capabilities(agent_id, description)

            self._capabilities[agent_id] = AgentCapability(
                agent_id=agent_id,
                agent_name=name,
                capabilities=capabilities,
                description=description,
            )

            for cap in capabilities:
                self._capability_index.setdefault(cap, []).append(agent_id)

    def _detect_capabilities(self, agent_id: str, description: str) -> list:
        """Auto-detect agent capabilities from ID and description."""
        text = f"{agent_id} {description}".lower()
        KEYWORDS = {
            "translation": ["translate", "translation", "language"],
            "search": ["search", "internet", "web"],
            "calculation": ["calculate", "math", "calculator"],
            "writing": ["write", "email", "report"],
            "summarization": ["summary", "summarize"],
        }
        detected = []
        for cap, keywords in KEYWORDS.items():
            if any(kw in text for kw in keywords):
                detected.append(cap)
        return detected or [agent_id]  # Fallback: agent_id as capability

    async def discover_agents(self, capability, exclude_ids=None):
        exclude = set(exclude_ids or [])
        return [
            self._capabilities[aid]
            for aid in self._capability_index.get(capability, [])
            if aid not in exclude and aid in self._capabilities
        ]

    async def select_agent(self, capability, query, exclude_ids=None):
        candidates = await self.discover_agents(capability, exclude_ids)
        return candidates[0] if candidates else None

    async def _execute_on_agent(self, agent_id, query, context):
        agent = self.agents.get(agent_id)
        if not agent:
            raise ValueError(f"Agent not found: {agent_id}")
        response = await agent.process(query, context)
        if hasattr(response, 'type') and response.type.value == "SUCCESS":
            return response.content
        if isinstance(response, dict):
            return response
        return {"result": str(response)}


def inject_collaboration(agents: dict) -> SimpleCollaborationService:
    """Create collaboration service and inject into all agents."""
    service = SimpleCollaborationService(agents)
    injected = 0
    for agent_id, agent in agents.items():
        if hasattr(agent, 'set_collaboration_service'):
            agent.set_collaboration_service(service)
            injected += 1
    print(f"Collaboration injected into {injected}/{len(agents)} agents")
    return service
```

### Using It in Server Setup

```python
async def init_app():
    await load_agents()

    # Enable collaboration
    collab_service = inject_collaboration(AGENTS)

    app = web.Application()
    app.router.add_post("/jsonrpc", jsonrpc_handler)
    app.router.add_get("/stream", stream_handler)
    return app
```

Now agents can call each other:

```python
class WritingAgent(SimpleAgent):
    agent_name = "Writing Agent"
    agent_description = "Professional document writing with translation support"

    async def handle(self, query, context=None):
        document = await self.ask_llm(f"Write a professional document about: {query}")

        # Collaborate: ask translation agent to translate
        if self.can_collaborate and "English" in query:
            result = await self.invoke_agent(
                capability="translation",
                query=f"Translate to English: {document}",
                timeout=20.0,
            )
            if result.status == CollaborationStatus.COMPLETED:
                document += f"\n\n---\n{result.data.get('answer', '')}"

        return AgentResponse.success(content={"answer": document}, message=document)
```

---

## Production ACP Server

A production-ready ACP server with CORS, health checks, and proper error handling:

```python
"""
Production ACP Server

Features:
- JSON-RPC endpoint for agent discovery/invocation
- SSE streaming for real-time responses
- CORS support for web frontends
- Health check endpoint
- Agent collaboration service
- Dynamic agent loading from agents.json
"""

import asyncio
import json
import os
import time
from aiohttp import web

try:
    import aiohttp_cors
    HAS_CORS = True
except ImportError:
    HAS_CORS = False


class ACPServer:
    def __init__(self, port: int = 8888, agents_config: str = "agents.json"):
        self.port = port
        self.agents_config = agents_config
        self.agents = {}
        self.collab_service = None
        self.start_time = time.time()

    async def load_agents(self):
        """Load agents from configuration."""
        # Import your agents here
        from my_agents import GreetingAgent, CalculatorAgent, SmartAgent

        agent_classes = [GreetingAgent, CalculatorAgent, SmartAgent]

        for agent_cls in agent_classes:
            try:
                agent = agent_cls()
                await agent.initialize()
                agent_id = agent.config.name.lower().replace(" ", "_")
                self.agents[agent_id] = agent
                print(f"  Loaded: {agent_id}")
            except Exception as e:
                print(f"  FAILED: {agent_cls.__name__} — {e}")

        print(f"Loaded {len(self.agents)} agents")

    def setup_collaboration(self):
        """Enable inter-agent collaboration."""
        self.collab_service = inject_collaboration(self.agents)

    async def handle_jsonrpc(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                status=400,
            )

        method = body.get("method", "")
        params = body.get("params", {})
        req_id = body.get("id", 1)

        if method == "list_agents":
            agents = [
                {
                    "agent_id": aid,
                    "name": a.config.name,
                    "description": a.config.description,
                }
                for aid, a in self.agents.items()
            ]
            return web.json_response({"jsonrpc": "2.0", "id": req_id, "result": {"agents": agents}})

        if method == "process":
            agent_id = params.get("agent_id", "")
            query = params.get("query", "")
            context = params.get("context", {})
            agent = self.agents.get(agent_id)
            if not agent:
                return web.json_response({
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32602, "message": f"Unknown agent: {agent_id}"},
                })
            try:
                result = await asyncio.wait_for(
                    agent.process(query, context),
                    timeout=60.0,
                )
                return web.json_response({"jsonrpc": "2.0", "id": req_id, "result": result.content})
            except asyncio.TimeoutError:
                return web.json_response({
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": "Agent timeout (60s)"},
                })

        return web.json_response({
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        })

    async def handle_stream(self, request: web.Request) -> web.StreamResponse:
        query = request.query.get("query", "")
        agent_id = request.query.get("agent_id", "")
        session_id = request.query.get("sessionid", "default")

        agent = self.agents.get(agent_id)
        if not agent:
            return web.json_response({"error": f"Unknown agent: {agent_id}"}, status=404)

        response = web.StreamResponse()
        response.headers["Content-Type"] = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Connection"] = "keep-alive"
        await response.prepare(request)

        async def send(event_type, data):
            payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
            await response.write(f"data: {payload}\n\n".encode("utf-8"))

        try:
            await send("initialization", {"message": f"Processing with {agent.config.name}"})
            result = await asyncio.wait_for(
                agent.process(query, {"sessionid": session_id}),
                timeout=60.0,
            )
            content = result.content
            answer = content.get("answer", str(content)) if isinstance(content, dict) else str(content)
            await send("chunk", {"content": answer})
            await send("complete", {"result": content})
        except asyncio.TimeoutError:
            await send("error", {"message": "Processing timeout (60s)"})
        except Exception as e:
            await send("error", {"message": str(e)})

        return response

    async def handle_health(self, request: web.Request) -> web.Response:
        uptime = time.time() - self.start_time
        return web.json_response({
            "status": "healthy",
            "agents": len(self.agents),
            "uptime_seconds": round(uptime, 1),
        })

    async def create_app(self) -> web.Application:
        await self.load_agents()
        self.setup_collaboration()

        app = web.Application()
        app.router.add_post("/jsonrpc", self.handle_jsonrpc)
        app.router.add_get("/stream", self.handle_stream)
        app.router.add_get("/health", self.handle_health)

        # CORS support
        if HAS_CORS:
            cors = aiohttp_cors.setup(app, defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*",
                    allow_methods="*",
                )
            })
            for route in list(app.router.routes()):
                cors.add(route)

        return app

    def run(self):
        print(f"Starting ACP server on http://localhost:{self.port}")
        web.run_app(self.create_app(), port=self.port)


if __name__ == "__main__":
    server = ACPServer(port=8888)
    server.run()
```

---

## Configuration with agents.json

### Full agents.json Example

```json
{
  "agents": [
    {
      "agent_id": "calculator_agent",
      "name": "Calculator Agent",
      "description": "Evaluates mathematical expressions safely",
      "type": "custom",
      "module": "agents.calculator_agent",
      "class_name": "CalculatorAgent",
      "keywords": ["calculate", "math", "compute", "arithmetic"],
      "config": {
        "provider": "google",
        "model": "gemini-2.5-flash-lite",
        "temperature": 0.1
      }
    },
    {
      "agent_id": "translation_agent",
      "name": "Translation Agent",
      "description": "Translates text between 10+ languages",
      "type": "custom",
      "module": "agents.translation_agent",
      "class_name": "TranslationAgent",
      "keywords": ["translate", "translation", "language"],
      "config": {
        "provider": "google",
        "model": "gemini-2.5-flash-lite",
        "temperature": 0.3,
        "supported_languages": ["en", "ko", "ja", "zh", "es", "fr", "de", "pt", "it", "ru"]
      }
    },
    {
      "agent_id": "writing_agent",
      "name": "Writing Agent",
      "description": "Professional document and email writing",
      "type": "custom",
      "module": "agents.writing_agent",
      "class_name": "WritingAgent",
      "keywords": ["write", "email", "report", "proposal", "document"],
      "config": {
        "provider": "google",
        "model": "gemini-2.5-flash-lite",
        "temperature": 0.7,
        "max_tokens": 6000
      }
    }
  ]
}
```

---

## Deployment

### Project Structure

```
my-acp-server/
├── server.py              # Main ACP server
├── agents/                # Agent implementations
│   ├── __init__.py
│   ├── calculator_agent.py
│   ├── translation_agent.py
│   └── writing_agent.py
├── configs/
│   └── agents.json        # Agent configuration
├── scripts/
│   ├── start.sh           # Start script with PID management
│   └── stop.sh            # Stop script
├── logs/                  # Log directory
├── .env                   # Environment variables (git-ignored)
├── .env.example           # Environment template
└── requirements.txt       # Dependencies
```

### Start Script

```bash
#!/bin/bash
# scripts/start.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/logs/acp_server.pid"
LOG_FILE="$PROJECT_DIR/logs/acp_server.log"

mkdir -p "$PROJECT_DIR/logs"

# Check if already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "ACP server already running (PID: $PID)"
        exit 0
    fi
    rm "$PID_FILE"
fi

# Start server
cd "$PROJECT_DIR"
nohup python server.py >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "ACP server started (PID: $!)"
echo "Logs: $LOG_FILE"
```

### Environment Variables

```bash
# .env
GOOGLE_API_KEY=your-gemini-api-key
OPENAI_API_KEY=your-openai-key        # Optional
ANTHROPIC_API_KEY=your-anthropic-key   # Optional

# Database (if agents need DB access)
LOGOSAI_DB_URL=postgresql://user:pass@host:5432/dbname

# Server config
ACP_PORT=8888
ACP_LOG_LEVEL=INFO
```

### Requirements

```
# requirements.txt
logosai>=0.9.0
aiohttp>=3.9.0
aiohttp-cors>=0.7.0
python-dotenv>=1.0.0
loguru>=0.7.0
```

---

## API Reference

### Server Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/jsonrpc` | POST | JSON-RPC 2.0 handler |
| `/stream` | GET | SSE streaming (params: `query`, `agent_id`, `sessionid`) |
| `/stream/multi` | GET | Multi-agent orchestrated streaming |
| `/health` | GET | Health check |

### JSON-RPC Methods

| Method | Params | Description |
|--------|--------|-------------|
| `list_agents` | — | List all registered agents |
| `process` | `agent_id`, `query`, `context` | Invoke a specific agent |

### SSE Event Types

| Type | Fields | Description |
|------|--------|-------------|
| `initialization` | `message`, `agent_id` | Processing started |
| `agent_selected` | `agent_id`, `agent_name` | Agent chosen for query |
| `chunk` | `content` | Partial response content |
| `complete` | `result`, `message` | Processing complete |
| `final_result` | `result`, `agent_id` | Final aggregated result |
| `error` | `message` | Error occurred |

### Using from Client Code

```python
from logosai.acp import ACPClient

# Connect to ACP server
client = ACPClient(endpoint="http://localhost:8888")

# List agents
agents = await client.list_agents()
for agent in agents:
    print(f"{agent['agent_id']}: {agent['description']}")

# Query an agent
result = await client.query("calculator_agent", "42 * 17")
print(result)  # {"answer": "714"}
```

### Using from CLI (curl)

```bash
# Health check
curl http://localhost:8888/health

# List agents
curl -X POST http://localhost:8888/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"list_agents","id":1}'

# Process query
curl -X POST http://localhost:8888/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"process","params":{"agent_id":"calculator_agent","query":"100 + 200"},"id":2}'

# SSE stream
curl -N "http://localhost:8888/stream?query=hello&agent_id=greeting_agent&sessionid=test"
```
