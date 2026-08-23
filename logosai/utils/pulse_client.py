"""LogosPulse Client — 경량 HTTP 메트릭 전송.

ACP Server와 logos_api에서 사용. Fire-and-forget 방식.
LogosPulse 서버가 다운이어도 에이전트 동작에 영향 없음.

Usage:
    from logosai.utils.pulse_client import send_execution, send_llm_call

    # 에이전트 실행 기록
    await send_execution(agent_id="scheduler_agent", query="일정 조회", duration_ms=3200)

    # LLM 호출 기록
    await send_llm_call(model="gemini-2.5-flash-lite", input_tokens=500, output_tokens=200)
"""

import os
import sys
import json
import logging
import asyncio
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PULSE_URL = os.getenv("LOGOS_PULSE_URL", "http://localhost:8095")
_TIMEOUT = 2  # seconds

# 전송 결과 누적 (2026-07-18)
# 배경: Pulse 가 07-15~18 죽어 있는 동안 예외가 전부 삼켜져 메트릭이 흔적 없이
#       유실됐다. fire-and-forget 계약은 유지하되, 실패는 반드시 보이게 한다.
_stats: Dict[str, Any] = {"sent": 0, "failed": 0, "last_error": ""}
_last_warn_ts = 0.0
_WARN_INTERVAL = 60  # 초 — 서버가 오래 죽어 있어도 로그가 폭주하지 않도록


# 실패분 스풀 (2026-07-19)
# Pulse 다운 중 유실을 막는다. 재전송이 안전하려면 멱등해야 하므로
# 클라이언트 발급 ID 를 쓰는 endpoint 만 대상으로 한다 (span 은 제외).
_SPOOL_PATH = os.getenv(
    "LOGOS_PULSE_SPOOL", os.path.expanduser("~/.logosai/pulse_spool.jsonl")
)
_SPOOL_MAX = 5000        # 장기 다운 시 디스크 고갈 방지 — 초과분은 오래된 것부터 폐기
_REPLAY_BATCH = 50       # 성공 1회당 재전송 상한 — 버스트로 실행을 지연시키지 않는다
_SPOOLABLE = (
    "/api/v1/ingest/execution",
    "/api/v1/ingest/llm-call",
    "/api/v1/ingest/event",   # 클라이언트 발급 event_id 로 멱등
    # 2026-07-31: span 편입. 서버가 ON CONFLICT DO NOTHING 으로 멱등해졌다.
    # 이전엔 재전송이 UniqueViolation 을 내서 제외돼 있었고, 그 탓에 전송 실패한
    # span 이 **그냥 버려졌다** — 생성 중 이벤트 루프가 막혀 2초 타임아웃이
    # 소진되면 그 생성의 관측이 통째로 사라졌다 (실측: FORGE 생성마다 유실).
    "/api/v1/ingest/span",
)
_replaying = False


def get_pulse_stats() -> Dict[str, Any]:
    """전송 누적 통계 (점검용)."""
    return dict(_stats)


def _spool_append(endpoint: str, data: dict) -> None:
    """실패한 페이로드를 디스크에 쌓는다. 실패해도 조용히 넘어간다."""
    if endpoint not in _SPOOLABLE:
        return  # 멱등하지 않은 endpoint 는 재전송 시 중복되므로 버린다
    try:
        os.makedirs(os.path.dirname(_SPOOL_PATH), exist_ok=True)
        with open(_SPOOL_PATH, "a") as f:
            f.write(json.dumps({"endpoint": endpoint, "data": data}) + "\n")

        # 상한 초과 시 오래된 것부터 폐기
        with open(_SPOOL_PATH) as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        if len(lines) > _SPOOL_MAX:
            with open(_SPOOL_PATH, "w") as f:
                f.write("\n".join(lines[-_SPOOL_MAX:]) + "\n")
    except Exception:
        pass


async def _replay_spool(session) -> None:
    """서버가 살아났을 때 쌓아둔 것을 재전송한다."""
    global _replaying
    if _replaying or not os.path.exists(_SPOOL_PATH):
        return
    _replaying = True
    try:
        import aiohttp
        with open(_SPOOL_PATH) as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        if not lines:
            return

        batch, rest = lines[:_REPLAY_BATCH], lines[_REPLAY_BATCH:]
        failed = []
        for line in batch:
            try:
                rec = json.loads(line)
                async with session.post(
                    f"{PULSE_URL}{rec['endpoint']}",
                    json=rec["data"],
                    timeout=aiohttp.ClientTimeout(total=_TIMEOUT),
                ) as resp:
                    if resp.status >= 400:
                        failed.append(line)
            except Exception:
                failed.append(line)  # 아직 못 보냈으면 보존

        remaining = failed + rest
        if remaining:
            with open(_SPOOL_PATH, "w") as f:
                f.write("\n".join(remaining) + "\n")
        else:
            os.remove(_SPOOL_PATH)

        if len(batch) - len(failed) > 0:
            logger.info("LogosPulse 스풀 재전송 %d건", len(batch) - len(failed))
    except Exception:
        pass
    finally:
        _replaying = False


def _truthy(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in ("1", "true", "yes", "on")


def _under_test() -> bool:
    """테스트 실행 중인가. pytest 가 매 테스트마다 세우는 변수를 본다.

    수집(collection) 단계에는 아직 없으므로 실행 모듈 존재도 함께 본다.
    """
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def _sending_blocked() -> bool:
    """전송을 막아야 하는가.

    명시적 차단이 최우선 — opt-in 이 그것을 뒤집으면 안 된다.
    """
    if _truthy("LOGOS_PULSE_DISABLED"):
        return True
    if _under_test() and not _truthy("LOGOSAI_PULSE_ALLOW_IN_TESTS"):
        return True
    return False


def _record_failure(reason: str) -> None:
    """실패를 집계하고 주기적으로만 경고한다."""
    global _last_warn_ts
    _stats["failed"] += 1
    _stats["last_error"] = reason[:200]

    now = time.monotonic()
    if now - _last_warn_ts >= _WARN_INTERVAL:
        _last_warn_ts = now
        logger.warning(
            "LogosPulse 전송 실패 (누적 %d건): %s", _stats["failed"], reason[:200]
        )


async def _post(endpoint: str, data: dict):
    """Fire-and-forget POST. Never blocks, never raises.

    상태 코드를 확인한다 — 확인하지 않던 탓에 llm_calls 의 422 거부가
    3주간 성공으로 집계됐다.

    ``LOGOS_PULSE_DISABLED`` 가 참이면 아무것도 보내지 않는다 (2026-08-02).
    테스트가 실제 관측 시스템에 데이터를 남기면 진짜 신호와 구분할 수 없다 —
    인가 이벤트를 배선한 뒤 실제로 테스트 발 이벤트가 대시보드에 올라왔다.
    스풀에도 넣지 않는다(나중에 재전송되면 같은 오염이 된다).

    2026-08-09: **테스트 실행 중이면 기본으로 막는다.** 위 스위치는 사람이
    켜야 했고, 그래서 안 켜졌다 — `orchestrator.stream_with_orchestrator`
    span 25건이 실제 Pulse DB 에 들어가 "ingress 유실" 로 오독됐다.
    (스풀이 7분 뒤 배달하는 바람에 즉시 측정으로는 잡히지도 않았다.)
    잊을 수 있는 방어는 방어가 아니므로 감지를 기본값으로 두고,
    Pulse 전송 자체를 검증해야 하는 테스트만 명시적으로 푼다.
    """
    if _sending_blocked():
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{PULSE_URL}{endpoint}",
                json=data,
                timeout=aiohttp.ClientTimeout(total=_TIMEOUT),
            ) as resp:
                if resp.status >= 400:
                    _record_failure(f"HTTP {resp.status} {endpoint}")
                    _spool_append(endpoint, data)
                else:
                    _stats["sent"] += 1
                    # 서버가 살아있음이 확인된 시점 — 밀린 것을 조금씩 흘려보낸다
                    await _replay_spool(session)
    except Exception as e:
        # 절대 전파하지 않는다 (에이전트 실행 차단 금지) — 대신 흔적을 남긴다
        _record_failure(f"{type(e).__name__}: {e} ({endpoint})")
        _spool_append(endpoint, data)


async def send_execution(
    agent_id: str,
    query: str = "",
    success: bool = True,
    duration_ms: float = 0,
    error_message: str = "",
    agent_name: str = "",
    correlation_id: str = "",
    user_email: str = "",
    session_id: str = "",
    token_count: int = 0,
    cost_usd: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
    execution_id: Optional[str] = None,  # N1 (2026-05-09): TraceSpan trace_id 로 link
    agent_revision: str = "",  # G1 (2026-08-22): 12자 hex, 빈 값 = 모름
) -> None:
    """에이전트 실행 기록 전송.

    N1: execution_id 를 명시 지정하면 LogosPulse 가 그 UUID 로 execution 저장.
    그러면 같은 trace_id 를 가진 span 들이 /traces/{execution_id}/tree 에서 조회 가능.
    None 이면 LogosPulse 가 자동 UUID 생성 (legacy 호환).

    G1: agent_revision 은 이 실행이 *어느 코드*였는지를 12자로 스탬프한다
    (`logosai.review.finding.revision_of`). 없으면 개선 전후 비교가 상관일 뿐
    귀속이 아니다. **빈 문자열은 '모름'이고 수신 측에서 NULL 로 저장된다** —
    키를 빼지 말 것. 모름 자체가 기록돼야 계측 공백을 셀 수 있다.
    """
    payload = {
        "agent_id": agent_id,
        "query": query[:200],
        "success": success,
        "duration_ms": duration_ms,
        "error_message": error_message[:500],
        "agent_name": agent_name,
        "correlation_id": correlation_id,
        "user_email": user_email,
        "session_id": session_id,
        "token_count": token_count,
        "cost_usd": cost_usd,
        "metadata": metadata,
        "agent_revision": agent_revision,
    }
    # ID 를 서버에 맡기면 스풀 재전송 때마다 새 행이 생긴다.
    # 클라이언트가 발급하면 record_execution 의 UPSERT 가 멱등하게 흡수한다.
    payload["execution_id"] = execution_id or str(uuid.uuid4())
    await _post("/api/v1/ingest/execution", payload)


async def send_llm_call(
    execution_id: str = "",
    agent_id: str = "",
    model: str = "",
    provider: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: float = 0,
    success: bool = True,
    error_message: str = "",
    prompt_preview: str = "",
) -> None:
    """LLM 호출 기록 전송."""
    await _post("/api/v1/ingest/llm-call", {
        # 클라이언트가 ID 를 발급해야 스풀 재전송이 중복을 만들지 않는다
        "call_id": str(uuid.uuid4()),
        "execution_id": execution_id,
        "agent_id": agent_id,
        "model": model,
        "provider": provider,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "duration_ms": duration_ms,
        "success": success,
        "error_message": error_message[:500],
        "prompt_preview": prompt_preview[:200],
    })


async def send_event(
    event_type: str,
    source: str = "",
    agent_id: str = "",
    severity: str = "info",
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """런타임 이벤트 전송 (회로 차단 / 롤백 / 인터랙션 등).

    지금까지 인메모리로만 존재해 프로세스 재시작과 함께 사라지던 신호들이다.
    """
    await _post("/api/v1/ingest/event", {
        # 클라이언트 발급 ID — 스풀 재전송이 중복을 만들지 않게
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "source": source,
        "agent_id": agent_id,
        "severity": severity,
        "payload": payload or {},
    })


_BG_TASKS: set = set()


def _fire_and_forget(coro, endpoint: str = "", data: dict = None) -> None:
    """배경 전송 공통 진입점 (2026-07-31).

    두 가지를 보장한다:
      1. **태스크 참조 유지** — 참조 없는 Task 는 GC 대상이라 바쁜 루프에서
         실행 전에 사라질 수 있다.
      2. **루프 부재 시 유실 금지** — 실행 중인 루프가 없으면 `ensure_future` 가
         RuntimeError 를 내고 기존 `except: pass` 가 흔적까지 지웠다.
         스풀 가능한 엔드포인트면 적재하고, 아니면 최소한 실패로 기록한다.
         (실측: FORGE 생성의 span 이 실패 로그조차 없이 통째로 사라졌다)
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        if endpoint and data is not None:
            _spool_append(endpoint, data)
        _record_failure(f"no running loop ({endpoint or 'unknown'})")
        return
    try:
        task = loop.create_task(coro)
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)
    except Exception as e:
        coro.close()
        if endpoint and data is not None:
            _spool_append(endpoint, data)
        _record_failure(f"{type(e).__name__}: {e} ({endpoint or 'unknown'})")


def send_event_bg(event_type: str, **kwargs) -> None:
    """Background send. 동기 코드(CircuitBreaker 등)에서 사용."""
    try:
        asyncio.ensure_future(send_event(event_type=event_type, **kwargs))
    except Exception:
        pass


def send_execution_bg(
    agent_id: str, **kwargs
) -> None:
    """Background send (asyncio.ensure_future). 동기 코드에서 사용."""
    try:
        asyncio.ensure_future(send_execution(agent_id=agent_id, **kwargs))
    except Exception:
        pass


def send_llm_call_bg(**kwargs) -> None:
    """Background send (asyncio.ensure_future). LLMClient callback에서 사용."""
    try:
        _fire_and_forget(send_llm_call(**kwargs), "/api/v1/ingest/llm-call", dict(kwargs))
    except Exception:
        pass


async def send_span(
    span_id: str = "",
    trace_id: str = "",
    parent_id: str = "",
    name: str = "",
    agent_id: str = "",
    status: str = "success",
    input_text: str = "",
    output_text: str = "",
    duration_ms: float = 0,
    metadata: Optional[Dict[str, Any]] = None,
    start_time: float = 0,
    end_time: float = 0,
) -> None:
    """트레이스 Span 전송."""
    await _post("/api/v1/ingest/span", {
        "span_id": span_id,
        "trace_id": trace_id,
        "parent_id": parent_id,
        "name": name,
        "agent_id": agent_id,
        "status": status,
        "start_time": start_time or None,  # epoch sec — 여정 타임라인용 실측 시각
        "end_time": end_time or None,
        "input_text": input_text[:200],
        "output_text": output_text[:200],
        "duration_ms": duration_ms,
        "metadata": metadata or {},
    })


async def send_conversation(
    trace_id: str = "", caller: str = "", callee: str = "", channel: str = "call_agent",
    query: str = "", answer: str = "", status: str = "success",
    duration_ms: float = 0, started_at: float = 0, session_id: str = "",
) -> None:
    """에이전트 간 대화 로그 — 스팬과 분리된 1급 기록 (전문 보존, 취소돼도 남김)."""
    await _post("/api/v1/ingest/conversation", {
        "trace_id": trace_id, "caller": caller, "callee": callee, "channel": channel,
        "query": query[:4000], "answer": answer[:4000], "status": status,
        "duration_ms": duration_ms, "started_at": started_at or None, "session_id": session_id,
    })


def send_conversation_bg(**kwargs) -> None:
    try:
        _fire_and_forget(send_conversation(**kwargs), "/api/v1/ingest/conversation", dict(kwargs))
    except Exception:
        pass


def send_span_bg(**kwargs) -> None:
    """Background span send."""
    try:
        _fire_and_forget(send_span(**kwargs), "/api/v1/ingest/span", dict(kwargs))
    except Exception:
        pass
