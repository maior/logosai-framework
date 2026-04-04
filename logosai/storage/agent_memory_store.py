"""AgentMemoryStore — PostgreSQL-backed persistent memory for agents.

Each agent can store and recall memories (facts, experiences, patterns).
Memories are automatically injected into LLM context for relevant queries.

Storage: PostgreSQL (logosai schema, agent_memories table)
Search: Hybrid (embedding cosine similarity + keyword matching)
Fallback: In-memory dict (when DB unavailable)

Usage:
    store = AgentMemoryStore()
    await store.initialize()

    await store.store("weather_agent", "Seoul weather pattern",
                      "Spring in Seoul is usually 10-15°C with occasional rain",
                      importance=0.8, tags=["weather", "seoul"])

    # 의미 기반 검색 — "수도 기온"으로도 "Seoul weather" 찾음
    memories = await store.recall("weather_agent", "수도 기온", top_k=3)
"""

import os
import time
import json as _json
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
        self._embed_client = None  # Gemini embedding client (lazy)

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
                    embedding JSONB,
                    UNIQUE(agent_id, key)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_mem_agent ON agent_memories(agent_id);
                CREATE INDEX IF NOT EXISTS idx_agent_mem_time ON agent_memories(created_at);
            """)
            # 기존 테이블에 embedding 컬럼이 없으면 추가
            try:
                await conn.execute("""
                    ALTER TABLE agent_memories ADD COLUMN IF NOT EXISTS embedding JSONB
                """)
            except Exception:
                pass  # 이미 존재

    # ══════════════════════════════════════════════════════════
    # Embedding
    # ══════════════════════════════════════════════════════════

    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Gemini embedding API로 텍스트 임베딩 생성. 실패 시 None 반환."""
        try:
            if self._embed_client is None:
                import google.genai as genai
                api_key = os.getenv("GOOGLE_API_KEY", "")
                if not api_key:
                    return None
                self._embed_client = genai.Client(api_key=api_key)

            result = self._embed_client.models.embed_content(
                model="gemini-embedding-001",
                contents=text[:500],  # 임베딩 입력 제한
            )
            return result.embeddings[0].values
        except Exception as e:
            logger.debug(f"Embedding failed: {e}")
            return None

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """두 벡터의 코사인 유사도 계산 (0~1)."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

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
        now = time.time()
        tags_json = _json.dumps(tags or [])

        # 임베딩 생성 (비동기, 실패해도 저장은 진행)
        embedding = await self._get_embedding(f"{key}: {content}")
        embedding_json = _json.dumps(embedding) if embedding else None

        if self._pool:
            try:
                async with self._pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO agent_memories (agent_id, key, content, memory_type, importance, tags, created_at, last_accessed_at, embedding)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $7, $8::jsonb)
                        ON CONFLICT (agent_id, key) DO UPDATE SET
                            content = EXCLUDED.content,
                            importance = EXCLUDED.importance,
                            tags = EXCLUDED.tags,
                            access_count = agent_memories.access_count + 1,
                            last_accessed_at = EXCLUDED.last_accessed_at,
                            embedding = EXCLUDED.embedding
                    """, agent_id, key, content, memory_type, importance, tags_json, now, embedding_json)

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

        Hybrid search: embedding cosine similarity + keyword matching.
        "서울 날씨"로 검색하면 "수도 기온 정보"도 의미적으로 찾을 수 있음.

        Args:
            agent_id: Agent ID
            query: Search query (semantic + keyword hybrid)
            tags: Filter by tags (any match)
            top_k: Max results
            min_importance: Minimum importance threshold
        """
        if self._pool:
            try:
                async with self._pool.acquire() as conn:
                    # 1단계: 해당 에이전트의 메모리 전부 가져오기 (최대 100개)
                    rows = await conn.fetch("""
                        SELECT *,
                               importance * (1.0 / (1.0 + (extract(epoch from now()) - created_at) / 86400.0)) as base_score
                        FROM agent_memories
                        WHERE agent_id = $1 AND importance >= $2
                        ORDER BY base_score DESC
                        LIMIT 100
                    """, agent_id, min_importance)

                    results = [dict(r) for r in rows]

                    if query and results:
                        # 2단계: 키워드 매칭 스코어
                        keywords = [w.lower() for w in query.split() if len(w) >= 2]
                        for r in results:
                            kw_score = 0.0
                            text = f"{r['key']} {r['content']}".lower()
                            for kw in keywords:
                                if kw in text:
                                    kw_score += 1.0
                            r["keyword_score"] = kw_score / max(len(keywords), 1)

                        # 3단계: 임베딩 유사도 스코어
                        query_embedding = await self._get_embedding(query)
                        for r in results:
                            emb = r.get("embedding")
                            if query_embedding and emb:
                                # DB에서 JSONB로 저장된 embedding 파싱
                                if isinstance(emb, str):
                                    emb = _json.loads(emb)
                                r["semantic_score"] = self._cosine_similarity(query_embedding, emb)
                            else:
                                r["semantic_score"] = 0.0

                        # 4단계: 하이브리드 스코어 = base_score × (0.4×semantic + 0.4×keyword + 0.2)
                        for r in results:
                            sem = r["semantic_score"]
                            kw = r["keyword_score"]
                            base = r["base_score"]
                            # semantic이나 keyword 중 하나라도 매칭되면 가산
                            relevance = 0.4 * sem + 0.4 * kw + 0.2  # 0.2는 base 보장
                            r["hybrid_score"] = base * relevance

                        # 최소 하나라도 매칭된 것만 (semantic>0.3 OR keyword>0)
                        results = [
                            r for r in results
                            if r["semantic_score"] > 0.3 or r["keyword_score"] > 0
                        ]
                        results.sort(key=lambda r: r["hybrid_score"], reverse=True)

                    # Tag filter
                    if tags:
                        tag_set = set(t.lower() for t in tags)
                        results = [
                            r for r in results
                            if any(t.lower() in tag_set for t in _json.loads(r.get("tags", "[]")))
                        ]

                    results = results[:top_k]

                    # Update access count
                    for r in results:
                        await conn.execute(
                            "UPDATE agent_memories SET access_count = access_count + 1, last_accessed_at = $1 WHERE id = $2",
                            time.time(), r["id"],
                        )

                    return results
            except Exception as e:
                logger.warning(f"AgentMemoryStore recall failed: {e}")

        # Fallback (in-memory, keyword only)
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
