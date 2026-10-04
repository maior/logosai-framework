"""이벤트 스트림이 계획 수립 도중에 끊기지 않는다.

ProgressStreamer.events() 는 0.5s 마다 깨어나 `_is_streaming` 이 거짓이면 끝낸다.
그런데 그 플래그는 workflow_start(계획·검증이 끝난 뒤)에서야 켜진다 — 계획 수립이
0.5s 를 넘기면 스트림이 끝나고, 그 뒤 planning_complete·실행 이벤트는 아무도 읽지
않는다. logos_api 는 결과 없이 재시도 3번 → 폴백 답 (2026-10-04 실측).

이 결함은 계획 LLM 호출이 이벤트 루프를 막는 동안엔 드러나지 않았다 — 루프가 멈춰
있으면 0.5s 시간 제한도 발동하지 못한다. 루프 차단을 고치자 그 아래가 드러났다.
"""
import asyncio

from logosai.orchestration import ProgressEventType, ProgressStreamer


async def _consume(streamer, out, keep_alive=None):
    async for event in streamer.events(keep_alive=keep_alive):
        out.append(event.type)


async def test_stream_stays_open_while_the_producer_is_alive():
    """keep_alive 가 참인 동안은 0.5s 무이벤트에도 끝내지 않는다 (계획 수립 구간)."""
    streamer = ProgressStreamer()
    seen = []

    async def producer():
        await streamer.planning_start("q")
        await asyncio.sleep(1.2)                   # 계획 수립 (루프는 막지 않는다)
        await streamer.workflow_start("q")
        await streamer.workflow_complete(success=True, final_output="done")

    task = asyncio.create_task(producer())
    consumer = asyncio.create_task(_consume(streamer, seen, keep_alive=lambda: not task.done()))
    await task
    await asyncio.wait_for(consumer, timeout=3)

    assert ProgressEventType.PLANNING_START in seen
    assert ProgressEventType.WORKFLOW_COMPLETE in seen, "계획 수립 중 스트림이 끊겼다"


async def test_stream_ends_when_the_producer_dies_without_a_final_event():
    """계획 단계 예외 — WORKFLOW_COMPLETE/ERROR 없이 생산자가 끝나도 스트림은 끝난다."""
    streamer = ProgressStreamer()
    seen = []

    async def producer():
        await streamer.planning_start("q")
        await asyncio.sleep(0.8)
        raise RuntimeError("planner failed")

    task = asyncio.create_task(producer())
    consumer = asyncio.create_task(_consume(streamer, seen, keep_alive=lambda: not task.done()))
    await asyncio.wait_for(consumer, timeout=3)    # 끝나지 않으면 TimeoutError
    assert task.done() and ProgressEventType.PLANNING_START in seen
    task.exception()                               # 회수 — 미처리 예외 경고 방지


async def test_without_keep_alive_the_old_rule_still_applies():
    """대조군 — 인자를 안 주는 기존 호출자는 동작이 그대로다 (비스트리밍 0.5s 후 종료)."""
    streamer = ProgressStreamer()
    seen = []
    consumer = asyncio.create_task(_consume(streamer, seen))

    await streamer.planning_start("q")
    await asyncio.wait_for(consumer, timeout=2)

    assert seen == [ProgressEventType.PLANNING_START]
