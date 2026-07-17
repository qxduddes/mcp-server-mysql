# Enterprise Governance

Authentication & authorization, data isolation & privacy, and audit logging for
`mysql-mcp`. This document describes **what the server actually does today** and
marks every not-yet-implemented enterprise control with a `[TODO]`/roadmap note
and its internal finding ID (`SEC-xxx`). It does not describe capabilities the
code lacks.

> **Governing principle (zero-trust):** the app-layer policy is defense-in-depth.
> **The security boundary is the database grant.** Bind the server to a
> least-privilege, read-only MySQL account and the most severe residual risks
> are neutralized regardless of application behavior.

---

## Authentication & Authorization

### Transport authentication (client → server)

| Mode | Mechanism |
|---|---|
| stdio | None — the trust boundary is the local OS user that spawned the process. |
| Streamable HTTP | **Fail-closed static bearer token** (`MCP_AUTH_TOKEN`). Requests must send `Authorization: Bearer <token>`; invalid tokens are rejected (401) and logged at `WARNING`. Anonymous operation requires the explicit `MCP_ALLOW_ANON=1` escape hatch (isolated networks only). |

### Database authorization (server → MySQL)

Database credentials are resolved **server-side only** and never accepted as
tool parameters:

- **Multi-profile:** `DB_PROFILES` is a JSON map of named connection profiles;
  a caller selects one per request with the `db_id` tool parameter.
- **Single-connection fallback:** `MYSQL_*` environment variables, used when
  `db_id` is empty. There is no default user — unset `MYSQL_USER` disables the
  fallback and tools return `MISSING_CREDENTIALS`.

Credential material is held as `SecretStr` with exactly two unwrap points
(`config.py`), flowing straight into the database client and nowhere else.

### Identity inheritance & least privilege

> **Not implemented — no OAuth 2.1 / OIDC / IAM identity inheritance.** The
> server does **not** map an end-user identity to the database session. In HTTP
> mode all callers share one bearer token and one synthetic `client_id`, and any
> holder can reach every configured `DB_PROFILES` profile via `db_id`. There is
> no per-user or per-profile authorization decision.
>
> `[TODO: roadmap — SEC-003. Options: (a) token→allowed-profiles scoping so each
> token maps to a subset of profiles; (b) OIDC/OAuth 2.1 resource-server mode
> that validates a caller JWT and maps claims to a profile/grant. Neither is
> implemented today.]`

**Least privilege is enforced at the database, not the app.** Bind each profile
to a read-only account scoped to only the tables it needs:

```sql
CREATE USER 'mcp_ro'@'%' IDENTIFIED BY '<strong-secret>';
GRANT SELECT, SHOW VIEW ON app_db.* TO 'mcp_ro'@'%';
-- no FILE, no PROCESS, no CREATE/DROP/ALTER, no INSERT/UPDATE/DELETE, no SUPER
```

Verify `secure_file_priv` is set so `INTO OUTFILE` is inert even if a code path
were missed (`SHOW VARIABLES LIKE 'secure_file_priv'`).

---

## Data Isolation & Privacy

### Isolation & state

- **Per-call connections.** Each tool call opens a short-lived connection and
  closes it; there is **no shared connection pool and no cross-request state or
  session caching**. A prompt-injected call cannot influence a later call's
  session.
- **No connection retargeting.** No tool can change the host/user/password; a
  session is pinned to its resolved profile.
- **Single statement per call**, enforced by a quote/comment-aware scanner and
  `CLIENT.MULTI_STATEMENTS` disabled at the driver.

### Token / result limiting

- **Row cap** (`MYSQL_MAX_ROWS`, default 1000) applied via bounded fetch, so a
  large result cannot exhaust server memory or flood the model context. When a
  result is clipped, tools surface `truncated: true` (and `truncationNote` for
  schema tools) so partial data is never presented as complete.
- **Per-query time limit** (`MYSQL_QUERY_TIMEOUT_MS`, default 10 000 ms) and
  **connect timeout** (`MYSQL_CONNECT_TIMEOUT_S`, default 10 s).

### Confidentiality in transit & at rest (of secrets)

- TLS to the database is **required for non-loopback hosts** and always
  verifies certificate + hostname (`MYSQL_SSL`, `MYSQL_SSL_CA`); there is no
  verify-off option.
- Passwords are `SecretStr`; never logged, never returned, never in error text.

### PII masking

> **Not implemented in the application layer.** The server does not mask, redact,
> or classify PII in returned rows. Any data the connected account can read can
> be returned to the model — including via `sample_rows` (`SELECT *`).
>
> `[TODO: roadmap — SEC-006. Interim control: enforce PII protection at the
> database via least-privilege grants and PII-masked views, and point the server
> at non-production or sanitized data. An optional server-side column/table
> allowlist is a candidate app-layer defense-in-depth control.]`

### Prompt-injection blast radius

Returned rows are untrusted input to the model. The read-only scope breaks the
injection→write loop; the injection→read→surface path is a residual risk. The
server does not currently delimit returned data as untrusted or screen it.
`[TODO: roadmap — SEC-005; see also SECURITY.md.]`

---

## Audit Logging

Every tool call emits exactly one structured JSON record to the
`mysql_mcp.audit` logger (stderr by default; route it to your log sink).

**Record schema:**

| Field | Type | Description |
|---|---|---|
| `ts` | string (ISO 8601, tz-aware) | Call timestamp |
| `tool` | string | Tool name (e.g. `query`, `sample_rows`) |
| `db_id` | string | Profile selected, or `"-"` for the env-fallback connection |
| `operation` | string | Classified operation (e.g. `QUERY`, `SHOW_TABLES`, `DESCRIBE`) |
| `target` | string | Database/table target (never the SQL text) |
| `ok` | boolean | Success/failure |
| `rowCount` | integer \| null | Rows returned (success only) |
| `durationMs` | number | Wall-clock duration |
| `errorCode` | string | Present on failure (e.g. `MYSQL_ERROR`, `QUERY_REQUIRES_READ_ONLY_SQL`) |

**Example:**

```json
{"ts": "2026-07-17T10:15:00.123-05:00", "tool": "query", "db_id": "staging",
 "operation": "QUERY", "target": "staging", "ok": true, "rowCount": 42,
 "durationMs": 18.4}
```

**What is never logged:** SQL text, bind values, row contents, or credentials
(row values may carry PII; SQL text may carry sensitive literals).

### Gaps

> - **No caller/session identifier.** In HTTP mode all callers share one token,
>   so records cannot be attributed to a specific client. `[TODO: roadmap —
>   SEC-012; depends on per-client auth, SEC-003.]`
> - **No Human-in-the-Loop (HITL) validation triggers.** The server has no
>   approval/confirmation workflow for sensitive operations. It is read-only, so
>   there are no mutating actions to gate — but no HITL hook exists for, e.g.,
>   flagging access to sensitive tables. `[TODO: roadmap — HITL not implemented.]`

---

## Deployment checklist (governance)

- [ ] Least-privilege, read-only DB account per profile (no FILE/DDL/write/SUPER).
- [ ] `secure_file_priv` set so `INTO OUTFILE` is inert.
- [ ] Server pointed at dev/staging or a PII-masked replica, not production.
- [ ] Credentials via environment / secrets manager only — never in chat/tool params.
- [ ] HTTP mode: strong `MCP_AUTH_TOKEN`; TLS terminated at a proxy; port not
      exposed to untrusted networks.
- [ ] `MYSQL_SSL=true` for any remote database.
- [ ] Audit log (`mysql_mcp.audit`) shipped to your monitoring sink; alert on
      spikes in `FORBIDDEN_READ_CONSTRUCT` / `QUERY_REQUIRES_READ_ONLY_SQL`
      (probing signal).
- [ ] Dependencies pinned; `pip-audit` green in CI; `uvx`/git deploys pin a tag.
