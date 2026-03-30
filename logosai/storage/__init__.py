"""LogosAI Local Storage — SQLite-backed persistence for personal use.

Provides lightweight, zero-config storage for:
- Agent learnings (L4)
- Session history
- Agent metrics

No external database required. Data stored in ~/.logosai/logosai.db
"""

from .local_store import LocalStore

__all__ = ["LocalStore"]
