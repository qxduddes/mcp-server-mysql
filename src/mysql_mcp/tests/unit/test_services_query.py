"""Tests for QueryService."""

import pytest

from mysql_mcp.errors import QueryPolicyError
from mysql_mcp.tests.fixtures.rows import USERS_ROWS, query_result


async def test_run_query_returns_camel_case_shape(query_service, mock_client) -> None:
    mock_client.execute.return_value = query_result(list(USERS_ROWS))
    result = await query_service.run_query("SELECT * FROM users")
    assert result == {
        "rows": USERS_ROWS,
        "rowCount": 2,
        "truncated": False,
        "maxRows": 1000,
    }
    mock_client.execute.assert_awaited_once_with("SELECT * FROM users", None)


async def test_run_query_executes_original_sql_with_params(query_service, mock_client) -> None:
    mock_client.execute.return_value = query_result([])
    await query_service.run_query("SELECT * FROM t WHERE a = %s;", ["x"])
    mock_client.execute.assert_awaited_once_with("SELECT * FROM t WHERE a = %s;", ["x"])


async def test_run_query_rejects_writes(query_service, mock_client) -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        await query_service.run_query("DELETE FROM users")
    assert exc_info.value.code == "QUERY_REQUIRES_READ_ONLY_SQL"
    mock_client.execute.assert_not_awaited()


async def test_run_query_rejects_forbidden_read(query_service, mock_client) -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        await query_service.run_query("SELECT * FROM t INTO OUTFILE '/tmp/x'")
    assert exc_info.value.code == "FORBIDDEN_READ_CONSTRUCT"
    mock_client.execute.assert_not_awaited()


async def test_run_query_rejects_multi_statement(query_service, mock_client) -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        await query_service.run_query("SELECT 1; DROP TABLE t")
    assert exc_info.value.code == "MULTI_STATEMENT_SQL"
    mock_client.execute.assert_not_awaited()


async def test_explain_builds_traditional_sql(query_service, mock_client) -> None:
    mock_client.execute.return_value = query_result([{"id": 1}])
    result = await query_service.explain("SELECT * FROM t;", None, "traditional")
    assert result["explainSql"] == "EXPLAIN SELECT * FROM t"
    assert result["originalSql"] == "SELECT * FROM t;"
    assert result["format"] == "traditional"
    mock_client.execute.assert_awaited_once_with("EXPLAIN SELECT * FROM t", None)


async def test_explain_builds_json_format(query_service, mock_client) -> None:
    mock_client.execute.return_value = query_result([])
    result = await query_service.explain("SELECT 1", None, "json")
    assert result["explainSql"] == "EXPLAIN FORMAT=JSON SELECT 1"


async def test_explain_rejects_invalid_format(query_service, mock_client) -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        await query_service.explain("SELECT 1", None, "yaml")
    assert exc_info.value.code == "INVALID_EXPLAIN_FORMAT"


async def test_explain_rejects_non_select(query_service, mock_client) -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        await query_service.explain("SHOW TABLES", None, "traditional")
    assert exc_info.value.code == "EXPLAIN_REQUIRES_SELECT"
    mock_client.execute.assert_not_awaited()
