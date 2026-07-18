"""[P8] SDK 단독 표준 스키마 파생 — ACP 없이 에이전트를 MCP tool / A2A skill로.

StandardExportMixin(logosai.mixins.standard_export)이 LogosAIAgent에 믹스인되어 있어
어떤 에이전트든 자기 자신을 표준 스키마로 self-describe 할 수 있다.
SimpleACPServer 등 SDK 단독 배포에서 표준 노출(Expose)을 구성할 때 쓴다.

실행:  python sdk_export_sample.py   (ACP 서버 불필요)
"""

import asyncio
import json

from logosai.agent import LogosAIAgent
from logosai.config import AgentConfig


class CalculatorAgent(LogosAIAgent):
    """사칙연산 에이전트 — 도구 2개를 등록한다."""

    def __init__(self):
        super().__init__(AgentConfig(
            name="계산 에이전트",
            agent_type="custom",
            description="두 수의 사칙연산을 수행합니다.",
            config={"tags": ["math", "calculator"],
                    "examples": ["3 더하기 5는?", "12 곱하기 4"]},
        ))
        self.register_tool(
            "add", "두 수를 더한다", lambda a, b: a + b,
            parameters={"a": {"type": "number", "description": "첫 번째 수", "required": True},
                        "b": {"type": "number", "description": "두 번째 수", "required": True}})
        self.register_tool(
            "multiply", "두 수를 곱한다", lambda a, b: a * b,
            parameters={"a": {"type": "number", "description": "첫 번째 수"},
                        "b": {"type": "number", "description": "두 번째 수"}})

    async def process(self, query, context=None):
        return None  # 데모 — 실제 로직은 생략


def main():
    agent = CalculatorAgent()

    print("─" * 60)
    print("  agent.to_mcp_tool()  — MCP tools/list 응답에 그대로 넣는다")
    print("─" * 60)
    print(json.dumps(agent.to_mcp_tool(), ensure_ascii=False, indent=2))

    print("\n" + "─" * 60)
    print("  agent.to_a2a_skill() — A2A AgentCard.skills 에 그대로 넣는다")
    print("─" * 60)
    print(json.dumps(agent.to_a2a_skill(), ensure_ascii=False, indent=2))

    print("\n  ✔ 파생 원천: self.config + self._tools — 별도 선언 없이 항상 코드와 일치")


if __name__ == "__main__":
    main()
