"""Smoke test: the full tool surface and its MCP metadata."""

from fastmcp import FastMCP

from mysql_mcp.tools import register_all_tools

EXPECTED_TOOLS = {
    "describe_table",
    "explain_query",
    "find_tables",
    "health_check",
    "inspect_schema",
    "list_databases",
    "list_tables",
    "query",
    "sample_rows",
}

# Tools the original TS server exposed that this port deliberately dropped
# (see CHANGELOG.md): connect (audit P1-2), use_database (audit LOW), and
# every write/DDL tool (read-only scope).
FORBIDDEN_TOOLS = {
    "connect",
    "use_database",
    "execute",
    "dry_run_execute",
    "create_table",
    "alter_table",
    "drop_table",
    "create_index",
    "drop_index",
    "create_database",
    "drop_database",
}


async def test_exactly_nine_read_only_tools() -> None:
    mcp = FastMCP("test")
    register_all_tools(mcp)
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert names == EXPECTED_TOOLS
    assert not names & FORBIDDEN_TOOLS


async def test_all_tools_have_titles_and_read_only_hint() -> None:
    mcp = FastMCP("test")
    register_all_tools(mcp)
    for tool in await mcp.list_tools():
        assert tool.title, f"{tool.name} missing title"
        assert tool.annotations is not None, f"{tool.name} missing annotations"
        assert tool.annotations.title == tool.title
        assert tool.annotations.readOnlyHint is True, f"{tool.name} missing readOnlyHint"


async def test_no_tool_accepts_credential_parameters() -> None:
    """Audit P1-2: credentials must never be tool parameters."""
    mcp = FastMCP("test")
    register_all_tools(mcp)
    for tool in await mcp.list_tools():
        schema = getattr(tool, "inputSchema", None) or getattr(tool, "parameters", None) or {}
        properties = schema.get("properties", {})
        assert properties, f"{tool.name} has no input schema to inspect"
        for forbidden in ("host", "port", "user", "password", "username"):
            assert forbidden not in properties, (
                f"{tool.name} exposes credential-like parameter '{forbidden}'"
            )
