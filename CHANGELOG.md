# Changelog

All notable changes to `mysql-mcp` are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/); this project adheres
to semantic versioning.

Security rationale references the internal audit (finding IDs `SEC-xxx` / audit
`Pn-x`); the detailed findings and remediation plan are kept private (not
published in this repository). See [SECURITY.md](SECURITY.md) for the public
security policy.

---

## [0.1.0] — 2026-07

Initial release: a security-hardened, **read-only** Python/FastMCP port of
[@nilsir/mcp-server-mysql](https://github.com/nilsir/mcp-server-mysql) v2.0.0.

### Changed vs. the TypeScript original

This is a deliberate, hardened, read-only port — not a 1:1 clone.

**Removed**

| Removed | Why |
|---|---|
| `connect` tool | Audit P1-2: it let the model pass host/user/password at runtime — credentials in the model context and a prompt-injection pivot to arbitrary hosts. Credentials are env-only now. |
| `use_database` tool | Audit LOW: executed `USE` with no policy gate and behaved unreliably over a pool. Every tool takes an optional `database` parameter instead. |
| `execute`, `dry_run_execute` | Read-only scope. |
| `create/alter/drop_table`, `create/drop_index`, `create/drop_database` | Read-only scope. Also moots audit P2-5 (raw string interpolation in the TS DDL builders). |
| `MYSQL_MODE`, `MYSQL_ALLOW_INSERT/UPDATE/DELETE/DDL` env vars | Meaningless without write tools; read-only is enforced by construction. |
| Confirm-must-match-target gates | Only protected the dropped destructive tools. |
| `user` default `root`, `password` default `""` | Audit LOW (insecure defaults): there is no default user; unset `MYSQL_USER` disables the env fallback. |

**Added (hardening)**

| Added | Detail |
|---|---|
| Forbidden-read denylist | `INTO OUTFILE`/`DUMPFILE`, `GET_LOCK`, `SLEEP`, `BENCHMARK`, `LOAD_FILE` rejected in read-classified SQL (`FORBIDDEN_READ_CONSTRUCT`). Audit P2-4. |
| TLS support | `MYSQL_SSL=true` with mandatory certificate + hostname verification; `MYSQL_SSL_CA` for private CAs. No verify-off option. Audit P2-6. |
| Centralized gate | All 9 tools route through one `execute_tool()` (credentials, policy, sanitization, audit). Audit P2-7. |
| Structured audit logging | One JSON record per tool call; never SQL text, values, or credentials. Audit P3-9. |
| Timeouts & caps | `MYSQL_CONNECT_TIMEOUT_S`, statement timeout via `MYSQL_QUERY_TIMEOUT_MS`, `MYSQL_MAX_ROWS`. Audit P3-10. |
| Multi-profile credentials | `DB_PROFILES` JSON env map + `db_id` tool parameter for shared HTTP deployments. |
| HTTP transport, fail-closed bearer auth | `MCP_AUTH_TOKEN` required, `MCP_ALLOW_ANON=1` escape hatch, data-free `/health`, Docker image, port 8004. The TS original was stdio-only. |
| `MYSQL_MAX_ROWS` default | TS defaulted to unlimited; this port defaults to 1000 (`0` disables). |

**Interface differences**

| Aspect | TS original | This port |
|---|---|---|
| Bind parameters | `params?: unknown[]` array | `params_json: str` — JSON array of scalars, validated server-side (`INVALID_PARAMS`). MCP params stay primitive. |
| Placeholder syntax | `?` (mysql2) | `%s` (PyMySQL/aiomysql). |
| Tool parameter names | camelCase | snake_case (`include_columns`, `db_id`) |
| Response keys | camelCase | camelCase (unchanged — `rowCount`, `tableName`, …) |
| Success envelope | JSON text + `structuredContent` | `json.dumps(..., indent=2)`; datetime → ISO 8601, Decimal → string, bytes → UTF-8 (replace) |
| Error envelope | `isError: true` + object | `"ERROR: <CODE>: <message>"` string; original codes preserved, new codes added |
| `sample_rows` limit | default 5, max 50 | Same, plus schema-level `ge=1 le=50` |
| `health_check` failure | `healthy: false` JSON | Same (JSON body, not an ERROR string) |

**Faithful quirks kept**

- First-keyword classification: `WITH` (CTEs) rejected as unsupported (future work).
- Row-cap semantics: when truncated, `rowCount` reports the cap, not the true total.
- Backtick strings ignore backslash escapes in the single-statement scanner.
- `describe_table` returns raw `DESCRIBE` rows; `inspect_schema` returns
  normalized camelCase `information_schema` shapes.

### Security hardening (second-pass audit, 2026-07-17)

- **Bounded fetch** — `execute` uses `fetchmany(max_rows + 1)` instead of
  `fetchall()`-then-slice; a huge result set can no longer exhaust memory
  (SEC-001). `MYSQL_MAX_ROWS=0` is an explicit opt-in to unbounded fetch.
- **Denylist comment-hardening** — comments stripped before the forbidden-read
  scan, closing the `INTO/**/OUTFILE` bypass (SEC-002).
- **Portable statement timeout** — MariaDB `max_statement_time` (s) vs MySQL
  `MAX_EXECUTION_TIME` (ms); degrades with a warning if unsupported, fixing
  total breakage on MariaDB/RDS-MariaDB (SEC-007).
- **Schema-truncation transparency** — `list_tables`/`inspect_schema`/
  `find_tables` emit `truncated`/`truncationNote` when the row cap clips a
  metadata result (SEC-008).
- **TLS fail-closed for remote** — plaintext to non-loopback hosts refused
  (SEC-010).
- **Supply-chain gate** — `pip-audit` in CI alongside ruff/mypy/pytest (SEC-009).

### Known open items (roadmap)

Tracked internally (see [SECURITY.md](SECURITY.md) and
[docs/security/governance.md](docs/security/governance.md)):

- Per-profile / per-client token authorization for multi-tenant HTTP (SEC-003).
- Rate limiting + bounded connection pool (SEC-004).
- LLM prompt-injection output delimiting/screening (SEC-005).
- Optional column/table allowlist for defense-in-depth PII control (SEC-006).
- CTE (`WITH`) support in the read classifier.
