"""AgentMemoryStore — PostgreSQL-backed persistent memory for agents.

Each agent can store and recall memories (facts, experiences, patterns).
Memories are automatically injected into LLM context for relevant queries.

Storage: PostgreSQL (logosai schema, agent_memories table)
Fallback: In-memory dict (when DB unavailable)

Usage:
    store = AgentMemoryStore()
    await store.initialize()

    await store.store("weather_agent", "Seoul weather pattern",
                      "Spring in Seoul is usually 10-15°C with occasional rain",
                      importance=0.8, tags=["weather", "seoul"])

    memories = await store.recall("weather_agent", "Seoul weather", top_k=3)
"""

import os
import time
from typing import Any, Dict, List, Optional

from loguru import logger


class AgentMemoryStore:
    """PostgreSQL-backed agent memory with in-memory fallback."""

    _instance = None

    @classmethod
    def get(cls) -> 'AgentMemoryStore':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, db_url: str = None):
        # Try env vars, then .env file
        self.db_url = db_url or os.getenv("LOGOSAI_DB_URL", "") or os.getenv("DATABASE_URL", "")
        if not self.db_url:
            # Try loading from .env files
            for env_path in [
                os.path.join(os.getcwd(), ".env"),
                os.path.join(os.path.dirname(__file__), "../../../.env"),  # logosai/.env
                os.path.expanduser("~/.logosai/.env"),
            ]:
                if os.path.exists(env_path):
                    try:
                        with open(env_path) as f:
                            for line in f:
                                line = line.strip()
                                if line.startswith("LOGOSAI_DB_URL=") or line.startswith("DATABASE_URL="):
                                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                                    if "postgresql" in val:
                                        self.db_url = val
                                        break
                    except Exception:
                        pass
                if self.db_url:
                    break
        self._pool = None
        self._fallback: Dict[str, List[Dict]] = {}  # agent_id → memories
        self._initialized = False

    async def initialize(self):
        """Create table and connection pool."""
        if self._initialized:
            return

        # Try PostgreSQL
        if self.db_url and "postgresql" in self.db_url:
            try:
                import asyncpg
                # Convert SQLAlchemy URL to asyncpg format
                url = self.db_url.replace("postgresql+asyncpg://", "postgresql://")
                self._pool = await asyncpg.create_pool(url, min_size=1, max_size=3, timeout=10)
                await self._create_table()
                self._initialized = True
                logger.info(f"AgentMemoryStore: PostgreSQL connected")
                return
            except Exception as e:
                logger.warning(f"AgentMemoryStore: PostgreSQL failed ({e}), using in-memory fallback")

        # Fallback: in-memory
        self._initialized = True
        logger.info("AgentMemoryStore: using in-memory fallback")

    async def _create_table(self):
        """Create agent_memories table if not exists."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_memories (
                    id SERIAL PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    memory_type TEXT DEFAULT 'fact',
                    importance REAL DEFAULT 0.5,
                    tags TEXT DEFAULT '[]',
                    access_count INTEGER DEFAULT 0,
                    created_at DOUBLE PRECISION NOT NULL,
                    last_accessed_at DOUBLE PRECISION,
                    UNIQUE(agent_id, key)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_mem_agent ON agent_memories(agent_id);
                CREATE INDEX IF NOT EXISTS idx_agent_mem_time ON agent_memories(created_at);
            """)

    # ══════════════════════════════════════════════════════════
    # Store
    # ══════════════════════════════════════════════════════════

    async def store(
        self,
        agent_id: str,
        key: str,
        content: str,
        memory_type: str = "fact",
        importance: float = 0.5,
        tags: List[str] = None,
    ) -> bool:
        """Store or update a memory.

        Args:
            agent_id: Which agent owns this memory
            key: Short identifier (dedup key)
            content: Full memory content
            memory_type: fact, experience, pattern, preference
            importance: 0.0-1.0 (higher = more important)
            tags: Searchable tags
        """
        import json
        now = time.time()
        tags_json = json.dumps(tags or [])

        if self._pool:
            try:
                async with self._pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO agent_memories (agent_id, key, content, memory_type, importance, tags, created_at, last_accessed_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                        ON CONFLICT (agent_id, key) DO UPDATE SET
                            content = EXCLUDED.content,
                            importance = EXCLUDED.importance,
                            tags = EXCLUDED.tags,
                            access_count = agent_memories.access_count + 1,
                            last_accessed_at = EXCLUDED.last_accessed_at
                    """, agent_id, key, content, memory_type, importance, tags_json, now)

                # Capacity management: max 100 memories per agent
                await self._enforce_capacity(conn, agent_id, max_per_agent=100)
                return True
            except Exception as e:
                logger.warning(f"AgentMemoryStore store failed: {e}")

        # Fallback
        if agent_id not in self._fallback:
            self._fallback[agent_id] = []
        # Dedup
        self._fallback[agent_id] = [m for m in self._fallback[agent_id] if m["key"] != key]
        self._fallback[agent_id].append({
            "key": key, "content": content, "memory_type": memory_type,
            "importance": importance, "tags": tags or [], "created_at": now,
            "access_count": 0,
        })
        # Limit per agent
        if len(self._fallback[agent_id]) > 100:
            self._fallback[agent_id] = sorted(
                self._fallback[agent_id], key=lambda m: m["importance"], reverse=True
            )[:100]
        return True

    # ══════════════════════════════════════════════════════════
    # Recall
    # ══════════════════════════════════════════════════════════

    async def recall(
        self,
        agent_id: str,
        query: str = "",
        tags: List[str] = None,
        top_k: int = 5,
        min_importance: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Recall relevant memories for an agent.

        Search by keyword matching in key+content, filtered by tags and importance.
        Results sorted by importance × recency.

        Args:
            agent_id: Agent ID
            query: Search query (keyword match in key and content)
            tags: Filter by tags (any match)
            top_k: Max results
            min_importance: Minimum importance threshold
        """
        import json

        if self._pool:
            try:
                async with self._pool.acquire() as conn:
                    # Keyword search in key + content
                    if query:
                        # Split query into keywords and match ANY keyword
                        keywords = [w for w in query.split() if len(w) >= 2]
                        if keywords:
                            # Build OR conditions for each keyword
                            conditions = " OR ".join([
                                f"(key ILIKE '%' || ${i+3} || '%' OR content ILIKE '%' || ${i+3} || '%')"
                                for i in range(len(keywords))
                            ])
                            sql = f"""
                                SELECT *,
                                       importance * (1.0 / (1.0 + (extract(epoch from now()) - created_at) / 86400.0)) as score
                                FROM agent_memories
                                WHERE agent_id = $1
                                  AND importance >= $2
                                  AND ({conditions})
                                ORDER BY score DESC
                                LIMIT ${len(keywords)+3}
                            """
                            rows = await conn.fetch(sql, agent_id, min_importance, *keywords, top_k)
                        else:
                            rows = []
                    else:
                        rows = await conn.fetch("""
                            SELECT *,
                                   importance * (1.0 / (1.0 + (extract(epoch from now()) - created_at) / 86400.0)) as score
                            FROM agent_memories
                            WHERE agent_id = $1 AND importance >= $2
                            ORDER BY score DESC
                            LIMIT $3
                        """, agent_id, min_importance, top_k)

                    results = [dict(r) for r in rows]

                    # Tag filter
                    if tags:
                        tag_set = set(t.lower() for t in tags)
                        results = [
                            r for r in results
                            if any(t.lower() in tag_set for t in json.loads(r.get("tags", "[]")))
                        ]

                    # Update access count
                    for r in results:
                        await conn.execute(
                            "UPDATE agent_memories SET access_count = access_count + 1, last_accessed_at = $1 WHERE id = $2",
                            time.time(), r["id"],
                        )

                    return results[:top_k]
            except Exception as e:
                logger.warning(f"AgentMemoryStore recall failed: {e}")

        # Fallback
        memories = self._fallback.get(agent_id, [])
        if query:
            q = query.lower()
            memories = [m for m in memories if q in m["key"].lower() or q in m["content"].lower()]
        if tags:
            tag_set = set(t.lower() for t in tags)
            memories = [m for m in memories if any(t.lower() in tag_set for t in m.get("tags", []))]
        memories = [m for m in memories if m.get("importance", 0) >= min_importance]
        memories.sort(key=lambda m: m.get("importance", 0), reverse=True)
        return memories[:top_k]

    # ══════════════════════════════════════════════════════════
    # Forget
    # ══════════════════════════════════════════════════════════

    async def forget(self, agent_id: str, key: str) -> bool:
        """Delete a specific memory."""
        if self._pool:
            try:
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM agent_memories WHERE agent_id = $1 AND key = $2",
                        agent_id, key,
                    )
                return True
            except Exception as e:
                logger.warning(f"AgentMemoryStore forget failed: {e}")

        if agent_id in self._fallback:
            self._fallback[agent_id] = [m for m in self._fallback[agent_id] if m["key"] != key]
        return True

    # ══════════════════════════════════════════════════════════
    # Stats
    # ══════════════════════════════════════════════════════════

    async def get_stats(self, agent_id: str = None) -> Dict[str, Any]:
        """Get memory statistics."""
        if self._pool:
            try:
                async with self._pool.acquire() as conn:
                    if agent_id:
                        row = await conn.fetchrow(
                            "SELECT COUNT(*) as count, AVG(importance) as avg_importance FROM agent_memories WHERE agent_id = $1",
                            agent_id,
                        )
                        return {"agent_id": agent_id, "count": row["count"], "avg_importance": float(row["avg_importance"] or 0)}
                    else:
                        rows = await conn.fetch(
                            "SELECT agent_id, COUNT(*) as count FROM agent_memories GROUP BY agent_id ORDER BY count DESC"
                        )
                        return {"agents": {r["agent_id"]: r["count"] for r in rows}, "total": sum(r["count"] for r in rows)}
            except Exception:
                pass

        # Fallback
        if agent_id:
            mems = self._fallback.get(agent_id, [])
            return {"agent_id": agent_id, "count": len(mems)}
        return {"agents": {k: len(v) for k, v in self._fallback.items()}}

    async def _enforce_capacity(self, conn, agent_id: str, max_per_agent: int = 100):
        """Delete lowest-importance memories if agent exceeds capacity."""
        try:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM agent_memories WHERE agent_id = $1", agent_id
            )
            if count > max_per_agent:
                # Delete excess — keep highest importance, most recently accessed
                excess = count - max_per_agent
                await conn.execute("""
                    DELETE FROM agent_memories WHERE id IN (
                        SELECT id FROM agent_memories
                        WHERE agent_id = $1
                        ORDER BY importance ASC, last_accessed_at ASC NULLS FIRST
                        LIMIT $2
                    )
                """, agent_id, excess)
                logger.info(f"AgentMemoryStore: pruned {excess} low-importance memories for {agent_id}")
        except Exception as e:
            logger.debug(f"Capacity enforcement failed: {e}")

    async def close(self):
        if self._pool:
            await self._pool.close()
