"""
Minimal LogosAI Agent example.

Run:
    python hello_agent.py
"""

import asyncio
from logosai.agent import LogosAIAgent
from logosai.config import AgentConfig
from logosai.types import AgentType, AgentResponse, AgentResponseType


class HelloAgent(LogosAIAgent):
    """Simple agent that greets the user."""

    def __init__(self):
        config = AgentConfig(
            name="Hello Agent",
            agent_type=AgentType.CUSTOM,
            description="A simple greeting agent",

        )
        super().__init__(config)

    async def process(self, query: str, context=None) -> AgentResponse:
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": f"Hello! You said: {query}"},
            message="Greeting generated",
        )


async def main():
    agent = HelloAgent()
    await agent.initialize()
    result = await agent.process("Hi there!")
    print(result.content["answer"])
    # agent lifecycle complete


if __name__ == "__main__":
    asyncio.run(main())
