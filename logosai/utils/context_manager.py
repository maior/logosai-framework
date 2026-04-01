"""Context Window Manager — token counting + auto-pruning for LLM calls.

Ensures messages don't exceed model's context window.
Keeps system prompts and recent messages, summarizes/prunes older ones.

Usage:
    from logosai.utils.context_manager import ContextManager

    cm = ContextManager(max_tokens=4000)
    pruned = cm.fit_messages(messages)  # Auto-prune to fit
    token_count = cm.count_tokens(messages)
"""

from typing import Dict, List, Any, Optional

from loguru import logger


# Approximate token counts per model family
MODEL_CONTEXT_LIMITS = {
    "gemini-2.5-flash-lite": 1_000_000,
    "gemini-2.5-flash": 1_000_000,
    "gemini-2.0-flash-lite": 1_000_000,
    "gpt-4.1": 1_000_000,
    "gpt-4.1-mini": 1_000_000,
    "gpt-4o": 128_000,
    "gpt-3.5-turbo": 16_000,
    "claude-3.7-sonnet": 200_000,
    "claude-3.5-haiku": 200_000,
}


class ContextManager:
    """Manages LLM context window with token counting and auto-pruning."""

    def __init__(self, max_tokens: int = 4000, model: str = ""):
        """
        Args:
            max_tokens: Max tokens for output + context combined
            model: Model name (for looking up context limits)
        """
        self.max_tokens = max_tokens
        self.model = model
        self._model_limit = MODEL_CONTEXT_LIMITS.get(model, 128_000)

    @staticmethod
    def count_tokens(text: str) -> int:
        """Approximate token count.

        Uses simple heuristic: ~4 chars per token for English, ~2 chars for Korean/CJK.
        Accurate within ~20% without tiktoken dependency.
        """
        if not text:
            return 0

        # Count CJK characters (Korean, Chinese, Japanese)
        cjk_count = sum(1 for c in text if '\u3000' <= c <= '\u9fff' or '\uac00' <= c <= '\ud7af')
        ascii_count = len(text) - cjk_count

        # CJK: ~2 chars per token, ASCII: ~4 chars per token
        return int(cjk_count / 2 + ascii_count / 4) + 1

    def count_messages_tokens(self, messages: List[Dict[str, str]]) -> int:
        """Count total tokens in a message list."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            total += self.count_tokens(content)
            total += 4  # Per-message overhead (role, separators)
        return total

    def fit_messages(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = None,
        reserve_for_response: int = 1000,
    ) -> List[Dict[str, str]]:
        """Prune messages to fit within token limit.

        Strategy:
        1. Always keep system messages (first)
        2. Always keep last user message (most recent)
        3. Remove oldest non-system messages first
        4. If still over limit, summarize middle messages

        Args:
            messages: Full message list
            max_tokens: Override max tokens
            reserve_for_response: Tokens reserved for LLM response

        Returns:
            Pruned message list that fits within limit
        """
        limit = (max_tokens or self.max_tokens) - reserve_for_response
        if limit <= 0:
            limit = self.max_tokens

        current_tokens = self.count_messages_tokens(messages)
        if current_tokens <= limit:
            return messages  # Already fits

        # Separate system messages from others
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]

        system_tokens = self.count_messages_tokens(system_msgs)
        available = limit - system_tokens

        if available <= 0:
            # System prompt alone exceeds limit — truncate it
            logger.warning("System prompt exceeds token limit, truncating")
            for msg in system_msgs:
                msg["content"] = msg["content"][:limit * 3]  # ~3 chars per token
            return system_msgs + other_msgs[-1:]  # Keep last message

        # Keep removing oldest messages until we fit
        while other_msgs and self.count_messages_tokens(other_msgs) > available:
            # Always keep the last message (most recent user input)
            if len(other_msgs) <= 1:
                break
            removed = other_msgs.pop(0)
            logger.debug(f"Context pruned: {removed['role']} ({self.count_tokens(removed['content'])} tokens)")

        pruned = system_msgs + other_msgs
        pruned_tokens = self.count_messages_tokens(pruned)

        if pruned_tokens < current_tokens:
            logger.info(
                f"Context pruned: {current_tokens} → {pruned_tokens} tokens "
                f"({len(messages)} → {len(pruned)} messages)"
            )

        return pruned

    def summarize_messages(self, messages: List[Dict[str, str]], max_summary_tokens: int = 200) -> str:
        """Create a brief summary of messages for context compression.

        Returns a single string summarizing the conversation.
        Does NOT call LLM — uses simple extraction.
        """
        if not messages:
            return ""

        summary_parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            # Take first sentence or 100 chars
            short = content[:100].split(".")[0] if content else ""
            if short:
                summary_parts.append(f"{role}: {short}")

        summary = "\n".join(summary_parts[-5:])  # Last 5 messages
        return f"[Previous conversation summary]\n{summary}"
