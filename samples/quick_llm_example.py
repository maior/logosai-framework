"""
quick_llm example — One-line LLM call, no setup needed.

Perfect for services that just need a quick LLM call without managing
agent lifecycle or client initialization.

Run:
    python quick_llm_example.py
"""

import asyncio
from logosai import quick_llm


async def main():
    # Simple call
    answer = await quick_llm("What is the capital of France?")
    print(f"Answer: {answer}")

    # With system prompt
    translation = await quick_llm(
        "Hello, how are you?",
        system_prompt="Translate the following text to Korean.",
        temperature=0.3,
    )
    print(f"Translation: {translation}")


if __name__ == "__main__":
    asyncio.run(main())
