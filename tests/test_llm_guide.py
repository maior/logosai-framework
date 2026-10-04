"""LLM 용 가이드(logosai/llms.txt)의 예제가 실제로 돈다.

생성형 AI 는 문서에 있는 호출을 그대로 쓴다. 예제가 틀리면 틀린 코드가 그대로 복제된다
(README 의 `@agent` 예제는 팩토리라는 사실을 빠뜨려, `joke_agent.process` 를 부르게
유도했다). 그래서 가이드의 모든 ```python 블록을 실행한다. LLM 은 가짜로 바꾼다 —
네트워크·키 없이, 결정적으로.
"""
import contextlib
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from logosai import guide
from logosai.utils.llm_client import LLMClient, LLMResponse

ROOT = Path(__file__).resolve().parents[1]
CRITIQUE_OK = '{"unnecessary_agents": [], "broken_chain": false, "reason": "ok"}'

#: 블록 순서대로, 출력에 있어야 할 것
EXPECT = [
    "가짜 답변",                                   # 2. SimpleAgent
    "가짜 답변",                                   # 2. @agent 팩토리
    "True 2 0\n가짜 답변",                         # 3. run — 두 에이전트 성공 + 최종 답
    "workflow_complete",                          # 3. run_streaming
    "['search_agent', 'excel_agent']",            # 4. WorkflowEngine 복합 실행
    "가짜 답변",                                   # 5. LLMClient
]


def _blocks(text):
    return re.findall(r"```python\n(.*?)```", text, re.S)


def _fake_reply(prompt):
    if "두 가지만 판정하라" in prompt:
        return CRITIQUE_OK
    if "사용 가능한 에이전트" in prompt:                # 계획 프롬프트 — 등록된 에이전트로 계획한다
        ids = re.findall(r"^## ([a-z0-9_]+_agent)\s*$", prompt, re.M)
        stages = [{"stage_id": i + 1, "execution_type": "sequential",
                   "agents": [{"agent_id": a, "sub_query": f"{a} 할 일",
                               "input_from": [f"stage_{i}"] if i else None}]}
                  for i, a in enumerate(ids[:2])]
        return json.dumps({"workflow_strategy": "sequential", "stages": stages})
    return "가짜 답변"


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "off")
    monkeypatch.setenv("LOGOS_PULSE_DISABLED", "1")

    async def initialize(self):
        self._initialized = True

    async def invoke_messages(self, messages, **kwargs):
        prompt = "\n".join(m.content if hasattr(m, "content") else m.get("content", "")
                           for m in messages)
        return LLMResponse(content=_fake_reply(prompt), provider="fake", model="fake",
                           metadata={"finish_reason": "stop", "truncated": False})

    monkeypatch.setattr(LLMClient, "initialize", initialize)
    monkeypatch.setattr(LLMClient, "invoke_messages", invoke_messages)


def _run(code):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(code, "<llms.txt>", "exec"), {"__name__": "__guide__"})
    return out.getvalue()


def test_guide_has_the_expected_examples():
    assert len(_blocks(guide.text())) == len(EXPECT)


@pytest.mark.parametrize("index", range(len(EXPECT)))
def test_guide_example_runs(fake_llm, index):
    code = _blocks(guide.text())[index]
    out = _run(code)
    assert EXPECT[index] in out, f"예제 {index + 1} 출력에 {EXPECT[index]!r} 가 없다:\n{out}"


def test_a_wrong_call_in_an_example_would_fail(fake_llm):
    """대조군 — 실행기가 틀린 예제를 통과시키지 않는다 (README 가 유도하던 그 실수)."""
    code = _blocks(guide.text())[1].replace("instance = joke_agent()", "instance = joke_agent")
    with pytest.raises(AttributeError):
        _run(code)


def test_guide_prints_from_the_module():
    out = subprocess.run([sys.executable, "-m", "logosai.guide"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.startswith("# LogosAI SDK"), out.stderr[-300:]


def test_guide_ships_in_the_wheel(tmp_path):
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "--no-build-isolation",
         "-q", "-w", str(tmp_path)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr[-500:]
    wheel = next(tmp_path.glob("logosai-*.whl"))
    names = zipfile.ZipFile(wheel).namelist()
    assert "logosai/llms.txt" in names and "logosai/guide.py" in names
