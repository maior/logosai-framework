"""LLM 비용 귀속 컨텍스트 — 실행 중인 에이전트를 async-safe 하게 식별한다.

배경 (2026-08-07 감사 실측):
  ACP 는 `server._current_agent_id` 라는 **공유 가변 필드**로 현재 에이전트를
  들고 있었고, 그 대입은 에이전트 실행이 **끝난 뒤** 한 번뿐이었다.
  결과: LLM 비용이 직전 요청의 에이전트에게 귀속됐다.
  실측 — 날씨/검색/요약이 돈 쿼리에서 llm_calls 가 calculator_agent(미실행)에
  2건 기록됨.

해법: TraceSpan 이 이미 agent_id 를 들고 있으므로 ContextVar 로 전파한다.
      LLM 호출은 항상 어떤 에이전트 span 안에서 일어나므로 소유자가 자명하다.

Usage: python tests/test_agent_context_attribution.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logosai.utils.trace_span import TraceSpan, get_current_agent_id


def test_agent_id_visible_inside_span():
    span = TraceSpan.start("weather_agent.process", agent_id="weather_agent")
    try:
        assert get_current_agent_id() == "weather_agent"
    finally:
        span.end()
    assert get_current_agent_id() is None, "span 종료 후 복원돼야 한다"


def test_nested_span_inner_agent_wins_then_restores():
    outer = TraceSpan.start("desktop_agent.process", agent_id="desktop_agent")
    inner = TraceSpan.start("call_agent(mail_agent)", agent_id="mail_agent")
    assert get_current_agent_id() == "mail_agent"
    inner.end()
    assert get_current_agent_id() == "desktop_agent", "호출 복귀 시 원래 소유자로"
    outer.end()


def test_span_without_agent_id_does_not_clobber_owner():
    """llm.* span 은 agent_id 가 비어 있다 — 조상의 소유권을 지워선 안 된다."""
    outer = TraceSpan.start("weather_agent.process", agent_id="weather_agent")
    llm = TraceSpan.start("llm.gemini-2.5-flash-lite")
    assert get_current_agent_id() == "weather_agent"
    llm.end()
    outer.end()


def test_record_does_not_pollute_context():
    """record() 는 사후 기록 — ContextVar 를 건드리지 않는다는 기존 계약 유지."""
    outer = TraceSpan.start("a_agent.process", agent_id="a_agent")
    TraceSpan.record("react.step1", started_at=0.0, agent_id="b_agent")
    assert get_current_agent_id() == "a_agent"
    outer.end()


def test_concurrent_agents_do_not_bleed():
    """공유 가변 필드였던 시절의 실제 결함 — 동시 요청이 서로를 덮어썼다."""
    seen = {}

    async def run(agent_id: str, delay: float):
        span = TraceSpan.start(f"{agent_id}.process", agent_id=agent_id)
        try:
            await asyncio.sleep(delay)          # 상대 요청이 끼어들 틈
            seen[agent_id] = get_current_agent_id()
        finally:
            span.end()

    async def main():
        await asyncio.gather(run("weather_agent", 0.02),
                             run("calculator_agent", 0.01),
                             run("summarization_agent", 0.015))

    asyncio.run(main())
    assert seen == {"weather_agent": "weather_agent",
                    "calculator_agent": "calculator_agent",
                    "summarization_agent": "summarization_agent"}, seen


def test_http_tool_span_declares_harness_tool_stage():
    """도구 span 이 stage 태그 없이 이름 모양에만 의존하고 있었다.

    실측(30일): tool_http(...) 39건이 metadata.stage 없이 이름 휴리스틱으로만
    분류됐다 — 이름이 바뀌면 도구 사용이 조용히 '미분류'로 사라진다.
    """
    import inspect
    from logosai.mixins import http_tool
    src = inspect.getsource(http_tool)
    assert 'stage="harness_tool"' in src, "tool_http span 에 stage 태그 없음"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = f = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            p += 1
        except Exception as e:
            print(f"  ✗ {fn.__name__}: {type(e).__name__}: {e}")
            f += 1
    print(f"\npass={p} fail={f}")
    sys.exit(1 if f else 0)
