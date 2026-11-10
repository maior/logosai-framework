"""Phase 2 — G6 langchain 완전 제거 (workflow ChatGoogleGenerativeAI) (2026-07-07).

표준 준비도 진단 G6: workflow/llm_orchestrator.py 가 모듈 레벨에서
`langchain_google_genai.ChatGoogleGenerativeAI` 를 import — deprecated
google.generativeai 경유로 '무한 hang' 위험(과거 실사). 이 경로를 LLMClient
(google.genai 직접)로 교체한다. 계약:
  - 모듈 레벨 langchain import 제거(import 시점 hang 위험 소거).
  - llm_orchestrator import 가 langchain_google_genai 를 sys.modules 로 끌지 않음.
  - initialize() 는 LLMClient 를 사용.
  - LLM 호출 경로는 self.llm.invoke_messages 사용(ainvoke/LCEL chain 아님).

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가 0건을 수집했다.
  - 직접 실행: python tests/test_g6_langchain_removal.py  → 마지막 줄 `RESULT: GREEN`

G6-3/G6-4 는 새 인터프리터에서 잰다. 예전엔 이 프로세스의 sys.modules 에서
langchain* 을 지운 뒤(되돌리지 않았다) import 했는데, pytest 세션에서는
llm_orchestrator 가 이미 import 돼 있을 수 있어 그 import 는 아무 일도 하지 않고
검사는 공허하게 통과한다. 새 프로세스는 그럴 일이 없고 이 프로세스도 건드리지 않는다.
"""
import os
import re
import subprocess
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":      # 스크립트 모드에서만 — pytest 는 pyproject 의 pythonpath 를 쓴다
    sys.path.insert(0, _PKG)

from _script_runner import block_pulse, run, run_tests, use_fake_api_keys  # noqa: E402

_IMPORT_PROBE = (
    "import sys\n"
    "{prelude}"
    "import logosai.workflow.llm_orchestrator as orch\n"
    "assert orch is not None\n"
    "print('PULLED=' + str('langchain_google_genai' in sys.modules))\n"
)


def _setup(mp):
    block_pulse(mp)
    use_fake_api_keys(mp)


def _teardown():
    pass


def _src(name):
    return open(os.path.join(_PKG, "logosai", "workflow", name), encoding="utf-8").read()


def _module_scope():
    """llm_orchestrator.py 의 첫 class 이전 = 모듈 스코프. 대조군 포함."""
    scope = _src("llm_orchestrator.py").split("class ", 1)[0]
    # 대조군: 잘라낸 것이 진짜 모듈 스코프다 — import 문이 있고, 같은 정규식이 그것을 잡는다.
    assert re.search(r"^\s*(from|import)\s+\w+", scope, re.M), "모듈 스코프에서 import 를 하나도 못 찾았다"
    assert re.search(r"^\s*(from|import)\s+langchain", "import langchain_core\n", re.M)
    return scope


def _import_in_fresh_interpreter(prelude=""):
    env = dict(os.environ, PYTHONPATH=_PKG, LOGOS_PULSE_DISABLED="1")
    return subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE.format(prelude=prelude)],
        cwd=_PKG, env=env, capture_output=True, text=True, timeout=180,
    )


def test_g6_1_no_module_scope_langchain_import():
    """G6-1 모듈 스코프 langchain import 없음"""
    assert not re.search(r"^\s*(from|import)\s+langchain", _module_scope(), re.M)


def test_g6_2_no_module_level_langchain_google_genai_reference():
    """G6-2 ChatGoogleGenerativeAI 모듈 레벨 참조 없음"""
    assert "langchain_google_genai" not in _module_scope()


def test_g6_3_import_succeeds_in_fresh_interpreter():
    """G6-3 import 성공(hang/에러 없음)"""
    proc = _import_in_fresh_interpreter()      # hang 이면 timeout 으로 실패한다
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "PULLED=" in proc.stdout


def test_g6_4_import_does_not_pull_langchain_google_genai():
    """G6-4 import 이 langchain_google_genai 를 sys.modules 로 안 끎"""
    proc = _import_in_fresh_interpreter()
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "PULLED=False" in proc.stdout
    # 대조군: 그 모듈이 sys.modules 에 있으면 같은 탐침이 True 를 낸다.
    planted = _import_in_fresh_interpreter(
        "import types\nsys.modules['langchain_google_genai'] = types.ModuleType('langchain_google_genai')\n")
    assert planted.returncode == 0, planted.stderr[-800:]
    assert "PULLED=True" in planted.stdout


def test_g6_5_initialize_sets_llmclient():
    """G6-5 initialize() → self.llm 은 LLMClient"""
    import logosai.workflow.llm_orchestrator as orch
    from logosai.utils.llm_client import LLMClient
    o = orch.LLMWorkflowOrchestrator(model="gemini-2.5-flash-lite")
    run(o.initialize())         # 예외가 나면 그대로 실패 (예전엔 잡아서 False 로 바꿨다)
    assert isinstance(o.llm, LLMClient)


class _Resp:
    content = ('{"intent":"information","complexity":"simple","complexity_score":0.2,'
               '"requires_multiple_agents":false,"reasoning":"r"}')


class _MockLLM:
    def __init__(self, resp=_Resp):
        self.invoke_called = False
        self._resp = resp

    async def invoke_messages(self, messages, **kw):
        self.invoke_called = True
        return self._resp()


def _analyze():
    import logosai.workflow.llm_orchestrator as orch
    o2 = orch.LLMWorkflowOrchestrator()
    o2._initialized = True
    o2.llm = _MockLLM()
    assert o2.llm.invoke_called is False        # 대조군: 호출 전에는 False
    res = run(o2.analyze_query_complexity("2+2 계산해줘"))
    return o2, res


def test_g6_6_call_path_uses_invoke_messages():
    """G6-6 호출 경로가 invoke_messages 사용"""
    o2, _ = _analyze()
    assert o2.llm.invoke_called is True


def test_g6_7_response_parsed_to_dict():
    """G6-7 응답 파싱 정상(dict 반환)"""
    _, res = _analyze()
    assert isinstance(res, dict)
    assert res.get("intent") == "information"


def test_g6_8_query_decomposer_has_no_langchain_reference():
    """G6-8 query_decomposer 전체 langchain 참조 없음"""
    qd_src = _src("query_decomposer.py")
    assert "class QueryDecomposer" in qd_src    # 대조군: 진짜 그 파일을 읽었다
    assert "langchain" not in qd_src


def test_g6_9_decompose_path_uses_invoke_messages():
    """G6-9 decompose 경로가 invoke_messages 사용"""
    import logosai.workflow.query_decomposer as qd

    class _Resp2:
        content = '{"sub_queries": []}'

    # decompose 경로가 invoke_messages 를 쓰는지(ainvoke 아님) — mock 주입
    dec = qd.QueryDecomposer(llm=_MockLLM(_Resp2))
    dec._initialized = True
    assert dec.llm.invoke_called is False       # 대조군: 호출 전에는 False
    try:
        # 단순쿼리 fast-path 를 우회할 만큼 복잡한 멀티스텝 쿼리(LLM 경로 강제)
        run(dec.decompose(
            "스페이스X 최신 뉴스를 검색하고 핵심을 요약한 다음 그 내용으로 발표자료를 만들어줘",
            [{"agent_id": "internet"}, {"agent_id": "summarizer"}, {"agent_id": "pptx"}]))
    except Exception as e:  # noqa: BLE001 — 빈 분해 결과에 대한 후처리 예외는 이 검사의 관심사가 아니다
        if not dec.llm.invoke_called:
            print("   decompose err:", e)
    assert dec.llm.invoke_called is True


# ══ pytest 배선 ═══════════════════════════════════════════════════════════

if "pytest" in sys.modules:
    import pytest

    @pytest.fixture(autouse=True)
    def _env(monkeypatch):
        _setup(monkeypatch)
        yield
        monkeypatch.undo()
        _teardown()


def main():
    return run_tests(globals(), setup=_setup, teardown=_teardown)


if __name__ == "__main__":
    sys.exit(main())
