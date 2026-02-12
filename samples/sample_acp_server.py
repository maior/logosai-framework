"""
Minimal ACP Server example — runs two sample agents on port 9000.

Requirements:
    pip install aiohttp logosai

Run:
    python sample_acp_server.py
    # Then test: curl http://localhost:9000/jsonrpc -d '{"jsonrpc":"2.0","method":"list_agents","id":1}'
"""

import asyncio
import json
from aiohttp import web

from hello_agent import HelloAgent
from calculator_agent import CalculatorAgent

# ---- Agent registry ----
AGENTS = {}


async def _load_agents():
    agents = [HelloAgent(), CalculatorAgent()]
    for a in agents:
        await a.initialize()
        AGENTS[a.config.name.lower().replace(" ", "_")] = a
    print(f"Loaded {len(AGENTS)} agents: {list(AGENTS.keys())}")


# ---- JSON-RPC handler ----
async def jsonrpc_handler(request: web.Request) -> web.Response:
    body = await request.json()
    method = body.get("method", "")
    params = body.get("params", {})
    req_id = body.get("id", 1)

    if method == "list_agents":
        agent_list = [
            {"agent_id": aid, "name": a.config.name, "description": a.config.description}
            for aid, a in AGENTS.items()
        ]
        return web.json_response({"jsonrpc": "2.0", "id": req_id, "result": {"agents": agent_list}})

    if method == "process":
        agent_id = params.get("agent_id", "")
        query = params.get("query", "")
        agent = AGENTS.get(agent_id)
        if not agent:
            return web.json_response(
                {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Unknown agent: {agent_id}"}},
            )
        result = await agent.process(query)
        return web.json_response({"jsonrpc": "2.0", "id": req_id, "result": result.content})

    return web.json_response(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}},
    )


async def init_app():
    await _load_agents()
    app = web.Application()
    app.router.add_post("/jsonrpc", jsonrpc_handler)
    return app


if __name__ == "__main__":
    print("Starting sample ACP server on http://localhost:9000")
    web.run_app(init_app(), port=9000)
