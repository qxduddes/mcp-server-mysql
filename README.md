# mysql-mcp

**Security-hardened, read-only MySQL MCP server.**

A Python (FastMCP) port of
[@nilsir/mcp-server-mysql](https://github.com/nilsir/mcp-server-mysql) v2.0.0,
restricted to the read-only tool surface and hardened per an internal security
audit (see [`audit/`](audit/) and [docs/SECURITY.md](docs/SECURITY.md)).

## What it does

Gives an MCP client (Claude Desktop, Claude Code, or any MCP-compliant app)
safe, read-only access to MySQL: run SELECT queries, explore schemas, explain
query plans, and sample data — with no way to write, no way to retarget the
connection, and no credentials in the model context.

## Tools (all read-only)

| Tool | Purpose |
|---|---|
| `query` | Run one SELECT / SHOW / DESCRIBE / EXPLAIN statement (with `%s` bind params) |
| `explain_query` | EXPLAIN a SELECT (traditional or JSON format) |
| `list_databases` | List databases |
| `list_tables` | List tables in a database |
| `describe_table` | Column structure of a table |
| `inspect_schema` | All tables + columns + indexes of a database at once |
| `find_tables` | Find tables by table/column name substring |
| `sample_rows` | Small row sample from a table (max 50) |
| `health_check` | Connection health + server status |

## Security posture

- **Read-only by construction** — no execute/DDL tools exist; the `query`
  classifier accepts read statements only and additionally blocks
  `INTO OUTFILE`/`DUMPFILE`, `SLEEP`, `GET_LOCK`, `BENCHMARK`, `LOAD_FILE`.
- **Env-only credentials** — the original's `connect` tool (runtime
  credentials as tool parameters) is removed; a prompt-injected session
  cannot repoint the connection.
- **Single statement per call**, enforced by a quote/comment-aware scanner
  *and* `CLIENT.MULTI_STATEMENTS` off at the driver.
- **TLS with mandatory certificate verification** (`MYSQL_SSL=true`); no
  verify-off option exists.
- **Fail-closed HTTP auth** — HTTP mode refuses to start without
  `MCP_AUTH_TOKEN`.
- **Centralized gate + audit log** — every call goes through one policy/
  credential/audit chokepoint; one JSON audit record per call, never SQL text
  or credentials.
- **Timeouts and caps** — connect timeout, `MAX_EXECUTION_TIME` per query,
  row cap (default 1000).

The full audit-finding → mitigation matrix and the deployment checklist
(least-privilege GRANT, `secure_file_priv`, non-production data) are in
[docs/SECURITY.md](docs/SECURITY.md).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

**stdio (Claude Desktop / Claude Code):**

```json
{
  "mcpServers": {
    "mysql-mcp": {
      "command": "/path/to/.venv/bin/python",
      "args": ["/path/to/mcp-mysql-server/server.py"],
      "env": {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_USER": "mcp_ro",
        "MYSQL_PASSWORD": "<secret>",
        "MYSQL_DATABASE": "app_db"
      }
    }
  }
}
```

**HTTP / Docker (multi-profile):**

```bash
docker build -t mysql-mcp .
docker run -d -p 8004:8004 \
  -e MCP_AUTH_TOKEN='<token>' \
  -e DB_PROFILES='{"staging":{"host":"db.internal","user":"mcp_ro","password":"<secret>","database":"app_db"}}' \
  mysql-mcp
# clients → http://host:8004/mcp with Authorization: Bearer <token>, db_id="staging"
```

Create the MySQL account first:

```sql
CREATE USER 'mcp_ro'@'%' IDENTIFIED BY '<strong-secret>';
GRANT SELECT, SHOW VIEW ON app_db.* TO 'mcp_ro'@'%';
```

## Documentation

| Doc | Contents |
|---|---|
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Setup, configuration, env var reference, verification |
| [docs/USAGE.md](docs/USAGE.md) | Tool reference, query rules, error codes, audit log |
| [docs/SECURITY.md](docs/SECURITY.md) | Audit-finding matrix, deployment checklist |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 3-layer design, request lifecycle, credential model |
| [docs/CONVERSION_PLAN.md](docs/CONVERSION_PLAN.md) | The TS → Python port plan and module map |
| [docs/CHANGES.md](docs/CHANGES.md) | Every divergence from the TypeScript original |
| [docs/TESTING.md](docs/TESTING.md) | Test suite layout, live-MySQL recipe |
| [audit/](audit/) | The original security audit + recommendations (PDF) |

## Development

```bash
pip install -e ".[dev]"
ruff check .        # lint
mypy                # strict type check
pytest              # 185 unit tests (~0.5 s); live tests skipped by default
```

## Architecture (one paragraph)

Strict 3-layer FastMCP package: `tools/` (interface — the only FastMCP
import) → `services/` (pure-Python logic) → `db.py` (the only aiomysql
import), with a pure `sql_policy.py` engine and a single `execute_tool()`
gate through which every call is credential-resolved, policy-checked,
sanitized, and audit-logged. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
