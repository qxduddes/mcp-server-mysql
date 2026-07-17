# MCP Contract — Primitives

The MCP interface exposed by `mysql-mcp`. This server implements the **Tools**
primitive only. **Resources** and **Prompts** are not implemented (see the
sections at the end).

- **Success envelope:** pretty-printed JSON (`json.dumps(result, indent=2)`).
  MySQL types are serialized as: `datetime`/`date`/`time` → ISO 8601, `Decimal`
  → string, `bytes` → UTF-8 (with replacement).
- **Error envelope:** a plain string `"ERROR: <CODE>: <message>"` (see
  [Error codes](#error-codes)).
- **Every tool** accepts an optional `db_id` selecting a named `DB_PROFILES`
  profile; omit it to use the single-connection environment fallback.
- **Every tool** is read-only (`annotations.readOnlyHint = true`).

---

## Tools Catalog

Parameter types are given in JSON Schema terms (the wire contract the model
sees). All string parameters that default to `""` are optional.

### `query`

Execute one read-only SQL statement and return rows.

| Field | Value |
|---|---|
| **Description (for LLMs)** | "Execute a read-only SQL query (SELECT/SHOW/DESCRIBE/EXPLAIN) and return rows as JSON. Use `%s` placeholders for bind values passed via `params_json`." |
| **Required params** | `sql: string` |
| **Optional params** | `params_json: string` (JSON array of scalar bind values, e.g. `["ACME", 10]`), `db_id: string` |
| **Output schema** | `{ "rows": object[], "rowCount": integer, "truncated": boolean, "maxRows": integer \| null }` |

```json
{
  "type": "object",
  "properties": {
    "sql": {"type": "string", "description": "One read-only SQL statement (SELECT/SHOW/DESCRIBE/EXPLAIN). Multi-statement input is rejected. Use %s placeholders."},
    "params_json": {"type": "string", "description": "Optional JSON array of scalar bind values for %s placeholders, e.g. '[\"ACME\", 10]'.", "default": ""},
    "db_id": {"type": "string", "description": "Optional named database profile; omit for the server default connection.", "default": ""}
  },
  "required": ["sql"]
}
```

### `explain_query`

Return the execution plan of a single `SELECT`.

| Field | Value |
|---|---|
| **Description (for LLMs)** | "Run EXPLAIN on a SELECT query and return the execution plan (traditional or JSON format)." |
| **Required params** | `sql: string` |
| **Optional params** | `params_json: string`, `format: string` (`"traditional"` \| `"json"`, default `"traditional"`), `db_id: string` |
| **Output schema** | `{ "format": string, "originalSql": string, "explainSql": string, "rowCount": integer, "rows": object[] }` |

### `list_databases`

| Field | Value |
|---|---|
| **Description (for LLMs)** | "List all databases visible to the configured MySQL account." |
| **Required params** | *(none)* |
| **Optional params** | `db_id: string` |
| **Output schema** | `{ "databases": string[] }` |

### `list_tables`

| Field | Value |
|---|---|
| **Description (for LLMs)** | "List tables in a database (uses the connection's default database if none is given)." |
| **Required params** | *(none)* |
| **Optional params** | `database: string`, `db_id: string` |
| **Output schema** | `{ "tables": string[], "database": string \| null, "truncated"?: boolean, "truncationNote"?: string }` |

### `describe_table`

| Field | Value |
|---|---|
| **Description (for LLMs)** | "Get the column structure of a table (DESCRIBE output): field, type, nullability, key, default, extra." |
| **Required params** | `table: string` |
| **Optional params** | `database: string`, `db_id: string` |
| **Output schema** | `{ "table": string, "database": string, "columns": [{ "Field": string, "Type": string, "Null": string, "Key": string, "Default": any, "Extra": string }] }` |

### `inspect_schema`

| Field | Value |
|---|---|
| **Description (for LLMs)** | "Inspect all tables, columns, and indexes of a database at once — a whole-schema overview." |
| **Required params** | *(none)* |
| **Optional params** | `database: string`, `include_columns: boolean` (default `true`), `include_indexes: boolean` (default `true`), `db_id: string` |
| **Output schema** | `{ "database": string, "tableCount": integer, "tables": [{ "tableName": string, "tableType": string, "engine": string, "rowsEstimate": integer, "tableComment": string, "columns": object[], "indexes": object[] }], "truncated"?: boolean, "truncationNote"?: string }` |

### `find_tables`

| Field | Value |
|---|---|
| **Description (for LLMs)** | "Find tables by matching a substring against table and column names." |
| **Required params** | `term: string` |
| **Optional params** | `database: string`, `db_id: string` |
| **Output schema** | `{ "database": string, "term": string, "matchCount": integer, "matches": [{ "tableName": string, "tableType": string, "engine": string, "matchedTableName": boolean, "matchedColumns": string[] }], "truncated"?: boolean, "truncationNote"?: string }` |

### `sample_rows`

| Field | Value |
|---|---|
| **Description (for LLMs)** | "Read a small sample of rows from a table (capped at 50) to see what the data looks like." |
| **Required params** | `table: string` |
| **Optional params** | `database: string`, `limit: integer` (1–50, default 5), `db_id: string` |
| **Output schema** | `{ "database": string, "table": string, "limit": integer, "rowCount": integer, "rows": object[] }` |

### `health_check`

| Field | Value |
|---|---|
| **Description (for LLMs)** | "Check MySQL connection health and basic server status (version, uptime, connections)." |
| **Required params** | *(none)* |
| **Optional params** | `db_id: string` |
| **Output schema** | `{ "healthy": true, "pingLatencyMs": number, "serverVersion": string, "uptime": string, "threadsConnected": string, "totalQueries": string }` — or `{ "healthy": false, "error": string }` |

---

## Writing queries (rules the model must follow)

- `query` accepts only `SELECT`/`SHOW`/`DESCRIBE`/`DESC`/`EXPLAIN`;
  `explain_query` accepts `SELECT` only.
- **One statement per call** — a second statement after `;` is refused
  (`MULTI_STATEMENT_SQL`).
- **Bind values use `%s` placeholders** (PyMySQL style, not `?`), passed as a
  JSON array string:

  ```json
  {
    "sql": "SELECT name FROM users WHERE org = %s AND age > %s",
    "params_json": "[\"ACME\", 30]"
  }
  ```

- File-I/O and stall functions are refused in any read query
  (`FORBIDDEN_READ_CONSTRUCT`): `INTO OUTFILE`, `INTO DUMPFILE`, `GET_LOCK`,
  `SLEEP`, `BENCHMARK`, `LOAD_FILE` (comments are stripped before scanning, so
  `INTO/**/OUTFILE` is also caught).
- Statements starting with `WITH` (CTEs) are currently unsupported — rewrite as
  a derived table: `SELECT ... FROM (SELECT ...) x`.
- Results are capped at `MYSQL_MAX_ROWS` (default 1000). When `truncated` is
  `true`, narrow the query with `WHERE`/`LIMIT`.

---

## Error codes

Failures return `"ERROR: <CODE>: <message>"`.

| Code | Meaning |
|---|---|
| `QUERY_REQUIRES_READ_ONLY_SQL` | Non-read statement sent to `query` |
| `FORBIDDEN_READ_CONSTRUCT` | File-I/O / lock / stall function in a read query |
| `MULTI_STATEMENT_SQL` | More than one statement in a call |
| `UNTERMINATED_COMMENT` | Unclosed `/* ... */` |
| `EXPLAIN_REQUIRES_SELECT` | `explain_query` got a non-SELECT |
| `INVALID_EXPLAIN_FORMAT` | `format` not `traditional`/`json` |
| `INVALID_PARAMS` | `params_json` not a JSON array of scalars |
| `INVALID_IDENTIFIER` | Empty/null-byte database or table name |
| `DATABASE_REQUIRED` | No database given and none configured |
| `MISSING_SEARCH_TERM` | Empty `term` in `find_tables` |
| `INVALID_DB_ID` | Malformed `db_id` |
| `UNKNOWN_PROFILE` | `db_id` not present in `DB_PROFILES` |
| `MISSING_CREDENTIALS` | No profile and no env fallback configured |
| `MYSQL_ERROR` | Sanitized MySQL server/driver error (includes errno) |

---

## Response presentation

The server ships MCP `instructions` telling the model to present results in
plain language (no tool names, no raw JSON, Markdown tables, human-readable
dates/numbers, note truncation) and to politely refuse write requests. Each
tool's docstring carries matching per-tool rendering guidance.

---

## Resources Blueprint

> **Not implemented.** This server does not expose any MCP Resources (read-only
> custom URI schemes such as `company://system/path`). All data access is
> through the Tools above.
>
> `[TODO: roadmap — if resource-style read access is desired (e.g.
> `mysql://<profile>/<database>/<table>` returning a schema or sample as a
> resource), it would be added here. Not currently planned.]`

## Prompts Catalog

> **Not implemented.** This server exposes no predefined MCP Prompts
> (parameterized templates).
>
> `[TODO: roadmap — candidate prompts such as "explain this schema" or "draft a
> safe analytical query" could be exposed here. Not currently planned.]`
