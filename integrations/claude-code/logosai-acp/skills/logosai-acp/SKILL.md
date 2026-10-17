---
name: logosai-acp
description: Use LogosAI ACP agents (calculation, search, weather, exchange rates, summarization and other domain agents) through the logosai MCP tools when the user asks for something one of those agents does, or mentions LogosAI / ACP agents.
---
# Using LogosAI agents

The `logosai` MCP server exposes two tools:

- `logosai_agents` — lists the agents this session may call (id and description).
- `logosai_ask` — sends a natural-language `query` to an agent. Pass `agent_id` when an allowlist is configured; the call is refused otherwise.

Guidelines:
1. Call `logosai_agents` once to see what is available before choosing an agent.
2. Give the agent the user's request in plain language; do not pre-solve it.
3. Treat the agent's answer as the result. If the tool reports an error or refusal, tell the user rather than substituting your own answer.
4. Agents outside the allowlist cannot be called. To change the allowlist or server URL, the user runs `/plugin configure logosai-acp`.
