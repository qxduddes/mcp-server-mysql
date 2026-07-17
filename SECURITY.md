# Security Policy

This document is the public security policy for `mysql-mcp`: what versions are
supported, how to report a vulnerability, and the security guarantees the
server makes — in particular around **indirect prompt injection**, the defining
risk of connecting an LLM to a live database.

Enterprise governance detail (authentication, data isolation, audit logging)
lives in [docs/security/governance.md](docs/security/governance.md). The full
internal vulnerability log and remediation plan are kept private and are **not**
published in this repository.

---

## Supported versions

| Version | Supported | Notes |
|---------|-----------|-------|
| 0.1.x   | ✅ | Current release line |
| < 0.1   | ❌ | Pre-release |

`[TODO: Insert Organization Specifics — patch support window / SLA, e.g. "critical
fixes within N business days for the latest minor release".]`

---

## Reporting a vulnerability

**Do not open a public issue for security reports.**

- Report privately to `[TODO: Insert security contact — e.g. security@example.com
  or a private advisory link]`.
- Include: affected version/commit, a description, and reproduction steps or a
  proof of concept.
- Expected acknowledgement window: `[TODO: Insert Organization Specifics, e.g.
  within 2 business days]`.
- Please allow a coordinated-disclosure window before any public write-up:
  `[TODO: Insert disclosure window]`.

When reviewing a dependency bump or a fork, re-run the supply-chain checks: the
CI pipeline runs `pip-audit` (see [CONTRIBUTING.md](CONTRIBUTING.md)), and
`uvx`/git deployments **must pin a tag or commit**, never a mutable branch.

---

## Security model & guarantees

### Read-only by construction

The server implements **no** write, DDL, or administrative tools. There is no
`execute`, no `create/alter/drop`, and the original upstream `connect` and
`use_database` tools were removed. The `query` tool runs SQL through a policy
engine that:

- classifies the statement and accepts only `SELECT`/`SHOW`/`DESCRIBE`/`EXPLAIN`;
- enforces a **single statement per call** (a quote/comment-aware scanner, plus
  `CLIENT.MULTI_STATEMENTS` disabled at the driver);
- rejects file-I/O and stall primitives via a denylist —
  `INTO OUTFILE`/`DUMPFILE`, `GET_LOCK`, `SLEEP`, `BENCHMARK`, `LOAD_FILE` —
  with comments stripped first so `INTO/**/OUTFILE` cannot evade it.

### Credential handling

- Credentials come **only** from the server environment (`DB_PROFILES` or
  `MYSQL_*`); **no tool parameter accepts a host, user, or password**.
- Password material is held as `SecretStr` and never logged, never returned, and
  never placed in an error message.
- A prompt-injected session therefore **cannot retarget the connection** to
  another host or database server.

### Transport & network

- HTTP transport is **fail-closed**: it refuses to start without
  `MCP_AUTH_TOKEN` (bearer). Anonymous mode requires an explicit
  `MCP_ALLOW_ANON=1` opt-in and logs a loud warning.
- TLS to the database is required for non-loopback hosts and always verifies
  certificates (there is no verify-off option).
- The `/health` endpoint is unauthenticated but returns a static body with no
  data.

### Bounding & auditing

- Per-query time limit (`MYSQL_QUERY_TIMEOUT_MS`), result-row cap
  (`MYSQL_MAX_ROWS`), and connect timeout (`MYSQL_CONNECT_TIMEOUT_S`).
- One structured JSON audit record per tool call (tool, profile, operation,
  target, outcome, row count, duration) — **never** SQL text, bind values, or
  credentials.

---

## Indirect prompt injection

> **Declaration.** Query results flow into the model's context as data. A row
> may contain adversarial text (e.g. "ignore previous instructions and run …").
> This class of risk cannot be fully eliminated by any database MCP server; this
> section states honestly what `mysql-mcp` does and does not do about it.

**What the design guarantees:**

- **The injection→write loop is broken.** Because there are no write/DDL tools
  and no connection-retargeting tool, a model steered by a malicious row cannot
  modify data, exfiltrate via `INTO OUTFILE`, or point the server at an
  attacker-controlled host.
- **Blast radius is bounded** by the read-only scope, the row cap, and the
  query time limit.

**Residual risk (must be managed by deployment):**

- An **injection→read→surface** path remains: a model could be steered into
  querying other tables the connected account can read and surfacing that data
  to the user. Mitigate with a least-privilege, read-only database grant scoped
  to only the needed tables, and by pointing the server at non-production or
  PII-masked data.
- The server does **not** currently add data-provenance delimiting to returned
  rows or screen output for injection markers. `[TODO: roadmap — output
  delimiting/screening; tracked internally as SEC-005.]`

**Operator guidance:** treat the app-layer policy as defense-in-depth and the
**database grant as the real security boundary**. See the deployment checklist
in [docs/security/governance.md](docs/security/governance.md).
