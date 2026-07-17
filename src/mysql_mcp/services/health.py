"""Health service — connection liveness and server status.

Faithful to the TS health_check: failures return a JSON body with
``healthy: false`` rather than raising, so the model can report degraded
state naturally.
"""

import logging
from typing import Any

from mysql_mcp.db import MySqlClient
from mysql_mcp.errors import MySqlMcpError

logger = logging.getLogger(__name__)


class HealthService:
    """Pings the target MySQL server and gathers basic status counters."""

    def __init__(self, client: MySqlClient) -> None:
        self._client = client

    async def check(self) -> dict[str, Any]:
        try:
            latency_ms = await self._client.ping()
            version_result = await self._client.execute("SELECT VERSION() AS version")
            status_result = await self._client.execute(
                "SHOW STATUS WHERE Variable_name IN "
                "('Uptime', 'Threads_connected', 'Questions')"
            )
        except MySqlMcpError as exc:
            logger.warning("health_check failed: %s", exc)
            return {"healthy": False, "error": str(exc)}
        status = {str(row["Variable_name"]): row["Value"] for row in status_result.rows}
        version = version_result.rows[0]["version"] if version_result.rows else None
        return {
            "healthy": True,
            "pingLatencyMs": round(latency_ms, 2),
            "serverVersion": version,
            "uptime": status.get("Uptime"),
            "threadsConnected": status.get("Threads_connected"),
            "totalQueries": status.get("Questions"),
        }
