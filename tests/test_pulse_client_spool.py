"""pulse_client 스풀 버퍼링/재전송 테스트 (2026-07-19).

배경: Pulse 가 2026-07-15~18 죽어 있는 동안 전송 실패분이 그대로 버려져
      3일치 메트릭이 영구 소실됐다. 실패분을 디스크에 모아뒀다가
      서버가 살아나면 재전송한다.

계약:
  - 절대 raise 하지 않는다 (에이전트 실행 차단 금지)
  - 스풀은 무제한이 아니다 (장기 다운 시 디스크 고갈 방지)

직접 실행: python tests/test_pulse_client_spool.py
"""

import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from logosai.utils import pulse_client

# 이 파일은 **전송 경로 자체**를 검증하므로, 2026-08-09 에 도입한
# "테스트 중 기본 차단" 을 명시적으로 푼다. monkeypatch 라 이 모듈 밖으로
# 새지 않는다 — 전역으로 세우면 막으려던 그 오염이 다시 열린다.
try:
    import pytest

    @pytest.fixture(autouse=True)
    def _allow_pulse_sending(monkeypatch):
        monkeypatch.setenv("LOGOSAI_PULSE_ALLOW_IN_TESTS", "1")
except ImportError:  # 직접 실행 경로는 __main__ 에서 세운다
    pass



class _StubHandler(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            _StubHandler.received.append(json.loads(body))
        except Exception:
            pass
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *args):
        pass


def _start_stub():
    _StubHandler.received = []
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _dead_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


def _spool_lines() -> list:
    path = pulse_client._SPOOL_PATH
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [ln for ln in f.read().splitlines() if ln.strip()]


def _reset(tmpdir: str):
    pulse_client._SPOOL_PATH = os.path.join(tmpdir, "spool.jsonl")
    if os.path.exists(pulse_client._SPOOL_PATH):
        os.remove(pulse_client._SPOOL_PATH)
    pulse_client._stats.update({"sent": 0, "failed": 0, "last_error": ""})


# ── 테스트 ────────────────────────────────────────────────
def test_failed_send_is_spooled(tmpdir):
    """서버가 죽어 있으면 페이로드를 버리지 않고 쌓아둔다."""
    _reset(tmpdir)
    pulse_client.PULSE_URL = _dead_url()

    asyncio.run(pulse_client._post("/api/v1/ingest/execution", {"agent_id": "a1"}))

    lines = _spool_lines()
    assert len(lines) == 1, f"스풀 미기록: {len(lines)}건"
    rec = json.loads(lines[0])
    assert rec["endpoint"] == "/api/v1/ingest/execution"
    assert rec["data"]["agent_id"] == "a1"
    print("PASS failed_send_is_spooled")


def test_spool_replayed_when_server_returns(tmpdir):
    """서버가 살아나면 쌓아둔 것이 재전송되고 스풀이 비워진다."""
    _reset(tmpdir)
    pulse_client.PULSE_URL = _dead_url()
    for i in range(3):
        asyncio.run(pulse_client._post("/api/v1/ingest/execution", {"agent_id": f"a{i}"}))
    assert len(_spool_lines()) == 3

    server, url = _start_stub()
    try:
        pulse_client.PULSE_URL = url
        asyncio.run(pulse_client._post("/api/v1/ingest/execution", {"agent_id": "live"}))
    finally:
        server.shutdown()

    agent_ids = {r.get("agent_id") for r in _StubHandler.received}
    assert {"a0", "a1", "a2"} <= agent_ids, f"재전송 누락: {agent_ids}"
    assert _spool_lines() == [], f"재전송 후 스풀 잔존: {_spool_lines()}"
    print("PASS spool_replayed_when_server_returns")


def test_spool_is_bounded(tmpdir):
    """장기 다운 시에도 스풀이 무한히 커지지 않는다 (오래된 것부터 폐기)."""
    _reset(tmpdir)
    pulse_client.PULSE_URL = _dead_url()
    original_max = pulse_client._SPOOL_MAX
    pulse_client._SPOOL_MAX = 5
    try:
        for i in range(12):
            asyncio.run(pulse_client._post("/api/v1/ingest/execution", {"agent_id": f"a{i}"}))
        lines = _spool_lines()
        assert len(lines) <= 5, f"상한 초과: {len(lines)}건"
        # 최신 것이 남아야 한다
        newest = json.loads(lines[-1])["data"]["agent_id"]
        assert newest == "a11", f"최신 항목 유실: {newest}"
    finally:
        pulse_client._SPOOL_MAX = original_max
    print("PASS spool_is_bounded")


def test_spool_only_idempotent_endpoints(tmpdir):
    """멱등한 endpoint 만 스풀한다 — span 은 2026-07-31 부터 포함.

    계약 정정: 예전엔 span ingest 가 `db.add` 라 재전송이 UniqueViolation 을 냈고,
    그래서 스풀 대상에서 제외했다. 그 결과 **전송 실패한 span 이 그냥 버려졌고**,
    FORGE 생성 과정이 통째로 관측에서 사라졌다(실측: Pulse 최신 span 이 9시간 전).
    서버를 `ON CONFLICT (id) DO NOTHING` 으로 멱등화했으므로 이제 스풀이 안전하다.

    반대로 멱등하지 않은 endpoint(conversation 등)는 여전히 제외돼야 한다.
    """
    _reset(tmpdir)
    pulse_client.PULSE_URL = _dead_url()

    asyncio.run(pulse_client._post("/api/v1/ingest/span", {"span_id": "s1"}))
    assert _spool_lines(), "span 이 스풀되지 않았다 — 전송 실패 시 유실된다"

    _reset(tmpdir)
    asyncio.run(pulse_client._post("/api/v1/ingest/conversation", {"trace_id": "t1"}))
    assert _spool_lines() == [], "멱등하지 않은 endpoint 가 스풀됨 (재전송 시 중복)"
    print("PASS spool_only_idempotent_endpoints")


if __name__ == "__main__":
    os.environ["LOGOSAI_PULSE_ALLOW_IN_TESTS"] = "1"  # 직접 실행 시에도 전송 허용
    _original_url = pulse_client.PULSE_URL
    _original_spool = pulse_client._SPOOL_PATH
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            test_failed_send_is_spooled(tmpdir)
            test_spool_replayed_when_server_returns(tmpdir)
            test_spool_is_bounded(tmpdir)
            test_spool_only_idempotent_endpoints(tmpdir)
            print("\n✅ 스풀 버퍼링 테스트 4/4 통과")
        finally:
            pulse_client.PULSE_URL = _original_url
            pulse_client._SPOOL_PATH = _original_spool
