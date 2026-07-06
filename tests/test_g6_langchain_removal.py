"""Phase 2 — G6 langchain 완전 제거 (workflow ChatGoogleGenerativeAI) (2026-07-07).

표준 준비도 진단 G6: workflow/llm_orchestrator.py 가 모듈 레벨에서
`langchain_google_genai.ChatGoogleGenerativeAI` 를 import — deprecated
google.generativeai 경유로 '무한 hang' 위험(과거 실사). 이 경로를 LLMClient
(google.genai 직접)로 교체한다. 계약:
  - 모듈 레벨 langchain import 제거(import 시점 hang 위험 소거).
  - llm_orchestrator import 가 langchain_google_genai 를 sys.modules 로 끌지 않음.
  - initialize() 는 LLMClient 를 사용.
  - LLM 호출 경로는 self.llm.invoke_messages 사용(ainvoke/LCEL chain 아님).

직접 실행: python logosai/tests/test_g6_langchain_removal.py
"""
import asyncio
import os
import re
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

    src_path = os.path.join(_PKG, "logosai", "workflow", "llm_orchestrator.py")
    src = open(src_path, encoding="utf-8").read()

    # ── 모듈 레벨 langchain import 제거 ──
    module_scope = src.split("class ", 1)[0]  # 첫 class 이전 = 모듈 스코프
    t("G6-1 모듈 스코프 langchain import 없음",
      not re.search(r"^\s*(from|import)\s+langchain", module_scope, re.M))
    t("G6-2 ChatGoogleGenerativeAI 모듈 레벨 참조 없음",
      "langchain_google_genai" not in module_scope)

    # ── import 시 langchain_google_genai 를 끌지 않음 ──
    for m in list(sys.modules):
        if m.startswith("langchain"):
            del sys.modules[m]
    import logosai.workflow.llm_orchestrator as orch
    t("G6-3 import 성공(hang/에러 없음)", orch is not None)
    t("G6-4 import 이 langchain_google_genai 를 sys.modules 로 안 끎",
      "langchain_google_genai" not in sys.modules)

    # ── initialize() → LLMClient ──
    from logosai.utils.llm_client import LLMClient
    o = orch.LLMWorkflowOrchestrator(model="gemini-2.5-flash-lite")
    try:
        run(o.initialize())
        init_ok = isinstance(o.llm, LLMClient)
    except Exception as e:  # noqa: BLE001
        init_ok = False
        print("   init err:", e)
    t("G6-5 initialize() → self.llm 은 LLMClient", init_ok)

    # ── LLM 호출 경로가 invoke_messages 사용(LCEL ainvoke 아님) ──
    class _Resp:
        content = '{"intent":"information","complexity":"simple","complexity_score":0.2,"requires_multiple_agents":false,"reasoning":"r"}'

    class _MockLLM:
        def __init__(self):
            self.invoke_called = False
        async def invoke_messages(self, messages, **kw):
            self.invoke_called = True
            return _Resp()

    o2 = orch.LLMWorkflowOrchestrator()
    o2._initialized = True
    o2.llm = _MockLLM()
    res = run(o2.analyze_query_complexity("2+2 계산해줘"))
    t("G6-6 호출 경로가 invoke_messages 사용", o2.llm.invoke_called is True)
    t("G6-7 응답 파싱 정상(dict 반환)", isinstance(res, dict) and res.get("intent") == "information")

    # ── query_decomposer.py 도 langchain 완전 제거 ──
    qd_path = os.path.join(_PKG, "logosai", "workflow", "query_decomposer.py")
    qd_src = open(qd_path, encoding="utf-8").read()
    t("G6-8 query_decomposer 전체 langchain 참조 없음", "langchain" not in qd_src)

    import logosai.workflow.query_decomposer as qd

    class _Resp2:
        content = '{"sub_queries": []}'

    class _MockLLM2:
        def __init__(self):
            self.invoke_called = False
        async def invoke_messages(self, messages, **kw):
            self.invoke_called = True
            return _Resp2()

    # decompose 경로가 invoke_messages 를 쓰는지(ainvoke 아님) — mock 주입
    dec = qd.QueryDecomposer(llm=_MockLLM2())
    dec._initialized = True
    try:
        # 단순쿼리 fast-path 를 우회할 만큼 복잡한 멀티스텝 쿼리(LLM 경로 강제)
        run(dec.decompose(
            "스페이스X 최신 뉴스를 검색하고 핵심을 요약한 다음 그 내용으로 발표자료를 만들어줘",
            [{"agent_id": "internet"}, {"agent_id": "summarizer"}, {"agent_id": "pptx"}]))
        used_invoke = dec.llm.invoke_called
    except Exception as e:  # noqa: BLE001
        used_invoke = getattr(dec.llm, "invoke_called", False)
        if not used_invoke:
            print("   decompose err:", e)
    t("G6-9 decompose 경로가 invoke_messages 사용", used_invoke is True)

    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
