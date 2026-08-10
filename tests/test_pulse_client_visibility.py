"""pulse_client 전송 실패 가시화 테스트 (2026-07-18).

배경: LogosPulse 가 2026-07-15~18 죽어 있는 동안 _post 가 예외를 전부 삼켜
      메트릭이 아무 흔적 없이 유실됐다. 실패가 보이도록 만드는 것이 목적.

계약: _post 는 어떤 경우에도 raise 하지 않는다 (에이전트 실행 차단 금지).

직접 실행: python tests/test_pulse_client_visibility.py
"""

import asyncio
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



# ── 상태 코드를 지정할 수 있는 최소 스텁 서버 ──────────────────
class _StubHandler(BaseHTTPRequestHandler):
    status = 200

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *args):
        pass  # 테스트 출력 오염 방지


def _start_stub(status: int):
    _StubHandler.status = status
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _free_port() -> int:
    """아무도 듣지 않는 포트 — 연결 거부를 재현한다."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _reset():
    pulse_client._stats.update({"sent": 0, "failed": 0, "last_error": ""})
    pulse_client._last_warn_ts = 0.0


# ── 테스트 ────────────────────────────────────────────────
def test_success_increments_sent():
    """2xx 응답이면 sent 가 증가한다."""
    _reset()
    server, url = _start_stub(200)
    try:
        pulse_client.PULSE_URL = url
        asyncio.run(pulse_client._post("/api/v1/ingest/execution", {"agent_id": "x"}))
    finally:
        server.shutdown()

    stats = pulse_client.get_pulse_stats()
    assert stats["sent"] == 1, f"sent 미증가: {stats}"
    assert stats["failed"] == 0, f"실패로 오분류: {stats}"
    print("PASS success_increments_sent")


def test_4xx_counted_as_failure():
    """422 같은 4xx 는 성공이 아니다 — 이걸 놓쳐서 llm_calls 유실이 3주간 숨었다."""
    _reset()
    server, url = _start_stub(422)
    try:
        pulse_client.PULSE_URL = url
        asyncio.run(pulse_client._post("/api/v1/ingest/llm-call", {"agent_id": "x"}))
    finally:
        server.shutdown()

    stats = pulse_client.get_pulse_stats()
    assert stats["failed"] == 1, f"4xx 를 실패로 세지 않음: {stats}"
    assert stats["sent"] == 0, f"4xx 를 성공으로 집계: {stats}"
    assert "422" in stats["last_error"], f"원인 미기록: {stats}"
    print("PASS 4xx_counted_as_failure")


def test_connection_refused_counted_and_never_raises():
    """Pulse 가 죽어 있어도 예외를 던지지 않되, 흔적은 남긴다."""
    _reset()
    pulse_client.PULSE_URL = f"http://127.0.0.1:{_free_port()}"

    asyncio.run(pulse_client._post("/api/v1/ingest/execution", {"agent_id": "x"}))

    stats = pulse_client.get_pulse_stats()
    assert stats["failed"] == 1, f"연결 실패 미집계: {stats}"
    assert stats["last_error"], "실패 원인이 비어 있음"
    print("PASS connection_refused_counted_and_never_raises")


def test_repeated_failures_accumulate():
    """실패가 누적 카운트되어 규모를 알 수 있어야 한다."""
    _reset()
    pulse_client.PULSE_URL = f"http://127.0.0.1:{_free_port()}"

    for _ in range(3):
        asyncio.run(pulse_client._post("/api/v1/ingest/span", {}))

    assert pulse_client.get_pulse_stats()["failed"] == 3
    print("PASS repeated_failures_accumulate")


if __name__ == "__main__":
    os.environ["LOGOSAI_PULSE_ALLOW_IN_TESTS"] = "1"  # 직접 실행 시에도 전송 허용
    _original = pulse_client.PULSE_URL
    _original_spool = pulse_client._SPOOL_PATH
    # 실패 전송은 스풀에 쌓인다 — 테스트가 사용자의 실제 스풀을 오염시키면 안 된다
    with tempfile.TemporaryDirectory() as tmpdir:
        pulse_client._SPOOL_PATH = os.path.join(tmpdir, "spool.jsonl")
        try:
            test_success_increments_sent()
            test_4xx_counted_as_failure()
            test_connection_refused_counted_and_never_raises()
            test_repeated_failures_accumulate()
            print("\n✅ pulse_client 가시성 테스트 4/4 통과")
        finally:
            pulse_client.PULSE_URL = _original
            pulse_client._SPOOL_PATH = _original_spool
