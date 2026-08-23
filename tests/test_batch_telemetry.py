"""배치/단독 스크립트의 관측 호스트 계약 (2026-08-22).

왜 이 모듈이 필요한가 — 실측 사고
────────────────────────────────
`review_audit.py` 가 `gemini-2.5-flash` 로 **544회** LLM 을 호출했는데
`/api/v1/costs` 의 by_model 에 그 모델이 **아예 없었다**. 스풀
(`~/.logosai/pulse_spool.jsonl`)조차 없었다 — 보내려다 실패한 것도 아니고
**애초에 아무도 보내지 않았다**.

원인은 두 겹이다.

  ① `LLMClient` 는 스스로 기록하지 않는다. 호스트가 `_metrics_callback` 을
     꽂아야 한다. 그런데 그걸 하는 곳은 ACP(`server.py`)와
     logos_api(`orchestrator_service.py`) 둘뿐이다. 스크립트는 호스트가 없다.

  ② 콜백을 꽂아도 새지 않는다는 보장이 없다. 전송은 fire-and-forget
     (`_fire_and_forget` → `loop.create_task`)인데, `asyncio.run(main())` 은
     반환 직전 남은 태스크를 **전부 취소**한다. 이 파일의
     `test_pending_bg_tasks_die_at_loop_exit` 가 그 사실을 못박는다:
     실측 결과 대기 3건 → 배달 0건 · 실패 집계 0건 · 스풀 0건. 실패로조차
     남지 않는 완전한 침묵이다.

그래서 이 계약의 핵심은 콜백 배선이 아니라 **종료 전 배수(drain)** 다.

전송 자체는 pytest 아래에서 기본 차단된다(`test_pulse_test_isolation.py`).
여기서는 그것과 싸우지 않는다 — 순수한 부분(페이로드 성형·배수 순서·
ContextVar 귀속)만 검증하고, 실제 배달은 스크립트를 진짜로 돌려서 확인한다.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logosai.utils import pulse_client as pc  # noqa: E402
from logosai.utils.batch_telemetry import (  # noqa: E402
    batch_run,
    drain_pulse,
    llm_metrics_payload,
)
from logosai.utils.llm_client import LLMClient  # noqa: E402
from logosai.utils.trace_span import (  # noqa: E402
    get_current_agent_id,
    get_current_trace_id,
)


# ── ① 가설 고정: 루프가 닫히면 대기 전송은 침묵 속에 죽는다 ──────────────

def test_pending_bg_tasks_die_at_loop_exit():
    """`asyncio.run` 종료가 fire-and-forget 을 죽인다 — 배수가 필요한 이유.

    이 테스트가 깨진다면 파이썬/pulse_client 쪽이 바뀐 것이고, 그때는
    `drain_pulse` 의 존재 이유를 다시 따져야 한다.
    """
    delivered = []

    async def slow():
        await asyncio.sleep(0.05)
        delivered.append(1)

    async def main():
        pc._fire_and_forget(slow())
        assert pc._BG_TASKS, "태스크가 등록조차 안 됐다 — 실험이 무의미"

    asyncio.run(main())
    assert delivered == [], "루프 종료 후에도 배달됐다면 가설이 틀린 것"


def test_drain_pulse_waits_for_pending_sends():
    """배수하면 같은 상황에서 배달된다."""
    delivered = []

    async def slow():
        await asyncio.sleep(0.05)
        delivered.append(1)

    async def main():
        for _ in range(3):
            pc._fire_and_forget(slow())
        return await drain_pulse(timeout=5.0)

    drained = asyncio.run(main())
    assert delivered == [1, 1, 1], f"배수했는데 {len(delivered)}건만 배달"
    assert drained == 3, f"배수 건수 보고가 틀리다: {drained}"


def test_drain_pulse_returns_on_timeout_without_hanging():
    """전송이 영원히 안 끝나도 스크립트를 붙잡지 않는다."""
    async def forever():
        await asyncio.sleep(30)

    async def main():
        pc._fire_and_forget(forever())
        return await drain_pulse(timeout=0.2)

    import time
    t0 = time.monotonic()
    drained = asyncio.run(main())
    elapsed = time.monotonic() - t0
    assert elapsed < 5, f"타임아웃을 넘겨 {elapsed:.1f}초 매달렸다"
    assert drained == 0, "끝나지 않은 전송을 배달됐다고 셌다"


def test_drain_pulse_is_noop_when_nothing_pending():
    assert asyncio.run(drain_pulse(timeout=1.0)) == 0


# ── ② 페이로드 성형 (순수) ──────────────────────────────────────────

def test_llm_metrics_payload_shapes_fields():
    out = llm_metrics_payload({
        "model": "gemini-2.5-flash",
        "provider": "google",
        "input_tokens": "120",     # 문자열로 와도 정수로
        "output_tokens": 30,
        "duration_ms": "812.5",
        "success": True,
        "prompt_preview": "판정하라",
    })
    assert out["model"] == "gemini-2.5-flash"
    assert out["input_tokens"] == 120
    assert out["output_tokens"] == 30
    assert out["duration_ms"] == 812.5
    assert out["success"] is True


def test_llm_metrics_payload_survives_garbage():
    """망가진 입력이 관측을 예외로 만들지 않는다 (LLM 응답을 막으면 안 된다)."""
    out = llm_metrics_payload({"input_tokens": None, "duration_ms": "x"})
    assert out["input_tokens"] == 0
    assert out["duration_ms"] == 0.0
    assert out["model"] == ""


def test_llm_metrics_payload_leaves_agent_empty_outside_trace():
    """trace 밖 호출은 agent_id 를 **비운다** — 그럴듯한 이름을 지어내지 않는다."""
    out = llm_metrics_payload({"model": "m"})
    assert out["agent_id"] == "", "trace 밖인데 에이전트를 추측했다"
    assert out["execution_id"] is None


# ── ③ batch_run 컨텍스트 계약 ───────────────────────────────────────

def test_batch_run_sets_trace_and_agent_context():
    """블록 안의 LLM 호출이 이 실행에 귀속되도록 ContextVar 가 서 있어야 한다."""
    seen = {}

    async def main():
        async with batch_run("census_probe") as run:
            seen["trace"] = get_current_trace_id()
            seen["agent"] = get_current_agent_id()
            seen["run_trace"] = run.trace_id

    asyncio.run(main())
    assert seen["agent"] == "batch.census_probe"
    assert seen["trace"] and seen["trace"] == seen["run_trace"]


def test_batch_run_llm_payload_is_attributed_to_the_batch():
    """블록 안에서는 콜백이 배치 실행에 비용을 붙인다."""
    got = {}

    async def main():
        async with batch_run("census_probe") as run:
            got["payload"] = llm_metrics_payload({"model": "m"})
            got["trace"] = run.trace_id

    asyncio.run(main())
    assert got["payload"]["agent_id"] == "batch.census_probe"
    assert got["payload"]["execution_id"] == got["trace"]


def test_batch_run_installs_callback_and_restores_it():
    """남의 호스트(ACP 등) 콜백을 덮지 않고, 자기 것은 반드시 걷어낸다."""
    before = LLMClient._metrics_callback
    inside = {}

    async def main():
        async with batch_run("census_probe"):
            inside["cb"] = LLMClient._metrics_callback

    asyncio.run(main())
    assert inside["cb"] is not None, "콜백을 꽂지 않았다 — 원인 ①이 그대로다"
    # `is not before` 를 함께 본다: 앞선 배치가 콜백을 흘려 두면 이 배치는
    # 아무것도 꽂지 않고도 "복원됐다"로 통과한다 — 실제로 그렇게 통과하는
    # 동안 다음 배치의 LLM 호출이 한 건도 안 세어졌다 (바운드 메서드 identity).
    assert inside["cb"] is not before, "이미 남의 콜백이 있었다 — 이전 배치가 흘렸다"
    assert LLMClient._metrics_callback is before, "콜백을 되돌리지 않았다"


def test_batch_run_does_not_override_existing_callback():
    sentinel_calls = []
    prev = LLMClient._metrics_callback
    LLMClient._metrics_callback = lambda d: sentinel_calls.append(d)
    try:
        async def main():
            async with batch_run("census_probe"):
                assert LLMClient._metrics_callback is not None
                assert sentinel_calls == []
                LLMClient._metrics_callback({"model": "m"})
        asyncio.run(main())
        assert len(sentinel_calls) == 1, "기존 호스트의 콜백이 밀려났다"
    finally:
        LLMClient._metrics_callback = prev


def test_batch_run_sends_execution_with_trace_id_as_execution_id():
    """실행 레코드의 id 가 trace_id 여야 span 트리와 연결된다."""
    sent = []
    orig = pc.send_execution

    async def fake(**kw):
        sent.append(kw)

    pc.send_execution = fake
    try:
        async def main():
            async with batch_run("census_probe", query="전수 census") as run:
                run.note(files=2)
                return run.trace_id
        trace_id = asyncio.run(main())
    finally:
        pc.send_execution = orig

    assert len(sent) == 1, f"실행 레코드가 {len(sent)}건 (1건이어야)"
    rec = sent[0]
    assert rec["execution_id"] == trace_id
    assert rec["agent_id"] == "batch.census_probe"
    assert rec["success"] is True
    assert rec["query"] == "전수 census"
    assert rec["metadata"]["files"] == 2
    assert rec["duration_ms"] > 0


def test_batch_run_records_failure_and_reraises():
    """실패한 배치가 '성공'으로 남으면 관측이 거짓말을 한다."""
    sent = []
    orig = pc.send_execution

    async def fake(**kw):
        sent.append(kw)

    pc.send_execution = fake
    try:
        async def main():
            async with batch_run("census_probe"):
                raise ValueError("망가짐")
        try:
            asyncio.run(main())
        except ValueError:
            pass
        else:
            raise AssertionError("예외를 삼켰다 — 스크립트가 실패를 못 본다")
    finally:
        pc.send_execution = orig

    assert len(sent) == 1
    assert sent[0]["success"] is False
    assert "망가짐" in sent[0]["error_message"]


def test_batch_run_keeps_tokens_in_metadata_not_in_token_count():
    """토큰은 metadata 에만. `token_count` 로 보내면 **이중 계상**된다.

    실측(2026-08-22 라이브): Pulse 는 llm-call 마다 소속 execution 에
    `token_count = token_count + :tokens` 로 이미 굴려 넣는다. 거기에 배치가
    자기 합계를 또 보내서 진짜 8,222 토큰이 by_agent 에 16,444 로 찍혔다.
    ACP 가 최종 execution 에 0 을 보내는 이유가 이것이다.
    """
    sent = []
    orig = pc.send_execution

    async def fake(**kw):
        sent.append(kw)

    pc.send_execution = fake
    try:
        async def main():
            async with batch_run("census_probe"):
                cb = LLMClient._metrics_callback
                cb({"model": "m", "input_tokens": 10, "output_tokens": 5})
                cb({"model": "m", "input_tokens": 7, "output_tokens": 3})
        asyncio.run(main())
    finally:
        pc.send_execution = orig

    assert "token_count" not in sent[0], "이중 계상 — Pulse 가 이미 굴려 넣는다"
    assert sent[0]["metadata"]["llm_calls"] == 2
    assert sent[0]["metadata"]["input_tokens"] == 17
    assert sent[0]["metadata"]["output_tokens"] == 8


def test_batch_run_drains_before_returning():
    """배수가 실행 레코드 전송 **뒤에** 와야 그 전송도 배달된다."""
    order = []
    orig = pc.send_execution

    async def fake(**kw):
        order.append("execution")

    pc.send_execution = fake
    try:
        async def main():
            async with batch_run("census_probe"):
                async def slow():
                    await asyncio.sleep(0.05)
                    order.append("span")
                pc._fire_and_forget(slow())
        asyncio.run(main())
    finally:
        pc.send_execution = orig

    assert "span" in order, "배수 전에 반환해 전송이 죽었다"
    assert order == ["execution", "span"], (
        f"실행 레코드 → 배수 순서가 아니다: {order}")


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = f = 0
    for k, fn in fns:
        try:
            fn()
            print(f"  ✓ {k}")
            p += 1
        except Exception as e:
            print(f"  ✗ {k}: {type(e).__name__}: {e}")
            f += 1
    print(f"\npass={p} fail={f}")
    sys.exit(1 if f else 0)
