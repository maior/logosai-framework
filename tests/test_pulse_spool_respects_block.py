"""전송이 막혀 있으면 대기 파일에도 쌓지 않는다 (2026-11-10).

무엇이 샜나
──────────
시험 중에는 Pulse 전송이 기본으로 막힌다(_sending_blocked). 그런데 실행 중인 이벤트 루프가 없을 때
_fire_and_forget 은 그 판정을 묻기 전에 대기 파일(~/.logosai/pulse_spool.jsonl)에 적재했다.
대기 파일은 나중에 서비스가 다시 보낸다 — 시험 실행 한 번에 시험용 span 18건이 실제 대기 파일에 쌓였다.
'막았다'가 '나중에 보낸다'로 바뀌는 길이다.
"""
import json

from logosai.utils import pulse_client as pc

SPAN = "/api/v1/ingest/span"


async def _noop():
    return None


def _fire(endpoint, data):
    pc._fire_and_forget(_noop(), endpoint, data)        # 동기 문맥 — 실행 중인 루프가 없다


def test_blocked_send_is_not_spooled(tmp_path, monkeypatch):
    spool = tmp_path / "spool.jsonl"
    monkeypatch.setattr(pc, "_SPOOL_PATH", str(spool))
    monkeypatch.delenv("LOGOSAI_PULSE_ALLOW_IN_TESTS", raising=False)
    assert pc._sending_blocked()                         # 전제: 시험 중엔 막혀 있다
    _fire(SPAN, {"name": "test.blocked"})
    assert not spool.exists() or spool.read_text() == ""


def test_allowed_send_without_a_loop_is_still_spooled(tmp_path, monkeypatch):
    """대조 — 막은 것이 '전부'가 아니다. 허용된 전송은 루프가 없어도 유실되지 않는다."""
    spool = tmp_path / "spool.jsonl"
    monkeypatch.setattr(pc, "_SPOOL_PATH", str(spool))
    monkeypatch.delenv("LOGOS_PULSE_DISABLED", raising=False)
    monkeypatch.setenv("LOGOSAI_PULSE_ALLOW_IN_TESTS", "1")
    assert not pc._sending_blocked()
    _fire(SPAN, {"name": "test.allowed"})
    rows = [json.loads(x) for x in spool.read_text().splitlines()]
    assert [r["data"]["name"] for r in rows] == ["test.allowed"]


def test_explicitly_disabled_send_is_not_spooled(tmp_path, monkeypatch):
    spool = tmp_path / "spool.jsonl"
    monkeypatch.setattr(pc, "_SPOOL_PATH", str(spool))
    monkeypatch.setenv("LOGOS_PULSE_DISABLED", "1")
    monkeypatch.setenv("LOGOSAI_PULSE_ALLOW_IN_TESTS", "1")
    _fire(SPAN, {"name": "test.disabled"})
    assert not spool.exists() or spool.read_text() == ""
