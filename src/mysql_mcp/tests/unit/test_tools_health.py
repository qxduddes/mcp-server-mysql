"""Tests for the health_check tool through a real FastMCP instance."""

import json

from mysql_mcp.tests.conftest import tool_text
from mysql_mcp.tests.fixtures.rows import query_result


async def test_health_check_healthy(health_mcp) -> None:
    mcp, mock_client, _ = health_mcp
    mock_client.ping.return_value = 2.5
    mock_client.execute.side_effect = [
        query_result([{"version": "8.4.0"}]),
        query_result(
            [
                {"Variable_name": "Uptime", "Value": "100"},
                {"Variable_name": "Threads_connected", "Value": "2"},
                {"Variable_name": "Questions", "Value": "7"},
            ]
        ),
    ]
    result = await mcp.call_tool("health_check", {})
    payload = json.loads(tool_text(result))
    assert payload["healthy"] is True
    assert payload["serverVersion"] == "8.4.0"


async def test_health_check_unhealthy_is_json_body(health_mcp) -> None:
    from mysql_mcp.errors import MySQLError

    mcp, mock_client, _ = health_mcp
    mock_client.ping.side_effect = MySQLError("Connection refused", errno=2003)
    result = await mcp.call_tool("health_check", {})
    payload = json.loads(tool_text(result))
    assert payload["healthy"] is False
    assert "Connection refused" in payload["error"]
