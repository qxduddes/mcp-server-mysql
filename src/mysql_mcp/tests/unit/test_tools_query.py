"""Tests for the query tools through a real FastMCP instance."""

import json

from mysql_mcp.errors import MySQLError
from mysql_mcp.tests.conftest import tool_text
from mysql_mcp.tests.fixtures.rows import USERS_ROWS, query_result


async def test_query_success_returns_json(query_mcp) -> None:
    mcp, mock_client, _ = query_mcp
    mock_client.execute.return_value = query_result(list(USERS_ROWS))
    result = await mcp.call_tool("query", {"sql": "SELECT * FROM users"})
    payload = json.loads(tool_text(result))
    assert payload["rows"] == USERS_ROWS
    assert payload["rowCount"] == 2
    assert payload["truncated"] is False


async def test_query_with_profile_uses_get_profile(query_mcp) -> None:
    mcp, mock_client, mock_settings = query_mcp
    mock_client.execute.return_value = query_result([])
    await mcp.call_tool("query", {"sql": "SELECT 1", "db_id": "staging"})
    mock_settings.get_profile.assert_called_once_with("staging")


async def test_query_unknown_profile(query_mcp) -> None:
    mcp, _, mock_settings = query_mcp
    mock_settings.get_profile.side_effect = KeyError("ghost")
    result = await mcp.call_tool("query", {"sql": "SELECT 1", "db_id": "ghost"})
    assert tool_text(result).startswith("ERROR: UNKNOWN_PROFILE")


async def test_query_missing_credentials(query_mcp) -> None:
    mcp, _, mock_settings = query_mcp
    mock_settings.default_params.return_value = None
    result = await mcp.call_tool("query", {"sql": "SELECT 1"})
    assert tool_text(result).startswith("ERROR: MISSING_CREDENTIALS")


async def test_query_invalid_db_id_format(query_mcp) -> None:
    mcp, _, _ = query_mcp
    result = await mcp.call_tool("query", {"sql": "SELECT 1", "db_id": "../etc/passwd"})
    assert tool_text(result).startswith("ERROR: INVALID_DB_ID")


async def test_query_rejects_write_sql(query_mcp) -> None:
    mcp, mock_client, _ = query_mcp
    result = await mcp.call_tool("query", {"sql": "DELETE FROM users"})
    assert tool_text(result).startswith("ERROR: QUERY_REQUIRES_READ_ONLY_SQL")
    mock_client.execute.assert_not_awaited()


async def test_query_rejects_forbidden_construct(query_mcp) -> None:
    mcp, _, _ = query_mcp
    result = await mcp.call_tool("query", {"sql": "SELECT SLEEP(10)"})
    assert tool_text(result).startswith("ERROR: FORBIDDEN_READ_CONSTRUCT")


async def test_query_rejects_multi_statement(query_mcp) -> None:
    mcp, _, _ = query_mcp
    result = await mcp.call_tool("query", {"sql": "SELECT 1; DROP TABLE t"})
    assert tool_text(result).startswith("ERROR: MULTI_STATEMENT_SQL")


async def test_query_params_json_bound(query_mcp) -> None:
    mcp, mock_client, _ = query_mcp
    mock_client.execute.return_value = query_result([])
    await mcp.call_tool(
        "query",
        {"sql": "SELECT * FROM t WHERE a = %s AND b = %s", "params_json": '["x", 10]'},
    )
    mock_client.execute.assert_awaited_once_with(
        "SELECT * FROM t WHERE a = %s AND b = %s", ["x", 10]
    )


async def test_query_invalid_params_json(query_mcp) -> None:
    mcp, _, _ = query_mcp
    result = await mcp.call_tool("query", {"sql": "SELECT 1", "params_json": "not json"})
    assert tool_text(result).startswith("ERROR: INVALID_PARAMS")


async def test_query_params_json_must_be_array_of_scalars(query_mcp) -> None:
    mcp, _, _ = query_mcp
    for bad in ('{"a": 1}', '[{"nested": true}]', "[[1]]"):
        result = await mcp.call_tool("query", {"sql": "SELECT 1", "params_json": bad})
        assert tool_text(result).startswith("ERROR: INVALID_PARAMS")


async def test_query_mysql_error_surfaced_with_code(query_mcp) -> None:
    mcp, mock_client, _ = query_mcp
    mock_client.execute.side_effect = MySQLError("Table 'x' doesn't exist", errno=1146)
    result = await mcp.call_tool("query", {"sql": "SELECT * FROM x"})
    text = tool_text(result)
    assert text.startswith("ERROR: MYSQL_ERROR")
    assert "1146" in text


async def test_query_unexpected_error_never_leaks(query_mcp) -> None:
    mcp, mock_client, _ = query_mcp
    mock_client.execute.side_effect = RuntimeError("secret-pw leaked in traceback")
    result = await mcp.call_tool("query", {"sql": "SELECT 1"})
    text = tool_text(result)
    assert text == "ERROR: Unexpected internal failure in query. Check server logs."
    assert "secret-pw" not in text


async def test_explain_query_success(query_mcp) -> None:
    mcp, mock_client, _ = query_mcp
    mock_client.execute.return_value = query_result([{"id": 1, "select_type": "SIMPLE"}])
    result = await mcp.call_tool("explain_query", {"sql": "SELECT * FROM users;"})
    payload = json.loads(tool_text(result))
    assert payload["explainSql"] == "EXPLAIN SELECT * FROM users"
    assert payload["format"] == "traditional"


async def test_explain_query_rejects_non_select(query_mcp) -> None:
    mcp, _, _ = query_mcp
    result = await mcp.call_tool("explain_query", {"sql": "SHOW TABLES"})
    assert tool_text(result).startswith("ERROR: EXPLAIN_REQUIRES_SELECT")


async def test_explain_query_invalid_format(query_mcp) -> None:
    mcp, _, _ = query_mcp
    result = await mcp.call_tool("explain_query", {"sql": "SELECT 1", "format": "xml"})
    assert tool_text(result).startswith("ERROR: INVALID_EXPLAIN_FORMAT")
