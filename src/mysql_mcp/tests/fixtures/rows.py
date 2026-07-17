"""Shared row payloads used across unit tests."""

from mysql_mcp.config import ConnectionParams
from mysql_mcp.db import QueryResult

TEST_PARAMS = ConnectionParams(
    host="db.test", port=3306, user="mcp_ro", password="secret-pw", database="app_db"
)

DB_PROFILES_JSON = (
    '{"staging": {"host": "db.test", "port": 3306, "user": "mcp_ro",'
    ' "password": "secret-pw", "database": "app_db"}}'
)

USERS_ROWS = [
    {"id": 1, "name": "Ada", "email": "ada@example.com"},
    {"id": 2, "name": "Grace", "email": "grace@example.com"},
]

DESCRIBE_ROWS = [
    {"Field": "id", "Type": "int", "Null": "NO", "Key": "PRI", "Default": None, "Extra": "auto_increment"},
    {"Field": "name", "Type": "varchar(255)", "Null": "YES", "Key": "", "Default": None, "Extra": ""},
]


def query_result(rows: list[dict], *, truncated: bool = False, max_rows: int = 1000) -> QueryResult:
    return QueryResult(rows=rows, row_count=len(rows), truncated=truncated, max_rows=max_rows)
