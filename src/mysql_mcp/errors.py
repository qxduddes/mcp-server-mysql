"""Typed error hierarchy for mysql-mcp.

Every error carries a stable machine-readable ``code`` that the tools layer
surfaces as ``ERROR: <CODE>: <message>``. Codes are preserved from the
TypeScript original (@nilsir/mcp-server-mysql) wherever the behavior was
ported, so clients that matched on them keep working.
"""


class MySqlMcpError(Exception):
    """Base error for all mysql-mcp domain errors."""

    code: str = "INTERNAL_ERROR"


class QueryPolicyError(MySqlMcpError):
    """SQL rejected by the read-only policy (classifier, scanner, or denylist)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class InvalidIdentifierError(MySqlMcpError):
    """Identifier is empty or contains a null byte."""

    code = "INVALID_IDENTIFIER"

    def __init__(self) -> None:
        super().__init__(
            "MySQL identifier must be a non-empty string without null bytes. "
            "Pass a database, table, column, or index name without control characters."
        )


class DatabaseRequiredError(MySqlMcpError):
    """No database given and the connection has no default database."""

    code = "DATABASE_REQUIRED"

    def __init__(self) -> None:
        super().__init__(
            "No database was provided and the MySQL connection has no default database. "
            "Pass the database argument or configure MYSQL_DATABASE."
        )


class MissingSearchTermError(MySqlMcpError):
    """find_tables called with an empty search term."""

    code = "MISSING_SEARCH_TERM"

    def __init__(self) -> None:
        super().__init__("Provide a non-empty search term to match table and column names.")


class MySQLError(MySqlMcpError):
    """Sanitized MySQL driver error (message never includes credentials)."""

    code = "MYSQL_ERROR"

    def __init__(self, message: str, errno: int | None = None, sqlstate: str | None = None) -> None:
        self.errno = errno
        self.sqlstate = sqlstate
        detail = message
        if errno is not None:
            detail = f"[{errno}] {detail}"
        if sqlstate:
            detail = f"{detail} (SQLSTATE {sqlstate})"
        super().__init__(detail)
