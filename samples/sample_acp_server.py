"""
Sample ACP Server — runs two agents (Hello + Calculator) on port 8888.

This is a minimal example of an ACP-compatible agent server that works
with logos_api (https://github.com/maior/logosai-api).

Requirements:
    pip install logosai

Run:
    python sample_acp_server.py
    # Then test: curl http://localhost:8888/jsonrpc -d '{"jsonrpc":"2.0","method":"list_agents","id":1}'

For use with logos_api:
    1. Start this server: python sample_acp_server.py
    2. Start logos_api:   uvicorn app.main:app --port 8090
    3. Start logos_web:   npm run dev (port 8010)
"""

import asyncio
import re
import json
from aiohttp import web

from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType


# ---- Sample Agents ----

class HelloAgent(LogosAIAgent):
    """Simple agent that greets the user."""

    def __init__(self):
        config = AgentConfig(
            name="Hello Agent",
            agent_type=AgentType.CUSTOM,
            description="A simple greeting agent that responds to any query",
        )
        super().__init__(config)

    async def process(self, query: str, context=None) -> AgentResponse:
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": f"Hello! You said: {query}"},
            message="Greeting generated",
        )


class CalculatorAgent(LogosAIAgent):
    """Simple calculator agent that evaluates math expressions."""

    def __init__(self):
        config = AgentConfig(
            name="Calculator Agent",
            agent_type=AgentType.CUSTOM,
            description="Evaluates arithmetic expressions safely (add, subtract, multiply, divide)",
        )
        super().__init__(config)

    async def process(self, query: str, context=None) -> AgentResponse:
        expr = re.sub(r"[^0-9+\-*/().\s]", "", query)
        if not expr.strip():
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": "No valid math expression found"},
                message="Parse error",
            )
        try:
            result = eval(expr, {"__builtins__": {}}, {})
            return AgentResponse(
                type=AgentResponseType.SUCCESS,
                content={"answer": f"{expr.strip()} = {result}"},
                message="Calculation complete",
            )
        except Exception as e:
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": str(e)},
                message="Calculation failed",
            )


# ---- Agent Registry ----
AGENTS = {}


async def _load_agents():
    agents = [HelloAgent(), CalculatorAgent()]
    for a in agents:
        await a.initialize()
        agent_id = a.config.name.lower().replace(" ", "_")
        AGENTS[agent_id] = a
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
                "name": a.config.name,
                "description": a.config.description,
            }
            for aid, a in AGENTS.items()
        ]
        return web.json_response(
            {"jsonrpc": "2.0", "id": req_id, "result": {"agents": agent_list}}
        )

    if method == "process":
        agent_id = params.get("agent_id", "")
        query = params.get("query", "")
        agent = AGENTS.get(agent_id)
        if not agent:
            return web.json_response(
                {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Unknown agent: {agent_id}"}},
            )
        result = await agent.process(query)
        return web.json_response(
            {"jsonrpc": "2.0", "id": req_id, "result": result.content}
        )

    return web.json_response(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}},
    )


# ---- SSE Stream Handler (logos_api compatible) ----
async def stream_handler(request: web.Request) -> web.StreamResponse:
    """SSE streaming endpoint compatible with logos_api's ACP client."""
    body = await request.json()
    query = body.get("query", "")
    sessionid = body.get("sessionid", "default")

    response = web.StreamResponse()
    response.content_type = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    await response.prepare(request)

    async def send_event(event_type: str, data: dict):
        payload = json.dumps(data, ensure_ascii=False)
        await response.write(f"event: {event_type}\ndata: {payload}\n\n".encode())

    # Send initialization
    await send_event("initialization", {"message": "System initializing", "session_id": sessionid})

    # Select first available agent (simple selection)
    agent_id = list(AGENTS.keys())[0] if AGENTS else None
    if not agent_id:
        await send_event("error", {"message": "No agents available"})
        return response

    agent = AGENTS[agent_id]
    await send_event("agent_started", {"agent_id": agent_id, "agent_name": agent.config.name})

    # Execute agent
    result = await agent.process(query)
    await send_event("agent_completed", {
        "agent_id": agent_id,
        "agent_name": agent.config.name,
        "result": result.content,
    })

    # Send final result
    await send_event("final_result", {
        "code": 0,
        "data": {
            "result": result.content.get("answer", str(result.content)),
            "agent_results": [{
                "agent_id": agent_id,
                "agent_name": agent.config.name,
                "result": result.content,
                "confidence": 0.9,
            }],
        },
    })

    return response


async def init_app():
    await _load_agents()
    app = web.Application()
    app.router.add_post("/jsonrpc", jsonrpc_handler)
    app.router.add_post("/stream/multi", stream_handler)
    return app


if __name__ == "__main__":
    PORT = 8888
    print(f"Starting sample ACP server on http://localhost:{PORT}")
    print(f"  JSON-RPC: POST http://localhost:{PORT}/jsonrpc")
    print(f"  SSE Stream: POST http://localhost:{PORT}/stream/multi")
    print(f"  Test: curl http://localhost:{PORT}/jsonrpc -d '{{\"jsonrpc\":\"2.0\",\"method\":\"list_agents\",\"id\":1}}'")
    web.run_app(init_app(), port=PORT)
