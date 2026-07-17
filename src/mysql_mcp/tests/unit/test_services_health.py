"""Tests for HealthService."""

from mysql_mcp.errors import MySQLError
from mysql_mcp.tests.fixtures.rows import query_result


async def test_check_healthy(health_service, mock_client) -> None:
    mock_client.ping.return_value = 3.14159
    mock_client.execute.side_effect = [
        query_result([{"version": "8.4.0"}]),
        query_result(
            [
                {"Variable_name": "Uptime", "Value": "86400"},
                {"Variable_name": "Threads_connected", "Value": "5"},
                {"Variable_name": "Questions", "Value": "1234"},
            ]
        ),
    ]
    result = await health_service.check()
    assert result == {
        "healthy": True,
        "pingLatencyMs": 3.14,
        "serverVersion": "8.4.0",
        "uptime": "86400",
        "threadsConnected": "5",
        "totalQueries": "1234",
    }


async def test_check_unhealthy_returns_json_not_raise(health_service, mock_client) -> None:
    mock_client.ping.side_effect = MySQLError("Connection refused", errno=2003)
    result = await health_service.check()
    assert result["healthy"] is False
    assert "Connection refused" in result["error"]
