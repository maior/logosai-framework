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

직접 실행: python logosai/tests/test_cli_scaffolding.py
"""
import ast
import importlib.util
import os
import sys
import tempfile

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PKG)


def main():
    fails = []

    def t(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    from logosai.cli import agent as cli_agent

    # ── scaffold: 유효한 템플릿 생성 ──
    with tempfile.TemporaryDirectory() as d:
        path = cli_agent.scaffold("weather_bot", d)
        t("C-1 scaffold 파일 생성", os.path.isfile(path) and path.endswith("weather_bot.py"))
        src = open(path).read()
        try:
            ast.parse(src)
            parsed = True
        except SyntaxError:
            parsed = False
        t("C-2 생성 코드 유효(ast.parse)", parsed)
        t("C-3 async process() 포함", "async def process" in src)
        t("C-4 PascalCase 클래스명(WeatherBot)", "class WeatherBot" in src)

        # ── 생성 코드가 실제 import·인스턴스화 가능 ──
        try:
            spec = importlib.util.spec_from_file_location("weather_bot_gen", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            inst = mod.WeatherBot()
            usable = hasattr(inst, "process")
        except Exception as e:  # noqa: BLE001
            usable = False
            print("   import err:", e)
        t("C-5 생성 에이전트 import·인스턴스화 가능", usable)

        # ── 중복 → FileExistsError ──
        dup_raised = False
        try:
            cli_agent.scaffold("weather_bot", d)
        except FileExistsError:
            dup_raised = True
        t("C-6 중복 이름 → FileExistsError(덮어쓰기 안 함)", dup_raised)

    # ── new 서브파서 파싱 + main 서버 없이 디스패치 ──
    with tempfile.TemporaryDirectory() as d:
        argv_bak = sys.argv[:]
        sys.argv = ["logosai-agent", "new", "greeter", "--dir", d]
        try:
            rc = cli_agent.main()
        except SystemExit as e:
            rc = e.code
        finally:
            sys.argv = argv_bak
        t("C-7 main new 디스패치 성공(rc==0)", rc == 0)
        t("C-8 new 로 파일 생성됨", os.path.isfile(os.path.join(d, "greeter.py")))

    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
