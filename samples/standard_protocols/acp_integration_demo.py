"""통합 데모 — ACP가 외부 MCP/A2A 시스템을 '설정 1항목'으로 편입해 호출하는 전 과정.

┌────────────────────────────────────────────────────────────────────┐
│  이 데모가 보여주는 것                                              │
│                                                                    │
│  [Consume]  ACP → 외부 표준 시스템 (프로토콜 자동전환)               │
│    사용자/에이전트는 agent_id만 안다. 프로토콜은 Driver가 처리:      │
│      internal_call("sample_tools", "3 더하기 5")   → MCP tools/call │
│      internal_call("partner_summary", "…요약해줘") → A2A message/send│
│                                                                    │
│  [되묻기]   필수 인자 부족 → input-required → continuation           │
│                                                                    │
│  [Expose]   외부 클라이언트 → ACP (/mcp, agent-card)                 │
└────────────────────────────────────────────────────────────────────┘

절차:
  1) 샘플 서버 2개 기동 (MCP:8901, A2A:8902)
  2) ACP가 편입 flag로 떠 있는지 확인 — 없으면 기동 안내 출력
  3) ACP를 통해 두 외부 시스템을 '로컬 에이전트처럼' 호출 (자동전환 시연)
  4) 되묻기 왕복 + Expose 방향 확인

실행:
  # 터미널 1 — ACP 를 편입 flag 로 기동 (예: 데모 전용 포트)
  cd <repo>/acp_server
  ACP_ENABLE_MCP=true ACP_ENABLE_A2A=true ACP_ENABLE_EXTERNAL=true \\
    ACP_EXTERNAL_CONFIG=<this_dir>/external_endpoints.sample.json \\
    python standalone_acp_server.py --port 8899 --enable-auto-agent-selection

  # 터미널 2 — 데모
  ACP_URL=http://localhost:8899 python acp_integration_demo.py
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import aiohttp

HERE = Path(__file__).parent
ACP_URL = os.getenv("ACP_URL", "http://localhost:8888")


def banner(title: str) -> None:
    print(f"\n{'─' * 62}\n  {title}\n{'─' * 62}")


async def jsonrpc(session, url: str, method: str, params=None, req_id=1):
    body = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params is not None:
        body["params"] = params
    async with session.post(url, json=body) as resp:
        return await resp.json()


def start_sample_servers() -> list:
    """샘플 외부 서버 2개를 서브프로세스로 기동."""
    procs = []
    for script, port, name in [("mcp_server_sample.py", 8901, "MCP"),
                               ("a2a_server_sample.py", 8902, "A2A")]:
        proc = subprocess.Popen([sys.executable, str(HERE / script)],
                                env={**os.environ, "PORT": str(port)},
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(proc)
        print(f"  ▸ 외부 {name} 샘플 서버 기동 (:{port}, pid {proc.pid})")
    return procs


async def check_acp(session) -> dict:
    """ACP 가용성 + 가상 에이전트 편입 여부 확인."""
    try:
        data = await jsonrpc(session, f"{ACP_URL}/jsonrpc", "list_agents")
        agents = {a["agent_id"]: a for a in data["result"]["agents"]}
        return agents
    except Exception:
        return {}


async def demo(session, agents: dict) -> None:
    # ── [Consume] 자동전환: 호출 문법이 로컬 에이전트와 완전히 동일 ──
    banner("[Consume] ACP → 외부 MCP  —  agent_id만 알면 된다 (프로토콜 자동전환)")
    resp = await jsonrpc(session, f"{ACP_URL}/jsonrpc", "query",
                         {"agent_id": "sample_tools", "query": "3 더하기 5는 얼마야?"})
    content = resp.get("result", {}).get("content", {})
    print(f"  query → sample_tools(가상 에이전트) → [McpDriver] → tools/call")
    print(f"  응답: {content.get('answer', content)}")

    banner("[Consume] ACP → 외부 A2A  —  같은 문법, 다른 프로토콜")
    resp = await jsonrpc(session, f"{ACP_URL}/jsonrpc", "query",
                         {"agent_id": "partner_summary",
                          "query": "LogosAI는 멀티에이전트 오케스트레이션 시스템으로 "
                                   "86개 전문 에이전트가 자동 라우팅으로 협업한다 를 요약해줘"},
                         req_id=2)
    content = resp.get("result", {}).get("content", {})
    print(f"  query → partner_summary(가상 에이전트) → [A2aDriver] → message/send")
    print(f"  응답: {content.get('answer', content)}")

    # ── [되묻기] 필수 인자 부족 → input-required → continuation ──
    banner("[되묻기] 좌표 없는 예보 요청 → 지어내지 않고 묻는다 → 답하면 이어간다")
    ask = await jsonrpc(session, f"{ACP_URL}/a2a", "message/send", {
        "message": {"role": "user", "kind": "message", "messageId": "d1",
                    "parts": [{"kind": "text", "text": "격자 예보 알려줘"}]},
        "metadata": {"skillId": "sample_tools"}}, req_id=3)
    task = ask.get("result", {})
    state = task.get("status", {}).get("state")
    print(f"  1차 요청 → Task state: {state}")
    if state == "input-required":
        fields = task.get("inputRequest", {}).get("fields", [])
        print(f"  시스템의 질문: {task['status'].get('message', '')}")
        print(f"  질문 필드(구조화): {[(f['id'], f['type']) for f in fields]}")
        cont = await jsonrpc(session, f"{ACP_URL}/a2a", "message/send", {
            "message": {"role": "user", "kind": "message", "messageId": "d2",
                        "taskId": task["id"],
                        "parts": [{"kind": "data", "data": {"nx": 60, "ny": 127}}]}}, req_id=4)
        done = cont.get("result", {})
        answer = ""
        for a in done.get("artifacts", []):
            for p in a.get("parts", []):
                if p.get("kind") == "text":
                    answer = p["text"]
        print(f"  답 전달({{nx:60, ny:127}}) → state: {done.get('status', {}).get('state')}")
        print(f"  최종 응답: {answer}")

    # ── [Expose] 반대 방향: 외부 클라이언트가 ACP를 표준으로 소비 ──
    banner("[Expose] 외부 클라이언트 → ACP  —  같은 서버가 MCP/A2A 서버이기도 하다")
    init = await jsonrpc(session, f"{ACP_URL}/mcp", "initialize",
                         {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "demo", "version": "1.0"}}, req_id=5)
    print(f"  /mcp initialize → {init.get('result', {}).get('serverInfo', {}).get('name')}")
    async with session.get(f"{ACP_URL}/.well-known/agent-card.json") as resp:
        card = await resp.json()
    ext_skills = [s["id"] for s in card["skills"] if s["id"] in ("sample_tools", "partner_summary")]
    print(f"  agent-card → skills {len(card['skills'])}개 — 편입된 외부 시스템도 skill로 노출: {ext_skills}")
    print(f"\n  ✔ 외부 시스템 N개를 붙여도 통합 코드는 0줄 — 선언(JSON) N항목뿐.")


async def main():
    print("═" * 62)
    print("  LogosAI 표준 프로토콜 통합 데모 (MCP · A2A 양방향)")
    print("═" * 62)
    procs = start_sample_servers()
    await asyncio.sleep(1.5)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
            agents = await check_acp(session)
            if not agents:
                print(f"\n⚠ ACP({ACP_URL})에 연결할 수 없습니다. 파일 상단 docstring의 "
                      f"기동 명령으로 ACP를 먼저 실행하세요.")
                return
            missing = [a for a in ("sample_tools", "partner_summary") if a not in agents]
            if missing:
                print(f"\n⚠ 가상 에이전트 미편입: {missing}")
                print("  ACP를 ACP_ENABLE_EXTERNAL=true + ACP_EXTERNAL_CONFIG="
                      f"{HERE / 'external_endpoints.sample.json'} 로 기동했는지 확인하세요.")
                return
            print(f"\n  ✔ ACP 연결 — 가상 에이전트 편입 확인: sample_tools(MCP), partner_summary(A2A)")
            print(f"    list_agents 상 type: {agents['sample_tools'].get('type')}")
            await demo(session, agents)
    finally:
        for proc in procs:
            proc.terminate()
        print("\n  샘플 서버 종료. 데모 끝.")


if __name__ == "__main__":
    asyncio.run(main())
