"""Tests for the MySqlClient database boundary (aiomysql fully mocked)."""

import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pymysql
import pytest

from mysql_mcp.config import ConnectionParams
from mysql_mcp.db import MySqlClient, build_ssl_context
from mysql_mcp.errors import MySQLError
from mysql_mcp.tests.fixtures.rows import USERS_ROWS

# db tests actually open (mocked) connections, so use a loopback host — remote
# hosts without TLS are refused by design (SEC-010, tested separately below).
LOCAL_PARAMS = ConnectionParams(
    host="127.0.0.1", port=3306, user="mcp_ro", password="secret-pw", database="app_db"
)


def _mock_connection(rows: list[dict]) -> tuple[MagicMock, AsyncMock]:
    """Build a mock aiomysql connection whose cursor returns the given rows."""
    cursor = AsyncMock()
    cursor.fetchall.return_value = rows
    cursor.fetchmany.return_value = rows
    cursor_cm = MagicMock()
    cursor_cm.__aenter__ = AsyncMock(return_value=cursor)
    cursor_cm.__aexit__ = AsyncMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cursor_cm
    conn.close = MagicMock()
    conn.ping = AsyncMock()
    conn.get_server_info = MagicMock(return_value="8.4.0")  # MySQL banner by default
    return conn, cursor


def _client(**kwargs) -> MySqlClient:
    defaults = {"connect_timeout": 10, "query_timeout_ms": 10_000, "max_rows": 1000}
    defaults.update(kwargs)
    return MySqlClient(LOCAL_PARAMS, **defaults)


async def test_execute_returns_rows() -> None:
    conn, cursor = _mock_connection(list(USERS_ROWS))
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)) as connect:
        result = await _client().execute("SELECT * FROM users")
    assert result.rows == USERS_ROWS
    assert result.row_count == 2
    assert result.truncated is False
    assert result.max_rows == 1000
    # multi-statements must stay off: client_flag is never passed
    assert "client_flag" not in connect.call_args.kwargs
    conn.close.assert_called_once()


async def test_execute_truncates_to_max_rows() -> None:
    rows = [{"n": i} for i in range(10)]
    conn, _ = _mock_connection(rows)
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)):
        result = await _client(max_rows=3).execute("SELECT * FROM t")
    assert result.truncated is True
    assert result.row_count == 3  # faithful: reports the cap, not the true total
    assert result.rows == rows[:3]


async def test_execute_uses_bounded_fetchmany() -> None:
    conn, cursor = _mock_connection([])
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)):
        await _client(max_rows=100).execute("SELECT * FROM t")
    # SEC-001: never fetchall() a capped query — fetch at most max_rows + 1
    cursor.fetchmany.assert_awaited_once_with(101)
    cursor.fetchall.assert_not_awaited()


async def test_execute_unlimited_uses_fetchall() -> None:
    conn, cursor = _mock_connection([])
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)):
        result = await _client(max_rows=0).execute("SELECT * FROM t")
    cursor.fetchall.assert_awaited_once()
    assert result.truncated is False


async def test_execute_sets_max_execution_time() -> None:
    conn, cursor = _mock_connection([])
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)):
        await _client(query_timeout_ms=5000).execute("SELECT 1")
    first = cursor.execute.await_args_list[0]
    assert first.args[0] == "SET SESSION MAX_EXECUTION_TIME = %s"
    assert first.args[1] == (5000,)


async def test_execute_mariadb_uses_max_statement_time() -> None:
    conn, cursor = _mock_connection([])
    conn.get_server_info = MagicMock(return_value="10.11.5-MariaDB-1:10.11.5+maria")
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)):
        await _client(query_timeout_ms=5000).execute("SELECT 1")
    first = cursor.execute.await_args_list[0]
    assert first.args[0] == "SET SESSION max_statement_time = %s"
    assert first.args[1] == (5.0,)  # milliseconds → seconds for MariaDB


async def test_execute_timeout_unsupported_degrades_gracefully() -> None:
    conn, cursor = _mock_connection([{"x": 1}])
    # First execute (the SET) fails with an unknown-variable error; the query
    # itself must still run rather than every call failing (SEC-007).
    cursor.execute.side_effect = [
        pymysql.err.OperationalError(1193, "Unknown system variable"),
        None,
    ]
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)):
        result = await _client(query_timeout_ms=5000).execute("SELECT 1")
    assert result.row_count == 1


async def test_execute_skips_max_execution_time_when_disabled() -> None:
    conn, cursor = _mock_connection([])
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)):
        await _client(query_timeout_ms=0).execute("SELECT 1")
    assert cursor.execute.await_count == 1
    assert cursor.execute.await_args.args == ("SELECT 1",)


async def test_execute_binds_params_as_tuple() -> None:
    conn, cursor = _mock_connection([])
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)):
        await _client().execute("SELECT * FROM t WHERE a = %s", ["x"])
    assert cursor.execute.await_args.args == ("SELECT * FROM t WHERE a = %s", ("x",))


async def test_execute_without_params_avoids_interpolation() -> None:
    conn, cursor = _mock_connection([])
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)):
        await _client().execute("SELECT '100%'")
    assert cursor.execute.await_args.args == ("SELECT '100%'",)


async def test_driver_error_translated_and_connection_closed() -> None:
    conn, cursor = _mock_connection([])
    cursor.execute.side_effect = pymysql.err.ProgrammingError(1146, "Table 'x' doesn't exist")
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)):
        with pytest.raises(MySQLError) as exc_info:
            await _client().execute("SELECT * FROM x")
    assert exc_info.value.errno == 1146
    assert "doesn't exist" in str(exc_info.value)
    conn.close.assert_called_once()


async def test_connect_failure_is_sanitized() -> None:
    with patch(
        "mysql_mcp.db.aiomysql.connect",
        AsyncMock(side_effect=pymysql.err.OperationalError(1045, "Access denied for user")),
    ):
        with pytest.raises(MySQLError) as exc_info:
            await _client().execute("SELECT 1")
    assert exc_info.value.errno == 1045
    assert "secret-pw" not in str(exc_info.value)


async def test_ping_returns_latency() -> None:
    conn, _ = _mock_connection([])
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)):
        latency = await _client().ping()
    assert latency >= 0
    conn.ping.assert_awaited_once()
    conn.close.assert_called_once()


async def test_remote_host_without_tls_refused() -> None:
    client = MySqlClient(
        ConnectionParams(host="db.remote", port=3306, user="u", password="p", database="d")
    )
    with pytest.raises(MySQLError) as exc_info:
        await client.execute("SELECT 1")
    assert "plaintext" in str(exc_info.value).lower()


async def test_remote_host_with_tls_allowed() -> None:
    conn, _ = _mock_connection([{"n": 1}])
    client = MySqlClient(
        ConnectionParams(host="db.remote", port=3306, user="u", password="p", database="d"),
        ssl_context=build_ssl_context(True),
    )
    with patch("mysql_mcp.db.aiomysql.connect", AsyncMock(return_value=conn)) as connect:
        result = await client.execute("SELECT 1")
    assert result.row_count == 1
    assert connect.call_args.kwargs["ssl"] is not None


def test_build_ssl_context_disabled() -> None:
    assert build_ssl_context(False) is None
    assert build_ssl_context(False, "/some/ca.pem") is None


def test_build_ssl_context_requires_verification() -> None:
    context = build_ssl_context(True)
    assert context is not None
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
