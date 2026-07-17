# Setup & Deployment

A sequential path from zero to a verified connection. Four stages:

1. [Environment secret provisioning](#1-environment-secret-provisioning)
2. [Local client configuration](#2-local-client-configuration)
3. [Production gateway / container deployment](#3-production-gateway--container-deployment)
4. [Capability verification](#4-capability-verification)

**Requirements:** Python ≥ 3.12; MySQL 5.7+/8.x or MariaDB 10.1+; optionally
Docker (HTTP container) and [`uv`](https://docs.astral.sh/uv/) (for `uvx`
git-based launch).

---

## 1. Environment secret provisioning

### 1a. Create a least-privilege, read-only MySQL account

Never connect as root. Scope the grant to only what the agent needs:

```sql
CREATE USER 'mcp_ro'@'%' IDENTIFIED BY '<strong-secret>';
GRANT SELECT, SHOW VIEW ON app_db.* TO 'mcp_ro'@'%';
-- no FILE, no DDL, no write, no SUPER
```

Point the server at dev/staging or a PII-masked replica, not production. See
[security/governance.md](security/governance.md) for the full rationale.

### 1b. Choose a credential model and provision secrets

| Model | Use when | Variables |
|---|---|---|
| **Single connection** | Local / desktop, one database | `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` |
| **Multi-profile** | Shared HTTP server, several databases | `DB_PROFILES` (JSON map); callers pass `db_id` |

Provision these via your platform's secret store (environment injection, AWS
SSM/Secrets Manager, Vault, etc.). `[TODO: Insert Organization Specifics — which
secret store and injection mechanism your environment uses.]`

**Full environment variable reference:**

| Variable | Default | Purpose |
|---|---|---|
| `MYSQL_HOST` | `127.0.0.1` | Fallback connection host |
| `MYSQL_PORT` | `3306` | Fallback connection port |
| `MYSQL_USER` | *(empty — fallback disabled)* | Fallback user; **no root default** |
| `MYSQL_PASSWORD` | *(empty)* | Fallback password (`SecretStr`) |
| `MYSQL_DATABASE` | *(empty)* | Fallback default database |
| `DB_PROFILES` | `{}` | JSON map of named profiles for `db_id` |
| `MYSQL_SSL` | `false` | Enable TLS (verification always required; mandatory for remote) |
| `MYSQL_SSL_CA` | *(empty)* | CA bundle path for private CAs |
| `MYSQL_MAX_ROWS` | `1000` | Result-row cap (`0` disables) |
| `MYSQL_QUERY_TIMEOUT_MS` | `10000` | Per-query time limit (`0` disables) |
| `MYSQL_CONNECT_TIMEOUT_S` | `10` | TCP connect timeout |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `MCP_HOST` | `0.0.0.0` | HTTP bind host |
| `MCP_PORT` | `8004` | HTTP bind port |
| `MCP_AUTH_TOKEN` | *(required for http)* | Bearer token; HTTP refuses to start without it |
| `MCP_ALLOW_ANON` | *(unset)* | Literal `1` = run HTTP without auth (isolated networks only) |

---

## 2. Local client configuration

Local clients use the **stdio** transport. Copy-pasteable files are in
[`../examples/`](../examples/).

### Option A — run from git with `uvx` (no clone, no venv)

`uvx` (from `uv`) fetches, builds, caches, and runs the `mysql-mcp` console
script. See [`../examples/claude_desktop_config.json`](../examples/claude_desktop_config.json)
and [`../examples/cursor_mcp.json`](../examples/cursor_mcp.json):

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

> **Pin `@<tag>`** (e.g. `@v0.1.0`) — never a mutable branch.

### Option B — cloned repo

```bash
git clone https://github.com/<org>/mcp-mysql-server && cd mcp-mysql-server
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

```json
{
  "mcpServers": {
    "mysql": {
      "command": "/path/to/mcp-mysql-server/.venv/bin/python",
      "args": ["/path/to/mcp-mysql-server/server.py"],
      "env": {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_USER": "mcp_ro",
        "MYSQL_PASSWORD": "<strong-secret>",
        "MYSQL_DATABASE": "app_db"
      }
    }
  }
}
```

Restart the client after editing its config.

---

## 3. Production gateway / container deployment

Production uses the **Streamable HTTP** transport with fail-closed bearer auth.
See [interface/transport.md](interface/transport.md).

### Docker

```bash
docker build -t mysql-mcp .
docker run -d --name mysql-mcp -p 8004:8004 \
  -e MCP_AUTH_TOKEN='<random-bearer-token>' \
  -e DB_PROFILES='{"staging":{"host":"db.internal","port":3306,"user":"mcp_ro","password":"<secret>","database":"app_db"}}' \
  -e MYSQL_SSL=true \
  mysql-mcp
```

A compose file is provided at
[`../examples/docker-compose.yml`](../examples/docker-compose.yml).

### Gateway wiring

Point your enterprise AI gateway / MCP client at `https://<host>/mcp` with
`Authorization: Bearer <token>` — see
[`../examples/enterprise_gateway_http.json`](../examples/enterprise_gateway_http.json).
Callers select a database with `db_id` per call.

Operational requirements:

- Terminate **TLS at a reverse proxy / load balancer**; do not expose port 8004
  directly to untrusted networks.
- Point health checks at `GET /health` (unauthenticated, static body).
- `[TODO: Insert Organization Specifics — gateway product, ingress/DNS, secret
  injection, and any per-team token issuance process. Note: per-profile token
  authorization is not yet implemented (SEC-003), so today one token reaches all
  profiles.]`

---

## 4. Capability verification

### Quick registration check (no credentials needed)

```bash
python - <<'EOF'
import asyncio, server
tools = asyncio.run(server.mcp.list_tools())
print(f"{len(tools)} tools:", sorted(t.name for t in tools))
EOF
# expect: 9 tools: ['describe_table', 'explain_query', 'find_tables',
#         'health_check', 'inspect_schema', 'list_databases', 'list_tables',
#         'query', 'sample_rows']
```

### MCP Inspector

Use the official [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
to connect and exercise the tools interactively:

```bash
# stdio
npx @modelcontextprotocol/inspector \
  uvx --from 'git+https://github.com/<org>/mcp-mysql-server@<tag>' mysql-mcp

# HTTP (server already running)
npx @modelcontextprotocol/inspector
# then connect to http://localhost:8004/mcp with header
# Authorization: Bearer <token>
```

Confirm: all 9 tools are listed with `readOnlyHint: true`; `health_check`
returns `healthy: true`; `list_databases`/`list_tables` return expected data.

### HTTP smoke test

```bash
curl -s http://localhost:8004/health                                  # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8004/mcp     # 401 (no bearer)
```

### Quality gates (from a clone)

```bash
pip install -e ".[dev]"
ruff check . && mypy && pytest
```
