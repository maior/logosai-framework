"""P0-1 관측 자동 배선 테스트 (2026-07-06).

표준 준비도 진단 G3: base process() 가 관측 신호를 자동 emit 해야 "그냥 만들면
Pulse 에 뜬다"는 표준 default 경험이 성립. 계약:
  - 서브클래스가 정의한 process 는 자동으로 관측 래핑된다 (_logos_observed).
  - enabled + standalone → execution emit + span 시작. process 결과 불변.
  - opt-out: env LOGOSAI_AUTO_OBSERVE=false 또는 agent._auto_observe=False → emit 없음.
  - fire-and-forget: emit 이 raise 해도 process 는 정상 반환.
  - 부모 trace 존재(ACP 내부) → execution 이중 emit 안 함 (ACP 소유). span 은 중첩.
  - 이중 서브클래싱 → 이중 래핑/이중 emit 없음.

직접 실행: python logosai/tests/test_auto_observability.py
"""
import asyncio
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PKG)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def main():
    fails = []

    def t(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    os.environ.pop("LOGOSAI_AUTO_OBSERVE", None)  # 기본 on

    import logosai.observability as obs
    from logosai.simple_agent import SimpleAgent
    from logosai.agent_types import AgentResponse

    # emit / span 을 레코더로 monkeypatch
    rec = {"exec": [], "span": 0, "raise": False}

    def fake_emit(agent_id, query, success, duration_ms, output="", error=None):
        if rec["raise"]:
            raise RuntimeError("pulse down")
        rec["exec"].append({"agent_id": agent_id, "success": success})

    class _FakeSpan:
        def end(self, *a, **k):
            pass

    def fake_span(agent_id, query):
        rec["span"] += 1
        return _FakeSpan()

    obs.emit_agent_execution = fake_emit
    obs.start_agent_span = fake_span

    class MyAgent(SimpleAgent):
        async def process(self, query, context=None):
            return AgentResponse.success(content={"answer": "ok:" + query})

    # ── 래핑 여부 ──
    t("O-1 서브클래스 process 자동 래핑",
      getattr(MyAgent.__dict__.get("process"), "_logos_observed", False) is True)

    # ── enabled + standalone ──
    a = MyAgent()
    res = run(a.process("hi"))
    ans = res.content.get("answer") if hasattr(res, "content") else None
    t("O-2 process 결과 불변", ans == "ok:hi")
    t("O-3 standalone → execution emit", len(rec["exec"]) == 1 and rec["exec"][0]["success"] is True)
    t("O-4 span 시작됨", rec["span"] >= 1)

    # ── opt-out: env ──
    rec["exec"].clear()
    os.environ["LOGOSAI_AUTO_OBSERVE"] = "false"
    run(a.process("x"))
    t("O-5 env false → emit 없음", len(rec["exec"]) == 0)
    os.environ.pop("LOGOSAI_AUTO_OBSERVE", None)

    # ── opt-out: agent attr ──
    rec["exec"].clear()
    a._auto_observe = False
    run(a.process("y"))
    t("O-6 _auto_observe=False → emit 없음", len(rec["exec"]) == 0)
    a._auto_observe = True

    # ── fire-and-forget: emit raise 해도 process 정상 ──
    rec["exec"].clear()
    rec["raise"] = True
    res2 = run(a.process("z"))
    t("O-7 emit 실패해도 process 정상 반환",
      hasattr(res2, "content") and res2.content.get("answer") == "ok:z")
    rec["raise"] = False

    # ── 실패 케이스: process 예외 → success False emit + 예외 전파 ──
    rec["exec"].clear()

    class FailAgent(SimpleAgent):
        async def process(self, query, context=None):
            raise ValueError("boom")

    fa = FailAgent()
    raised = False
    try:
        run(fa.process("q"))
    except ValueError:
        raised = True
    t("O-8 process 예외 전파 유지", raised)
    t("O-9 실패도 execution emit(success False)",
      len(rec["exec"]) == 1 and rec["exec"][0]["success"] is False)

    # ── 부모 trace 존재 → execution 이중 emit 안 함 ──
    rec["exec"].clear()
    from logosai.utils.trace_span import TraceSpan
    parent = TraceSpan.start(name="parent", agent_id="acp")
    run(a.process("nested"))
    parent.end()
    t("O-10 부모 trace 있으면 execution emit 생략(ACP 소유)", len(rec["exec"]) == 0)

    # ── 이중 서브클래싱 → 이중 emit 없음 ──
    rec["exec"].clear()

    class ChildAgent(MyAgent):  # process 재정의 안 함 → 상속(이미 래핑됨)
        pass

    ca = ChildAgent()
    run(ca.process("c"))
    t("O-11 상속 서브클래스 이중 emit 없음", len(rec["exec"]) == 1)

    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
