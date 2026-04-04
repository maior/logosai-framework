"""MemoryMixin — 영속 메모리 (PostgreSQL).

agent.py에서 분리. 사용하는 인스턴스 변수:
  self._memory_store: AgentMemoryStore (lazy)
  self.id: str
  self.logger: Logger
"""

from __future__ import annotations

import asyncio
from typing import Dict, Any, Optional, List


class MemoryMixin:
    """영속 메모리 — memorize, recall, forget."""

    def _init_memory(self):
        """__init__에서 호출. 메모리 관련 인스턴스 변수 초기화."""
        self._memory_store = None

    async def _ensure_memory(self):
        """Lazy-initialize memory store."""
        if self._memory_store is None:
            try:
                from ..storage.agent_memory_store import AgentMemoryStore
                self._memory_store = AgentMemoryStore.get()
                await self._memory_store.initialize()
            except Exception as e:
                self.logger.debug(f"Memory store unavailable: {e}")

    async def memorize(self, key: str, content: str, importance: float = -1, tags: List[str] = None):
        """Store a memory for this agent.

        If importance is not provided (-1), LLM auto-evaluates it.
        """
        await self._ensure_memory()
        if not self._memory_store:
            return

        if importance < 0:
            importance = await self._evaluate_memory_importance(key, content)

        await self._memory_store.store(self.id, key, content, importance=importance, tags=tags)

    async def _evaluate_memory_importance(self, key: str, content: str) -> float:
        """LLM auto-evaluates memory importance (0.0 - 1.0)."""
        try:
            llm = getattr(self, '_llm', None) or getattr(self, 'llm_client', None)
            if not llm:
                return 0.5

            import re
            resp = await asyncio.wait_for(llm.invoke(
                f"Rate the importance of this information for an AI agent on a scale of 0.0 to 1.0.\n\n"
                f"Key: {key}\nContent: {content}\n\n"
                f"Criteria:\n"
                f"- 0.9-1.0: Critical (user preferences, recurring errors, key facts)\n"
                f"- 0.7-0.8: Important (useful patterns, domain knowledge)\n"
                f"- 0.4-0.6: Moderate (general information)\n"
                f"- 0.1-0.3: Low (trivial, temporary)\n\n"
                f"Return ONLY a number between 0.0 and 1.0."
            ), timeout=5)
            text = resp.content if hasattr(resp, 'content') else str(resp)
            match = re.search(r'(\d+\.?\d*)', text.strip())
            if match:
                return max(0.0, min(1.0, float(match.group(1))))
        except Exception:
            pass
        return 0.5

    async def recall(self, query: str = "", tags: List[str] = None, top_k: int = 5) -> List[Dict]:
        """Recall relevant memories for this agent."""
        await self._ensure_memory()
        if self._memory_store:
            return await self._memory_store.recall(self.id, query=query, tags=tags, top_k=top_k)
        return []

    async def recall_as_context(self, query: str = "", top_k: int = 3) -> str:
        """Recall memories and format as LLM context string."""
        memories = await self.recall(query, top_k=top_k)
        if not memories:
            return ""
        lines = [f"- {m['key']}: {m['content']}" for m in memories]
        return "Relevant memories from past interactions:\n" + "\n".join(lines)

    async def forget(self, key: str):
        """Delete a specific memory."""
        await self._ensure_memory()
        if self._memory_store:
            await self._memory_store.forget(self.id, key)
