"""
LogosAI 간단한 에이전트 템플릿

이 템플릿은 가장 기본적인 에이전트 구현 방법을 보여줍니다.
"""

import asyncio
from typing import Dict, Any
from logosai import ConversationalAgent, AgentConfig, AgentType


class SimpleAgent(ConversationalAgent):
    """간단한 에이전트 예제"""
    
    def __init__(self):
        config = AgentConfig(
            name="Simple Agent",
            agent_type=AgentType.GENERAL,
            description="기본적인 에이전트 예제",
            config={}
        )
        super().__init__(config)
    
    async def execute_with_parameters(self, query: str, parameters: Dict[str, Any]) -> Any:
        """에이전트 실행 로직"""
        return {
            "message": f"안녕하세요! 당신의 질문은: {query}",
            "parameters": parameters,
            "response": "이것은 간단한 응답입니다."
        }


async def main():
    """실행 예제"""
    # 에이전트 생성 및 초기화
    agent = SimpleAgent()
    await agent.initialize()
    
    # 에이전트 실행
    result = await agent.process("안녕하세요!")
    print(f"결과: {result.message}")
    print(f"내용: {result.content}")
    
    # 에이전트 종료
    await agent.shutdown()


if __name__ == "__main__":
    asyncio.run(main())