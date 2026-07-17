"""Fixtures for live MySQL integration tests.

These tests need a real MySQL server and are skipped unless
MYSQL_RUN_LIVE_TESTS=1. Recipe for a disposable target (see docs/setup.md §4):

    docker run --rm -d --name mysql-mcp-test -p 3307:3306 \
      -e MYSQL_ROOT_PASSWORD=test -e MYSQL_DATABASE=demo mysql:8.4

    MYSQL_RUN_LIVE_TESTS=1 MYSQL_HOST=127.0.0.1 MYSQL_PORT=3307 \
      MYSQL_USER=root MYSQL_PASSWORD=test MYSQL_DATABASE=demo \
      .venv/bin/pytest src/mysql_mcp/tests/integration -m live -v
"""

import os

import pytest

from mysql_mcp.config import ConnectionParams
from mysql_mcp.db import MySqlClient

LIVE = os.environ.get("MYSQL_RUN_LIVE_TESTS") == "1"

requires_live = pytest.mark.skipif(
    not LIVE, reason="live MySQL tests require MYSQL_RUN_LIVE_TESTS=1"
)


@pytest.fixture
def live_client() -> MySqlClient:
    params = ConnectionParams(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", ""),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DATABASE", ""),
    )
    return MySqlClient(params)


@pytest.fixture
async def seeded_client(live_client: MySqlClient):
    """Create and populate a small demo table for the duration of a test.

    Uses a raw connection (not client.execute) because seeding needs writes
    and MySqlClient itself has no write path — the policy layer would refuse
    the SQL at the service level anyway.
    """
    import aiomysql

    conn = await aiomysql.connect(
        host=live_client.params.host,
        port=live_client.params.port,
        user=live_client.params.user,
        password=live_client.params.password,
        db=live_client.params.database or None,
        autocommit=True,
    )
    async with conn.cursor() as cur:
        await cur.execute("DROP TABLE IF EXISTS mcp_demo_users")
        await cur.execute(
            "CREATE TABLE mcp_demo_users ("
            "id INT PRIMARY KEY AUTO_INCREMENT, "
            "name VARCHAR(64) NOT NULL, "
            "email VARCHAR(128))"
        )
        await cur.execute(
            "INSERT INTO mcp_demo_users (name, email) VALUES "
            "('Ada', 'ada@example.com'), ('Grace', 'grace@example.com')"
        )
    try:
        yield live_client
    finally:
        async with conn.cursor() as cur:
            await cur.execute("DROP TABLE IF EXISTS mcp_demo_users")
        conn.close()
