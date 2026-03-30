"""LogosAI CLI — Personal AI agent framework.

Usage:
    logosai init                  Initialize ~/.logosai/ with config and database
    logosai serve [--port 9000]   Start agent server
    logosai status                Show agent server status
    logosai agents                List registered agents
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

LOGOSAI_DIR = os.path.expanduser("~/.logosai")
CONFIG_PATH = os.path.join(LOGOSAI_DIR, "config.json")
DB_PATH = os.path.join(LOGOSAI_DIR, "logosai.db")

DEFAULT_CONFIG = {
    "mode": "personal",
    "version": "0.12.0",
    "llm": {
        "provider": "google",
        "model": "gemini-2.5-flash-lite",
    },
    "server": {
        "host": "localhost",
        "port": 9000,
    },
    "storage": {
        "type": "sqlite",
        "path": DB_PATH,
    },
}


def cmd_init(args):
    """Initialize LogosAI personal environment."""
    os.makedirs(LOGOSAI_DIR, exist_ok=True)

    if os.path.exists(CONFIG_PATH) and not args.force:
        print(f"Already initialized: {CONFIG_PATH}")
        print("Use --force to reinitialize.")
        return

    with open(CONFIG_PATH, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)

    # Initialize SQLite database
    async def _init_db():
        from logosai.storage import LocalStore
        store = LocalStore(DB_PATH)
        await store.initialize()
        await store.close()

    asyncio.run(_init_db())

    print(f"""
LogosAI initialized!

  Config: {CONFIG_PATH}
  Database: {DB_PATH}

Quick start:
  1. Set your API key:
     export GOOGLE_API_KEY=your-key

  2. Create an agent:
     from logosai import agent, AgentResponse

     @agent(name="My Agent", description="Does something cool")
     async def my_agent(query, context=None, llm=None):
         response = await llm.invoke(f"Help with: {{query}}")
         return AgentResponse.success(content={{"answer": response.content}})

  3. Start server:
     logosai serve
""")


def cmd_serve(args):
    """Start LogosAI agent server."""
    from logosai.cli.serve import main as serve_main
    sys.argv = ["logosai-serve", "--port", str(args.port)]
    serve_main()


def cmd_status(args):
    """Show status."""
    print(f"LogosAI Personal v0.12.0")
    print(f"  Config: {CONFIG_PATH} {'(exists)' if os.path.exists(CONFIG_PATH) else '(not initialized)'}")
    print(f"  Database: {DB_PATH} {'(exists)' if os.path.exists(DB_PATH) else '(not initialized)'}")

    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        print(f"  Mode: {config.get('mode', 'unknown')}")
        print(f"  LLM: {config.get('llm', {}).get('provider', '?')}/{config.get('llm', {}).get('model', '?')}")

    # Check API keys
    for key_name in ["GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
        val = os.environ.get(key_name, "")
        status = f"***{val[-4:]}" if val else "(not set)"
        print(f"  {key_name}: {status}")

    if os.path.exists(DB_PATH):
        size = os.path.getsize(DB_PATH)
        print(f"  DB size: {size / 1024:.1f} KB")


def cmd_agents(args):
    """List agents (requires running server)."""
    import requests
    port = args.port
    try:
        resp = requests.post(
            f"http://localhost:{port}/jsonrpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "list_agents"},
            timeout=3,
        )
        data = resp.json()
        agents = data.get("result", {}).get("agents", [])
        print(f"Agents on localhost:{port}: {len(agents)}")
        for a in agents:
            name = a.get("name", a.get("id", "?"))
            desc = a.get("description", "")[:60]
            print(f"  - {name}: {desc}")
    except Exception:
        print(f"Cannot connect to localhost:{port}. Is the server running?")
        print("  Start with: logosai serve")


def main():
    parser = argparse.ArgumentParser(
        prog="logosai",
        description="LogosAI — Personal AI agent framework",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize personal environment")
    p_init.add_argument("--force", action="store_true", help="Reinitialize")

    # serve
    p_serve = sub.add_parser("serve", help="Start agent server")
    p_serve.add_argument("--port", type=int, default=9000)

    # status
    sub.add_parser("status", help="Show status")

    # agents
    p_agents = sub.add_parser("agents", help="List registered agents")
    p_agents.add_argument("--port", type=int, default=9000)

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "agents":
        cmd_agents(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
