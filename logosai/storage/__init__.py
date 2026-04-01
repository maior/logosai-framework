"""LogosAI Storage — persistent storage for agents.

- LocalStore: SQLite-backed (personal mode, pip install logosai)
- AgentMemoryStore: PostgreSQL-backed (dev/production)
"""

try:
    from .local_store import LocalStore
except ImportError:
    LocalStore = None

try:
    from .agent_memory_store import AgentMemoryStore
except ImportError:
    AgentMemoryStore = None

__all__ = [x for x in ["LocalStore", "AgentMemoryStore"] if x is not None]
