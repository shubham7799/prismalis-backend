"""
Entry point: python mcp_server.py

Self-contained regardless of working directory:
  - resolves the project root from __file__
  - loads .env from that root before any app imports
  - adds the root to sys.path so `app.*` imports work from anywhere
"""

import sys
from pathlib import Path

# ── Bootstrap ─────────────────────────────────────────────────────────────────
# Must happen before any app.* import so env vars are set before config reads them.

_ROOT = Path(__file__).parent.resolve()

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv          # noqa: E402 (must be after sys.path fix)
load_dotenv(_ROOT / ".env", override=False)

# ── MCP server ────────────────────────────────────────────────────────────────

import app.mcp.tools                    # noqa: F401, E402 — registers all tools
from app.mcp.server import mcp          # noqa: E402

if __name__ == "__main__":
    mcp.run()
