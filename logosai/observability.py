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

try:  # 예산 초과 예외 — guardrails 미가용 시에도 except 절이 유효하도록 fallback
    from logosai.utils.guardrails import HarnessBudgetExceeded as _HarnessBudgetExceeded
except Exception:  # noqa: BLE001
    class _HarnessBudgetExceeded(Exception):
        pass


def auto_observe_enabled(agent: Any) -> bool:
    """이 에이전트에 자동 관측을 적용할지. attr opt-out > env(기본 on)."""
    if getattr(agent, "_auto_observe", None) is False:
        return False
    return os.getenv("LOGOSAI_AUTO_OBSERVE", "true").lower() == "true"


def start_agent_span(agent_id: str, query: Any, harness_meta: Optional[dict] = None):
    """에이전트 실행 root/child span 시작. 실패해도 None 반환(비침습).

    harness_meta 를 span metadata 에 실어 보내는 이유(2026-08-03): 하네스 한도는
    **에이전트 프로세스의 env** 로 정해지는데, 관측 쪽(Pulse)은 그 env 를 볼 수 없다.
    한도를 모르면 "실행시간이 한도에 얼마나 근접했나"를 판정할 수 없고, 더 나쁘게는
    '차단 0건'이 정상인지 계측이 죽은 건지 구분할 수 없다. 이미 보내는 payload 에
    필드 몇 개를 얹는 것뿐이라 새 이벤트를 쏟지 않는다.
    """
    try:
        from logosai.utils.trace_span import TraceSpan
        return TraceSpan.start(
            name=f"agent.{agent_id}",
            agent_id=str(agent_id),
            input_text=str(query)[:500],
            stage="agent",
            metadata=dict(harness_meta or {}),
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


def resolve_harness(agent: Any):
    """이 에이전트에 하네스(실행 타임아웃)를 적용할지 + 타임아웃 초.

    반환: (enabled, timeout_s). attr opt-out > env opt-out > 타임아웃 결정.
      - agent._harness is False → 미적용.
      - env LOGOSAI_HARNESS in {off,false,0,no} → 미적용.
      - agent._harness=숫자(초) 또는 {"timeout_s": n} → 그 값.
      - 아니면 env LOGOSAI_HARNESS_TIMEOUT(기본 120초).
    """
    h = getattr(agent, "_harness", None)
    if h is False:
        return (False, 0.0)
    if os.getenv("LOGOSAI_HARNESS", "on").lower() in ("off", "false", "0", "no"):
        return (False, 0.0)
    timeout: Optional[float] = None
    if isinstance(h, (int, float)) and not isinstance(h, bool) and h > 0:
        timeout = float(h)
    elif isinstance(h, dict) and h.get("timeout_s"):
        timeout = float(h["timeout_s"])
    if timeout is None:
        try:
            timeout = float(os.getenv("LOGOSAI_HARNESS_TIMEOUT", "120"))
        except (TypeError, ValueError):
            timeout = 120.0
    return (True, timeout)


def _timeout_response(agent_id: str, timeout_s: float):
    """하네스 타임아웃 시 graceful AgentResponse.error (매달리지 않음)."""
    from logosai.agent_types import AgentResponse
    return AgentResponse.error(
        f"harness timeout: agent '{agent_id}' exceeded {timeout_s}s budget"
    )


def resolve_harness_budget(agent: Any):
    """실행당 LLM 호출/토큰 상한 결정. (max_calls, max_tokens), 미설정은 None.

    소스: _harness dict(max_llm_calls/max_tokens) > env(LOGOSAI_HARNESS_MAX_CALLS
    /LOGOSAI_HARNESS_MAX_TOKENS) > 기본(25 호출 / 200000 토큰).
    호출부는 harness enabled 일 때만 부른다(opt-out 은 resolve_harness 가 게이트).
    """
    max_calls: Optional[int] = None
    max_tokens: Optional[int] = None
    h = getattr(agent, "_harness", None)
    if isinstance(h, dict):
        if h.get("max_llm_calls") is not None:
            max_calls = int(h["max_llm_calls"])
        if h.get("max_tokens") is not None:
            max_tokens = int(h["max_tokens"])
    if max_calls is None:
        try:
            max_calls = int(os.getenv("LOGOSAI_HARNESS_MAX_CALLS", "25"))
        except (TypeError, ValueError):
            max_calls = 25
    if max_tokens is None:
        try:
            max_tokens = int(os.getenv("LOGOSAI_HARNESS_MAX_TOKENS", "200000"))
        except (TypeError, ValueError):
            max_tokens = 200000
    # 0/음수 → 무제한(None)
    max_calls = max_calls if (max_calls and max_calls > 0) else None
    max_tokens = max_tokens if (max_tokens and max_tokens > 0) else None
    return (max_calls, max_tokens)


def _budget_response(agent_id: str, exc: Exception):
    """하네스 예산(호출/토큰) 초과 시 graceful AgentResponse.error."""
    from logosai.agent_types import AgentResponse
    return AgentResponse.error(
        f"harness budget: agent '{agent_id}' {exc}"
    )


def _budget_kind(message: str) -> str:
    """예산 초과 메시지 → 어느 상한에 걸렸나 ('calls' | 'tokens' | 'unknown').

    guardrails 가 내는 문구('LLM call budget exceeded' / 'token budget exceeded')
    를 그대로 분류한다. 문구가 바뀌면 unknown 으로 떨어질 뿐 발행은 유지된다.
    """
    m = str(message or "").lower()
    if "call budget" in m:
        return "calls"
    if "token budget" in m:
        return "tokens"
    return "unknown"


def emit_harness_block(kind: str, agent_id: str, detail: str,
                       payload: Optional[dict] = None) -> None:
    """하네스가 실행을 잘랐다는 사실을 런타임 이벤트로 발행 (2026-08-03).

    이 발행이 없던 동안 하네스는 '보이지 않는 가드레일'이었다 — 타임아웃으로
    잘린 실행이 span 에 status=error 로만 남아 일반 오류와 구분되지 않았고,
    ACP 경로에서는 execution 레코드조차 나가지 않았다(부모 trace 존재 시 미발행).

    **전이에서만 발행**한다: 정상 실행은 이 함수를 지나지 않는다. 차단이 일어난
    순간에만 호출되므로 정상 트래픽마다 이벤트가 쏟아질 여지가 없다.
    fire-and-forget — 발행이 실패해도 에이전트 실행을 절대 막지 않는다.
    """
    try:
        from logosai.utils.pulse_client import send_event_bg
        body = {"agent_id": str(agent_id), "detail": str(detail)[:300]}
        body.update(payload or {})
        send_event_bg(
            f"harness.{kind}",
            source="logosai.harness",
            agent_id=str(agent_id),
            # 차단은 크래시가 아니라 '의도된 절단'이다. 그러나 사용자 요청은
            # 미완으로 끝났으므로 info 가 아닌 warning.
            severity="warning",
            payload=body,
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
        import asyncio as _aio
        observe = auto_observe_enabled(self)
        h_enabled, h_timeout = resolve_harness(self)
        # 둘 다 off → 원본 그대로 (오버헤드 0).
        if not observe and not h_enabled:
            return await process_fn(self, query, context)

        agent_id = getattr(self, "id", None) or type(self).__name__
        # 부모 trace 유무는 span 시작 '전에' 판정 (start 가 ContextVar 를 세팅하므로).
        had_parent = _current_trace_id() is not None
        # 실행 예산(호출/토큰 상한) — harness 활성 시에만. begin 은 wait_for
        # 태스크 생성 '전' 바깥 컨텍스트에서 (caps 가 복사되어 하위 호출에 보임).
        budget_tok = None
        max_calls = max_tokens = None
        if h_enabled:
            try:
                from logosai.utils.guardrails import begin_execution_budget
                max_calls, max_tokens = resolve_harness_budget(self)
                budget_tok = begin_execution_budget(max_calls, max_tokens)
            except Exception:
                budget_tok = None
        # 유효 한도를 span 에 실어 관측 쪽이 '한도 대비 실행시간'을 판정할 수 있게.
        # 한도 결정(resolve_harness_budget)이 span 시작보다 앞서야 하므로 순서를 옮겼다.
        h_meta = {}
        if h_enabled:
            h_meta = {"harness_timeout_s": h_timeout,
                      "harness_max_calls": max_calls,
                      "harness_max_tokens": max_tokens}
        span = start_agent_span(agent_id, query, h_meta) if observe else None
        t0 = time.monotonic()
        success, err = True, None
        block_kind = None  # 하네스 차단 종류 — span metadata 로도 남긴다
        try:
            if h_enabled and h_timeout and h_timeout > 0:
                try:
                    return await _aio.wait_for(
                        process_fn(self, query, context), timeout=h_timeout)
                except _aio.TimeoutError:
                    # 하네스 타임아웃 — 매달리지 않고 graceful error 반환.
                    success, err = False, f"harness timeout ({h_timeout}s)"
                    block_kind = "timeout"
                    emit_harness_block("timeout", agent_id, err,
                                       {"timeout_s": h_timeout})
                    return _timeout_response(agent_id, h_timeout)
            return await process_fn(self, query, context)
        except _HarnessBudgetExceeded as be:  # 호출/토큰 상한 초과 → graceful
            success, err = False, str(be)
            block_kind = "budget"
            emit_harness_block("budget_exceeded", agent_id, err,
                               {"budget_kind": _budget_kind(err),
                                "max_calls": max_calls, "max_tokens": max_tokens})
            return _budget_response(agent_id, be)
        except Exception as e:  # noqa: BLE001 — 성공/실패 관측 후 원래 예외 재전파
            success, err = False, str(e)
            raise
        finally:
            if budget_tok is not None:
                try:
                    from logosai.utils.guardrails import reset_execution_budget
                    reset_execution_budget(budget_tok)
                except Exception:
                    pass
            dur_ms = (time.monotonic() - t0) * 1000.0
            try:
                if span is not None:
                    # 차단이면 사유를 span 본문·metadata 에 남긴다. 예전엔 output=""
                    # 이라 "status=error 인데 왜인지 알 수 없는 span" 만 남았다.
                    span.end(
                        success=success,
                        output=(err or "") if block_kind else "",
                        metadata={"harness_block": block_kind} if block_kind else None,
                    )
            except Exception:
                pass
            # execution 레코드는 관측 on + standalone(부모 trace 없음)에서만.
            # (하네스만 on이고 관측 off면 emit 안 함) ACP 이중 emit 방지.
            # emit 자체가 오작동해도 process 결과를 절대 훼손하지 않도록 방어.
            if observe and not had_parent:
                try:
                    emit_agent_execution(agent_id, query, success, dur_ms, error=err)
                except Exception:
                    pass

    _wrapped._logos_observed = True  # type: ignore[attr-defined]
    return _wrapped
