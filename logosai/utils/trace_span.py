"""TraceSpan — 경량 트레이싱 단위.

OpenTelemetry 패턴의 간소화 버전. 에이전트 실행의 각 단계를 Span으로 기록.
LogosPulse에 fire-and-forget으로 전송.

Usage:
    span = TraceSpan.start("agent.process", agent_id="scheduler_agent", input="일정 조회")
    try:
        result = await do_work()
        span.end(success=True, output=str(result)[:200])
    except Exception as e:
        span.end(success=False, output=str(e)[:200])

Hierarchy:
    parent_span = TraceSpan.start("desktop_agent.process", ...)
    child_span = TraceSpan.start("call_agent(mail)", parent=parent_span, ...)
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from uuid import uuid4
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# Context variable for trace propagation (thread/async safe)
_current_trace_id: ContextVar[Optional[str]] = ContextVar('_current_trace_id', default=None)
_current_span_id: ContextVar[Optional[str]] = ContextVar('_current_span_id', default=None)


@dataclass
class TraceSpan:
    """트레이싱 단위. 시작/종료 패턴."""

    id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: str = ""
    parent_id: str = ""
    name: str = ""
    agent_id: str = ""
    status: str = "running"  # running, success, error
    input_preview: str = ""
    output_preview: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    _token_trace: Any = field(default=None, repr=False)
    _token_span: Any = field(default=None, repr=False)

    @classmethod
    def start(
        cls,
        name: str,
        agent_id: str = "",
        input_text: str = "",
        trace_id: str = "",
        parent_id: str = "",
        metadata: Optional[Dict] = None,
    ) -> 'TraceSpan':
        """새 Span 시작. context에 자동 등록."""
        # trace_id: 새 트레이스 or 기존 이어받기
        effective_trace_id = trace_id or _current_trace_id.get() or str(uuid4())
        effective_parent_id = parent_id or _current_span_id.get() or ""

        span = cls(
            trace_id=effective_trace_id,
            parent_id=effective_parent_id,
            name=name,
            agent_id=agent_id,
            input_preview=input_text[:200] if input_text else "",
            start_time=time.time(),
            metadata=metadata or {},
        )

        # Context에 현재 span 등록 (자식 span이 자동으로 parent 참조)
        span._token_trace = _current_trace_id.set(span.trace_id)
        span._token_span = _current_span_id.set(span.id)

        logger.debug(f"Span start: {name} (trace={span.trace_id[:8]}, parent={span.parent_id[:8] if span.parent_id else 'root'})")
        return span

    def end(self, success: bool = True, output: str = "", metadata: Optional[Dict] = None):
        """Span 종료 + LogosPulse 전송."""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = "success" if success else "error"
        self.output_preview = output[:200] if output else ""
        if metadata:
            self.metadata.update(metadata)

        # Context 복원 (이전 parent로)
        if self._token_trace:
            _current_trace_id.reset(self._token_trace)
        if self._token_span:
            _current_span_id.reset(self._token_span)

        # LogosPulse에 전송 (fire-and-forget)
        try:
            from logosai.utils.pulse_client import send_span_bg
            send_span_bg(
                span_id=self.id,
                trace_id=self.trace_id,
                parent_id=self.parent_id,
                name=self.name,
                agent_id=self.agent_id,
                status=self.status,
                input_text=self.input_preview,
                output_text=self.output_preview,
                duration_ms=self.duration_ms,
                metadata=self.metadata,
            )
        except Exception:
            pass  # Never block

        logger.debug(f"Span end: {self.name} ({self.duration_ms:.0f}ms, {self.status})")


# Helper: 현재 trace/span ID 가져오기
def get_current_trace_id() -> Optional[str]:
    return _current_trace_id.get()

def get_current_span_id() -> Optional[str]:
    return _current_span_id.get()
