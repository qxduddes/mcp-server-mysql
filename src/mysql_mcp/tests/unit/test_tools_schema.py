"""Tests for the schema tools through a real FastMCP instance."""

import json

from mysql_mcp.tests.conftest import tool_text
from mysql_mcp.tests.fixtures.rows import DESCRIBE_ROWS, query_result


async def test_list_databases(schema_mcp) -> None:
    mcp, mock_client, _ = schema_mcp
    mock_client.execute.return_value = query_result([{"Database": "app_db"}])
    result = await mcp.call_tool("list_databases", {})
    assert json.loads(tool_text(result)) == {"databases": ["app_db"]}


async def test_list_tables(schema_mcp) -> None:
    mcp, mock_client, _ = schema_mcp
    mock_client.execute.return_value = query_result([{"Tables_in_app_db": "users"}])
    result = await mcp.call_tool("list_tables", {"database": "app_db"})
    payload = json.loads(tool_text(result))
    assert payload == {"tables": ["users"], "database": "app_db"}


async def test_describe_table(schema_mcp) -> None:
    mcp, mock_client, _ = schema_mcp
    mock_client.execute.return_value = query_result(list(DESCRIBE_ROWS))
    result = await mcp.call_tool("describe_table", {"table": "users"})
    payload = json.loads(tool_text(result))
    assert payload["table"] == "users"
    assert payload["columns"][0]["Field"] == "id"


async def test_describe_table_invalid_identifier(schema_mcp) -> None:
    mcp, _, _ = schema_mcp
    result = await mcp.call_tool("describe_table", {"table": "bad\x00name"})
    assert tool_text(result).startswith("ERROR: INVALID_IDENTIFIER")


async def test_find_tables_missing_term(schema_mcp) -> None:
    mcp, _, _ = schema_mcp
    result = await mcp.call_tool("find_tables", {"term": "  "})
    assert tool_text(result).startswith("ERROR: MISSING_SEARCH_TERM")


async def test_sample_rows_clamps_via_field_validation(schema_mcp) -> None:
    mcp, mock_client, _ = schema_mcp
    mock_client.execute.return_value = query_result([{"id": 1}])
    result = await mcp.call_tool("sample_rows", {"table": "users", "limit": 50})
    payload = json.loads(tool_text(result))
    assert payload["limit"] == 50


async def test_sample_rows_default_limit(schema_mcp) -> None:
    mcp, mock_client, _ = schema_mcp
    mock_client.execute.return_value = query_result([])
    result = await mcp.call_tool("sample_rows", {"table": "users"})
    payload = json.loads(tool_text(result))
    assert payload["limit"] == 5


async def test_inspect_schema_flags(schema_mcp) -> None:
    mcp, mock_client, _ = schema_mcp
    mock_client.execute.return_value = query_result([])
    result = await mcp.call_tool(
        "inspect_schema",
        {"database": "app_db", "include_columns": False, "include_indexes": False},
    )
    payload = json.loads(tool_text(result))
    assert payload == {"database": "app_db", "tableCount": 0, "tables": []}
    assert mock_client.execute.await_count == 1


async def test_schema_tool_unknown_profile(schema_mcp) -> None:
    mcp, _, mock_settings = schema_mcp
    mock_settings.get_profile.side_effect = KeyError("ghost")
    result = await mcp.call_tool("list_tables", {"db_id": "ghost"})
    assert tool_text(result).startswith("ERROR: UNKNOWN_PROFILE")
