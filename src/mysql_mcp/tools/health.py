"""Health tool — database connectivity and server status."""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from mysql_mcp.services.health import HealthService
from mysql_mcp.tools._utils import execute_tool


def register_health_tools(mcp: FastMCP) -> None:
    """Attach the health_check tool to the given FastMCP server."""

    @mcp.tool(
        title="Check database health",
        annotations={"title": "Check database health", "readOnlyHint": True},
    )
    async def health_check(
        db_id: Annotated[
            str,
            Field(
                description=(
                    "Optional named database profile configured on the server. "
                    "Omit to use the server's default connection."
                )
            ),
        ] = "",
    ) -> str:
        """Check MySQL connection health and basic server status.

        Use this tool when the user asks whether the database is reachable,
        what version it runs, or when queries are unexpectedly failing.
        Returns JSON: {healthy, pingLatencyMs, serverVersion, uptime,
        threadsConnected, totalQueries} — or {healthy: false, error} when the
        server cannot be reached.

        Presentation: never mention this tool's name to the user or announce
        that a tool is being called — answer directly with the status.

        Preferred rendering — card-based layout: a status card with a
        green/red health badge, plus a compact metrics card (latency, version,
        uptime, connections).

        Fallback — Markdown: one-line status first ("healthy, 3 ms latency"),
        then bold-labeled key metrics.

        Formatting rules (both modes): render uptime in human units (days/
        hours); never paste raw JSON unless explicitly asked.
        """
        return await execute_tool(
            "health_check",
            db_id,
            lambda client: HealthService(client).check(),
            operation="HEALTH_CHECK",
            target=db_id or "default",
        )
