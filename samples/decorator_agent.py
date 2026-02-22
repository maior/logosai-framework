"""
Decorator-based agent example — Minimal agent definition.

The @agent decorator converts an async function into a full LogosAI agent
with lifecycle management, error handling, and ACP compatibility.

Run:
    python decorator_agent.py
"""

import asyncio
from logosai import agent, AgentResponse


@agent(name="Joke Agent", description="Tells jokes about any topic")
async def joke_agent(query, context=None, llm=None):
    response = await llm.invoke(f"Tell a short, funny joke about: {query}")
    return AgentResponse.success(
        message=response.content,
        content={"answer": response.content},
    )


async def main():
    j = joke_agent()  # Creates a SimpleAgent instance
    result = await j.process("programming")
    print(f"Joke: {result.content.get('answer', result.message)}")


if __name__ == "__main__":
    asyncio.run(main())
