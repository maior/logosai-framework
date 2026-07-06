"""자동 관측(auto-observability) — 표준 default 경험 (P0-1, 2026-07-06).

표준 준비도 진단 G3 해소: 평범한 에이전트도 "그냥 만들면" LogosPulse 에
관측 신호가 뜨도록, base process() 를 관측 래퍼로 감싼다.

설계 원칙:
  - fire-and-forget: 관측이 실패해도 에이전트 실행을 절대 막지 않는다.
  - opt-out: env LOGOSAI_AUTO_OBSERVE=false 또는 agent._auto_observe=False.
  - 중첩 정합: TraceSpan 은 ContextVar 로 자동 중첩(ACP root 하위 child /
    standalone 시 root). execution 레코드는 **부모 trace 가 없을 때만** emit
    → ACP 런타임이 이미 execution 을 소유하는 경로에서 이중 emit 방지.
  - 무침습: process() 시그니처·호출부 불변. 서브클래스가 정의한 process 만 1회 래핑.

pulse_client / trace_span 은 지연 import (순환 import·선택 의존성 회피).
"""
from __future__ import annotations

import functools
import os
import time
from typing import Any, Callable, Optional


def auto_observe_enabled(agent: Any) -> bool:
    """이 에이전트에 자동 관측을 적용할지. attr opt-out > env(기본 on)."""
    if getattr(agent, "_auto_observe", None) is False:
        return False
    return os.getenv("LOGOSAI_AUTO_OBSERVE", "true").lower() == "true"


def start_agent_span(agent_id: str, query: Any):
    """에이전트 실행 root/child span 시작. 실패해도 None 반환(비침습)."""
    try:
        from logosai.utils.trace_span import TraceSpan
        return TraceSpan.start(
            name=f"agent.{agent_id}",
            agent_id=str(agent_id),
            input_text=str(query)[:500],
            stage="agent",
        )
    except Exception:
        return None


def emit_agent_execution(agent_id: str, query: Any, success: bool,
                         duration_ms: float, output: str = "",
                         error: Optional[str] = None) -> None:
    """execution 레코드 fire-and-forget 전송. 절대 raise 안 함."""
    try:
        from logosai.utils.pulse_client import send_execution_bg
        send_execution_bg(
            agent_id=str(agent_id),
            agent_name=str(agent_id),
            query=str(query)[:500],
            success=bool(success),
            duration_ms=float(duration_ms),
            error_message=str(error or ""),
        )
    except Exception:
        pass


def _current_trace_id() -> Optional[str]:
    try:
        from logosai.utils.trace_span import get_current_trace_id
        return get_current_trace_id()
    except Exception:
        return None


def observe_process(process_fn: Callable) -> Callable:
    """async process(self, query, context=None) 를 관측 래핑.

    이미 래핑된 함수(_logos_observed)는 그대로 반환(이중 래핑 방지).
    """
    if getattr(process_fn, "_logos_observed", False):
        return process_fn

    @functools.wraps(process_fn)
    async def _wrapped(self, query, context=None):
        if not auto_observe_enabled(self):
            return await process_fn(self, query, context)

        agent_id = getattr(self, "id", None) or type(self).__name__
        # 부모 trace 유무는 span 시작 '전에' 판정 (start 가 ContextVar 를 세팅하므로).
        had_parent = _current_trace_id() is not None
        span = start_agent_span(agent_id, query)
        t0 = time.monotonic()
        success, err = True, None
        try:
            return await process_fn(self, query, context)
        except Exception as e:  # noqa: BLE001 — 성공/실패 관측 후 원래 예외 재전파
            success, err = False, str(e)
            raise
        finally:
            dur_ms = (time.monotonic() - t0) * 1000.0
            try:
                if span is not None:
                    span.end(success=success, output="")
            except Exception:
                pass
            # execution 레코드는 standalone(부모 trace 없음)에서만 — ACP 이중 emit 방지.
            # emit 자체가 오작동해도 process 결과를 절대 훼손하지 않도록 방어.
            if not had_parent:
                try:
                    emit_agent_execution(agent_id, query, success, dur_ms, error=err)
                except Exception:
                    pass

    _wrapped._logos_observed = True  # type: ignore[attr-defined]
    return _wrapped
