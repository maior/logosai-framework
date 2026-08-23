"""외부 MCP 서버 예제 — LogosAI ACP가 '소비(Consume)'할 수 있는 표준 도구 서버.

MCP(Model Context Protocol) Streamable HTTP의 최소 구현:
  POST /mcp 에 JSON-RPC 2.0 — initialize / notifications/* / tools/list / tools/call

도구 2개:
  - add               : a, b 필수 → 합계 (결정적 데모)
  - get_grid_forecast : nx, ny 필수 → 가짜 예보 (ACP '되묻기(ask-and-retry)' 데모용 —
                        자연어에 좌표가 없으면 ACP가 input-required로 사용자에게 되묻는다)

실행:  python mcp_server_sample.py            # 기본 포트 8901
ACP 편입:  external_endpoints.sample.json 참조 (protocol=mcp, url=http://localhost:8901/mcp)
"""

import json
import os

from aiohttp import web

TOOLS = [
    {
        "name": "add",
        "description": "두 숫자의 합을 계산합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "첫 번째 수"},
                "b": {"type": "number", "description": "두 번째 수"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "get_grid_forecast",
        "description": "기상 격자 좌표의 날씨 예보를 조회합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "nx": {"type": "integer", "description": "격자 X좌표"},
                "ny": {"type": "integer", "description": "격자 Y좌표"},
            },
            "required": ["nx", "ny"],
        },
    },
]


def call_tool(name: str, args: dict) -> dict:
    """도구 실행 → MCP 결과 포맷 {content:[...], structuredContent, isError}."""
    if name == "add":
        total = args["a"] + args["b"]
        return {
            "content": [{"type": "text", "text": f"{args['a']} + {args['b']} = {total}"}],
            "structuredContent": {"sum": total},
            "isError": False,
        }
    if name == "get_grid_forecast":
        nx, ny = args["nx"], args["ny"]
        return {
            "content": [{"type": "text", "text": f"격자({nx},{ny}) 예보: 맑음, 26.5°C"}],
            "structuredContent": {"nx": nx, "ny": ny, "sky": "맑음", "temp_c": 26.5},
            "isError": False,
        }
    return {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True}


async def handle_mcp(request: web.Request) -> web.Response:
    body = json.loads(await request.text())
    method, req_id = body.get("method", ""), body.get("id")
    params = body.get("params", {}) or {}

    # 알림은 응답 본문 없이 202 (MCP Streamable HTTP 규약)
    if method.startswith("notifications/"):
        return web.Response(status=202)

    if method == "initialize":
        result = {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "sample-tools-mcp", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            result = call_tool(params.get("name", ""), params.get("arguments", {}) or {})
        except (KeyError, TypeError) as e:
            # 인자 오류는 도구 실행 실패로 (JSON-RPC 에러 아님 — MCP 규약)
            result = {"content": [{"type": "text", "text": f"인자 오류: {e}"}], "isError": True}
    else:
        return web.json_response(
            {"jsonrpc": "2.0", "id": req_id,
             "error": {"code": -32601, "message": f"Method not found: {method}"}})

    return web.json_response({"jsonrpc": "2.0", "id": req_id, "result": result})


def main() -> None:
    port = int(os.getenv("PORT", "8901"))
    app = web.Application()
    app.router.add_post("/mcp", handle_mcp)
    print(f"[sample-tools-mcp] http://localhost:{port}/mcp  (tools: add, get_grid_forecast)")
    web.run_app(app, port=port, print=None)


if __name__ == "__main__":
    main()
