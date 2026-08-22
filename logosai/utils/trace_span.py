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
# 현재 실행 중인 에이전트. LLM 비용·메트릭 귀속의 근거다.
# 공유 가변 필드로 들고 있으면 동시 요청끼리 덮어써 미실행 에이전트에 비용이 붙는다.
_current_agent_id: ContextVar[Optional[str]] = ContextVar('_current_agent_id', default=None)
# 현재 '실행'(= 하나의 요청 경계). LLM 비용이 매달릴 execution 행의 id 다.
#
# trace_id 로는 안 된다 (2026-08-22): 오케스트레이터가 다단계 워크플로를 한 trace 로
# 묶으므로 한 trace 에 실행이 여럿이다. trace 를 실행 id 로 쓰면 단계들이 같은 PK 로
# UPSERT 되어 서로를 덮어쓴다(실측 30일: 요청 228 → 행 70).
# 공유 필드가 아니라 ContextVar 인 이유는 `_current_agent_id` 와 같다 —
# 동시 요청이 섞이면 실행하지도 않은 에이전트에 비용이 붙는다(2026-07-19).
_current_execution_id: ContextVar[Optional[str]] = ContextVar('_current_execution_id', default=None)


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
    _token_agent: Any = field(default=None, repr=False)
    _token_exec: Any = field(default=None, repr=False)
    # 이미 닫혔는가 (2026-08-09). root span 종료를 `finally` 로 보장하면
    # 정상 분기는 end() 를 두 번 겪는다 — 이중 전송과 ContextVar 토큰 재사용
    # (`Token has already been used once`)을 여기서 막는다.
    _ended: bool = field(default=False, repr=False)

    @classmethod
    def start(
        cls,
        name: str,
        agent_id: str = "",
        input_text: str = "",
        trace_id: str = "",
        parent_id: str = "",
        metadata: Optional[Dict] = None,
        stage: str = "",
        execution_root: bool = False,
    ) -> 'TraceSpan':
        """새 Span 시작. context에 자동 등록.

        Args:
            execution_root: 이 span 이 하나의 **실행**(요청 경계)이라고 선언한다.
                그러면 이 안에서 일어나는 LLM 비용이 이 span 의 id 를 실행 id 로
                삼는다. 한 trace 에 실행이 여럿일 수 있으므로(다단계 워크플로)
                trace_id 를 실행 id 로 쓰면 안 된다 — `_current_execution_id` 주석 참조.
                선언하지 않으면 소유권을 건드리지 않는다: `llm.*`/`tool_*` 같은
                span 이 실행 소유권을 가로채면 비용이 자기 자신에게 붙는다.
        """
        # trace_id: 새 트레이스 or 기존 이어받기
        effective_trace_id = trace_id or _current_trace_id.get() or str(uuid4())
        effective_parent_id = parent_id or _current_span_id.get() or ""

        _meta = dict(metadata or {})
        if stage:
            # 여정(journey) 단계 규약 — LogosPulse가 스테이지/스윔레인 구분에 사용.
            # ingress|plan|route|agent|a2a_call|harness_react|harness_tool|harness_plan|llm|external|integrate
            _meta["stage"] = stage
        span = cls(
            trace_id=effective_trace_id,
            parent_id=effective_parent_id,
            name=name,
            agent_id=agent_id,
            input_preview=input_text[:200] if input_text else "",
            start_time=time.time(),
            metadata=_meta,
        )

        # Context에 현재 span 등록 (자식 span이 자동으로 parent 참조)
        span._token_trace = _current_trace_id.set(span.trace_id)
        span._token_span = _current_span_id.set(span.id)
        # agent_id 가 있을 때만 소유권 갱신 — llm.*/tool_* 처럼 비어 있는 span 은
        # 조상 에이전트의 소유권을 지우면 안 된다.
        if agent_id:
            span._token_agent = _current_agent_id.set(agent_id)
        if execution_root:
            span._token_exec = _current_execution_id.set(span.id)

        logger.debug(f"Span start: {name} (trace={span.trace_id[:8]}, parent={span.parent_id[:8] if span.parent_id else 'root'})")
        return span

    def end(self, success: bool = True, output: str = "", metadata: Optional[Dict] = None):
        """Span 종료 + LogosPulse 전송. 두 번째 호출부터는 무동작(멱등)."""
        if self._ended:
            return
        self._ended = True
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
        if self._token_agent:
            _current_agent_id.reset(self._token_agent)
        if self._token_exec:
            _current_execution_id.reset(self._token_exec)

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
                start_time=self.start_time,  # 실제 시작시각 — 여정 타임라인 정합
                end_time=self.end_time,
            )
        except Exception:
            pass  # Never block

        logger.debug(f"Span end: {self.name} ({self.duration_ms:.0f}ms, {self.status})")


    @classmethod
    def record(
        cls,
        name: str,
        started_at: float,
        agent_id: str = "",
        input_text: str = "",
        output: str = "",
        success: bool = True,
        stage: str = "",
        metadata: Optional[Dict] = None,
    ) -> None:
        """이미 끝난 작업을 사후 기록 (start~end를 한 번에).

        루프 내부처럼 시작 시점에 span 객체를 들고 있기 번거로운 곳에서 사용.
        started_at은 time.time() 기준. ContextVar를 건드리지 않아 부모 오염이 없다.
        """
        _meta = dict(metadata or {})
        if stage:
            _meta["stage"] = stage
        span = cls(
            trace_id=_current_trace_id.get() or str(uuid4()),
            parent_id=_current_span_id.get() or "",
            name=name,
            agent_id=agent_id,
            input_preview=input_text[:200] if input_text else "",
            start_time=started_at,
            metadata=_meta,
        )
        # ContextVar 미등록 상태이므로 end()의 reset은 no-op(토큰 None)
        span.end(success=success, output=output)


# Helper: 현재 trace/span ID 가져오기
def get_current_trace_id() -> Optional[str]:
    return _current_trace_id.get()

def get_current_execution_id() -> Optional[str]:
    """현재 실행(요청 경계)의 id. 선언된 실행 루트가 없으면 None.

    None 을 trace_id 로 대신 채우지 않는다 — 폴백이 옳은지는 호출자가 안다.
    (배치는 1 배치 = 1 trace = 1 실행이라 trace_id 폴백이 맞고,
     다단계 워크플로는 그렇지 않다.)
    """
    return _current_execution_id.get()

def get_current_span_id() -> Optional[str]:
    return _current_span_id.get()

def get_current_agent_id() -> Optional[str]:
    """현재 실행 중인 에이전트 (LLM 비용 귀속용). 모르면 None — 추측하지 않는다."""
    return _current_agent_id.get()


# ──────────────────────────────────────────────────────────────────
# W3C Trace Context propagation (2026-05-09, Phase 4b)
# ──────────────────────────────────────────────────────────────────
# logos_api 가 ACP 호출 시 보내는 `traceparent` HTTP header 를 ACP 측이
# 받아서 같은 trace_id 로 span 기록 → cross-service trace tree 통합.
# ──────────────────────────────────────────────────────────────────


def parse_traceparent(header: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """W3C traceparent header → (trace_id_uuid, parent_span_id).

    Format: 00-{32hex_trace}-{16hex_span}-{flags}

    Returns:
        (trace_id, span_id) — UUID 형식의 trace_id 와 16hex span_id
        잘못된 format 이면 (None, None)
    """
    if not header or not isinstance(header, str):
        return (None, None)
    parts = header.strip().split("-")
    if len(parts) != 4:
        return (None, None)
    version, tid_hex, sid_hex, _flags = parts
    if version != "00" or len(tid_hex) != 32 or len(sid_hex) != 16:
        return (None, None)
    # validate hex
    try:
        int(tid_hex, 16)
        int(sid_hex, 16)
    except ValueError:
        return (None, None)
    # 32 hex → UUID 형식 (8-4-4-4-12) 으로 정규화
    trace_id = (
        f"{tid_hex[0:8]}-{tid_hex[8:12]}-{tid_hex[12:16]}-"
        f"{tid_hex[16:20]}-{tid_hex[20:32]}"
    )
    return (trace_id, sid_hex)


class TraceContext:
    """ContextVar 에 외부 trace_id 를 set/reset 하는 context manager.

    Usage:
        trace_id, parent_id = parse_traceparent(request.headers.get("traceparent"))
        with TraceContext(trace_id, parent_id):
            # 이 블록 안에서 시작하는 모든 TraceSpan 이 외부 trace 이어받음
            span = TraceSpan.start("agent.process", agent_id="x")
            ...
            span.end()

    None 입력은 no-op (기존 동작 유지).
    """

    def __init__(self, trace_id: Optional[str] = None, parent_id: Optional[str] = None):
        self._trace_id = trace_id
        self._parent_id = parent_id
        self._token_trace = None
        self._token_span = None

    def __enter__(self) -> 'TraceContext':
        if self._trace_id:
            self._token_trace = _current_trace_id.set(self._trace_id)
        if self._parent_id:
            self._token_span = _current_span_id.set(self._parent_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._token_span is not None:
            _current_span_id.reset(self._token_span)
        if self._token_trace is not None:
            _current_trace_id.reset(self._token_trace)
