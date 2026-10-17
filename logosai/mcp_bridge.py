"""logosai mcp — ACP 서버를 MCP 클라이언트(Claude Code · Codex 등)에 잇는 stdio 브리지.

    claude mcp add logosai -- logosai mcp --acp http://localhost:8888
    codex  mcp add logosai -- logosai mcp --acp http://localhost:8888

브리지는 **ACP 프로토콜로 말한다** — 도구 목록은 JSON-RPC `list_agents`, 실행은
`POST /stream` 의 마지막 complete/error 이벤트. 그래서 서버에 /mcp 를 켜지 않아도
Logos ACP 와 `logosai serve`(SimpleACPServer) 양쪽에 붙는다. MCP 는 바깥으로 난 문이고,
에이전트의 의미(선택·실행·결과 봉투)는 ACP 서버가 정한다.

설계 결정
  · router 모드(기본): `logosai_agents` + `logosai_ask` 두 도구. 에이전트 수만큼 도구를
    펼치면 MCP 클라이언트의 컨텍스트를 도구 설명이 먹는다. `direct` 는 에이전트별 도구.
  · 허용 목록(--agents)은 실행 **전에** 거른다. 목록이 있으면 router 도 agent_id 를
    요구한다 — 서버가 목록 밖 에이전트를 고를 수 있기 때문이다.
  · 토큰은 환경변수 LOGOSAI_ACP_TOKEN 에서만 — 명령 인자는 클라이언트 설정 파일에 평문으로 남는다.
  · 실패 판정은 SDK 정본 `agent_outcome.failure_reason()` 하나.
  · stdout 은 프로토콜 전용(한 줄에 한 메시지), 로그는 stderr.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Protocol

from .agent_outcome import failure_reason

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "logosai", "version": "1"}
TOOL_NAME_RE = re.compile(r"[a-zA-Z0-9_-]{1,64}")
_SANITIZE = re.compile(r"[^a-zA-Z0-9_-]")


class AcpTransport(Protocol):
    async def list_agents(self) -> List[Dict[str, Any]]: ...
    async def run(self, query: str, agent_id: str = "") -> Dict[str, Any]: ...


# ── 전송 계층 ─────────────────────────────────────────────────────────

def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def parse_sse_outcome(raw: str) -> Dict[str, Any]:
    """SSE 본문 → {ok, result, error}. 마지막 complete/error 이벤트가 결과다.

    끝맺음(complete/error)이 없으면 성공이 아니다 — 끊긴 스트림을 성공으로 적지 않는다.
    """
    outcome: Optional[Dict[str, Any]] = None
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        event, data_lines = "", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            continue
        kind = event or (payload.get("type") if isinstance(payload, dict) else "")
        if kind not in ("complete", "error"):
            continue
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        if kind == "error":
            msg = data.get("error") if isinstance(data, dict) else None
            outcome = {"ok": False, "result": None, "error": str(msg or data)[:500]}
            continue
        reason = failure_reason(data)
        if reason:
            outcome = {"ok": False, "result": None, "error": reason}
        else:
            body = data.get("result", data) if isinstance(data, dict) else data
            outcome = {"ok": True, "result": body, "error": ""}
    return outcome or {"ok": False, "result": None,
                       "error": "스트림이 complete 없이 끝났다 (결과를 알 수 없음)"}


class HttpAcpTransport:
    """ACP 서버(Logos ACP · logosai serve)와 HTTP 로 말한다."""

    def __init__(self, base_url: str, token: str = "", timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    async def _session(self):
        import aiohttp
        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout),
                                     headers=auth_headers(self.token))

    async def list_agents(self) -> List[Dict[str, Any]]:
        async with await self._session() as s:
            async with s.post(f"{self.base_url}/jsonrpc",
                              json={"jsonrpc": "2.0", "id": 1, "method": "list_agents", "params": {}}) as r:
                if r.status != 200:
                    raise RuntimeError(f"list_agents HTTP {r.status}")
                body = await r.json(content_type=None)
        if body.get("error"):
            raise RuntimeError(f"list_agents: {body['error'].get('message', body['error'])}")
        result = body.get("result") or {}
        agents = result.get("agents", result) if isinstance(result, dict) else result
        return [a for a in (agents or []) if isinstance(a, dict) and (a.get("agent_id") or a.get("id"))]

    async def run(self, query: str, agent_id: str = "") -> Dict[str, Any]:
        payload: Dict[str, Any] = {"query": query}
        if agent_id:
            payload["agent_id"] = agent_id
        try:
            async with await self._session() as s:
                async with s.post(f"{self.base_url}/stream", json=payload,
                                  headers={"Accept": "text/event-stream"}) as r:
                    raw = await r.text()
                    if r.status != 200:
                        return {"ok": False, "result": None, "error": f"HTTP {r.status}: {raw[:300]}"}
        except asyncio.TimeoutError:
            return {"ok": False, "result": None, "error": f"{self.timeout:.0f}초 안에 끝나지 않았다"}
        except Exception as e:                       # 연결 실패도 도구 오류로 돌려준다
            return {"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"}
        return parse_sse_outcome(raw)


# ── MCP 브리지 ────────────────────────────────────────────────────────

def _tool_name(agent_id: str) -> str:
    name = _SANITIZE.sub("_", agent_id).strip("_")[:64]
    return name or "agent"


def _text_of(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("answer", "result", "content", "message", "text"):
            v = result.get(key)
            if isinstance(v, str) and v.strip():
                return v
            if isinstance(v, dict):
                inner = _text_of(v)
                if inner:
                    return inner
    return json.dumps(result, ensure_ascii=False, default=str) if result is not None else ""


def _tool_result(text: str, is_error: bool, structured: Any = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if isinstance(structured, dict):
        out["structuredContent"] = structured
    return out


class McpBridge:
    def __init__(self, transport: AcpTransport, mode: str = "router",
                 allow: Optional[Iterable[str]] = None):
        if mode not in ("router", "direct"):
            raise ValueError(f"mode 는 router|direct: {mode}")
        self.transport = transport
        self.mode = mode
        self.allow = [a for a in (allow or []) if a] or None

    def _allowed(self, agent_id: str) -> bool:
        return self.allow is None or agent_id in self.allow

    async def _agents(self) -> List[Dict[str, Any]]:
        agents = await self.transport.list_agents()
        return [a for a in agents if self._allowed(a.get("agent_id") or a.get("id"))]

    async def handle(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = msg.get("method", "")
        req_id = msg.get("id")
        if "id" not in msg:                  # 알림 — 응답하지 않는다
            return None
        params = msg.get("params") or {}
        try:
            if method == "initialize":
                asked = params.get("protocolVersion")
                version = asked if asked in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
                return _ok(req_id, {"protocolVersion": version,
                                    "capabilities": {"tools": {"listChanged": False}},
                                    "serverInfo": SERVER_INFO})
            if method == "ping":
                return _ok(req_id, {})
            if method == "tools/list":
                return _ok(req_id, {"tools": await self._list_tools()})
            if method == "tools/call":
                return await self._call(req_id, params)
            return _err(req_id, -32601, f"Method not found: {method}")
        except Exception as e:               # 서버 연결 실패 등 — 클라이언트를 죽이지 않는다
            return _err(req_id, -32603, f"{type(e).__name__}: {e}")

    async def _list_tools(self) -> List[Dict[str, Any]]:
        if self.mode == "router":
            hint = f" 허용된 에이전트: {', '.join(self.allow)}." if self.allow else ""
            return [
                {"name": "logosai_agents",
                 "description": "LogosAI 에이전트 목록(id·설명)을 돌려준다. logosai_ask 의 agent_id 를 고를 때 쓴다.",
                 "inputSchema": {"type": "object", "properties": {}}},
                {"name": "logosai_ask",
                 "description": "LogosAI 에이전트에게 질의한다. agent_id 를 생략하면 서버가 적합한 에이전트를 고른다." + hint,
                 "inputSchema": {"type": "object", "required": ["query"], "properties": {
                     "query": {"type": "string", "description": "에이전트에게 보낼 요청(자연어)"},
                     "agent_id": {"type": "string", "description": "실행할 에이전트 id (logosai_agents 참고)"}}}},
            ]
        tools = []
        for a in await self._agents():
            aid = a.get("agent_id") or a.get("id")
            tools.append({"name": _tool_name(aid),
                          "description": (a.get("description") or a.get("name") or aid)[:1024],
                          "inputSchema": {"type": "object", "required": ["query"],
                                          "properties": {"query": {"type": "string"}}}})
        return tools

    async def _call(self, req_id, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name", "")
        args = params.get("arguments") or {}
        if self.mode == "router" and name == "logosai_agents":
            agents = await self._agents()
            lines = [f"- {a.get('agent_id') or a.get('id')}: {a.get('description') or a.get('name') or ''}".rstrip()
                     for a in agents]
            return _ok(req_id, _tool_result("\n".join(lines) or "(에이전트 없음)", False,
                                            {"agents": agents}))
        if self.mode == "router" and name == "logosai_ask":
            agent_id = (args.get("agent_id") or "").strip()
        elif self.mode == "direct":
            by_name = {_tool_name(a.get("agent_id") or a.get("id")): (a.get("agent_id") or a.get("id"))
                       for a in await self._agents()}
            if name not in by_name:
                return _err(req_id, -32602, f"Unknown tool: {name}")
            agent_id = by_name[name]
        else:
            return _err(req_id, -32602, f"Unknown tool: {name}")

        query = (args.get("query") or "").strip()
        if not query:
            return _ok(req_id, _tool_result("query 가 비어 있다.", True))
        if self.allow is not None and not agent_id:
            return _ok(req_id, _tool_result(
                f"허용 목록이 있으므로 agent_id 를 지정해야 한다: {', '.join(self.allow)}", True))
        if agent_id and not self._allowed(agent_id):
            return _ok(req_id, _tool_result(f"허용되지 않은 에이전트: {agent_id}", True))

        outcome = await self.transport.run(query, agent_id)
        if not outcome.get("ok"):
            return _ok(req_id, _tool_result(outcome.get("error") or "실행 실패", True))
        result = outcome.get("result")
        reason = failure_reason(result)
        if reason:
            return _ok(req_id, _tool_result(reason, True))
        return _ok(req_id, _tool_result(_text_of(result), False,
                                        result if isinstance(result, dict) else None))


def _ok(req_id, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# ── stdio ─────────────────────────────────────────────────────────────

async def serve_lines(bridge: McpBridge, lines: Iterable[str], out) -> None:
    """줄 단위 JSON-RPC 처리 (테스트·serve_stdio 공용). 응답은 한 줄에 하나."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply: Optional[Dict[str, Any]] = _err(None, -32700, "Parse error")
        else:
            reply = await bridge.handle(msg) if isinstance(msg, dict) else _err(None, -32600, "Invalid Request")
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            out.flush()


async def serve_stdio(bridge: McpBridge) -> None:
    loop = asyncio.get_running_loop()

    def _lines():
        return iter(sys.stdin.readline, "")

    # stdin 은 블로킹이라 읽기는 스레드에서, 처리는 이 루프에서 한 줄씩
    it = _lines()
    while True:
        line = await loop.run_in_executor(None, lambda: next(it, None))
        if line is None:
            break
        await serve_lines(bridge, [line], sys.stdout)
