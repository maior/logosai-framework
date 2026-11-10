"""Phase 2 — CLI 스캐폴딩(logosai-agent new) 테스트 (2026-07-06).

표준 준비도 진단 Phase 2: 바이브코딩 골든패스. client·serve CLI 는 이미
있으나 '새 에이전트 템플릿 생성'(scaffolding)이 없었다 — 기존 logosai-agent
CLI 에 new 서브커맨드를 additive 로 추가한다(pyproject·기존 코드 미변경).
계약:
  - agent.scaffold(name, dir) → 유효한 SimpleAgent 템플릿 .py 생성
    (ast.parse 통과, process() 포함, PascalCase 클래스명).
  - 생성 코드는 실제 import·인스턴스화 가능(계약 준수).
  - 중복 이름은 덮어쓰지 않고 FileExistsError(안전).
  - new 서브파서가 파싱되고 main 이 서버 없이 디스패치.

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가 0건을 수집했다.
  - 직접 실행: python tests/test_cli_scaffolding.py  → 마지막 줄 `RESULT: GREEN`
"""
import ast
import importlib.util
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":      # 스크립트 모드에서만 — pytest 는 pyproject 의 pythonpath 를 쓴다
    sys.path.insert(0, _PKG)

from _script_runner import block_pulse, run_tests  # noqa: E402


def _setup(mp):
    block_pulse(mp)


def _teardown():
    pass


def _cli():
    from logosai.cli import agent as cli_agent
    return cli_agent


def _scaffold(tmp_path):
    """weather_bot 템플릿 생성 → (경로, 소스)"""
    path = _cli().scaffold("weather_bot", str(tmp_path))
    return path, open(path, encoding="utf-8").read()


def _run_new(tmp_path, monkeypatch):
    """`logosai-agent new greeter --dir <tmp>` 를 서버 없이 디스패치 → 종료 코드"""
    monkeypatch.setattr(sys, "argv", ["logosai-agent", "new", "greeter", "--dir", str(tmp_path)])
    try:
        return _cli().main()
    except SystemExit as e:
        return e.code


# ── scaffold: 유효한 템플릿 생성 ──

def test_c1_scaffold_creates_file(tmp_path):
    """C-1 scaffold 파일 생성"""
    path, _ = _scaffold(tmp_path)
    assert os.path.isfile(path)
    assert path.endswith("weather_bot.py")


def test_c2_generated_code_parses(tmp_path):
    """C-2 생성 코드 유효(ast.parse)"""
    _, src = _scaffold(tmp_path)
    assert src.strip(), "생성된 파일이 비어 있다"      # 빈 문자열도 ast.parse 는 통과한다
    ast.parse(src)      # SyntaxError 면 그대로 실패


def test_c3_generated_code_has_async_process(tmp_path):
    """C-3 async process() 포함"""
    _, src = _scaffold(tmp_path)
    assert "async def process" in src


def test_c4_class_name_is_pascal_case(tmp_path):
    """C-4 PascalCase 클래스명(WeatherBot)"""
    _, src = _scaffold(tmp_path)
    assert "class WeatherBot" in src


def test_c5_generated_agent_imports_and_instantiates(tmp_path):
    """C-5 생성 에이전트 import·인스턴스화 가능"""
    path, _ = _scaffold(tmp_path)
    # 예외가 나면 그대로 실패 (예전엔 잡아서 False 로 바꿨다). sys.modules 에는 등록하지 않는다.
    spec = importlib.util.spec_from_file_location("weather_bot_gen", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    inst = mod.WeatherBot()
    assert hasattr(inst, "process")


def test_c6_duplicate_name_raises_and_does_not_overwrite(tmp_path):
    """C-6 중복 이름 → FileExistsError(덮어쓰기 안 함)"""
    path, _ = _scaffold(tmp_path)       # 대조군: 첫 생성은 예외 없이 된다
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 사용자가 고친 내용\n")
    dup_raised = False
    try:
        _cli().scaffold("weather_bot", str(tmp_path))
    except FileExistsError:
        dup_raised = True
    assert dup_raised
    assert open(path, encoding="utf-8").read() == "# 사용자가 고친 내용\n", "기존 파일을 덮어썼다"


# ── new 서브파서 파싱 + main 서버 없이 디스패치 ──

def test_c7_main_new_dispatch_returns_zero(tmp_path, monkeypatch):
    """C-7 main new 디스패치 성공(rc==0)"""
    assert _run_new(tmp_path, monkeypatch) == 0


def test_c8_new_creates_the_file(tmp_path, monkeypatch):
    """C-8 new 로 파일 생성됨"""
    target = os.path.join(str(tmp_path), "greeter.py")
    assert not os.path.exists(target)       # 대조군: 실행 전에는 없다
    _run_new(tmp_path, monkeypatch)
    assert os.path.isfile(target)


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
