"""logosai mcp — ACP 서버를 MCP 클라이언트(Claude Code·Codex 등)에 잇는 stdio 브리지.

브리지는 ACP 프로토콜로 말한다: 도구 목록은 JSON-RPC `list_agents`, 실행은 `POST /stream`
의 마지막 complete/error 이벤트. 그래서 서버에 /mcp 를 켜지 않아도 Logos ACP 와
`logosai serve`(SimpleACPServer) 양쪽에 붙는다.

계약:
  · MCP 수명주기: initialize(버전 협상) · notifications(무응답) · ping · tools/list · tools/call
  · router 모드(기본): logosai_agents + logosai_ask — 에이전트 수만큼 도구를 펼치지 않는다
  · 허용 목록 밖 에이전트는 실행 전에 거절 (서버 호출 자체가 없어야 한다)
  · 실패 판정은 SDK 정본 failure_reason() — 봉투가 실패면 isError
  · 토큰은 환경변수에서만, Authorization: Bearer 로
  · 실제 SimpleACPServer 를 띄워 끝단까지 (가짜 서버만으로는 형식 불일치를 못 잡는다)
"""
import asyncio
import io
import json
import os
import subprocess
import sys

import pytest

from logosai import mcp_bridge as mb


class FakeTransport:
    def __init__(self, agents=None, results=None):
        self.agents = agents if agents is not None else [
            {"agent_id": "calculator_agent", "name": "계산기", "description": "사칙연산"},
            {"agent_id": "file_agent", "name": "파일", "description": "로컬 파일 읽기"},
            {"agent_id": "날씨_agent", "name": "날씨", "description": "날씨 조회"},
        ]
        self.results = results or {}
        self.runs = []

    async def list_agents(self):
        return list(self.agents)

    async def run(self, query, agent_id=""):
        self.runs.append((query, agent_id))
        return self.results.get(agent_id, {"ok": True, "result": {"answer": f"{agent_id}:{query}"}, "error": ""})


def call(bridge, method, params=None, id_=1):
    msg = {"jsonrpc": "2.0", "method": method}
    if id_ is not None:
        msg["id"] = id_
    if params is not None:
        msg["params"] = params
    return asyncio.run(bridge.handle(msg))


# ── 수명주기 ──────────────────────────────────────────────────────────

def test_initialize_negotiates_known_version_and_names_itself():
    b = mb.McpBridge(FakeTransport())
    r = call(b, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})["result"]
    assert r["protocolVersion"] == "2025-06-18"
    assert r["serverInfo"]["name"] == "logosai" and "tools" in r["capabilities"]


def test_initialize_falls_back_to_our_version_for_unknown_request():
    b = mb.McpBridge(FakeTransport())
    r = call(b, "initialize", {"protocolVersion": "1999-01-01"})["result"]
    assert r["protocolVersion"] in mb.SUPPORTED_PROTOCOL_VERSIONS


def test_notifications_get_no_response_and_ping_does():
    b = mb.McpBridge(FakeTransport())
    assert call(b, "notifications/initialized", id_=None) is None
    assert call(b, "ping")["result"] == {}                      # 대조군 — 요청에는 응답한다


def test_unknown_method_is_method_not_found():
    b = mb.McpBridge(FakeTransport())
    assert call(b, "resources/list")["error"]["code"] == -32601


# ── 도구 목록 ─────────────────────────────────────────────────────────

def test_router_mode_exposes_two_tools_not_one_per_agent():
    b = mb.McpBridge(FakeTransport())
    tools = call(b, "tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == {"logosai_agents", "logosai_ask"}
    ask = next(t for t in tools if t["name"] == "logosai_ask")
    assert ask["inputSchema"]["required"] == ["query"] and "agent_id" in ask["inputSchema"]["properties"]


def test_direct_mode_one_tool_per_allowed_agent_with_safe_names():
    b = mb.McpBridge(FakeTransport(), mode="direct", allow=["calculator_agent", "날씨_agent"])
    names = [t["name"] for t in call(b, "tools/list")["result"]["tools"]]
    assert "calculator_agent" in names and not any("file_agent" in n for n in names)
    assert all(mb.TOOL_NAME_RE.fullmatch(n) for n in names)     # 한글 id 도 규칙에 맞게
    assert len(names) == 2


def test_agents_tool_lists_only_allowed_agents():
    b = mb.McpBridge(FakeTransport(), allow=["calculator_agent"])
    r = call(b, "tools/call", {"name": "logosai_agents", "arguments": {}})["result"]
    text = r["content"][0]["text"]
    assert "calculator_agent" in text and "file_agent" not in text


# ── 실행 ──────────────────────────────────────────────────────────────

def test_ask_returns_answer_text():
    t = FakeTransport()
    b = mb.McpBridge(t)
    r = call(b, "tools/call", {"name": "logosai_ask", "arguments": {"query": "1+1", "agent_id": "calculator_agent"}})["result"]
    assert r["isError"] is False and r["content"][0]["text"] == "calculator_agent:1+1"
    assert t.runs == [("1+1", "calculator_agent")]


def test_disallowed_agent_is_refused_before_any_server_call():
    t = FakeTransport()
    b = mb.McpBridge(t, allow=["calculator_agent"])
    r = call(b, "tools/call", {"name": "logosai_ask", "arguments": {"query": "x", "agent_id": "file_agent"}})["result"]
    assert r["isError"] is True and t.runs == []
    call(b, "tools/call", {"name": "logosai_ask", "arguments": {"query": "x", "agent_id": "calculator_agent"}})
    assert t.runs == [("x", "calculator_agent")]               # 대조군 — 허용된 것은 간다


def test_router_without_agent_id_lets_server_choose_unless_allowlisted():
    t = FakeTransport()
    call(mb.McpBridge(t), "tools/call", {"name": "logosai_ask", "arguments": {"query": "q"}})
    assert t.runs == [("q", "")]                                # 서버가 고른다
    t2 = FakeTransport()
    r = call(mb.McpBridge(t2, allow=["calculator_agent"]), "tools/call",
             {"name": "logosai_ask", "arguments": {"query": "q"}})["result"]
    # 허용 목록이 있으면 서버가 목록 밖을 고를 수 있으므로 agent_id 를 요구한다
    assert r["isError"] is True and t2.runs == []


def test_failure_envelope_becomes_tool_error():
    t = FakeTransport(results={"calculator_agent": {
        "ok": True, "result": {"response_type": "error", "error": "quota exceeded"}, "error": ""}})
    r = call(mb.McpBridge(t), "tools/call",
             {"name": "logosai_ask", "arguments": {"query": "1", "agent_id": "calculator_agent"}})["result"]
    assert r["isError"] is True and "quota" in r["content"][0]["text"]


def test_transport_error_becomes_tool_error():
    t = FakeTransport(results={"calculator_agent": {"ok": False, "result": None, "error": "stream error: boom"}})
    r = call(mb.McpBridge(t), "tools/call",
             {"name": "logosai_ask", "arguments": {"query": "1", "agent_id": "calculator_agent"}})["result"]
    assert r["isError"] is True and "boom" in r["content"][0]["text"]


def test_missing_query_and_unknown_tool():
    b = mb.McpBridge(FakeTransport())
    r = call(b, "tools/call", {"name": "logosai_ask", "arguments": {}})["result"]
    assert r["isError"] is True
    assert call(b, "tools/call", {"name": "nope", "arguments": {}})["error"]["code"] == -32602


# ── 전송 계층 ─────────────────────────────────────────────────────────

def test_auth_header_only_when_token_given():
    assert mb.auth_headers("") == {}
    assert mb.auth_headers("abc")["Authorization"] == "Bearer abc"


def test_sse_parser_takes_last_complete_or_error():
    raw = ("event: start\ndata: {\"type\": \"start\"}\n\n"
           "event: chunk\ndata: {\"type\": \"chunk\", \"data\": {\"content\": \"x\"}}\n\n"
           "event: complete\ndata: {\"type\": \"complete\", \"data\": {\"result\": {\"answer\": \"42\"}}}\n\n")
    assert mb.parse_sse_outcome(raw) == {"ok": True, "result": {"answer": "42"}, "error": ""}
    err = "event: error\ndata: {\"type\": \"error\", \"data\": {\"error\": \"bad\"}}\n\n"
    out = mb.parse_sse_outcome(err)
    assert out["ok"] is False and "bad" in out["error"]
    assert mb.parse_sse_outcome("event: start\ndata: {}\n\n")["ok"] is False   # 끝맺음 없음 ≠ 성공


# ── stdio 루프 ────────────────────────────────────────────────────────

def test_stdio_loop_one_line_per_response_and_parse_errors():
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        "{not json",
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]
    out = io.StringIO()
    asyncio.run(mb.serve_lines(mb.McpBridge(FakeTransport()), iter(lines), out))
    replies = [json.loads(l) for l in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, None, 2]       # 알림엔 응답 없음
    assert replies[1]["error"]["code"] == -32700


# ── 끝단: 실제 SimpleACPServer ────────────────────────────────────────

async def test_end_to_end_against_real_simple_acp_server():
    from aiohttp.test_utils import TestServer
    from logosai.acp import SimpleACPServer
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse

    class Echo(SimpleAgent):
        async def handle(self, query, context=None):
            return AgentResponse.success(content={"answer": f"echo:{query}"})

    srv = SimpleACPServer(port=0)
    srv.add(Echo(), "echo_agent")
    ts = TestServer(srv._create_app())
    await ts.start_server()
    try:
        base = str(ts.make_url("")).rstrip("/")
        b = mb.McpBridge(mb.HttpAcpTransport(base, timeout=30))
        tools = (await b.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": "logosai_agents", "arguments": {}}}))["result"]
        assert "echo_agent" in tools["content"][0]["text"]
        r = (await b.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                             "params": {"name": "logosai_ask",
                                        "arguments": {"query": "안녕", "agent_id": "echo_agent"}}}))["result"]
        assert r["isError"] is False and r["content"][0]["text"] == "echo:안녕"
    finally:
        await ts.close()


# ── CLI 배선 ──────────────────────────────────────────────────────────

def test_cli_has_mcp_command():
    p = subprocess.run([sys.executable, "-m", "logosai.cli.main", "mcp", "--help"],
                       capture_output=True, text=True, timeout=60,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert p.returncode == 0 and "--acp" in p.stdout and "LOGOSAI_ACP_TOKEN" in p.stdout
