"""하네스 테스트는 pytest 가 수집할 수 있어야 한다 (2026-11-10).

사고 — 하네스 테스트 파일들은 있었는데 전부 `def main()` + `if __name__ ==
"__main__"` 형태의 스크립트였다. `pytest tests/test_harness_budget.py
--collect-only` 는 "no tests collected" 였고 종료 코드도 조용했다. 즉 테스트가
"있다"고 믿는 동안 회귀를 자동으로 잡는 것은 0건이었다.

이 파일은 그 상태로 **조용히 되돌아가는 것**을 막는다. 대상 파일에 pytest 가
수집할 함수(`test_*`, 모듈 수준 또는 클래스 안)가 하나도 없으면 실패한다.
"""
import ast
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_PATTERNS = (
    "test_harness*.py", "test_auto_observability.py", "test_guardrails*.py",
    # 2026-11-10 2차 변환분 — LLM 클라이언트·프레임워크 계약·CLI·패키징.
    "test_llm_*.py", "test_anthropic_stream_tools.py", "test_g6_langchain_removal.py",
    "test_framework_*.py", "test_eval_golden_runner.py", "test_cli_scaffolding.py",
    "test_g8_extras_reorg.py",
)

# 반드시 검사 대상에 들어 있어야 하는 파일 — glob 이 빗나가 빈 목록을 검사하고
# 초록이 되는 일을 막는 대조군이다.
_MUST_INCLUDE = (
    "test_harness_budget.py",
    "test_harness_timeout.py",
    "test_harness_override.py",
    "test_auto_observability.py",
    "test_guardrails.py",
    "test_guardrails_eval.py",
    # 2차 변환분 11개
    "test_llm_multi_provider.py",
    "test_llm_native_no_langchain.py",
    "test_llm_onprem_base_url.py",
    "test_llm_provider_config.py",
    "test_anthropic_stream_tools.py",
    "test_g6_langchain_removal.py",
    "test_framework_contracts.py",
    "test_framework_standard_upgrades.py",
    "test_eval_golden_runner.py",
    "test_cli_scaffolding.py",
    "test_g8_extras_reorg.py",
)


def _guarded_files():
    files = set()
    for pattern in _PATTERNS:
        files.update(_TESTS_DIR.glob(pattern))
    return sorted(files)


def collectable_test_functions(source: str):
    """pytest 가 수집할 함수 이름들 — 모듈 수준 `test_*` 와 클래스 바로 아래 `test_*`.

    함수 안에 중첩된 `def test_x` 는 pytest 가 수집하지 않으므로 세지 않는다.
    """
    func_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    names = []
    for node in ast.parse(source).body:
        if isinstance(node, func_types) and node.name.startswith("test_"):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            names.extend(f"{node.name}.{child.name}" for child in node.body
                         if isinstance(child, func_types) and child.name.startswith("test_"))
    return names


def test_checker_tells_script_style_from_collectable():
    """검사기 자체의 대조군 — 스크립트형은 0, 수집 가능한 것은 센다."""
    script_style = (
        "def main():\n"
        "    def test_inner():\n"      # 중첩 — 수집되지 않는다
        "        pass\n"
        "    print('RESULT: GREEN')\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    assert collectable_test_functions(script_style) == []

    collectable = (
        "def test_a(): pass\n"
        "async def test_b(): pass\n"
        "def helper(): pass\n"
        "class TestC:\n"
        "    def test_d(self): pass\n"
        "    async def test_e(self): pass\n"
        "    def helper(self): pass\n"
    )
    assert collectable_test_functions(collectable) == [
        "test_a", "test_b", "TestC.test_d", "TestC.test_e"]


def test_harness_test_files_expose_collectable_tests():
    files = _guarded_files()
    names = [f.name for f in files]

    # 대조군: 검사할 것이 실제로 있다.
    assert names, f"{_TESTS_DIR} 에서 검사 대상 파일을 하나도 찾지 못했다 (패턴: {_PATTERNS})"
    missing = [n for n in _MUST_INCLUDE if n not in names]
    assert not missing, (
        f"검사 대상에 있어야 할 파일이 없다: {missing}. 파일을 옮기거나 이름을 바꿨다면 "
        f"이 테스트의 _PATTERNS / _MUST_INCLUDE 도 함께 고칠 것 — 안 그러면 그 파일은 무방비가 된다."
    )

    counts = {f.name: len(collectable_test_functions(f.read_text(encoding="utf-8")))
              for f in files}
    uncollected = sorted(name for name, n in counts.items() if n == 0)
    assert not uncollected, (
        "pytest 가 테스트를 하나도 수집하지 못하는 파일: " + ", ".join(uncollected) + ".\n"
        "이 파일들은 `python tests/<파일>` 로만 도는 스크립트라 pytest/CI 에서는 "
        "검사 0건으로 조용히 지나간다.\n"
        "고치는 법: 각 검사를 모듈 수준 `def test_…()` / `async def test_…()` 로 꺼내고 "
        "(검사 하나 = 함수 하나, 출력이 아니라 `assert`), `main()` 은 그 함수들을 부르게 한다. "
        "본보기: tests/test_harness_budget.py."
    )
