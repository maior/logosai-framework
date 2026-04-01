"""LogosAI Built-in Tools — ready-to-use tools for agents.

Usage:
    from logosai.tools import BUILTIN_TOOLS, BUILTIN_EXECUTORS

    result = await agent.run_with_tools(query, BUILTIN_TOOLS, BUILTIN_EXECUTORS)
"""

from .builtin import BUILTIN_TOOLS, BUILTIN_EXECUTORS

__all__ = ["BUILTIN_TOOLS", "BUILTIN_EXECUTORS"]
