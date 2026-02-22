"""
LogosAI Text Utilities — Shared text processing for LLM responses.

Eliminates duplicated JSON parsing, markdown cleanup, and text truncation
patterns found across 20+ agents and multiple services.

v0.9.0
"""

import json
import re
from typing import Any, Dict, List, Optional


def parse_llm_json(text: str, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Extract and parse JSON from LLM response text.

    Handles common LLM output formats:
      - ```json { ... } ```
      - ``` { ... } ```
      - Raw JSON string
      - JSON with trailing text

    Args:
        text: Raw LLM response text
        fallback: Default dict if parsing fails (default: empty dict)

    Returns:
        Parsed dict, or fallback if parsing fails.

    Usage:
        from logosai.utils.text_utils import parse_llm_json

        result = parse_llm_json('```json\\n{"key": "value"}\\n```')
        # → {"key": "value"}
    """
    if fallback is None:
        fallback = {}

    if not text or not isinstance(text, str):
        return fallback

    text = text.strip()

    # 1. Try extracting from markdown code blocks: ```json ... ``` or ``` ... ```
    json_block = extract_json_block(text)
    if json_block:
        try:
            result = json.loads(json_block)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 2. Try parsing raw text as JSON directly
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 3. Try finding JSON object boundaries { ... }
    brace_match = re.search(r'\{[\s\S]*\}', text)
    if brace_match:
        try:
            result = json.loads(brace_match.group())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return fallback


def extract_json_block(text: str) -> Optional[str]:
    """
    Extract raw JSON string from markdown code blocks.

    Supports:
      - ```json { ... } ```
      - ``` { ... } ```

    Args:
        text: Text potentially containing markdown code blocks.

    Returns:
        Extracted JSON string, or None if not found.
    """
    if not text:
        return None

    # Match ```json ... ``` or ``` ... ``` (with optional language tag)
    pattern = r'```(?:json)?\s*\n?([\s\S]*?)\n?\s*```'
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()

    return None


def clean_markdown_code(text: str) -> str:
    """
    Remove markdown code fences from LLM response.

    Handles:
      - ```python ... ```
      - ```json ... ```
      - ``` ... ```
      - Leading/trailing whitespace

    Args:
        text: Text with potential markdown code fences.

    Returns:
        Cleaned text without code fences.
    """
    if not text:
        return ""

    text = text.strip()

    # Remove opening fence with optional language tag
    if text.startswith("```"):
        # Remove first line if it's just the fence
        first_newline = text.find("\n")
        if first_newline > 0:
            text = text[first_newline + 1:]
        else:
            text = text[3:]

    # Remove closing fence
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3]

    return text.strip()


def extract_code_block(text: str, language: str = "") -> Optional[str]:
    """
    Extract code block content for a specific language.

    Args:
        text: Text containing markdown code blocks.
        language: Language tag to match (e.g. "python", "json"). Empty matches any.

    Returns:
        Code block content, or None if not found.
    """
    if not text:
        return None

    if language:
        pattern = rf'```{re.escape(language)}\s*\n([\s\S]*?)\n\s*```'
    else:
        pattern = r'```(?:\w*)\s*\n([\s\S]*?)\n\s*```'

    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()

    return None


def truncate_for_prompt(text: str, max_chars: int = 500, suffix: str = "...") -> str:
    """
    Truncate text for LLM prompt inclusion.

    Truncates at word boundary when possible.

    Args:
        text: Text to truncate.
        max_chars: Maximum character length.
        suffix: Suffix to append when truncated.

    Returns:
        Truncated text.
    """
    if not text or len(text) <= max_chars:
        return text or ""

    # Try to truncate at word boundary
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.7:
        truncated = truncated[:last_space]

    return truncated + suffix
