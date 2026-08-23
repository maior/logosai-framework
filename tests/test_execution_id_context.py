"""LLM 비용이 붙는 실행 id (2026-08-22).

왜 필요해졌나
───────────
실행 행의 id 를 `trace_id` 에서 **요청별 `span.id`** 로 바꿨다(이중 ID 부채 상환).
그런데 `llm_metrics_payload` 는 `execution_id = get_current_trace_id()` 를 쓰고
있었다 — 결합의 한쪽 끝만 옮긴 셈이라 롤업이 끊겼다.

실측: 2단계 워크플로에서 진짜 행 2개는 `token_count=0`, 대신
`{"placeholder": true}` **유령 행**이 5,529 토큰을 들고 생겼다. 유실을 고치려다
새 유실을 만든 것이다.

경계는 trace 가 아니라 '실행'이다
──────────────────────────────
한 trace 에 실행이 여럿일 수 있다(오케스트레이터의 다단계 워크플로).
비용은 **그 실행**에 붙어야 하므로 trace 가 아니라 실행을 가리키는 ContextVar 가
필요하다. `_current_agent_id` 가 같은 이유로 이미 존재한다 — 공유 필드로 들고
있으면 동시 요청이 섞인다(2026-07-19, 미실행 calculator_agent 에 비용이 붙었던 일).

폴백은 trace_id 로 둔다
────────────────────
배치 실행(`batch_run`)은 `execution_id = trace_id` 로 기록한다 — 1 배치 = 1 trace =
1 실행이라 그 등식이 참이다. 실행 루트를 선언하지 않은 호출자의 동작을 바꾸지 않는다.

직접 실행: python tests/test_execution_id_context.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 전송 차단용 env 를 여기서 세우지 않는다 — `os.environ` 은 프로세스 전역이라
# 다른 파일의 테스트를 조용히 죽인다(2026-07 사고: 그렇게 8건이 죽었고 파일 단독
# 실행은 통과해서 오래 안 보였다). `pulse_client._sending_blocked()` 가 pytest 를
# 감지해 이미 기본 차단한다.

from logosai.utils.trace_span import (  # noqa: E402
    TraceSpan, get_current_execution_id, get_current_trace_id,
)


def test_execution_root_publishes_its_own_id():
    """실행 루트를 선언한 span 의 id 가 곧 실행 id 다."""
    s = TraceSpan.start("test.agent_a.process", agent_id="a", execution_root=True)
    try:
        assert get_current_execution_id() == s.id
        assert get_current_execution_id() != get_current_trace_id()
    finally:
        s.end()


def test_two_executions_in_one_trace_get_different_ids():
    """이 테스트가 원래 결함 그 자체다 — 다단계 워크플로."""
    root = TraceSpan.start("test.orchestrator", agent_id="orch")
    try:
        a = TraceSpan.start("test.stage_a.process", agent_id="internet_agent",
                            execution_root=True)
        first = get_current_execution_id()
        a.end()

        b = TraceSpan.start("test.stage_b.process", agent_id="summarization_agent",
                            execution_root=True)
        second = get_current_execution_id()
        b.end()

        assert first and second
        assert first != second, "두 단계가 같은 실행 id 를 받았다 — PK 가 충돌한다"
        assert a.trace_id == b.trace_id, "같은 워크플로인데 trace 가 갈라졌다"
    finally:
        root.end()


def test_execution_id_restores_after_end():
    """실행이 끝나면 그 소유권도 끝난다. 남아 있으면 다음 실행의 비용이 섞인다."""
    outer = TraceSpan.start("test.outer.process", agent_id="outer", execution_root=True)
    outer_id = get_current_execution_id()
    inner = TraceSpan.start("test.inner.process", agent_id="inner", execution_root=True)
    assert get_current_execution_id() == inner.id
    inner.end()
    assert get_current_execution_id() == outer_id, "중첩 실행이 끝난 뒤 복원되지 않았다"
    outer.end()


def test_plain_span_does_not_claim_execution_ownership():
    """llm.* / tool_* 처럼 실행이 아닌 span 은 소유권을 가로채지 않는다."""
    root = TraceSpan.start("test.agent_a.process", agent_id="a", execution_root=True)
    owner = get_current_execution_id()
    child = TraceSpan.start("test.llm.call")
    assert get_current_execution_id() == owner, "일반 span 이 실행 소유권을 빼앗았다"
    child.end()
    root.end()


def test_no_execution_root_means_none():
    """모름 ≠ 지어내기. 실행 루트가 없으면 빈 값이고, 폴백 판단은 호출자 몫이다."""
    s = TraceSpan.start("test.standalone")
    try:
        assert get_current_execution_id() is None
    finally:
        s.end()


# ─────────────────────────────────────────────────────────────
# 페이로드 성형이 실제로 그 값을 쓰는가 (배선)
# ─────────────────────────────────────────────────────────────

def test_payload_uses_execution_id_not_trace_id():
    from logosai.utils.batch_telemetry import llm_metrics_payload

    s = TraceSpan.start("test.agent_a.process", agent_id="a", execution_root=True)
    try:
        p = llm_metrics_payload({"model": "m", "input_tokens": 10, "output_tokens": 5})
        assert p["execution_id"] == s.id, (
            f"비용이 실행이 아닌 곳에 붙는다: {p['execution_id']} != {s.id}"
        )
        assert p["agent_id"] == "a"
    finally:
        s.end()


def test_payload_falls_back_to_trace_id_for_batch():
    """배치는 execution_id == trace_id 로 기록한다. 그 동작을 깨지 않는다."""
    from logosai.utils.batch_telemetry import llm_metrics_payload

    s = TraceSpan.start("test.batch.job", agent_id="test.batch.job")  # 실행 루트 선언 없음
    try:
        p = llm_metrics_payload({"model": "m"})
        assert p["execution_id"] == s.trace_id
    finally:
        s.end()


# ─────────────────────────────────────────────────────────────
# 성형은 한 곳뿐이어야 한다 (호스트별 사본 금지)
# ─────────────────────────────────────────────────────────────

def test_no_host_reimplements_the_payload_shaping():
    """LLM 비용 페이로드를 각 호스트가 따로 만들면 집계가 조용히 갈린다.

    실제로 그랬다: logos_api 는 SDK 에 위임하도록 정리됐는데 **ACP 만 사본**이
    남아 `get_current_trace_id()` 를 쓰고 있었다. 실행 id 를 바꾸자 ACP 쪽만
    옛 값을 보내 비용이 유령 행에 쌓였다(진짜 행 2개 token_count=0 / 유령 11,100).

    판정 기준: `send_llm_call_bg(...)` 를 부르면서 `execution_id=` 를 **직접**
    넘기는 호스트가 있으면 사본이다. 위임하면 `**payload` 로 넘어간다.
    """
    import ast
    import os

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    hosts = [
        os.path.join(root, "acp_server", "acp_modules", "server.py"),
        os.path.join(root, "logos_api", "app", "services", "orchestrator_service.py"),
    ]
    offenders = []
    for path in hosts:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = (getattr(n.func, "id", "") or getattr(n.func, "attr", ""))
            if name != "send_llm_call_bg":
                continue
            if any(k.arg == "execution_id" for k in n.keywords):
                offenders.append(f"{os.path.basename(path)}:{n.lineno}")

    assert not offenders, (
        "호스트가 비용 페이로드를 직접 성형한다 (SDK 위임하지 않음): "
        f"{offenders} — 실행 id 규칙이 바뀌면 이 호스트만 옛 값을 보낸다"
    )

if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  ❌ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
