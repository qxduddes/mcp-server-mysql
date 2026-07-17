# MCP Contract — Transport

`mysql-mcp` selects its transport at startup from the `MCP_TRANSPORT`
environment variable. Two transports are supported: **stdio** (local
development / desktop clients) and **Streamable HTTP** (production / shared
deployments). The legacy **SSE** transport has been removed.

```bash
MCP_TRANSPORT=stdio  python -m mysql_mcp.server   # or: python server.py  (default)
MCP_TRANSPORT=http   python server.py             # streamable HTTP at /mcp
```

---

## Comparison

| Aspect | `stdio` (local dev) | `http` (production) |
|---|---|---|
| Wire | JSON-RPC over stdin/stdout | MCP Streamable HTTP at `POST /mcp` |
| Launch | Client spawns the process as a subprocess | Long-running server / container |
| Authentication | None (trust boundary is the local process) | **Fail-closed bearer token** (`Authorization: Bearer <token>`) |
| Multi-tenant | Single connection (env fallback), typically | Multi-profile via `DB_PROFILES` + `db_id` |
| Health probe | n/a (`/health` inert) | `GET /health` → `{"status":"ok"}` (unauthenticated, data-free) |
| Typical client | Claude Desktop, Cursor, Claude Code | Enterprise AI gateway, remote agents |
| Default bind | n/a | `MCP_HOST=0.0.0.0`, `MCP_PORT=8004` |

---

## stdio

The default. The MCP client launches the server as a child process and speaks
JSON-RPC over stdin/stdout. **Logs (including the audit log) go to stderr**, so
they never corrupt the protocol stream on stdout.

There is no authentication layer — the security boundary is the local user
account that spawned the process. Use stdio for desktop clients and local
development. See [../setup.md](../setup.md) and [`../../examples/`](../../examples/)
for client configuration.

---

## Streamable HTTP

Production transport. The server exposes the MCP Streamable HTTP endpoint at
`POST /mcp` and an unauthenticated liveness probe at `GET /health`.

**Fail-closed authentication.** In HTTP mode the server **refuses to start**
without `MCP_AUTH_TOKEN`:

```
ERROR: HTTP transport requires MCP_AUTH_TOKEN. Clients must send
'Authorization: Bearer <token>'. Set MCP_ALLOW_ANON=1 to run without
authentication on an isolated, trusted network only.
```

- Clients authenticate with `Authorization: Bearer <token>`.
- Invalid tokens are rejected (401) and logged at `WARNING`.
- Anonymous mode requires the explicit escape hatch `MCP_ALLOW_ANON=1` (the
  literal string `1`) and logs a loud warning — intended for isolated/trusted
  networks only.

> **Authorization scope.** The bearer token is a single shared secret; any
> holder can address every profile configured in `DB_PROFILES` via `db_id`.
> Per-client / per-profile authorization is **not yet implemented**. See
> [../security/governance.md](../security/governance.md) (SEC-003).

**TLS.** Terminate TLS in front of the server (reverse proxy / load balancer);
do not expose the port directly to untrusted networks. TLS to the **database**
is configured separately (`MYSQL_SSL`) and is mandatory for non-loopback hosts.

**The `/health` route** deliberately returns a static body with no
configuration or version information and performs no database probing, so a
database outage cannot cause a load balancer to recycle a healthy instance. It
bypasses bearer auth by design (only `/mcp` is token-protected).

---

## SSE (removed)

The legacy Server-Sent Events transport (`/sse` + `/messages/`) has been
removed. Setting `MCP_TRANSPORT=sse` exits with a migration error:

```
ERROR: The SSE transport is not supported. Set MCP_TRANSPORT=http — the server
uses the streamable-HTTP transport; clients connect to http://<host>:<port>/mcp.
```

Migrate SSE clients to the Streamable HTTP endpoint at `/mcp`.

---

## Transport-related environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `MCP_HOST` | `0.0.0.0` | HTTP bind host |
| `MCP_PORT` | `8004` | HTTP bind port |
| `MCP_AUTH_TOKEN` | *(required for http)* | Bearer token; HTTP refuses to start without it |
| `MCP_ALLOW_ANON` | *(unset)* | Literal `1` = run HTTP without auth (isolated networks only) |

Database-connection variables are documented in [../setup.md](../setup.md).
