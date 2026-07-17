"""Query service — read-only SQL execution and EXPLAIN plans.

Response keys are camelCase, faithful to the TS original's JSON shapes.
"""

from collections.abc import Sequence
from typing import Any

from mysql_mcp.db import MySqlClient
from mysql_mcp.errors import QueryPolicyError
from mysql_mcp.sql_policy import assert_explain_select, assert_read_allowed, classify_sql

_EXPLAIN_FORMATS = frozenset({"traditional", "json"})


class QueryService:
    """Runs policy-gated read queries through an injected MySqlClient."""

    def __init__(self, client: MySqlClient) -> None:
        self._client = client

    async def run_query(self, sql: str, params: Sequence[Any] | None = None) -> dict[str, Any]:
        """Execute one read-classified statement; returns rows + truncation info."""
        classification = classify_sql(sql)
        assert_read_allowed(classification)
        result = await self._client.execute(sql, params)
        return {
            "rows": result.rows,
            "rowCount": result.row_count,
            "truncated": result.truncated,
            "maxRows": result.max_rows or None,
        }

    async def explain(
        self, sql: str, params: Sequence[Any] | None = None, fmt: str = "traditional"
    ) -> dict[str, Any]:
        """EXPLAIN a single SELECT; fmt is 'traditional' or 'json'."""
        if fmt not in _EXPLAIN_FORMATS:
            raise QueryPolicyError(
                "INVALID_EXPLAIN_FORMAT",
                "format must be 'traditional' or 'json'.",
            )
        classification = classify_sql(sql)
        assert_explain_select(classification)
        prefix = "EXPLAIN FORMAT=JSON " if fmt == "json" else "EXPLAIN "
        explain_sql = prefix + classification.normalized_sql
        result = await self._client.execute(explain_sql, params)
        return {
            "format": fmt,
            "originalSql": sql,
            "explainSql": explain_sql,
            "rowCount": result.row_count,
            "rows": result.rows,
        }
