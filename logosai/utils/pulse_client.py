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
import logging
import asyncio
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PULSE_URL = os.getenv("LOGOS_PULSE_URL", "http://localhost:8095")
_TIMEOUT = 2  # seconds


async def _post(endpoint: str, data: dict):
    """Fire-and-forget POST. Never blocks, never raises."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{PULSE_URL}{endpoint}",
                json=data,
                timeout=aiohttp.ClientTimeout(total=_TIMEOUT),
            )
    except Exception:
        pass  # Silent — never block agent execution


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
    if execution_id:
        payload["execution_id"] = execution_id
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
