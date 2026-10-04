"""LLM 용 사용 가이드를 출력한다 — `python -m logosai.guide`.

생성형 AI 에게 이 SDK 사용법을 넘길 때 쓴다. 저장소 없이 설치본만 있어도 된다.
가이드의 Python 블록은 tests/test_llm_guide.py 가 실제로 실행해 검증한다.
"""
from importlib import resources


def text() -> str:
    """가이드 본문 (logosai/llms.txt)."""
    return resources.files("logosai").joinpath("llms.txt").read_text(encoding="utf-8")


def main() -> None:
    print(text())


if __name__ == "__main__":
    main()
