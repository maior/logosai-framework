"""
SimpleAgent example — Zero boilerplate.

Compare with hello_agent.py to see the difference:
  - hello_agent.py: 30+ lines with AgentConfig, __init__, super().__init__
  - This file: 15 lines with just class attributes + handle()

Run:
    python simple_hello_agent.py
"""

import asyncio
from logosai import SimpleAgent, AgentResponse


class HelloAgent(SimpleAgent):
    agent_name = "Hello Agent"
    agent_description = "A simple greeting agent"

    async def handle(self, query, context=None):
        greeting = await self.ask_llm(f"Generate a friendly greeting for someone who said: {query}")
        return AgentResponse.success(
            message=greeting,
            content={"answer": greeting},
        )


async def main():
    agent = HelloAgent()
    result = await agent.process("Hi there!")
    print(f"Response: {result.content.get('answer', result.message)}")


if __name__ == "__main__":
    asyncio.run(main())
