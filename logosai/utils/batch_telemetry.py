"""배치/단독 스크립트를 위한 관측 호스트 (2026-08-22).

무엇을 메우는가
──────────────
`LLMClient` 는 **스스로 기록하지 않는다**. 호스트가 `_metrics_callback` 을
꽂아야 비용이 Pulse 에 남는다. 그런데 그 일을 하는 곳은 두 군데뿐이다:

    acp_server/acp_modules/server.py            (ACP 서버)
    logos_api/app/services/orchestrator_service.py (FastAPI)

그래서 **호스트가 없는 스크립트**의 LLM 호출은 전부 사라진다. 실측:
`review_audit.py` 가 `gemini-2.5-flash` 로 544회 호출했는데
`/api/v1/costs` 의 by_model 에 그 모델이 아예 없었다. 스풀
(`~/.logosai/pulse_spool.jsonl`)조차 없었다 — 보내려다 실패한 게 아니라
**아무도 보내지 않았다**.

왜 콜백만으로는 부족한가 (핵심)
──────────────────────────────
콜백을 꽂아도 그대로면 여전히 샌다. 전송은 fire-and-forget 이고
(`pulse_client._fire_and_forget` → `loop.create_task`), `asyncio.run(main())` 은
반환 직전 `_cancel_all_tasks` 로 남은 태스크를 **전부 취소**한다.

실험(2026-08-22, 로컬 더미 수신 서버):

    main() 종료 직전 대기 태스크 3
    asyncio.run() 반환 후 수신 건수: 0
    stats: {'sent': 0, 'failed': 0}          ← 실패로조차 안 남는다
    spool 존재: False                        ← 재전송 기회도 없다

서버는 살아 있었고 페이로드도 멀쩡했다. 죽인 것은 **프로세스 종료**다.
그래서 이 모듈의 알맹이는 콜백 배선이 아니라 종료 전 배수(`drain_pulse`)다.

쓰는 법
──────
    from logosai.utils.batch_telemetry import batch_run

    async def main():
        async with batch_run("review_audit", query="정밀도 감사") as run:
            ...                       # 이 안의 LLM 호출이 전부 기록된다
            run.note(sampled=120)     # 실행 레코드 metadata 보강

    asyncio.run(main())

지키는 규약 (`CLAUDE.md` — Pulse 수집 규약)
───────────────────────────────────────
· 귀속은 `TraceSpan` 의 ContextVar. 공유 가변 필드를 쓰지 않는다.
· trace 밖 호출의 `agent_id` 는 **비운다** — 그럴듯한 이름을 지어내지 않는다.
· 배치의 정체는 *모름이 아니라 아는 것*이므로 `batch.<job>` 으로 밝혀 적는다.
  등록된 ACP 에이전트인 척하지 않도록 접두사를 붙인다.
· 200 OK ≠ 저장됨이므로 이 모듈이 "성공"을 단언하지 않는다. 대신 배수 뒤
  전송/실패 건수를 **사람이 보게** 찍는다.
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from logosai.utils import pulse_client
from logosai.utils.llm_client import LLMClient
from logosai.utils.trace_span import TraceSpan

#: 배치 실행의 agent_id 접두사. 등록 에이전트와 섞이면 Agents 탭이 거짓말을 한다.
AGENT_PREFIX = "batch."


# ── 페이로드 성형 (순수) ────────────────────────────────────────────

def llm_metrics_payload(data: Any) -> Dict[str, Any]:
    """`LLMClient` 메트릭 → `send_llm_call` 인자. 순수 함수.

    귀속은 ContextVar(`get_current_agent_id`) — 공유 필드는 동시 요청이 섞인다.
    trace 밖 호출은 agent_id 를 **비워 둔다**: 그럴듯한 에이전트에 붙이면
    없는 사실을 지어내는 것이다.

    (logos_api 의 `build_llm_metrics_payload` 가 이 함수를 위임한다. 정의가
    둘이면 한쪽만 고쳐지고, 그러면 두 호스트의 비용 집계가 조용히 갈린다.)
    """
    d = data if isinstance(data, dict) else {}
    exec_id, agent_id = None, ""
    try:
        from logosai.utils.trace_span import (
            get_current_trace_id, get_current_agent_id, get_current_execution_id)
        # 실행 id 우선 (2026-08-22). trace_id 는 한 trace 에 실행이 하나뿐일 때만
        # 맞는 값이다 — 다단계 워크플로에서 trace_id 를 쓰면 비용이 진짜 실행 행이
        # 아니라 `{"placeholder": true}` 유령 행에 쌓인다(실측: 진짜 행 2개
        # token_count=0, 유령 행 5,529). 배치처럼 실행 루트를 선언하지 않는
        # 호출자는 trace_id 폴백이 옳다 — 거기서는 1 배치 = 1 trace = 1 실행이다.
        exec_id = get_current_execution_id() or get_current_trace_id() or None
        agent_id = get_current_agent_id() or ""
    except Exception:
        pass

    def _int(key: str) -> int:
        try:
            return int(d.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    try:
        duration = float(d.get("duration_ms") or 0)
    except (TypeError, ValueError):
        duration = 0.0

    return {
        "execution_id": exec_id,
        "agent_id": agent_id,
        "model": str(d.get("model") or ""),
        "provider": str(d.get("provider") or ""),
        "input_tokens": _int("input_tokens"),
        "output_tokens": _int("output_tokens"),
        "duration_ms": duration,
        "success": bool(d.get("success", True)),
        "prompt_preview": str(d.get("prompt_preview") or ""),
    }


# ── 배수 ───────────────────────────────────────────────────────────

async def drain_pulse(timeout: float = 15.0) -> int:
    """대기 중인 fire-and-forget 전송이 끝날 때까지 기다린다.

    반환값은 **실제로 끝난 태스크 수**다. 취소·미완은 세지 않는다 —
    보내지도 않은 것을 보냈다고 세면 이 모듈이 고치려는 그 거짓말이 된다.

    timeout 이 있는 이유: Pulse 가 죽어 있으면 각 전송이 2초(`_TIMEOUT`)를
    쓰고 실패한다. 그 실패는 스풀에 남아 다음 기회에 배달되므로, 여기서
    무한정 매달려 배치 작업을 붙잡을 이유가 없다.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return 0

    deadline = time.monotonic() + timeout
    watched: set = set()
    while True:
        # 다른(이미 닫힌) 루프의 태스크를 기다리면 ValueError 가 난다.
        watched |= {t for t in list(pulse_client._BG_TASKS)
                    if t.get_loop() is loop}
        pending = {t for t in watched if not t.done()}
        remaining = deadline - time.monotonic()
        if not pending or remaining <= 0:
            break
        await asyncio.wait(pending, timeout=remaining)

    return sum(1 for t in watched if t.done() and not t.cancelled())


# ── 실행 핸들 ───────────────────────────────────────────────────────

class BatchRun:
    """배치 한 번의 관측 상태. `batch_run()` 이 만들어 준다."""

    def __init__(self, job: str, query: str = "",
                 metadata: Optional[Dict[str, Any]] = None):
        self.job = job
        self.agent_id = f"{AGENT_PREFIX}{job}"
        self.query = query
        self.metadata: Dict[str, Any] = dict(metadata or {})
        self.trace_id: str = ""
        self.llm_calls = 0
        self.llm_failures = 0
        self.input_tokens = 0
        self.output_tokens = 0

    @property
    def token_count(self) -> int:
        return self.input_tokens + self.output_tokens

    def note(self, **kv: Any) -> "BatchRun":
        """실행 레코드 metadata 에 실측치를 얹는다 (파일 수, 표본 수 등)."""
        self.metadata.update(kv)
        return self

    def _on_llm(self, data: Any) -> None:
        """`LLMClient._metrics_callback` — 집계하고 전송한다.

        절대 예외를 내지 않는다. 관측이 LLM 응답을 막으면 안 된다.
        """
        try:
            payload = llm_metrics_payload(data)
            self.llm_calls += 1
            self.input_tokens += payload["input_tokens"]
            self.output_tokens += payload["output_tokens"]
            if not payload["success"]:
                self.llm_failures += 1
            pulse_client.send_llm_call_bg(**payload)
        except Exception:
            pass


@asynccontextmanager
async def batch_run(
    job: str,
    query: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    drain_timeout: float = 15.0,
    quiet: bool = False,
):
    """배치 작업을 Pulse 에 하나의 실행으로 남긴다.

    Args:
        job: 작업 이름. `batch.<job>` 으로 기록된다.
        query: 무엇을 하는 실행인지 한 줄. 대시보드에 그대로 보인다.
        metadata: 실행 레코드에 붙일 부가 정보 (`run.note()` 로도 추가 가능).
        drain_timeout: 종료 전 전송 배수 상한(초).
        quiet: 마지막 요약 한 줄을 찍지 않는다.

    블록 안의 예외는 실패로 기록한 뒤 **그대로 다시 던진다** — 삼키면
    스크립트가 자기 실패를 못 본다.
    """
    run = BatchRun(job, query=query, metadata=metadata)

    # 남의 호스트(ACP·logos_api)가 이미 꽂아 둔 콜백은 덮지 않는다.
    #
    # `run._on_llm` 을 두 번 쓰지 않고 한 번만 만들어 쥔다: 바운드 메서드는
    # **접근할 때마다 새 객체**라 `installed is run._on_llm` 이 항상 False 였다.
    # 그 탓에 첫 배치의 콜백이 영영 안 걷히고, 이후 배치는 "이미 호스트가
    # 있다"고 판단해 자기 호출을 한 건도 못 셌다 (테스트에서 실측: 토큰 0).
    own_cb = run._on_llm
    prev_cb = LLMClient._metrics_callback
    installed = prev_cb is None
    if installed:
        LLMClient._metrics_callback = own_cb

    # 루트 span. agent_id 를 세워야 그 안의 LLM 비용이 이 실행에 귀속된다.
    span = TraceSpan.start(
        name=f"batch.{job}",
        agent_id=run.agent_id,
        input_text=query,
        stage="agent",
        metadata={"job": job, "host": "batch_telemetry"},
    )
    run.trace_id = span.trace_id

    stats_before = pulse_client.get_pulse_stats()
    started = time.monotonic()
    success, error_message = True, ""
    try:
        yield run
    except BaseException as e:  # noqa: BLE001 — 기록만 하고 그대로 전파
        success = False
        error_message = f"{type(e).__name__}: {e}"
        raise
    finally:
        duration_ms = (time.monotonic() - started) * 1000

        span.end(success=success,
                 output=f"llm_calls={run.llm_calls} tokens={run.token_count}")

        if installed and LLMClient._metrics_callback is own_cb:
            LLMClient._metrics_callback = prev_cb

        meta = dict(run.metadata)
        meta.update({
            "job": job,
            "host": "batch_telemetry",
            "llm_calls": run.llm_calls,
            "llm_failures": run.llm_failures,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
        })
        try:
            # execution_id = trace_id 여야 같은 trace 의 span 들이
            # /traces/{id}/tree 에서 이 실행 아래로 모인다.
            #
            # token_count·cost_usd 를 **보내지 않는다**. Pulse 는 llm-call 을
            # 받을 때마다 소속 execution 에 `token_count = token_count + :tokens`
            # 로 이미 굴려 넣는다(`metrics_collector.record_llm_call`). 여기서
            # 실측치를 또 보내면 이중 계상된다 — 실측(2026-08-22 라이브): 진짜
            # 8,222 토큰이 by_agent 에 **16,444** 로 찍혔다. ACP 가 최종
            # execution 에 0 을 보내는 이유가 이것이다.
            # 관측한 수치는 metadata 에만 남긴다(합산 대상이 아니다).
            await pulse_client.send_execution(
                agent_id=run.agent_id,
                query=query or job,
                success=success,
                duration_ms=duration_ms,
                error_message=error_message,
                agent_name=job,
                metadata=meta,
                execution_id=run.trace_id,
            )
        except Exception:
            pass  # 관측이 배치의 종료 코드를 바꾸지 않는다

        drained = await drain_pulse(drain_timeout)

        if not quiet:
            after = pulse_client.get_pulse_stats()
            sent = after.get("sent", 0) - stats_before.get("sent", 0)
            failed = after.get("failed", 0) - stats_before.get("failed", 0)
            # 실패를 숨기지 않는다. 200 OK 도 '저장됨'을 뜻하지 않으므로
            # 여기서 단언하지 않고 관측 가능한 사실만 적는다.
            line = (f"[pulse] {run.agent_id} · LLM {run.llm_calls}회"
                    f"(실패 {run.llm_failures}) · 토큰 {run.token_count}"
                    f" · 전송 {sent} 실패 {failed} · 배수 {drained}"
                    f" · trace={run.trace_id[:8]}")
            if failed:
                line += "  ⚠️ 실패분은 스풀에 남아 다음 기회에 재전송된다"
            print(line, flush=True)
