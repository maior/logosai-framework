"""실행 기록이 '어느 코드 리비전에서 났는지'를 실어 나르는지 (G1, 2026-08-22).

왜 이 테스트가 필요한가
──────────────────────
Pulse 수신 측은 2026-08-21 에 이미 완성돼 있었다 — `ingest.ExecutionRecord`
에 `agent_revision` 필드, `metrics_collector` 의 `COALESCE` 저장, 리비전별
비교 API(`routers/review.py`)까지. 그런데 **발신 측에 인자가 없어** 값이 한
번도 채워지지 않았고, `agent_executions.agent_revision` 은 전 행 NULL 이었다.

컬럼이 있다는 것과 값이 온다는 것은 다른 문제다. 이 테스트는 그 간극을 고정한다.

리비전 없이 코드를 고치면 "고쳤더니 좋아졌다"는 **상관이지 귀속이 아니다** —
같은 기간에 쉬운 쿼리로 트래픽이 쏠려도 똑같이 좋아 보인다.

직접 실행: python tests/test_pulse_execution_revision.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logosai.utils import pulse_client as pc  # noqa: E402


def _capture(**kwargs):
    """send_execution 이 _post 로 넘기는 payload 를 가로챈다 (전송하지 않는다)."""
    seen = {}

    async def fake_post(endpoint, data):
        seen["endpoint"] = endpoint
        seen["data"] = data

    orig = pc._post
    pc._post = fake_post
    try:
        asyncio.run(pc.send_execution(**kwargs))
    finally:
        pc._post = orig
    return seen


def test_revision_reaches_payload():
    """명시한 리비전이 그대로 실린다."""
    seen = _capture(agent_id="file_agent", agent_revision="abc123def456")
    assert seen["endpoint"] == "/api/v1/ingest/execution"
    assert seen["data"]["agent_revision"] == "abc123def456", seen["data"]
    print("PASS revision_reaches_payload")


def test_unknown_revision_is_empty_not_missing():
    """모르면 빈 문자열 — 키를 통째로 빼면 수신 측 기본값에 기대게 된다.

    사상 ⑦(모름 ≠ 없음): 빈 문자열은 수신 측에서 NULL 로 저장돼 어떤 리비전에도
    귀속되지 않는다. 그 '모름' 자체가 기록돼야 나중에 계측 공백을 셀 수 있다.
    """
    seen = _capture(agent_id="file_agent")
    assert "agent_revision" in seen["data"], "키가 사라졌다 — 모름을 표현할 수 없다"
    assert seen["data"]["agent_revision"] == "", seen["data"]["agent_revision"]
    print("PASS unknown_revision_is_empty_not_missing")


def test_existing_fields_untouched():
    """기존 계약을 깨지 않는다 — 이 함수는 세 곳에서 호출된다."""
    seen = _capture(
        agent_id="file_agent",
        query="q" * 300,
        success=False,
        duration_ms=12.5,
        error_message="boom",
        agent_name="파일",
        correlation_id="c1",
        user_email="a@b.c",
        session_id="s1",
        token_count=7,
        cost_usd=0.5,
        metadata={"trace_id": "t1"},
        execution_id="fixed-id",
        agent_revision="0123456789ab",
    )
    d = seen["data"]
    assert d["execution_id"] == "fixed-id"
    assert len(d["query"]) == 200, "query 절단 규칙이 바뀌었다"
    assert d["success"] is False and d["token_count"] == 7 and d["cost_usd"] == 0.5
    assert d["metadata"] == {"trace_id": "t1"}
    assert d["agent_revision"] == "0123456789ab"
    print("PASS existing_fields_untouched")


def test_bg_helper_forwards_revision():
    """send_execution_bg 는 **kwargs 통과 — 배선이 끊기지 않았는지 확인."""
    import inspect

    src = inspect.getsource(pc.send_execution_bg)
    assert "**kwargs" in src, "bg 헬퍼가 인자를 선별 전달하면 리비전이 조용히 사라진다"
    print("PASS bg_helper_forwards_revision")


if __name__ == "__main__":
    test_revision_reaches_payload()
    test_unknown_revision_is_empty_not_missing()
    test_existing_fields_untouched()
    test_bg_helper_forwards_revision()
    print("\n4/4 통과")
