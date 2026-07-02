"""[Expose 방향] LogosAI ACP를 'MCP 서버'로 소비하는 표준 클라이언트 예제.

어떤 MCP 클라이언트(Claude Code, IDE, LLM 앱)든 이 시퀀스로 ACP의 86+ 에이전트를
도구처럼 사용한다:  initialize → notifications/initialized → tools/list → tools/call

사전 조건: ACP가 MCP flag로 실행 중이어야 함
  ACP_ENABLE_MCP=true ./acp_server/scripts/start.sh

실행:  ACP_URL=http://localhost:8888 python mcp_client_sample.py
"""

import asyncio
import json
import os

import aiohttp

ACP_URL = os.getenv("ACP_URL", "http://localhost:8888")
MCP = f"{ACP_URL}/mcp"


async def rpc(session: aiohttp.ClientSession, method: str, params=None, req_id=1):
    body = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params is not None:
        body["params"] = params
    async with session.post(MCP, json=body) as resp:
        data = await resp.json()
    if "error" in data:
        raise RuntimeError(f"{method} → {data['error']}")
    return data["result"]


async def main():
    async with aiohttp.ClientSession() as session:
        # ① 핸드셰이크
        init = await rpc(session, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "logosai-sample-client", "version": "1.0"}})
        print(f"① initialize  → server: {init['serverInfo']['name']} "
              f"(protocol {init['protocolVersion']})")

        async with session.post(MCP, json={"jsonrpc": "2.0",
                                           "method": "notifications/initialized"}) as r:
            print(f"② initialized → HTTP {r.status} (알림, 응답 본문 없음)")

        # ③ 도구 목록 — router 모드면 acp_query 1개 (86+ 에이전트 자동 라우팅의 관문)
        tools = (await rpc(session, "tools/list", req_id=2))["tools"]
        print(f"③ tools/list  → {[t['name'] for t in tools]}")

        # ④ 실행 — agent_id 지정 (특정 에이전트 직접 호출)
        result = await rpc(session, "tools/call", {
            "name": "acp_query",
            "arguments": {"query": "25 곱하기 4는?", "agent_id": "math_agent"}}, req_id=3)
        print(f"④ tools/call (직접 지정) → isError={result['isError']}")
        print(f"   {result['content'][0]['text'][:100].strip()}...")

        # ⑤ 실행 — agent_id 생략 (ACP TaskClassifier가 자동 라우팅)
        result = await rpc(session, "tools/call", {
            "name": "acp_query",
            "arguments": {"query": "오늘 서울 날씨 알려줘"}}, req_id=4)
        print(f"⑤ tools/call (자동 라우팅) → isError={result['isError']}")
        print(f"   {result['content'][0]['text'][:100].strip()}...")
        # 구조화 데이터(지도·표 등)는 structuredContent에 보존된다
        print(f"   structuredContent keys: {list((result.get('structuredContent') or {}).keys())[:5]}")


if __name__ == "__main__":
    asyncio.run(main())
