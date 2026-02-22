"""
LogosAI ACP (Agent Collaboration Protocol) Module

Provides server and client components for agent communication:
  - SimpleACPServer: Dead-simple multi-agent server (v0.9.0, recommended)
  - ACPServer: Advanced single-agent server with auth & stats
  - ACPClient: Client for connecting to ACP servers
"""

import logging

logger = logging.getLogger(__name__)

__version__ = "1.1.0"

# === SimpleACPServer (v0.9.0 — recommended) ===
try:
    from .simple_server import SimpleACPServer
except ImportError as e:
    logger.debug(f"SimpleACPServer not available: {e}")

    class SimpleACPServer:  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            raise ImportError("aiohttp is required. Install: pip install aiohttp")

# === ACPServer (advanced) ===
try:
    from .server import ACPServer
except ImportError as e:
    logger.debug(f"ACPServer not available: {e}")

    class ACPServer:  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            raise ImportError("ACP server dependencies not available.")

# === ACPClient ===
try:
    from .client import ACPClient, create_client
except ImportError as e:
    logger.debug(f"ACPClient not available: {e}")

    class ACPClient:  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            raise ImportError("ACP client dependencies not available.")

    def create_client(*a, **kw):
        raise ImportError("ACP client dependencies not available.")

__all__ = ["SimpleACPServer", "ACPServer", "ACPClient", "create_client", "__version__"] 