# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Commands

```bash
# Create and activate virtual environment (required once; needs Python ≥ 3.12)
python3 -m venv .venv
source .venv/bin/activate

# Install package (editable) — runtime only
pip install -e .

# Install with dev dependencies (testing + linting)
pip install -e ".[dev]"

# Run all tests (live MySQL tests auto-skip)
pytest

# Run unit tests only
pytest src/mysql_mcp/tests/unit -v

# Run live MySQL tests (requires a real server — see docs/TESTING.md)
MYSQL_RUN_LIVE_TESTS=1 MYSQL_HOST=127.0.0.1 MYSQL_PORT=3307 \
MYSQL_USER=root MYSQL_PASSWORD=test MYSQL_DATABASE=demo \
pytest src/mysql_mcp/tests/integration -m live -v

# Run a single test file
pytest src/mysql_mcp/tests/unit/test_sql_policy.py

# Run with coverage
pytest src/mysql_mcp/tests/unit --cov=mysql_mcp --cov-report=term-missing

# Lint with auto-fix / format / type check
ruff check src/ --fix
ruff format src/
mypy

# Verify tool registration (no credentials needed)
python - <<'EOF'
import asyncio, server
tools = asyncio.run(server.mcp.list_tools())
print(f"{len(tools)} tools registered")   # expect: 9
EOF
```

## What this project is

A **read-only** MySQL MCP server: a security-hardened Python port of the
TypeScript `@nilsir/mcp-server-mysql` v2.0.0. The security audit that drove
the design is in `audit/` (PDFs); the finding→mitigation matrix is in
`docs/SECURITY.md`; every divergence from the original is in `docs/CHANGES.md`.

## Architecture

Strict 3-layer FastMCP package (see `docs/ARCHITECTURE.md` for the full
picture):

```
tools/          ← Interface layer: the ONLY place FastMCP is imported
services/       ← Service layer: pure Python, no FastMCP, no aiomysql
db.py           ← Infrastructure layer: the ONLY place aiomysql is imported
sql_policy.py   ← Pure-Python read-only policy engine
```

**The centralized gate:** every tool body is a single delegation to
`execute_tool()` in `tools/_utils.py`, which validates `db_id`, resolves
credentials, builds the client, runs the service action, emits one JSON audit
record (`mysql_mcp.audit` logger — never SQL text, values, or credentials),
and formats the envelope (JSON success / `"ERROR: <CODE>: <message>"`
failure). Never bypass it.

**Credential model** (`config.py`): multi-profile `DB_PROFILES` JSON env map
selected via the `db_id` tool parameter, with single-connection `MYSQL_*` env
fallback when `db_id` is empty. No default user. Password material is
`SecretStr`; the only unwrap points are `get_profile()` and
`default_params()`.

**SQL policy** (`sql_policy.py`): single-statement scanner (quote/comment
state machine; backticks don't honor backslash escapes; trailing `;` +
comments OK, `;;` rejected) → first-keyword classifier (read =
SELECT/SHOW/EXPLAIN/DESCRIBE/DESC) → forbidden-read denylist (INTO
OUTFILE/DUMPFILE, GET_LOCK, SLEEP, BENCHMARK, LOAD_FILE). CTEs (`WITH`) are
rejected — faithful to the original; documented future work.

**Error hierarchy** (`errors.py`): `MySqlMcpError(code)` →
`QueryPolicyError(code, msg)`, `InvalidIdentifierError`,
`DatabaseRequiredError`, `MissingSearchTermError`,
`MySQLError(msg, errno, sqlstate)`.

**Server entry point** (`server.py`): `MCP_TRANSPORT` = `stdio` (default) |
`http` (streamable HTTP at `/mcp`, port 8004). HTTP auth is **fail-closed**
(`MCP_AUTH_TOKEN` required; `MCP_ALLOW_ANON=1` literal-1 escape hatch with a
loud warning). `GET /health` is an unauthenticated, data-free liveness probe
— keep it static. The FastMCP `instructions` tell the model to present
results in plain language and refuse write requests — keep them when touching
the constructor.

## Adding a new tool

Think twice: this server is deliberately read-only. Never add execute/DDL
tools or any tool accepting credentials/host parameters.

1. Add a method to the appropriate service in `services/` (identifiers via
   `quote_identifier`/`qualified_identifier`, values as bound `%s` params).
2. Add a nested `@mcp.tool()` function in the matching `tools/*.py`
   registrar:
   - `title` set twice: `@mcp.tool(title="...", annotations={"title": "...",
     "readOnlyHint": True})`
   - Primitive params only via `Annotated[..., Field(description=...)]`;
     include `db_id: str = ""` last
   - The body is a single `execute_tool(...)` call
   - Docstring: when to use it → return shape → `Presentation:` /
     `Preferred rendering — card-based layout:` / `Fallback — Markdown:` /
     `Formatting rules (both modes):` sections
3. Update `EXPECTED_TOOLS` in
   `src/mysql_mcp/tests/unit/test_tools_registration.py`, add tool tests, and
   update the tool tables in `README.md` and `docs/USAGE.md`.

## Testing

`asyncio_mode = "auto"` — **do not add `@pytest.mark.asyncio`**.

- Tools are nested closures — test via `FastMCP` + `await mcp.call_tool(...)`
  using the `query_mcp`/`schema_mcp`/`health_mcp` fixtures (yield-inside-with;
  they patch `mysql_mcp.tools._utils.settings` and
  `mysql_mcp.tools._utils._make_client`).
- Service tests: `AsyncMock(spec=MySqlClient)` with `params`/`max_rows` set
  explicitly (instance attrs are not in the spec); assert exact SQL text.
- Live tests: `@pytest.mark.live`, skipped unless `MYSQL_RUN_LIVE_TESTS=1`.

## Key constraints

- `services/`, `sql_policy.py`, `identifiers.py`, `config.py`, `errors.py`
  must never import fastmcp; only `db.py` imports aiomysql.
- Tool parameters must be primitives — bind values travel as `params_json`
  (JSON array of scalars, parsed by `parse_params_json`).
- Placeholders are `%s` (PyMySQL), not `?`. With no params, `cur.execute(sql)`
  is called without an args tuple so literal `%` is safe.
- Response keys are camelCase (faithful to the TS original); tool parameters
  are snake_case.
- All tool returns are `str` — JSON on success, `"ERROR: <CODE>: ..."` on
  failure. `except Exception` blocks `logger.exception(...)` and return a
  generic message — never raw exception text.
- Row capping is post-fetch slicing; when truncated, `rowCount` reports the
  cap (faithful).
- Credentials are never hardcoded, never tool parameters, never logged.
- TLS verification can never be disabled (`build_ssl_context` has no
  verify-off path) — do not add one.
- HTTP mode is fail-closed; `/health` stays data-free.
- The audit log must never contain SQL text, bind values, or credentials.
