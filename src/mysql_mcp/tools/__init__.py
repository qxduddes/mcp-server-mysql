"""Interface layer — the only package that imports FastMCP.

Tools are nested functions inside register_*_tools() and are not importable
from outside; register them on a FastMCP instance via register_all_tools().
"""

from fastmcp import FastMCP

from mysql_mcp.tools.health import register_health_tools
from mysql_mcp.tools.query import register_query_tools
from mysql_mcp.tools.schema import register_schema_tools

__all__ = ["register_all_tools"]


def register_all_tools(mcp: FastMCP) -> None:
    """Register all 9 read-only tools."""
    register_query_tools(mcp)
    register_schema_tools(mcp)
    register_health_tools(mcp)
