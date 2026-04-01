"""Built-in tools for LogosAI agents.

Tools:
- calculator: Math calculations (eval-based, safe subset)
- datetime_tool: Current date/time, date arithmetic
- text_tool: Text manipulation (count, extract, translate intent)
"""

import math
from datetime import datetime, timedelta
from typing import Dict, Any, List


# ============================================================
# Tool Definitions (for LLM function calling)
# ============================================================

BUILTIN_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "calculator",
        "description": "수학 계산을 수행합니다. 사칙연산, 제곱근, 삼각함수, 퍼센트 등. Python math 라이브러리 사용 가능.",
        "parameters": {
            "expression": {
                "type": "string",
                "description": "계산할 Python 수식 (예: 325/60, math.sqrt(144), 100*1.08**5)",
            }
        },
    },
    {
        "name": "datetime_tool",
        "description": "현재 날짜/시간을 조회하거나, 날짜 계산을 수행합니다.",
        "parameters": {
            "action": {
                "type": "string",
                "description": "수행할 작업: 'now' (현재 시각), 'add_days' (날짜 더하기), 'diff' (날짜 차이)",
            },
            "days": {
                "type": "string",
                "description": "더하거나 뺄 일수 (add_days에서 사용)",
                "required": False,
            },
            "date1": {
                "type": "string",
                "description": "첫 번째 날짜 YYYY-MM-DD (diff에서 사용)",
                "required": False,
            },
            "date2": {
                "type": "string",
                "description": "두 번째 날짜 YYYY-MM-DD (diff에서 사용)",
                "required": False,
            },
        },
    },
    {
        "name": "text_tool",
        "description": "텍스트 분석/가공 도구. 글자수 세기, 단어 수, 키워드 추출 등.",
        "parameters": {
            "action": {
                "type": "string",
                "description": "'count_chars' (글자수), 'count_words' (단어수), 'extract_numbers' (숫자 추출)",
            },
            "text": {
                "type": "string",
                "description": "분석할 텍스트",
            },
        },
    },
]


# ============================================================
# Tool Executors (actual implementations)
# ============================================================

_SAFE_BUILTINS = {
    "abs": abs, "round": round, "min": min, "max": max,
    "int": int, "float": float, "len": len,
    "sum": sum, "pow": pow,
}
_SAFE_MATH = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}


async def _calculator(expression: str = "") -> str:
    """Safe math evaluation."""
    try:
        safe_globals = {"__builtins__": _SAFE_BUILTINS, "math": math, **_SAFE_MATH}
        result = eval(expression, safe_globals)
        return f"{expression} = {result}"
    except Exception as e:
        return f"계산 오류: {e}"


async def _datetime_tool(action: str = "now", days: str = "0", date1: str = "", date2: str = "") -> str:
    """Date/time operations."""
    try:
        if action == "now":
            now = datetime.now()
            return f"현재: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.strftime('%A')})"

        elif action == "add_days":
            d = int(days)
            target = datetime.now() + timedelta(days=d)
            direction = "후" if d >= 0 else "전"
            return f"{abs(d)}일 {direction}: {target.strftime('%Y-%m-%d')} ({target.strftime('%A')})"

        elif action == "diff":
            d1 = datetime.strptime(date1, "%Y-%m-%d")
            d2 = datetime.strptime(date2, "%Y-%m-%d")
            diff = abs((d2 - d1).days)
            return f"{date1}와 {date2}의 차이: {diff}일"

        return f"알 수 없는 작업: {action}"
    except Exception as e:
        return f"날짜 처리 오류: {e}"


async def _text_tool(action: str = "count_chars", text: str = "") -> str:
    """Text analysis."""
    try:
        if action == "count_chars":
            return f"글자 수: {len(text)}"
        elif action == "count_words":
            words = text.split()
            return f"단어 수: {len(words)}"
        elif action == "extract_numbers":
            import re
            numbers = re.findall(r'-?\d+\.?\d*', text)
            return f"추출된 숫자: {numbers}"
        return f"알 수 없는 작업: {action}"
    except Exception as e:
        return f"텍스트 처리 오류: {e}"


BUILTIN_EXECUTORS: Dict[str, Any] = {
    "calculator": _calculator,
    "datetime_tool": _datetime_tool,
    "text_tool": _text_tool,
}
