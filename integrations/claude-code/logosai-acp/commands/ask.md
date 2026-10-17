---
description: Ask a LogosAI agent (via the logosai_ask MCP tool)
argument-hint: "[agent_id] <question>"
---
Answer the request below by calling the `logosai_ask` tool from the logosai MCP server.

- If the first word of the request is an agent id listed by `logosai_agents`, pass it as `agent_id` and the rest as `query`.
- Otherwise call `logosai_agents` first, pick the most suitable allowed agent, then call `logosai_ask`.
- Report the agent's answer. If the tool returns an error (for example an agent outside the allowlist), say so plainly instead of answering from your own knowledge.

Request: $ARGUMENTS
