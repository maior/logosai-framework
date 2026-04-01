"""Retry utilities for LogosAI agents.

@retry decorator with exponential backoff for LLM calls and tool execution.

Usage:
    from logosai.utils.retry import retry, RetryConfig

    @retry(max_retries=3, backoff_base=1.0)
    async def call_llm(prompt):
        return await llm.invoke(prompt)

    # Or with config
    @retry(config=RetryConfig(max_retries=3, retry_on=(TimeoutError, ConnectionError)))
    async def risky_operation():
        ...
"""

import asyncio
import functools
import time
from dataclasses import dataclass, field
from typing import Tuple, Type, Optional, Callable, Any

from loguru import logger


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 3
    backoff_base: float = 1.0          # seconds (doubles each retry)
    backoff_max: float = 10.0          # max delay between retries
    retry_on: Tuple[Type[Exception], ...] = (Exception,)
    non_retryable: Tuple[Type[Exception], ...] = (
        KeyboardInterrupt, SystemExit, NotImplementedError, TypeError, ValueError,
    )

    def is_retryable(self, error: Exception) -> bool:
        """Check if an error is retryable."""
        if isinstance(error, self.non_retryable):
            return False
        return isinstance(error, self.retry_on)

    def get_delay(self, attempt: int) -> float:
        """Exponential backoff delay."""
        delay = self.backoff_base * (2 ** attempt)
        return min(delay, self.backoff_max)


DEFAULT_CONFIG = RetryConfig()


def retry(
    max_retries: int = None,
    backoff_base: float = None,
    config: RetryConfig = None,
    on_retry: Callable = None,
):
    """Decorator: retry async functions with exponential backoff.

    Args:
        max_retries: Override default max retries
        backoff_base: Override default backoff base
        config: Full RetryConfig object
        on_retry: Callback(attempt, error) called before each retry

    Examples:
        @retry(max_retries=3)
        async def call_llm(prompt):
            ...

        @retry(config=RetryConfig(retry_on=(TimeoutError,)))
        async def fetch_data():
            ...
    """
    cfg = config or RetryConfig(
        max_retries=max_retries or DEFAULT_CONFIG.max_retries,
        backoff_base=backoff_base or DEFAULT_CONFIG.backoff_base,
    )

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(cfg.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt >= cfg.max_retries or not cfg.is_retryable(e):
                        raise
                    delay = cfg.get_delay(attempt)
                    logger.debug(
                        f"Retry {attempt+1}/{cfg.max_retries} for {func.__name__}: "
                        f"{type(e).__name__}: {str(e)[:80]} (delay={delay:.1f}s)"
                    )
                    if on_retry:
                        on_retry(attempt + 1, e)
                    await asyncio.sleep(delay)
            raise last_error
        return wrapper
    return decorator


async def retry_llm_json(
    llm,
    messages: list,
    max_retries: int = 2,
    **kwargs,
) -> str:
    """Retry LLM call with JSON re-prompting on parse failure.

    If LLM returns non-JSON, adds "Respond with valid JSON only" and retries.

    Args:
        llm: LLMClient instance
        messages: Message list
        max_retries: Max re-prompt attempts

    Returns:
        LLM response content string (hopefully valid JSON)
    """
    import json
    import re

    for attempt in range(max_retries + 1):
        try:
            if hasattr(llm, 'invoke_messages'):
                response = await asyncio.wait_for(
                    llm.invoke_messages(messages, **kwargs), timeout=15
                )
            else:
                response = await asyncio.wait_for(
                    llm.invoke(messages[-1]["content"] if messages else "", **kwargs), timeout=15
                )

            content = response.content if hasattr(response, 'content') else str(response)

            # Try to find JSON in response
            json_match = re.search(r'[\[{].*[}\]]', content, re.DOTALL)
            if json_match:
                json.loads(json_match.group())  # Validate
                return content  # Valid JSON found

            # No JSON — re-prompt
            if attempt < max_retries:
                messages.append({"role": "user", "content":
                    "Your response was not valid JSON. Please respond with ONLY a valid JSON object or array. "
                    "No markdown, no explanation, just JSON."
                })
                logger.debug(f"retry_llm_json: attempt {attempt+1}, re-prompting for JSON")
                continue

            return content  # Return as-is after all retries

        except asyncio.TimeoutError:
            if attempt < max_retries:
                logger.debug(f"retry_llm_json: timeout, retry {attempt+1}")
                await asyncio.sleep(1)
                continue
            raise
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(0.5)
                continue
            raise

    return ""
