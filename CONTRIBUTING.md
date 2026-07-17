# Contributing

Thanks for improving `mysql-mcp`. This is a **read-only** MySQL MCP server with
a deliberately small, security-hardened surface. Contributions must preserve
that posture and meet the tool-definition testing standards below — MCP tool
schemas are the contract an LLM reasons over, and a malformed schema silently
breaks downstream agent behavior.

## Ground rules

- **Read-only only.** Do not add write, DDL, administrative, or
  connection-retargeting tools, and do not add any tool parameter that accepts a
  host, user, or password. These are hard constraints, not preferences.
- **Never weaken a security control.** TLS verification, fail-closed HTTP auth,
  the SQL policy denylist, credential secrecy, and the audit log must not be
  made optional or bypassable.
- **Docs-as-contract.** User-facing behavior changes must update the relevant
  file under `docs/` and [CHANGELOG.md](CHANGELOG.md).

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Workflow

1. Branch from the current default branch.
2. Make the change with tests.
3. Run the full quality gate locally (below).
4. Open a PR describing the change and its security impact. CI must pass.

## Quality gates (must pass locally and in CI)

```bash
ruff check .        # lint
ruff format .       # formatting
mypy                # strict type checking
pytest              # full test suite (live MySQL tests auto-skip)
```

CI additionally runs `pip-audit` and fails on any known-vulnerable dependency
(see `.github/workflows/ci.yml`). Keep dependency bounds tight and re-verify on
every bump.

## Mandatory testing standards for tool (`json-schema`) definitions

Every MCP tool is exposed to the model as a JSON Schema. A wrong or vague schema
causes the LLM to call the tool incorrectly or avoid it — a downstream reasoning
break that unit tests of business logic won't catch. Therefore **every tool
must satisfy all of the following, enforced by tests:**

1. **Primitive parameters only.** Parameters must be `str`, `int`, `float`, or
   `bool` (or `None`) declared with `Annotated[<type>, Field(description=...)]`.
   No `dict`, no `list`, no `Any`. Structured input (e.g. bind values) travels
   as a JSON-encoded **string** parameter (`params_json`) parsed and validated
   server-side.
2. **Every parameter has a description** written for an LLM — what it is and
   when to set it. Required vs optional must be correct (optional params have
   defaults).
3. **Display metadata is set twice** for client coverage:
   `@mcp.tool(title="…", annotations={"title": "…", "readOnlyHint": True})`.
   Every tool in this server is read-only, so `readOnlyHint` must be `True`.
4. **The docstring is the LLM's instruction manual** — it must state when to
   call the tool, the return shape, and the standard presentation guidance.
5. **Registration test coverage.** Add/extend
   `src/mysql_mcp/tests/unit/test_tools_registration.py` so that:
   - the tool appears in `EXPECTED_TOOLS`;
   - it carries a `title` and `annotations.readOnlyHint is True`;
   - it exposes **no** credential-like parameter (`host`/`port`/`user`/
     `password`/`username`) — this test is a security guardrail, not a nicety.
6. **Behavioral tests** via the FastMCP instance (`await mcp.call_tool(...)`),
   covering the success envelope and the error envelope
   (`"ERROR: <CODE>: <message>"`), including malformed input.

### Example: a well-formed tool parameter

```python
from typing import Annotated
from pydantic import Field

async def sample_rows(
    table: Annotated[str, Field(description="Table name to sample from.")],
    database: Annotated[str, Field(description="Database name (optional; uses the connection default).")] = "",
    limit: Annotated[int, Field(description="Rows to sample (default 5, max 50).", ge=1, le=50)] = 5,
    db_id: Annotated[str, Field(description="Named DB profile; omit for the default connection.")] = "",
) -> str:
    ...
```

## Architecture invariants (enforced by review)

The server uses a strict layering — keep imports flowing one way:

- `tools/` is the **only** package that imports `fastmcp`.
- `db.py` is the **only** module that imports `aiomysql`.
- `services/`, `sql_policy.py`, `identifiers.py`, `config.py`, `errors.py` are
  pure Python (no FastMCP, no driver).
- Every tool body delegates to the single `execute_tool()` gate in
  `tools/_utils.py` (credential resolution, policy, error sanitization, audit
  logging). Do not bypass it.

See [CLAUDE.md](CLAUDE.md) for the full "adding a new tool" recipe and
[docs/interface/primitives.md](docs/interface/primitives.md) for the current
tool contract.

## Adding or changing a tool — checklist

- [ ] Service method added in `services/` (identifiers quoted; values bound as `%s`)
- [ ] Nested `@mcp.tool()` added in the right `tools/*.py`, delegating to `execute_tool()`
- [ ] Primitive params with LLM-facing descriptions; `readOnlyHint: True`
- [ ] `test_tools_registration.py` updated (name, metadata, no-credential-params)
- [ ] Behavioral success + error tests added
- [ ] `docs/interface/primitives.md` and `CHANGELOG.md` updated
- [ ] `ruff` / `mypy` / `pytest` green
