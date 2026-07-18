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
_SPOOLABLE = ("/api/v1/ingest/execution", "/api/v1/ingest/llm-call")
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
    """
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
) -> None:
    """에이전트 실행 기록 전송.

    N1: execution_id 를 명시 지정하면 LogosPulse 가 그 UUID 로 execution 저장.
    그러면 같은 trace_id 를 가진 span 들이 /traces/{execution_id}/tree 에서 조회 가능.
    None 이면 LogosPulse 가 자동 UUID 생성 (legacy 호환).
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
        asyncio.ensure_future(send_llm_call(**kwargs))
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
        asyncio.ensure_future(send_conversation(**kwargs))
    except Exception:
        pass


def send_span_bg(**kwargs) -> None:
    """Background span send."""
    try:
        asyncio.ensure_future(send_span(**kwargs))
    except Exception:
        pass
