"""MySQL identifier quoting (port of mysqlIdentifiers.ts).

Identifiers are backtick-quoted with embedded backticks doubled; empty names
and names containing null bytes are rejected. Values are never handled here —
they go through driver-bound parameters.
"""

from mysql_mcp.errors import InvalidIdentifierError


def quote_identifier(name: str) -> str:
    """Return the backtick-quoted form of ``name``.

    Raises InvalidIdentifierError for empty/whitespace-only names or names
    containing a null byte (faithful to the TS original).
    """
    if not name or not name.strip() or "\x00" in name:
        raise InvalidIdentifierError()
    escaped = name.replace("`", "``")
    return f"`{escaped}`"


def qualified_identifier(name: str, database: str = "") -> str:
    """Return ```db`.`name``` when a database is given, else ```name```."""
    if database:
        return f"{quote_identifier(database)}.{quote_identifier(name)}"
    return quote_identifier(name)
