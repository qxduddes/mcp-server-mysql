"""Read-only SQL policy (faithful port of sqlPolicy.ts, plus audit hardening).

Pure Python — no FastMCP, no database driver. Three responsibilities:

1. Single-statement enforcement: a quote- and comment-aware character scanner
   rejects any SQL containing a second real statement after a ``;``.
2. Classification: the first keyword (after leading comments) maps to a
   category. Only ``read`` (SELECT / SHOW / EXPLAIN / DESCRIBE / DESC) is ever
   executable in this server; the other categories exist purely to produce
   precise error messages.
3. Forbidden-read denylist (audit P2-4, new vs. the TS original): read-classified
   SQL is additionally scanned for file-writing and lock/stall primitives
   (INTO OUTFILE / DUMPFILE, GET_LOCK, SLEEP, BENCHMARK, LOAD_FILE).

Scanner semantics preserved from the original:
- Backslash escapes are honored inside ``'`` and ``"`` strings but NOT inside
  backtick identifiers.
- ``--`` and ``#`` start line comments; ``/* ... */`` is a block comment.
- A trailing ``;`` followed only by whitespace/comments is allowed.

Known faithful limitation: statements starting with ``WITH`` (CTEs) are
rejected because classification is first-keyword only (documented in
docs/CHANGES.md as future work).
"""

import re
from dataclasses import dataclass

from mysql_mcp.errors import QueryPolicyError

READ_OPERATIONS = frozenset({"SELECT", "SHOW", "EXPLAIN", "DESCRIBE", "DESC"})

_CATEGORY_BY_OPERATION: dict[str, str] = {
    "SELECT": "read",
    "SHOW": "read",
    "EXPLAIN": "read",
    "DESCRIBE": "read",
    "DESC": "read",
    "INSERT": "data-write",
    "UPDATE": "data-write",
    "DELETE": "data-write",
    "REPLACE": "data-write",
    "CREATE": "schema",
    "ALTER": "schema",
    "DROP": "schema",
    "TRUNCATE": "schema",
    "RENAME": "schema",
    "USE": "admin",
    "GRANT": "admin",
    "REVOKE": "admin",
    "FLUSH": "admin",
    "KILL": "admin",
    "SET": "admin",
}

# CREATE/DROP DATABASE|SCHEMA escalate to admin (faithful to the TS classifier).
_ADMIN_SECOND_KEYWORDS = frozenset({"DATABASE", "SCHEMA"})

_FIRST_KEYWORD_RE = re.compile(r"^([A-Za-z_]+)")
_SECOND_KEYWORD_RE = re.compile(r"^[A-Za-z_]+\s+([A-Za-z_]+)")
_TRAILING_SEMICOLONS_RE = re.compile(r";+\s*$")

# Audit P2-4: file I/O and lock/stall primitives are never legitimate in a
# read-only exploration query. Word-bounded, case-insensitive.
FORBIDDEN_READ_RE = re.compile(
    r"\b(INTO\s+(?:OUT|DUMP)FILE|GET_LOCK|SLEEP|BENCHMARK|LOAD_FILE)\b",
    re.IGNORECASE,
)

# SEC-002: MySQL treats comments as token separators, so `INTO/**/OUTFILE`
# parses as `INTO OUTFILE` and would slip past a `\s+`-based denylist. Strip
# comments (for analysis only) before scanning so multi-token constructs can't
# be split by an interposed comment.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"(--[^\n]*|#[^\n]*)")


def _strip_all_comments(sql: str) -> str:
    """Replace every comment with a space (analysis-only; never executed)."""
    return _LINE_COMMENT_RE.sub(" ", _BLOCK_COMMENT_RE.sub(" ", sql))


@dataclass(frozen=True)
class SqlClassification:
    """Result of classify_sql: first keyword, its category, normalized SQL."""

    operation: str
    category: str
    normalized_sql: str


def strip_leading_comments(sql: str) -> str:
    """Strip leading whitespace and any number of leading SQL comments."""
    rest = sql
    while True:
        rest = rest.lstrip()
        if rest.startswith("--") or rest.startswith("#"):
            newline = rest.find("\n")
            if newline == -1:
                return ""
            rest = rest[newline + 1 :]
        elif rest.startswith("/*"):
            end = rest.find("*/", 2)
            if end == -1:
                raise QueryPolicyError(
                    "UNTERMINATED_COMMENT",
                    "SQL contains an unterminated block comment. Close it with */.",
                )
            rest = rest[end + 2 :]
        else:
            return rest


def ensure_single_statement(sql: str) -> None:
    """Reject SQL containing more than one real statement.

    Character scanner tracking string literals, backtick identifiers, and all
    three comment forms. A ``;`` outside those contexts is only allowed when
    followed exclusively by whitespace/comments.
    """
    quote: str | None = None
    in_line_comment = False
    in_block_comment = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
        elif in_block_comment:
            if ch == "*" and i + 1 < n and sql[i + 1] == "/":
                in_block_comment = False
                i += 1
        elif quote is not None:
            # Backslash escapes apply in ' and " strings, not in backticks.
            if ch == "\\" and quote != "`":
                i += 1
            elif ch == quote:
                quote = None
        else:
            if ch == "-" and i + 1 < n and sql[i + 1] == "-":
                in_line_comment = True
                i += 1
            elif ch == "#":
                in_line_comment = True
            elif ch == "/" and i + 1 < n and sql[i + 1] == "*":
                in_block_comment = True
                i += 1
            elif ch in ("'", '"', "`"):
                quote = ch
            elif ch == ";":
                tail = sql[i + 1 :]
                # Trailing ';' (plus comments/whitespace) is fine; anything
                # else is a second statement.
                if strip_leading_comments(tail).strip():
                    raise QueryPolicyError(
                        "MULTI_STATEMENT_SQL",
                        "Multi-statement SQL is not allowed. "
                        "Send exactly one SQL statement per tool call.",
                    )
        i += 1


def classify_sql(sql: str) -> SqlClassification:
    """Classify one SQL statement by its first keyword.

    Enforces single-statement first, then strips leading comments and trailing
    semicolons before extracting the keyword.
    """
    ensure_single_statement(sql)
    normalized = _TRAILING_SEMICOLONS_RE.sub("", strip_leading_comments(sql).strip()).strip()
    match = _FIRST_KEYWORD_RE.match(normalized)
    if not match:
        return SqlClassification(
            operation="UNKNOWN", category="unsupported", normalized_sql=normalized
        )
    operation = match.group(1).upper()
    category = _CATEGORY_BY_OPERATION.get(operation, "unsupported")
    if operation in ("CREATE", "DROP"):
        second = _SECOND_KEYWORD_RE.match(normalized)
        if second and second.group(1).upper() in _ADMIN_SECOND_KEYWORDS:
            category = "admin"
            operation = f"{operation}_DATABASE"
    return SqlClassification(operation=operation, category=category, normalized_sql=normalized)


def assert_read_allowed(classification: SqlClassification) -> None:
    """Gate for the query tool: read category only, minus forbidden constructs."""
    if classification.category != "read":
        raise QueryPolicyError(
            "QUERY_REQUIRES_READ_ONLY_SQL",
            f"{classification.operation} operations are not allowed in the query tool. "
            "Use query only for SELECT, SHOW, DESCRIBE, or EXPLAIN statements.",
        )
    forbidden = FORBIDDEN_READ_RE.search(_strip_all_comments(classification.normalized_sql))
    if forbidden:
        raise QueryPolicyError(
            "FORBIDDEN_READ_CONSTRUCT",
            "File I/O and lock functions are not allowed in read-only queries "
            f"(blocked construct: {forbidden.group(1)}). "
            "Remove INTO OUTFILE/DUMPFILE and lock/stall calls.",
        )


def assert_explain_select(classification: SqlClassification) -> None:
    """Gate for explain_query: strictly SELECT (not SHOW/DESCRIBE/EXPLAIN)."""
    if classification.operation != "SELECT":
        raise QueryPolicyError(
            "EXPLAIN_REQUIRES_SELECT",
            "explain_query accepts a single SELECT statement only.",
        )
