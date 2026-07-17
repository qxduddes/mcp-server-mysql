"""Schema navigation tools — databases, tables, columns, indexes, samples.

Interface layer only: primitive parameters, no business logic, every call
routes through the centralized execute_tool gate.
"""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from mysql_mcp.services.schema import SchemaService
from mysql_mcp.tools._utils import execute_tool

_DB_FIELD = Field(
    description=(
        "Database name (optional — uses the connection's default database when omitted)."
    )
)
_DB_ID_FIELD = Field(
    description=(
        "Optional named database profile configured on the server. "
        "Omit to use the server's default connection."
    )
)


def register_schema_tools(mcp: FastMCP) -> None:
    """Attach the six schema navigation tools to the given FastMCP server."""

    @mcp.tool(
        title="List databases",
        annotations={"title": "List databases", "readOnlyHint": True},
    )
    async def list_databases(
        db_id: Annotated[str, _DB_ID_FIELD] = "",
    ) -> str:
        """List all databases visible to the configured MySQL account.

        Use this tool when the user wants to know which databases (schemas)
        exist on the server. Returns JSON: {databases: [...]}.

        Presentation: never mention this tool's name to the user or announce
        that a tool is being called — answer directly with the information.

        Preferred rendering — card-based layout: when the client supports rich
        widgets, render a single card with the database names as a clean list
        or chips.

        Fallback — Markdown: one-line summary (count), then a bulleted list.

        Formatting rules (both modes): never paste raw JSON unless explicitly
        asked; skip MySQL system schemas in the summary unless asked.
        """
        return await execute_tool(
            "list_databases",
            db_id,
            lambda client: SchemaService(client).list_databases(),
            operation="SHOW_DATABASES",
            target=db_id or "default",
        )

    @mcp.tool(
        title="List tables",
        annotations={"title": "List tables", "readOnlyHint": True},
    )
    async def list_tables(
        database: Annotated[str, _DB_FIELD] = "",
        db_id: Annotated[str, _DB_ID_FIELD] = "",
    ) -> str:
        """List tables in a database.

        Use this tool when the user wants to see what tables exist. Returns
        JSON: {tables: [...], database}.

        Presentation: never mention this tool's name to the user or announce
        that a tool is being called — answer directly with the information.

        Preferred rendering — card-based layout: a header card naming the
        database and a table-list card.

        Fallback — Markdown: one-line summary (database + count), then a
        bulleted list of tables.

        Formatting rules (both modes): never paste raw JSON unless explicitly
        asked.
        """
        return await execute_tool(
            "list_tables",
            db_id,
            lambda client: SchemaService(client).list_tables(database),
            operation="SHOW_TABLES",
            target=database or "(default db)",
        )

    @mcp.tool(
        title="Describe table",
        annotations={"title": "Describe table", "readOnlyHint": True},
    )
    async def describe_table(
        table: Annotated[str, Field(description="Table name.")],
        database: Annotated[str, _DB_FIELD] = "",
        db_id: Annotated[str, _DB_ID_FIELD] = "",
    ) -> str:
        """Get the column structure of a table (DESCRIBE output).

        Use this tool when the user asks about a table's columns, types,
        keys, or defaults. Returns JSON: {table, database, columns:
        [{Field, Type, Null, Key, Default, Extra}]}.

        Presentation: never mention this tool's name to the user or announce
        that a tool is being called — answer directly with the information.

        Preferred rendering — card-based layout: a header card with the table
        name and a columns table card (name, type, nullable, key, default).

        Fallback — Markdown: one-line summary, then a compact Markdown table
        of the columns.

        Formatting rules (both modes): never paste raw JSON unless explicitly
        asked; highlight primary keys in the summary.
        """
        return await execute_tool(
            "describe_table",
            db_id,
            lambda client: SchemaService(client).describe_table(table, database),
            operation="DESCRIBE",
            target=f"{database or '(default db)'}.{table}",
        )

    @mcp.tool(
        title="Inspect schema",
        annotations={"title": "Inspect schema", "readOnlyHint": True},
    )
    async def inspect_schema(
        database: Annotated[str, _DB_FIELD] = "",
        include_columns: Annotated[
            bool, Field(description="Include per-table column details (default true).")
        ] = True,
        include_indexes: Annotated[
            bool, Field(description="Include per-table index details (default true).")
        ] = True,
        db_id: Annotated[str, _DB_ID_FIELD] = "",
    ) -> str:
        """Inspect all tables, columns, and indexes of a database at once.

        Use this tool when the user wants an overview of a whole schema —
        e.g. to understand an unfamiliar database or plan queries. Returns
        JSON: {database, tableCount, tables: [{tableName, tableType, engine,
        rowsEstimate, tableComment, columns, indexes}]}.

        Presentation: never mention this tool's name to the user or announce
        that a tool is being called — answer directly with the information.

        Preferred rendering — card-based layout: a header card for the
        database (table count), then one card per table with its columns and
        indexes as compact tables.

        Fallback — Markdown: one-line summary, then a section per table with
        Markdown tables for columns/indexes.

        Formatting rules (both modes): never paste raw JSON unless explicitly
        asked; rowsEstimate is approximate — say "about N rows".
        """
        return await execute_tool(
            "inspect_schema",
            db_id,
            lambda client: SchemaService(client).inspect_schema(
                database, include_columns, include_indexes
            ),
            operation="INSPECT_SCHEMA",
            target=database or "(default db)",
        )

    @mcp.tool(
        title="Find tables",
        annotations={"title": "Find tables", "readOnlyHint": True},
    )
    async def find_tables(
        term: Annotated[
            str, Field(description="Search term matched against table and column names.")
        ],
        database: Annotated[str, _DB_FIELD] = "",
        db_id: Annotated[str, _DB_ID_FIELD] = "",
    ) -> str:
        """Find tables by matching table or column names.

        Use this tool when the user knows roughly what they're looking for
        ("something with customer emails") but not the exact table. Returns
        JSON: {database, term, matchCount, matches: [{tableName, tableType,
        engine, matchedTableName, matchedColumns}]}.

        Presentation: never mention this tool's name to the user or announce
        that a tool is being called — answer directly with the information.

        Preferred rendering — card-based layout: a header card with the search
        term and one row per match showing why it matched (name vs columns).

        Fallback — Markdown: one-line summary (match count), then a compact
        Markdown table of matches.

        Formatting rules (both modes): never paste raw JSON unless explicitly
        asked.
        """
        return await execute_tool(
            "find_tables",
            db_id,
            lambda client: SchemaService(client).find_tables(term, database),
            operation="FIND_TABLES",
            target=database or "(default db)",
        )

    @mcp.tool(
        title="Sample table rows",
        annotations={"title": "Sample table rows", "readOnlyHint": True},
    )
    async def sample_rows(
        table: Annotated[str, Field(description="Table name to sample from.")],
        database: Annotated[str, _DB_FIELD] = "",
        limit: Annotated[
            int, Field(description="Number of rows to sample (default 5, max 50).", ge=1, le=50)
        ] = 5,
        db_id: Annotated[str, _DB_ID_FIELD] = "",
    ) -> str:
        """Read a small sample of rows from a table (capped at 50).

        Use this tool to show the user what a table's data looks like without
        writing SQL — e.g. right after describe_table. Returns JSON:
        {database, table, limit, rowCount, rows}.

        Presentation: never mention this tool's name to the user or announce
        that a tool is being called — answer directly with the information.

        Preferred rendering — card-based layout: a header card naming the
        table and a results table card with the sampled rows.

        Fallback — Markdown: one-line summary, then a compact Markdown table
        of the rows.

        Formatting rules (both modes): human-readable dates and numbers;
        never paste raw JSON unless explicitly asked; note that this is a
        sample, not the full table.
        """
        return await execute_tool(
            "sample_rows",
            db_id,
            lambda client: SchemaService(client).sample_rows(table, database, limit),
            operation="SAMPLE_ROWS",
            target=f"{database or '(default db)'}.{table}",
        )
