"""
SimpleACPServer — Dead-simple multi-agent ACP server.

Create and run an ACP server in ~10 lines of code:

    from logosai import SimpleAgent, AgentResponse
    from logosai.acp import SimpleACPServer

    class GreetingAgent(SimpleAgent):
        agent_name = "Greeting Agent"
        agent_description = "Says hello"
        async def handle(self, query, context=None):
            return AgentResponse.success(content={"answer": f"Hello! {query}"})

    server = SimpleACPServer(port=9000)
    server.add(GreetingAgent())
    server.run()

Features:
  - JSON-RPC (list_agents, process)
  - SSE streaming (/stream)
  - Health check (/health)
  - CORS enabled
  - Auto agent_id from class name

v0.9.0
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

from ..agent import LogosAIAgent
from ..agent_types import AgentResponse, AgentResponseType

logger = logging.getLogger(__name__)

__all__ = ["SimpleACPServer"]


def _make_agent_id(agent) -> str:
    """Generate agent_id from agent class name or name attribute.

    Examples:
        TranslationAgent -> translation_agent
        GreetingAgent    -> greeting_agent
        My Custom Agent  -> my_custom_agent
    """
    name = getattr(agent, "name", None) or getattr(agent, "agent_name", None) or type(agent).__name__
    # CamelCase -> snake_case
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
    s = re.sub(r"(?<=[A-Z])([A-Z][a-z])", r"_\1", s)
    # Spaces and special chars -> underscore
    s = re.sub(r"[\s\-]+", "_", s)
    return s.lower().strip("_")


class SimpleACPServer:
    """Multi-agent ACP server with minimal setup.

    Provides:
      - POST /jsonrpc — JSON-RPC 2.0 (list_agents, process, get_server_info)
      - GET/POST /stream — SSE streaming for single agent
      - GET /health — Health check
      - CORS headers on all responses

    Usage:
        server = SimpleACPServer(port=8888)
        server.add(MyAgent())
        server.add(AnotherAgent(), agent_id="custom_id")
        server.run()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8888,
        cors_origins: str = "*",
    ):
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp is required for SimpleACPServer. Install: pip install aiohttp"
            )

        self.host = host
        self.port = port
        self.cors_origins = cors_origins
        self.agents: Dict[str, LogosAIAgent] = {}
        self._start_time = None

    # ─── Agent Registration ──────────────────────────────

    def add(self, agent: LogosAIAgent, agent_id: Optional[str] = None) -> str:
        """Register an agent.

        Args:
            agent: Agent instance (LogosAIAgent or SimpleAgent)
            agent_id: Custom ID. If None, auto-generated from class name.

        Returns:
            The agent_id used for registration.
        """
        aid = agent_id or _make_agent_id(agent)

        if aid in self.agents:
            logger.warning(f"Agent '{aid}' already registered — replacing.")

        self.agents[aid] = agent
        logger.info(f"Registered agent: {aid} ({getattr(agent, 'name', type(agent).__name__)})")
        return aid

    def remove(self, agent_id: str):
        """Remove an agent by ID."""
        self.agents.pop(agent_id, None)

    # ─── Run ─────────────────────────────────────────────

    def run(self):
        """Start the server (blocking)."""
        if not self.agents:
            logger.warning("No agents registered. Server will start but cannot process queries.")

        logger.info(f"Starting SimpleACPServer on {self.host}:{self.port} with {len(self.agents)} agent(s)")
        for aid in self.agents:
            agent = self.agents[aid]
            logger.info(f"  - {aid}: {getattr(agent, 'description', '') or getattr(agent, 'agent_description', '')}")

        app = self._create_app()
        web.run_app(app, host=self.host, port=self.port, print=lambda msg: logger.info(msg))

    async def start(self):
        """Start the server (async, non-blocking). Returns runner for cleanup."""
        if not self.agents:
            logger.warning("No agents registered.")

        app = self._create_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info(f"SimpleACPServer listening on {self.host}:{self.port}")
        return runner

    # ─── App Setup ───────────────────────────────────────

    def _create_app(self) -> web.Application:
        app = web.Application()
        self._start_time = datetime.now()

        # CORS middleware
        @web.middleware
        async def cors_middleware(request, handler):
            if request.method == "OPTIONS":
                return web.Response(
                    status=200,
                    headers={
                        "Access-Control-Allow-Origin": self.cors_origins,
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type, Authorization",
                        "Access-Control-Max-Age": "86400",
                    },
                )
            response = await handler(request)
            response.headers["Access-Control-Allow-Origin"] = self.cors_origins
            return response

        app.middlewares.append(cors_middleware)

        # Routes
        app.router.add_post("/jsonrpc", self._handle_jsonrpc)
        app.router.add_get("/stream", self._handle_stream)
        app.router.add_post("/stream", self._handle_stream)
        app.router.add_get("/health", self._handle_health)

        return app

    # ─── Health ──────────────────────────────────────────

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "agents": len(self.agents),
            "uptime": str(datetime.now() - self._start_time) if self._start_time else "0",
        })

    # ─── JSON-RPC ────────────────────────────────────────

    async def _handle_jsonrpc(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                status=400,
            )

        req_id = body.get("id")
        method = body.get("method", "")
        params = body.get("params", {})

        response = {"jsonrpc": "2.0", "id": req_id}

        if method == "list_agents":
            response["result"] = {"agents": self._list_agents_info()}

        elif method == "process":
            query = params.get("query", "")
            agent_id = params.get("agent_id", "")
            context = params.get("context", {})

            if not query:
                response["error"] = {"code": -32602, "message": "query is required"}
            elif agent_id and agent_id not in self.agents:
                response["error"] = {
                    "code": -32602,
                    "message": f"Unknown agent_id: {agent_id}",
                    "data": {"available": list(self.agents.keys())},
                }
            else:
                aid = agent_id or next(iter(self.agents), None)
                if not aid:
                    response["error"] = {"code": -32603, "message": "No agents available"}
                else:
                    result = await self._run_agent(aid, query, context)
                    response["result"] = result

        elif method == "get_server_info":
            response["result"] = {
                "version": "0.9.0",
                "uptime": str(datetime.now() - self._start_time) if self._start_time else "0",
                "num_agents": len(self.agents),
                "supported_methods": ["list_agents", "process", "get_server_info"],
            }

        else:
            response["error"] = {"code": -32601, "message": f"Unknown method: {method}"}

        return web.json_response(response)

    # ─── SSE Streaming ───────────────────────────────────

    async def _handle_stream(self, request: web.Request) -> web.StreamResponse:
        """SSE streaming endpoint — compatible with production ACP event format."""
        try:
            # Parse params
            if request.method == "POST":
                body = await request.json()
                query = body.get("query", "")
                agent_id = body.get("agent_id", "")
                email = body.get("email", "")
                session_id = body.get("sessionid", "")
            else:
                query = request.query.get("query", "")
                agent_id = request.query.get("agent_id", "")
                email = request.query.get("email", "")
                session_id = request.query.get("sessionid", "")

            if not query:
                return web.json_response({"error": "query is required"}, status=400)

            # Prepare SSE response
            sse = web.StreamResponse(
                status=200,
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "Access-Control-Allow-Origin": self.cors_origins,
                },
            )
            await sse.prepare(request)

            # Select agent
            aid = agent_id if agent_id in self.agents else next(iter(self.agents), None)
            if not aid:
                await self._sse_write(sse, "error", {"error": "No agents available"})
                await sse.write_eof()
                return sse

            agent = self.agents[aid]

            # Event: agent_selected
            await self._sse_write(sse, "agent_selected", {
                "type": "agent_selected",
                "data": {
                    "agent_id": aid,
                    "agent_name": getattr(agent, "name", aid),
                    "selection_reason": "explicit" if agent_id else "auto",
                    "confidence": 1.0 if agent_id else 0.5,
                },
            })

            # Event: start
            await self._sse_write(sse, "start", {
                "type": "start",
                "data": {"agent_id": aid, "query": query[:200]},
            })

            # Run agent
            context = {"email": email, "session_id": session_id, "streaming": True}

            # If agent supports process_stream, use it
            if hasattr(agent, "process_stream") and asyncio.iscoroutinefunction(getattr(agent, "process_stream", None)):
                async for event in agent.process_stream(query, context):
                    event_type = event.get("type", "message")
                    await self._sse_write(sse, event_type, event)
                    if event_type in ("complete", "error"):
                        break
            else:
                # Event: progress
                await self._sse_write(sse, "progress", {
                    "type": "progress",
                    "data": {"stage": "processing", "message": f"Processing..."},
                })

                # Run process()
                result = await agent.process(query, context)

                # Extract content
                if hasattr(result, "content"):
                    result_content = result.content
                elif isinstance(result, dict):
                    result_content = result
                else:
                    result_content = {"answer": str(result)}

                # Event: complete
                await self._sse_write(sse, "complete", {
                    "type": "complete",
                    "data": {
                        "result": result_content,
                        "response_type": (
                            result.type.value
                            if hasattr(result, "type") and hasattr(result.type, "value")
                            else "success"
                        ),
                        "message": getattr(result, "message", ""),
                        "metadata": getattr(result, "metadata", {}),
                    },
                })

            await sse.write_eof()
            return sse

        except Exception as e:
            logger.error(f"Stream error: {e}")
            if "sse" in locals() and sse.prepared:
                await self._sse_write(sse, "error", {"error": str(e), "error_type": type(e).__name__})
                await sse.write_eof()
                return sse
            return web.json_response({"error": str(e)}, status=500)

    # ─── Helpers ─────────────────────────────────────────

    def _list_agents_info(self) -> List[Dict[str, Any]]:
        result = []
        for aid, agent in self.agents.items():
            result.append({
                "agent_id": aid,
                "name": getattr(agent, "name", aid),
                "type": str(getattr(agent, "agent_type", "CUSTOM")),
                "description": getattr(agent, "description", "") or getattr(agent, "agent_description", ""),
            })
        return result

    async def _run_agent(self, agent_id: str, query: str, context: Dict) -> Dict[str, Any]:
        agent = self.agents.get(agent_id)
        if agent is None:
            return {"error": f"Unknown agent: {agent_id}", "error_type": "AgentNotFound"}
        try:
            result = await agent.process(query, context)
            if hasattr(result, "content"):
                return {
                    "result": result.content,
                    "response_type": (
                        result.type.value
                        if hasattr(result, "type") and hasattr(result.type, "value")
                        else "success"
                    ),
                    "message": getattr(result, "message", ""),
                }
            return {"result": result if isinstance(result, dict) else str(result)}
        except Exception as e:
            return {"error": str(e), "error_type": type(e).__name__}

    @staticmethod
    async def _sse_write(response: web.StreamResponse, event_type: str, data: Any):
        payload = json.dumps(data, ensure_ascii=False, default=str)
        msg = f"event: {event_type}\ndata: {payload}\n\n"
        await response.write(msg.encode("utf-8"))
