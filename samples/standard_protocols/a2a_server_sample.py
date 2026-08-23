"""외부 A2A 에이전트 예제 — LogosAI ACP가 '소비(Consume)'할 수 있는 표준 에이전트.

A2A(Agent2Agent) 프로토콜의 최소 구현:
  GET  /.well-known/agent-card.json  — discovery (AgentCard)
  POST /a2a                          — JSON-RPC 2.0: message/send → Task 반환

역할: "파트너사 문서 요약 에이전트" 흉내 — 받은 텍스트를 요약 스타일로 가공해 반환.
(실제 파트너 A2A 에이전트가 이 자리에 오면 ACP는 설정 1항목으로 편입한다)

실행:  python a2a_server_sample.py            # 기본 포트 8902
ACP 편입:  external_endpoints.sample.json 참조 (protocol=a2a, url=http://localhost:8902)
"""

import json
import os
import time
import uuid

from aiohttp import web

PORT = int(os.getenv("PORT", "8902"))

AGENT_CARD = {
    "protocolVersion": "0.3.0",
    "name": "Partner Summary Agent",
    "description": "파트너사 제공 문서 요약 에이전트 (샘플) — 텍스트를 한 줄 요약으로 가공합니다.",
    "url": f"http://localhost:{PORT}/a2a",
    "preferredTransport": "JSONRPC",
    "version": "1.0.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain", "application/json"],
    "skills": [
        {
            "id": "summarize",
            "name": "한 줄 요약",
            "description": "긴 텍스트를 핵심 한 줄로 요약합니다.",
            "tags": ["summary", "text"],
            "examples": ["이 회의록을 한 줄로 요약해줘"],
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        }
    ],
}


def summarize(text: str) -> str:
    """데모용 규칙 기반 '요약' — 실서비스라면 여기가 파트너사의 LLM/모델."""
    words = text.split()
    head = " ".join(words[:12])
    return f"[요약] {head}{' …' if len(words) > 12 else ''} (원문 {len(words)}단어)"


def make_task(state: str, text: str = "", data: dict | None = None) -> dict:
    task = {
        "id": str(uuid.uuid4()),
        "contextId": str(uuid.uuid4()),
        "kind": "task",
        "status": {"state": state,
                   "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "artifacts": [],
    }
    if state == "completed":
        parts = [{"kind": "text", "text": text}]
        if data:
            parts.append({"kind": "data", "data": data})
        task["artifacts"] = [{"artifactId": str(uuid.uuid4()), "parts": parts}]
    return task


async def handle_card(_request: web.Request) -> web.Response:
    return web.json_response(AGENT_CARD)


async def handle_a2a(request: web.Request) -> web.Response:
    body = json.loads(await request.text())
    method, req_id = body.get("method", ""), body.get("id")
    params = body.get("params", {}) or {}

    if method == "message/send":
        parts = (params.get("message", {}) or {}).get("parts", [])
        text = "\n".join(p.get("text", "") for p in parts
                         if isinstance(p, dict) and p.get("kind") == "text").strip()
        if not text:
            return web.json_response(
                {"jsonrpc": "2.0", "id": req_id,
                 "error": {"code": -32602, "message": "text part가 필요합니다"}})
        summary = summarize(text)
        task = make_task("completed", summary, {"summary": summary, "input_words": len(text.split())})
        return web.json_response({"jsonrpc": "2.0", "id": req_id, "result": task})

    return web.json_response(
        {"jsonrpc": "2.0", "id": req_id,
         "error": {"code": -32601, "message": f"Method not found: {method}"}})


def main() -> None:
    app = web.Application()
    app.router.add_get("/.well-known/agent-card.json", handle_card)
    app.router.add_post("/a2a", handle_a2a)
    print(f"[partner-summary-a2a] card: http://localhost:{PORT}/.well-known/agent-card.json")
    web.run_app(app, port=PORT, print=None)


if __name__ == "__main__":
    main()
