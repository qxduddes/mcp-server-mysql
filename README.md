# mysql-mcp

> **Secure, read-only MySQL access for AI agents.** A Model Context Protocol
> (MCP) server that lets Claude, Cursor, and other MCP clients explore and
> query MySQL/MariaDB databases — with no ability to write, no way to retarget
> the connection, and no credentials in the model context.

Python (FastMCP) port of
[@nilsir/mcp-server-mysql](https://github.com/nilsir/mcp-server-mysql),
restricted to the read-only tool surface and hardened against the risks of
connecting an LLM to a live database.

---

## Value proposition

Enterprise data lives in MySQL/MariaDB (application databases, analytics
replicas, Amazon RDS/Aurora). `mysql-mcp` exposes that data to AI agents and
analysts **for reading only** through a zero-trust-oriented interface:

- **Read-only by construction** — there are no write/DDL tools. The `query`
  tool accepts only `SELECT`/`SHOW`/`DESCRIBE`/`EXPLAIN` and additionally
  blocks file-I/O and stall primitives (`INTO OUTFILE`, `SLEEP`, `GET_LOCK`,
  `BENCHMARK`, `LOAD_FILE`).
- **Credentials never enter the model context** — connection details come only
  from the server's environment; no tool accepts a host, user, or password.
- **Fail-closed HTTP** — the network transport refuses to start without a
  bearer token.
- **Bounded** — per-query time limits, a result-row cap, connect timeouts, and
  single-statement enforcement.
- **Auditable** — one structured JSON log record per tool call (never SQL text,
  values, or credentials).

The read-only scope and these controls answer the audit that drove this port;
see [SECURITY.md](SECURITY.md) and [docs/security/governance.md](docs/security/governance.md).

---

## Capabilities (9 read-only tools)

| Tool | Purpose |
|------|---------|
| `query` | Run one `SELECT`/`SHOW`/`DESCRIBE`/`EXPLAIN` statement (with `%s` bind params) |
| `explain_query` | Return the execution plan of a `SELECT` (traditional or JSON) |
| `list_databases` | List databases |
| `list_tables` | List tables in a database |
| `describe_table` | Column structure of a table |
| `inspect_schema` | All tables + columns + indexes of a database at once |
| `find_tables` | Find tables by table/column name substring |
| `sample_rows` | Small row sample from a table (max 50) |
| `health_check` | Connection health + server status |

Full request/response schemas and error codes:
[docs/interface/primitives.md](docs/interface/primitives.md).

> **Note:** this server exposes MCP **Tools** only. It does **not** expose MCP
> Resources or Prompts (see the roadmap notes in
> [docs/interface/primitives.md](docs/interface/primitives.md)).

---

## Agent Integration Quickstart

First create a least-privilege MySQL account (do not use root):

```sql
CREATE USER 'mcp_ro'@'%' IDENTIFIED BY '<strong-secret>';
GRANT SELECT, SHOW VIEW ON app_db.* TO 'mcp_ro'@'%';
```

Then wire up your client. Ready-to-copy files live in [`examples/`](examples/).

### Claude Desktop (stdio, run straight from git via `uvx`)

Requires [`uv`](https://docs.astral.sh/uv/) (`brew install uv`). No clone, no
virtualenv — `uvx` fetches, builds, caches, and runs the `mysql-mcp` console
script. Edit *Settings → Developer → Edit Config*:

```json
{
  "mcpServers": {
    "mysql": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/<org>/mcp-mysql-server@<tag>",
        "mysql-mcp"
      ],
      "env": {
        "MYSQL_HOST": "your-db-host",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "mcp_ro",
        "MYSQL_PASSWORD": "<strong-secret>",
        "MYSQL_DATABASE": "app_db",
        "MYSQL_SSL": "true"
      }
    }
  }
}
```

> **Pin `@<tag>`** (e.g. `@v0.1.0`) — never track a mutable branch. Running
> unpinned code straight from git is a supply-chain risk.

### Cursor (stdio)

Add to `~/.cursor/mcp.json` (or the project `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "mysql": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/<org>/mcp-mysql-server@<tag>", "mysql-mcp"],
      "env": {
        "MYSQL_HOST": "your-db-host",
        "MYSQL_USER": "mcp_ro",
        "MYSQL_PASSWORD": "<strong-secret>",
        "MYSQL_DATABASE": "app_db",
        "MYSQL_SSL": "true"
      }
    }
  }
}
```

### Enterprise AI gateway (Streamable HTTP + bearer token)

For a shared, centrally-hosted deployment, run the server in HTTP mode (see
[docs/setup.md](docs/setup.md)) and point your gateway at it. Credentials for
one or more databases are configured **server-side** via `DB_PROFILES`; clients
select a profile per call with `db_id` and authenticate with a bearer token:

```json
{
  "mcpServers": {
    "mysql": {
      "type": "http",
      "url": "https://mysql-mcp.internal.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${MYSQL_MCP_TOKEN}"
      }
    }
  }
}
```

> **Authorization note:** the bearer token is a single shared secret; any holder
> can reach every configured `DB_PROFILES` profile. Per-client / per-profile
> authorization is **not yet implemented** — see
> [docs/security/governance.md](docs/security/governance.md) (SEC-003).

---

## Documentation

| Area | Document |
|------|----------|
| Deployment & onboarding | [docs/setup.md](docs/setup.md) |
| MCP contract (tools, schemas, errors) | [docs/interface/primitives.md](docs/interface/primitives.md) |
| Transports (stdio vs HTTP) | [docs/interface/transport.md](docs/interface/transport.md) |
| Enterprise governance (authn/authz, privacy, audit) | [docs/security/governance.md](docs/security/governance.md) |
| Security policy & reporting | [SECURITY.md](SECURITY.md) |
| Contributing & tool-testing standards | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Change history | [CHANGELOG.md](CHANGELOG.md) |
| Working with the codebase (for AI coding agents) | [CLAUDE.md](CLAUDE.md) |

## Requirements

- Python ≥ 3.12
- MySQL 5.7+/8.x or MariaDB 10.1+ to connect to
- Docker (optional, for the HTTP container)
- `uv` (optional, for `uvx` git-based launch)

## License & status

Version 0.1.0. See [CHANGELOG.md](CHANGELOG.md). `[TODO: Insert Organization
license and support statement]`.
