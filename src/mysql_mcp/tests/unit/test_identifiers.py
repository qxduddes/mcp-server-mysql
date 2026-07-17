"""Tests for MySQL identifier quoting."""

import pytest

from mysql_mcp.errors import InvalidIdentifierError
from mysql_mcp.identifiers import qualified_identifier, quote_identifier


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("users", "`users`"),
        ("weird name", "`weird name`"),
        ("back`tick", "`back``tick`"),
        ("x`", "`x```"),
    ],
)
def test_quote_identifier(name: str, expected: str) -> None:
    assert quote_identifier(name) == expected


@pytest.mark.parametrize("name", ["", "   ", "a\x00b", "\x00"])
def test_quote_identifier_rejects_invalid(name: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        quote_identifier(name)


def test_qualified_identifier_with_database() -> None:
    assert qualified_identifier("users", "app_db") == "`app_db`.`users`"


def test_qualified_identifier_without_database() -> None:
    assert qualified_identifier("users") == "`users`"


def test_qualified_identifier_escapes_both_parts() -> None:
    assert qualified_identifier("t`b", "d`b") == "`d``b`.`t``b`"
