"""LocalStore — SQLite-backed persistence for personal LogosAI.

Single-file database at ~/.logosai/logosai.db.
Thread-safe, async-compatible, zero-config.

Usage:
    store = LocalStore()
    await store.initialize()

    # Learnings
    await store.save_learning("agent_id", "pattern", "solution", confidence=0.9, tags=["gmail"])
    learnings = await store.get_learnings(tags=["gmail"])

    # Sessions
    await store.save_message(session_id, agent_id, query, response)
    history = await store.get_session_history(session_id)

    # Metrics
    await store.log_agent_call(agent_id, query, success=True, duration_ms=150)
    stats = await store.get_agent_stats()
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

# Default database location
DEFAULT_DB_DIR = os.path.expanduser("~/.logosai")
DEFAULT_DB_PATH = os.path.join(DEFAULT_DB_DIR, "logosai.db")


class LocalStore:
    """SQLite-backed local storage for personal LogosAI."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    async def initialize(self):
        """Create database and tables if they don't exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        logger.info(f"LocalStore initialized: {self.db_path}")

    def _create_tables(self):
        c = self._conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_agent TEXT NOT NULL,
                pattern TEXT NOT NULL,
                solution TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                tags TEXT DEFAULT '[]',
                created_at REAL NOT NULL,
                usage_count INTEGER DEFAULT 0,
                UNIQUE(source_agent, pattern)
            );

            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_session_id ON session_messages(session_id);

            CREATE TABLE IF NOT EXISTS agent_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                query TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 1,
                duration_ms INTEGER DEFAULT 0,
                error TEXT DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_calls_agent ON agent_calls(agent_id);
            CREATE INDEX IF NOT EXISTS idx_agent_calls_time ON agent_calls(created_at);
        """)
        c.commit()

    def _ensure_conn(self):
        if not self._conn:
            raise RuntimeError("LocalStore not initialized. Call await store.initialize() first.")

    # ══════════════════════════════════════════════════════════
    # Learnings (L4)
    # ══════════════════════════════════════════════════════════

    async def save_learning(
        self,
        source_agent: str,
        pattern: str,
        solution: str,
        confidence: float = 0.5,
        tags: List[str] = None,
    ) -> int:
        """Save or update a learning entry. Returns row ID."""
        self._ensure_conn()
        tags_json = json.dumps(tags or [])
        now = time.time()
        try:
            self._conn.execute(
                """INSERT INTO learnings (source_agent, pattern, solution, confidence, tags, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_agent, pattern) DO UPDATE SET
                     solution = excluded.solution,
                     confidence = excluded.confidence,
                     tags = excluded.tags,
                     usage_count = usage_count + 1""",
                (source_agent, pattern, solution, confidence, tags_json, now),
            )
            self._conn.commit()
            return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        except Exception as e:
            logger.warning(f"Failed to save learning: {e}")
            return -1

    async def get_learnings(
        self,
        source_agent: str = None,
        tags: List[str] = None,
        min_confidence: float = 0.0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query learnings with optional filters."""
        self._ensure_conn()
        query = "SELECT * FROM learnings WHERE confidence >= ?"
        params: list = [min_confidence]

        if source_agent:
            query += " AND source_agent = ?"
            params.append(source_agent)

        query += " ORDER BY usage_count DESC, confidence DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        results = [dict(r) for r in rows]

        # Filter by tags (JSON array overlap)
        if tags:
            tag_set = set(tags)
            results = [
                r for r in results
                if tag_set & set(json.loads(r.get("tags", "[]")))
            ]

        return results

    # ══════════════════════════════════════════════════════════
    # Session History
    # ══════════════════════════════════════════════════════════

    async def save_message(
        self,
        session_id: str,
        agent_id: str,
        content: str,
        role: str = "user",
    ):
        """Save a message to session history."""
        self._ensure_conn()
        self._conn.execute(
            "INSERT INTO session_messages (session_id, agent_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, agent_id, role, content, time.time()),
        )
        self._conn.commit()

    async def get_session_history(
        self, session_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get message history for a session."""
        self._ensure_conn()
        rows = self._conn.execute(
            "SELECT * FROM session_messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    async def list_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent sessions with last message preview."""
        self._ensure_conn()
        rows = self._conn.execute(
            """SELECT session_id,
                      MAX(created_at) as last_activity,
                      COUNT(*) as message_count,
                      MIN(content) as first_message
               FROM session_messages
               GROUP BY session_id
               ORDER BY last_activity DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════
    # Agent Metrics
    # ══════════════════════════════════════════════════════════

    async def log_agent_call(
        self,
        agent_id: str,
        query: str,
        success: bool = True,
        duration_ms: int = 0,
        error: str = "",
    ):
        """Log an agent call for metrics."""
        self._ensure_conn()
        self._conn.execute(
            "INSERT INTO agent_calls (agent_id, query, success, duration_ms, error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, query[:500], int(success), duration_ms, error[:300], time.time()),
        )
        self._conn.commit()

        # Auto-cleanup: keep last 10K calls
        self._conn.execute(
            "DELETE FROM agent_calls WHERE id NOT IN (SELECT id FROM agent_calls ORDER BY id DESC LIMIT 10000)"
        )

    async def get_agent_stats(self, agent_id: str = None) -> Dict[str, Any]:
        """Get success/failure stats per agent."""
        self._ensure_conn()
        query = """
            SELECT agent_id,
                   COUNT(*) as total,
                   SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
                   SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count,
                   ROUND(AVG(duration_ms)) as avg_duration_ms
            FROM agent_calls
        """
        params = []
        if agent_id:
            query += " WHERE agent_id = ?"
            params.append(agent_id)
        query += " GROUP BY agent_id ORDER BY total DESC"

        rows = self._conn.execute(query, params).fetchall()
        stats = {}
        for r in rows:
            d = dict(r)
            d["success_rate"] = round(d["success_count"] / d["total"] * 100, 1) if d["total"] > 0 else 0
            stats[d["agent_id"]] = d
        return stats

    # ══════════════════════════════════════════════════════════
    # Lifecycle
    # ══════════════════════════════════════════════════════════

    async def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def is_initialized(self) -> bool:
        return self._conn is not None
