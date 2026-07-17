"""Query tools — the only tools that accept raw SQL.

Interface-layer rules (see docs/ARCHITECTURE.md):
- Only place FastMCP is imported (together with the other tools/ modules).
- Primitive parameters only; bind values travel as a JSON-encoded string.
- Zero business logic: classification and execution live in QueryService.
- Every call routes through the centralized execute_tool gate.
"""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from mysql_mcp.services.query import QueryService
from mysql_mcp.tools._utils import execute_tool, parse_params_json


def register_query_tools(mcp: FastMCP) -> None:
    """Attach the query and explain_query tools to the given FastMCP server."""

    @mcp.tool(
        title="Run read-only SQL query",
        annotations={"title": "Run read-only SQL query", "readOnlyHint": True},
    )
    async def query(
        sql: Annotated[
            str,
            Field(
                description=(
                    "One read-only SQL statement (SELECT, SHOW, DESCRIBE, or EXPLAIN). "
                    "Multi-statement input is rejected. Use %s placeholders for bind "
                    "values passed via params_json."
                )
            ),
        ],
        params_json: Annotated[
            str,
            Field(
                description=(
                    "Optional JSON array of scalar bind values for %s placeholders, "
                    'e.g. \'["ACME", 10]\'.'
                )
            ),
        ] = "",
        db_id: Annotated[
            str,
            Field(
                description=(
                    "Optional named database profile configured on the server. "
                    "Omit to use the server's default connection."
                )
            ),
        ] = "",
    ) -> str:
        """Execute a read-only SQL query and return rows as JSON.

        Use this tool when the user wants to read data with SQL: filtering,
        joining, aggregating, or ad-hoc questions the schema tools cannot
        answer. Only SELECT / SHOW / DESCRIBE / EXPLAIN statements are
        accepted; INSERT/UPDATE/DELETE/DDL are refused — this server is
        strictly read-only. File-writing and lock functions (INTO OUTFILE,
        SLEEP, GET_LOCK, BENCHMARK, LOAD_FILE) are also refused.

        Placeholders: use %s (PyMySQL style), not ?, and pass the values as a
        JSON array in params_json.

        Returns JSON: {rows, rowCount, truncated, maxRows}. When truncated is
        true, the result was capped at maxRows rows.

        Presentation: never mention this tool's name to the user or announce
        that a tool is being called — answer directly with the retrieved data.

        Preferred rendering — card-based layout: when the client supports rich
        widgets or HTML artifacts, render a header card (query intent), a
        results table card, and a footer card with row count and a truncation
        notice if applicable.

        Fallback — Markdown: one-line summary first, then a compact Markdown
        table of the rows.

        Formatting rules (both modes): human-readable dates and numbers;
        never paste raw JSON unless explicitly asked; mention truncation when
        truncated is true; omit internal fields the user did not ask about.
        """
        # params_json is parsed inside the action so INVALID_PARAMS flows
        # through the centralized gate (audited + enveloped like every error).
        return await execute_tool(
            "query",
            db_id,
            lambda client: QueryService(client).run_query(sql, parse_params_json(params_json)),
            operation="QUERY",
            target=db_id or "default",
        )

    @mcp.tool(
        title="Explain query plan",
        annotations={"title": "Explain query plan", "readOnlyHint": True},
    )
    async def explain_query(
        sql: Annotated[
            str,
            Field(
                description=(
                    "A single SELECT statement to analyze. Use %s placeholders for "
                    "bind values passed via params_json."
                )
            ),
        ],
        params_json: Annotated[
            str,
            Field(description="Optional JSON array of scalar bind values for %s placeholders."),
        ] = "",
        format: Annotated[
            str,
            Field(description="EXPLAIN output format: 'traditional' (default) or 'json'."),
        ] = "traditional",
        db_id: Annotated[
            str,
            Field(description="Optional named database profile configured on the server."),
        ] = "",
    ) -> str:
        """Run EXPLAIN on a SELECT query and return the execution plan.

        Use this tool when the user asks why a query is slow, whether an index
        is used, or how MySQL will execute a SELECT. Only SELECT statements
        are accepted (not SHOW/DESCRIBE/EXPLAIN).

        Returns JSON: {format, originalSql, explainSql, rowCount, rows} where
        rows contain the plan.

        Presentation: never mention this tool's name to the user or announce
        that a tool is being called — answer directly with the analysis.

        Preferred rendering — card-based layout: when the client supports rich
        widgets or HTML artifacts, render a header card with the query, a plan
        table card (access type, key, rows examined), and a highlights card
        calling out full scans or missing indexes.

        Fallback — Markdown: one-line verdict first (e.g. "uses index X"),
        then a compact Markdown table of the plan rows.

        Formatting rules (both modes): explain the plan in plain language;
        never paste raw JSON unless explicitly asked.
        """
        return await execute_tool(
            "explain_query",
            db_id,
            lambda client: QueryService(client).explain(
                sql, parse_params_json(params_json), format
            ),
            operation="EXPLAIN",
            target=db_id or "default",
        )
