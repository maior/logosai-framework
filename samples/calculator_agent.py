"""
Calculator Agent example — no external API keys or databases required.

Run:
    python calculator_agent.py
"""

import asyncio
import re
from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType


class CalculatorAgent(LogosAIAgent):
    """Simple calculator agent that evaluates math expressions."""

    def __init__(self):
        config = AgentConfig(
            name="Calculator Agent",
            agent_type=AgentType.CUSTOM,
            description="Evaluates arithmetic expressions safely",

        )
        super().__init__(config)

    async def process(self, query: str, context=None) -> AgentResponse:
        expr = re.sub(r"[^0-9+\-*/().\s]", "", query)
        if not expr.strip():
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": "No valid expression found"},
                message="Parse error",
            )
        try:
            result = eval(expr, {"__builtins__": {}}, {})  # restricted eval
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


async def main():
    agent = CalculatorAgent()
    await agent.initialize()

    queries = ["3 + 5", "100 / 4 * 2", "(10 + 20) * 3"]
    for q in queries:
        result = await agent.process(q)
        print(f"  {q} -> {result.content.get('answer', result.content.get('error'))}")

    # agent lifecycle complete


if __name__ == "__main__":
    asyncio.run(main())
