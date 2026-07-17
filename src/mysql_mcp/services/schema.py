"""Schema service — database/table navigation and inspection.

All identifiers go through quote_identifier/qualified_identifier; every
information_schema filter is a bound %s parameter. Response keys are
camelCase, faithful to the TS original (schemaContext.ts).
"""

from typing import Any

from mysql_mcp.db import MySqlClient
from mysql_mcp.errors import DatabaseRequiredError, MissingSearchTermError
from mysql_mcp.identifiers import qualified_identifier, quote_identifier

_SAMPLE_LIMIT_DEFAULT = 5
_SAMPLE_LIMIT_MAX = 50


def _escape_like_pattern(value: str) -> str:
    """Escape LIKE metacharacters (used with ESCAPE '\\\\')."""
    return value.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%")


def _normalize_sample_limit(limit: int) -> int:
    """Default 5, floor 1, cap 50 (faithful to normalizeSampleLimit)."""
    if limit < 1:
        return _SAMPLE_LIMIT_DEFAULT
    return min(limit, _SAMPLE_LIMIT_MAX)


def _mark_truncation(payload: dict[str, Any], truncated: bool) -> None:
    """Surface MYSQL_MAX_ROWS truncation on metadata results (SEC-008).

    Schema/metadata queries share the query row cap; when they hit it the view
    is incomplete, so callers must be told rather than shown partial data as if
    it were the whole picture.
    """
    if truncated:
        payload["truncated"] = True
        payload["truncationNote"] = (
            "Result was capped by MYSQL_MAX_ROWS; this schema view is incomplete. "
            "Narrow the scope or raise MYSQL_MAX_ROWS on the server."
        )


class SchemaService:
    """Read-only schema navigation through an injected MySqlClient."""

    def __init__(self, client: MySqlClient) -> None:
        self._client = client

    def _resolve_database(self, database: str) -> str:
        """Explicit argument wins; else the connection's default database."""
        effective = database or self._client.params.database
        if not effective:
            raise DatabaseRequiredError()
        return effective

    async def list_databases(self) -> dict[str, Any]:
        result = await self._client.execute("SHOW DATABASES")
        return {"databases": [next(iter(row.values())) for row in result.rows]}

    async def list_tables(self, database: str = "") -> dict[str, Any]:
        if database:
            sql = f"SHOW TABLES FROM {quote_identifier(database)}"
        elif self._client.params.database:
            sql = "SHOW TABLES"
        else:
            raise DatabaseRequiredError()
        result = await self._client.execute(sql)
        payload: dict[str, Any] = {
            "tables": [next(iter(row.values())) for row in result.rows],
            "database": database or self._client.params.database or None,
        }
        _mark_truncation(payload, result.truncated)
        return payload

    async def describe_table(self, table: str, database: str = "") -> dict[str, Any]:
        effective = self._resolve_database(database)
        result = await self._client.execute(
            f"DESCRIBE {qualified_identifier(table, effective)}"
        )
        return {"table": table, "database": effective, "columns": result.rows}

    async def inspect_schema(
        self,
        database: str = "",
        include_columns: bool = True,
        include_indexes: bool = True,
    ) -> dict[str, Any]:
        effective = self._resolve_database(database)
        tables_result = await self._client.execute(
            "SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_ROWS, TABLE_COMMENT "
            "FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s "
            "ORDER BY TABLE_NAME",
            [effective],
        )
        tables: dict[str, dict[str, Any]] = {}
        for row in tables_result.rows:
            tables[str(row["TABLE_NAME"])] = {
                "tableName": row["TABLE_NAME"],
                "tableType": row["TABLE_TYPE"],
                "engine": row["ENGINE"],
                "rowsEstimate": row["TABLE_ROWS"],
                "tableComment": row["TABLE_COMMENT"],
                "columns": [],
                "indexes": [],
            }
        if include_columns:
            columns_result = await self._client.execute(
                "SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_TYPE, "
                "IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s "
                "ORDER BY TABLE_NAME, ORDINAL_POSITION",
                [effective],
            )
            for row in columns_result.rows:
                table = tables.get(str(row["TABLE_NAME"]))
                if table is not None:
                    table["columns"].append(
                        {
                            "columnName": row["COLUMN_NAME"],
                            "ordinalPosition": row["ORDINAL_POSITION"],
                            "columnType": row["COLUMN_TYPE"],
                            "isNullable": row["IS_NULLABLE"],
                            "columnKey": row["COLUMN_KEY"],
                            "columnDefault": row["COLUMN_DEFAULT"],
                            "extra": row["EXTRA"],
                            "columnComment": row["COLUMN_COMMENT"],
                        }
                    )
        if include_indexes:
            indexes_result = await self._client.execute(
                "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME "
                "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = %s "
                "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
                [effective],
            )
            for row in indexes_result.rows:
                table = tables.get(str(row["TABLE_NAME"]))
                if table is not None:
                    table["indexes"].append(
                        {
                            "indexName": row["INDEX_NAME"],
                            "nonUnique": row["NON_UNIQUE"],
                            "sequence": row["SEQ_IN_INDEX"],
                            "columnName": row["COLUMN_NAME"],
                        }
                    )
        truncated = tables_result.truncated
        if include_columns:
            truncated = truncated or columns_result.truncated
        if include_indexes:
            truncated = truncated or indexes_result.truncated
        payload: dict[str, Any] = {
            "database": effective,
            "tableCount": len(tables),
            "tables": list(tables.values()),
        }
        _mark_truncation(payload, truncated)
        return payload

    async def find_tables(self, term: str, database: str = "") -> dict[str, Any]:
        if not term.strip():
            raise MissingSearchTermError()
        effective = self._resolve_database(database)
        pattern = f"%{_escape_like_pattern(term.strip())}%"
        result = await self._client.execute(
            "SELECT t.TABLE_NAME, t.TABLE_TYPE, t.ENGINE, c.COLUMN_NAME "
            "FROM information_schema.TABLES t "
            "LEFT JOIN information_schema.COLUMNS c "
            "ON c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME "
            "AND c.COLUMN_NAME LIKE %s ESCAPE '\\\\' "
            "WHERE t.TABLE_SCHEMA = %s "
            "AND (t.TABLE_NAME LIKE %s ESCAPE '\\\\' OR c.COLUMN_NAME IS NOT NULL) "
            "ORDER BY t.TABLE_NAME, c.COLUMN_NAME",
            [pattern, effective, pattern],
        )
        needle = term.strip().lower()
        matches: dict[str, dict[str, Any]] = {}
        for row in result.rows:
            name = str(row["TABLE_NAME"])
            entry = matches.setdefault(
                name,
                {
                    "tableName": row["TABLE_NAME"],
                    "tableType": row["TABLE_TYPE"],
                    "engine": row["ENGINE"],
                    "matchedTableName": needle in name.lower(),
                    "matchedColumns": [],
                },
            )
            if row["COLUMN_NAME"] is not None:
                entry["matchedColumns"].append(row["COLUMN_NAME"])
        payload: dict[str, Any] = {
            "database": effective,
            "term": term.strip(),
            "matchCount": len(matches),
            "matches": list(matches.values()),
        }
        _mark_truncation(payload, result.truncated)
        return payload

    async def sample_rows(
        self, table: str, database: str = "", limit: int = _SAMPLE_LIMIT_DEFAULT
    ) -> dict[str, Any]:
        effective = self._resolve_database(database)
        normalized_limit = _normalize_sample_limit(limit)
        result = await self._client.execute(
            f"SELECT * FROM {qualified_identifier(table, effective)} LIMIT %s",
            [normalized_limit],
        )
        return {
            "database": effective,
            "table": table,
            "limit": normalized_limit,
            "rowCount": result.row_count,
            "rows": result.rows,
        }
