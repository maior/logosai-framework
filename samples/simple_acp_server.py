#!/usr/bin/env python3
"""
Example: Run a multi-agent ACP server with SimpleACPServer.

This is the easiest way to host your agents over JSON-RPC + SSE streaming.

Usage:
    python simple_acp_server.py

Then test:
    # List agents
    curl -s http://localhost:9000/jsonrpc \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":1,"method":"list_agents"}'

    # Process a query
    curl -s http://localhost:9000/jsonrpc \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":2,"method":"process","params":{"query":"Hello!","agent_id":"greeting_agent"}}'

    # SSE streaming
    curl -N "http://localhost:9000/stream?query=Hello&agent_id=greeting_agent"

    # Health check
    curl http://localhost:9000/health
"""

from logosai import SimpleAgent, AgentResponse
from logosai.acp import SimpleACPServer


class GreetingAgent(SimpleAgent):
    agent_name = "Greeting Agent"
    agent_description = "A friendly agent that greets users"

    async def handle(self, query, context=None):
        answer = f"Hello! You said: {query}"
        return AgentResponse.success(
            content={"answer": answer},
            message=answer,
        )


class EchoAgent(SimpleAgent):
    agent_name = "Echo Agent"
    agent_description = "Echoes back what you say"

    async def handle(self, query, context=None):
        return AgentResponse.success(
            content={"answer": query, "echo": True},
            message=f"Echo: {query}",
        )


class CalculatorAgent(SimpleAgent):
    agent_name = "Calculator Agent"
    agent_description = "Evaluates simple math expressions"
    llm_temperature = 0.0

    async def handle(self, query, context=None):
        prompt = f"Calculate the following and return ONLY the numeric result: {query}"
        answer = await self.ask_llm(prompt)
        return AgentResponse.success(
            content={"answer": answer, "expression": query},
            message=answer,
        )


if __name__ == "__main__":
    server = SimpleACPServer(port=9000)

    server.add(GreetingAgent())
    server.add(EchoAgent())
    server.add(CalculatorAgent())

    print("Starting server on http://localhost:9000")
    print(f"  Agents: {list(server.agents.keys())}")
    print(f"  Endpoints: /jsonrpc, /stream, /health")

    server.run()
