"""End-to-end tests against a real MySQL server (skipped by default).

Run with MYSQL_RUN_LIVE_TESTS=1 — see integration/conftest.py for the
disposable-docker recipe.
"""

import pytest

from mysql_mcp.errors import QueryPolicyError
from mysql_mcp.services.health import HealthService
from mysql_mcp.services.query import QueryService
from mysql_mcp.services.schema import SchemaService
from mysql_mcp.tests.integration.conftest import requires_live

pytestmark = [pytest.mark.integration, pytest.mark.live, requires_live]


async def test_query_roundtrip(seeded_client) -> None:
    service = QueryService(seeded_client)
    result = await service.run_query(
        "SELECT name FROM mcp_demo_users WHERE email = %s", ["ada@example.com"]
    )
    assert result["rowCount"] == 1
    assert result["rows"][0]["name"] == "Ada"


async def test_schema_navigation_roundtrip(seeded_client) -> None:
    service = SchemaService(seeded_client)
    tables = await service.list_tables()
    assert "mcp_demo_users" in tables["tables"]
    described = await service.describe_table("mcp_demo_users")
    assert {col["Field"] for col in described["columns"]} == {"id", "name", "email"}
    found = await service.find_tables("demo_users")
    assert found["matchCount"] >= 1
    sample = await service.sample_rows("mcp_demo_users", limit=1)
    assert sample["rowCount"] == 1


async def test_explain_roundtrip(seeded_client) -> None:
    service = QueryService(seeded_client)
    result = await service.explain("SELECT * FROM mcp_demo_users", None, "traditional")
    assert result["rowCount"] >= 1


async def test_health_roundtrip(live_client) -> None:
    result = await HealthService(live_client).check()
    assert result["healthy"] is True
    assert result["serverVersion"]


async def test_write_sql_refused_live(seeded_client) -> None:
    service = QueryService(seeded_client)
    with pytest.raises(QueryPolicyError) as exc_info:
        await service.run_query("DELETE FROM mcp_demo_users")
    assert exc_info.value.code == "QUERY_REQUIRES_READ_ONLY_SQL"


async def test_sleep_refused_live(seeded_client) -> None:
    service = QueryService(seeded_client)
    with pytest.raises(QueryPolicyError) as exc_info:
        await service.run_query("SELECT SLEEP(5)")
    assert exc_info.value.code == "FORBIDDEN_READ_CONSTRUCT"


async def test_multi_statement_refused_live(seeded_client) -> None:
    service = QueryService(seeded_client)
    with pytest.raises(QueryPolicyError) as exc_info:
        await service.run_query("SELECT 1; DELETE FROM mcp_demo_users")
    assert exc_info.value.code == "MULTI_STATEMENT_SQL"
