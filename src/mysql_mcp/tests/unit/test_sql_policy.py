"""Table-driven tests for the SQL policy — the security-critical module."""

import pytest

from mysql_mcp.errors import QueryPolicyError
from mysql_mcp.sql_policy import (
    assert_explain_select,
    assert_read_allowed,
    classify_sql,
    ensure_single_statement,
    strip_leading_comments,
)

# ─── Classification ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sql", "operation", "category"),
    [
        ("SELECT * FROM t", "SELECT", "read"),
        ("select 1", "SELECT", "read"),
        ("  SeLeCt 1", "SELECT", "read"),
        ("SHOW TABLES", "SHOW", "read"),
        ("EXPLAIN SELECT 1", "EXPLAIN", "read"),
        ("DESCRIBE t", "DESCRIBE", "read"),
        ("DESC t", "DESC", "read"),
        ("INSERT INTO t VALUES (1)", "INSERT", "data-write"),
        ("UPDATE t SET a=1", "UPDATE", "data-write"),
        ("DELETE FROM t", "DELETE", "data-write"),
        ("REPLACE INTO t VALUES (1)", "REPLACE", "data-write"),
        ("CREATE TABLE t (id INT)", "CREATE", "schema"),
        ("CREATE DATABASE d", "CREATE_DATABASE", "admin"),
        ("CREATE SCHEMA d", "CREATE_DATABASE", "admin"),
        ("DROP TABLE t", "DROP", "schema"),
        ("DROP DATABASE d", "DROP_DATABASE", "admin"),
        ("ALTER TABLE t ADD c INT", "ALTER", "schema"),
        ("TRUNCATE t", "TRUNCATE", "schema"),
        ("RENAME TABLE a TO b", "RENAME", "schema"),
        ("USE db", "USE", "admin"),
        ("GRANT ALL ON *.* TO x", "GRANT", "admin"),
        ("REVOKE ALL ON *.* FROM x", "REVOKE", "admin"),
        ("FLUSH PRIVILEGES", "FLUSH", "admin"),
        ("KILL 42", "KILL", "admin"),
        ("SET NAMES utf8", "SET", "admin"),
        # CTEs are (faithfully) unsupported — first-keyword classification
        ("WITH x AS (SELECT 1) SELECT * FROM x", "WITH", "unsupported"),
        ("CALL sp()", "CALL", "unsupported"),
    ],
)
def test_classify_sql(sql: str, operation: str, category: str) -> None:
    classification = classify_sql(sql)
    assert classification.operation == operation
    assert classification.category == category


def test_classify_strips_leading_comments_and_trailing_semicolon() -> None:
    classification = classify_sql("-- note\n/* more */ SELECT 1;  ")
    assert classification.operation == "SELECT"
    assert classification.normalized_sql == "SELECT 1"


def test_classify_empty_sql_is_unsupported() -> None:
    classification = classify_sql("   ")
    assert classification.operation == "UNKNOWN"
    assert classification.category == "unsupported"


def test_classify_comment_only_sql_is_unsupported() -> None:
    classification = classify_sql("-- just a comment")
    assert classification.category == "unsupported"


# ─── Single-statement scanner ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT 1;",
        "SELECT 1; -- trailing comment",
        "SELECT 1; /* trailing block */",
        "SELECT 1;   \n  ",
        "SELECT 'a;b'",
        'SELECT "a;b"',
        "SELECT `a;b` FROM t",
        r"SELECT 'a\';b'",
        "SELECT '-- not a comment; still string'",
        "SELECT 1 -- comment with ; semicolon",
        "SELECT 1 # comment with ; semicolon",
        "SELECT /* ; */ 1",
    ],
)
def test_single_statement_accepted(sql: str) -> None:
    ensure_single_statement(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1;DROP TABLE t",
        # Faithful to the TS scanner: empty statements (';;') are rejected too
        "SELECT 1;;",
        "SELECT 1; /* c */ SELECT 2",
        "SELECT 1; -- c\nSELECT 2",
        # Backticks do NOT honor backslash escapes: the backtick closes at the
        # backslash-adjacent backtick, so the ';' is outside a string.
        "SELECT `a\\`; DROP TABLE t; SELECT `b`",
    ],
)
def test_multi_statement_rejected(sql: str) -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        ensure_single_statement(sql)
    assert exc_info.value.code == "MULTI_STATEMENT_SQL"


def test_unterminated_block_comment_after_semicolon() -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        ensure_single_statement("SELECT 1; /* unterminated")
    assert exc_info.value.code == "UNTERMINATED_COMMENT"


# ─── strip_leading_comments ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 1", "SELECT 1"),
        ("  \n SELECT 1", "SELECT 1"),
        ("-- c\nSELECT 1", "SELECT 1"),
        ("# c\nSELECT 1", "SELECT 1"),
        ("/* c */SELECT 1", "SELECT 1"),
        ("/* a */ -- b\n # c\n SELECT 1", "SELECT 1"),
        ("-- only comment", ""),
    ],
)
def test_strip_leading_comments(sql: str, expected: str) -> None:
    assert strip_leading_comments(sql) == expected


def test_strip_leading_comments_unterminated_block() -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        strip_leading_comments("/* never closed SELECT 1")
    assert exc_info.value.code == "UNTERMINATED_COMMENT"


# ─── Read gate + forbidden-read denylist (audit P2-4) ────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users",
        "SHOW TABLES",
        "DESCRIBE users",
        "EXPLAIN SELECT 1",
        # Word boundaries: column names containing denied words must pass
        "SELECT sleep_total FROM metrics",
        "SELECT benchmark_id FROM runs",
        "SELECT outfile_path FROM exports",
        "SELECT get_lock_count FROM stats",
    ],
)
def test_read_allowed(sql: str) -> None:
    assert_read_allowed(classify_sql(sql))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users INTO OUTFILE '/tmp/x'",
        "SELECT * FROM users INTO  DUMPFILE '/tmp/x'",
        "select * from users into outfile '/tmp/x'",
        "SELECT SLEEP(10)",
        "SELECT GET_LOCK('a', 10)",
        "SELECT BENCHMARK(1000000, MD5('x'))",
        "SELECT LOAD_FILE('/etc/passwd')",
        # SEC-002 bypass regression: MySQL treats /**/ as whitespace, so these
        # must be caught even though the denied tokens are split by a comment.
        "SELECT 1 INTO/**/OUTFILE '/tmp/x'",
        "SELECT 1 INTO/* c */DUMPFILE '/tmp/x'",
        "SELECT 1 -- pre\n INTO OUTFILE '/tmp/x'",
    ],
)
def test_forbidden_read_constructs_rejected(sql: str) -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        assert_read_allowed(classify_sql(sql))
    assert exc_info.value.code == "FORBIDDEN_READ_CONSTRUCT"


@pytest.mark.parametrize(
    ("sql", "operation"),
    [
        ("INSERT INTO t VALUES (1)", "INSERT"),
        ("UPDATE t SET a=1", "UPDATE"),
        ("DELETE FROM t", "DELETE"),
        ("DROP TABLE t", "DROP"),
        ("CREATE DATABASE d", "CREATE_DATABASE"),
        ("USE db", "USE"),
        ("GRANT ALL ON *.* TO x", "GRANT"),
        ("WITH x AS (SELECT 1) SELECT 1", "WITH"),
    ],
)
def test_non_read_rejected(sql: str, operation: str) -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        assert_read_allowed(classify_sql(sql))
    assert exc_info.value.code == "QUERY_REQUIRES_READ_ONLY_SQL"
    assert operation in str(exc_info.value)


def test_multi_statement_blocks_before_classification() -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        classify_sql("SELECT 1; DELETE FROM t")
    assert exc_info.value.code == "MULTI_STATEMENT_SQL"


# ─── assert_explain_select ────────────────────────────────────────────────────


def test_explain_accepts_select() -> None:
    assert_explain_select(classify_sql("SELECT * FROM t;"))


@pytest.mark.parametrize(
    "sql",
    ["SHOW TABLES", "DESCRIBE t", "EXPLAIN SELECT 1", "INSERT INTO t VALUES (1)"],
)
def test_explain_rejects_non_select(sql: str) -> None:
    with pytest.raises(QueryPolicyError) as exc_info:
        assert_explain_select(classify_sql(sql))
    assert exc_info.value.code == "EXPLAIN_REQUIRES_SELECT"
