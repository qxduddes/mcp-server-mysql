"""Tests for SchemaService — exact SQL text and shape assertions."""

import pytest

from mysql_mcp.errors import (
    DatabaseRequiredError,
    InvalidIdentifierError,
    MissingSearchTermError,
)
from mysql_mcp.services.schema import SchemaService, _escape_like_pattern, _normalize_sample_limit
from mysql_mcp.tests.fixtures.rows import DESCRIBE_ROWS, TEST_PARAMS, query_result


async def test_list_databases(schema_service, mock_client) -> None:
    mock_client.execute.return_value = query_result(
        [{"Database": "app_db"}, {"Database": "information_schema"}]
    )
    result = await schema_service.list_databases()
    assert result == {"databases": ["app_db", "information_schema"]}
    mock_client.execute.assert_awaited_once_with("SHOW DATABASES")


async def test_list_tables_with_database(schema_service, mock_client) -> None:
    mock_client.execute.return_value = query_result([{"Tables_in_other": "users"}])
    result = await schema_service.list_tables("other")
    assert result == {"tables": ["users"], "database": "other"}
    mock_client.execute.assert_awaited_once_with("SHOW TABLES FROM `other`")


async def test_list_tables_uses_connection_default(schema_service, mock_client) -> None:
    mock_client.execute.return_value = query_result([{"Tables_in_app_db": "users"}])
    result = await schema_service.list_tables()
    assert result["database"] == TEST_PARAMS.database
    mock_client.execute.assert_awaited_once_with("SHOW TABLES")


async def test_list_tables_requires_database(schema_service, mock_client) -> None:
    mock_client.params = TEST_PARAMS.__class__(
        host="h", port=3306, user="u", password="p", database=""
    )
    with pytest.raises(DatabaseRequiredError):
        await schema_service.list_tables()


async def test_describe_table_quotes_identifiers(schema_service, mock_client) -> None:
    mock_client.execute.return_value = query_result(list(DESCRIBE_ROWS))
    result = await schema_service.describe_table("users", "other")
    assert result == {"table": "users", "database": "other", "columns": DESCRIBE_ROWS}
    mock_client.execute.assert_awaited_once_with("DESCRIBE `other`.`users`")


async def test_describe_table_rejects_null_byte_table(schema_service, mock_client) -> None:
    with pytest.raises(InvalidIdentifierError):
        await schema_service.describe_table("bad\x00name")
    mock_client.execute.assert_not_awaited()


async def test_inspect_schema_full_shape(schema_service, mock_client) -> None:
    tables = query_result(
        [
            {
                "TABLE_NAME": "users", "TABLE_TYPE": "BASE TABLE", "ENGINE": "InnoDB",
                "TABLE_ROWS": 42, "TABLE_COMMENT": "",
            }
        ]
    )
    columns = query_result(
        [
            {
                "TABLE_NAME": "users", "COLUMN_NAME": "id", "ORDINAL_POSITION": 1,
                "COLUMN_TYPE": "int", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI",
                "COLUMN_DEFAULT": None, "EXTRA": "auto_increment", "COLUMN_COMMENT": "",
            }
        ]
    )
    indexes = query_result(
        [
            {
                "TABLE_NAME": "users", "INDEX_NAME": "PRIMARY", "NON_UNIQUE": 0,
                "SEQ_IN_INDEX": 1, "COLUMN_NAME": "id",
            }
        ]
    )
    mock_client.execute.side_effect = [tables, columns, indexes]
    result = await schema_service.inspect_schema("app_db")
    assert result["database"] == "app_db"
    assert result["tableCount"] == 1
    table = result["tables"][0]
    assert table["tableName"] == "users"
    assert table["rowsEstimate"] == 42
    assert table["columns"][0]["columnName"] == "id"
    assert table["indexes"][0]["indexName"] == "PRIMARY"
    # every information_schema filter is a bound parameter
    for call in mock_client.execute.await_args_list:
        assert call.args[1] == ["app_db"]


async def test_inspect_schema_can_exclude_details(schema_service, mock_client) -> None:
    mock_client.execute.return_value = query_result(
        [{"TABLE_NAME": "t", "TABLE_TYPE": "BASE TABLE", "ENGINE": "InnoDB",
          "TABLE_ROWS": 0, "TABLE_COMMENT": ""}]
    )
    result = await schema_service.inspect_schema(
        "app_db", include_columns=False, include_indexes=False
    )
    assert mock_client.execute.await_count == 1
    assert result["tables"][0]["columns"] == []
    assert result["tables"][0]["indexes"] == []


async def test_find_tables_escapes_like_pattern(schema_service, mock_client) -> None:
    mock_client.execute.return_value = query_result(
        [{"TABLE_NAME": "discounts", "TABLE_TYPE": "BASE TABLE", "ENGINE": "InnoDB",
          "COLUMN_NAME": "pct_50%_off"}]
    )
    result = await schema_service.find_tables("50%_off\\", "app_db")
    bound = mock_client.execute.await_args.args[1]
    assert bound[0] == "%50\\%\\_off\\\\%"
    assert bound[1] == "app_db"
    assert result["matchCount"] == 1
    assert result["matches"][0]["matchedColumns"] == ["pct_50%_off"]
    assert result["matches"][0]["matchedTableName"] is False


async def test_find_tables_marks_table_name_match(schema_service, mock_client) -> None:
    mock_client.execute.return_value = query_result(
        [{"TABLE_NAME": "Users", "TABLE_TYPE": "BASE TABLE", "ENGINE": "InnoDB",
          "COLUMN_NAME": None}]
    )
    result = await schema_service.find_tables("user", "app_db")
    assert result["matches"][0]["matchedTableName"] is True
    assert result["matches"][0]["matchedColumns"] == []


async def test_find_tables_requires_term(schema_service, mock_client) -> None:
    with pytest.raises(MissingSearchTermError):
        await schema_service.find_tables("   ")
    mock_client.execute.assert_not_awaited()


async def test_sample_rows_binds_limit(schema_service, mock_client) -> None:
    mock_client.execute.return_value = query_result([{"id": 1}])
    result = await schema_service.sample_rows("users", "app_db", 10)
    mock_client.execute.assert_awaited_once_with(
        "SELECT * FROM `app_db`.`users` LIMIT %s", [10]
    )
    assert result == {
        "database": "app_db", "table": "users", "limit": 10, "rowCount": 1,
        "rows": [{"id": 1}],
    }


async def test_inspect_schema_surfaces_truncation(schema_service, mock_client) -> None:
    # SEC-008: when a metadata query hits MYSQL_MAX_ROWS the schema view is
    # incomplete and must be flagged, not presented as the whole picture.
    mock_client.execute.side_effect = [
        query_result(
            [{"TABLE_NAME": "t", "TABLE_TYPE": "BASE TABLE", "ENGINE": "InnoDB",
              "TABLE_ROWS": 0, "TABLE_COMMENT": ""}]
        ),
        query_result([], truncated=True),  # columns query capped
        query_result([]),
    ]
    result = await schema_service.inspect_schema("app_db")
    assert result["truncated"] is True
    assert "incomplete" in result["truncationNote"].lower()


async def test_list_tables_surfaces_truncation(schema_service, mock_client) -> None:
    mock_client.execute.return_value = query_result(
        [{"Tables_in_app_db": "t"}], truncated=True
    )
    result = await schema_service.list_tables("app_db")
    assert result["truncated"] is True


async def test_inspect_schema_not_truncated_has_no_flag(schema_service, mock_client) -> None:
    mock_client.execute.return_value = query_result([])
    result = await schema_service.inspect_schema("app_db")
    assert "truncated" not in result


@pytest.mark.parametrize(("requested", "effective"), [(0, 5), (-3, 5), (50, 50), (999, 50), (1, 1)])
def test_normalize_sample_limit(requested: int, effective: int) -> None:
    assert _normalize_sample_limit(requested) == effective


def test_escape_like_pattern() -> None:
    assert _escape_like_pattern(r"a\b_c%d") == r"a\\b\_c\%d"
