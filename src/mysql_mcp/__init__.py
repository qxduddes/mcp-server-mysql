"""mysql-mcp — security-hardened, read-only MySQL MCP server.

Python port of @nilsir/mcp-server-mysql v2.0.0 (TypeScript), restricted to the
read-only tool surface and hardened per the internal security audit (see
docs/SECURITY.md).

Public boundary:
- register_all_tools(mcp) — attach all 9 read-only tools to a FastMCP instance
- MySqlSettings / settings — pydantic-settings configuration singleton
- MySqlClient — the sole database I/O boundary
"""

from mysql_mcp.config import MySqlSettings, settings
from mysql_mcp.db import MySqlClient
from mysql_mcp.tools import register_all_tools

__all__ = ["MySqlClient", "MySqlSettings", "register_all_tools", "settings"]
