"""Shared fixtures.

Tools are nested closures and cannot be imported directly, so tool tests go
through a real FastMCP instance. Fixtures use the yield-inside-with pattern so
patches on settings and the client factory remain active at call_tool() time.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP

from mysql_mcp.db import MySqlClient
from mysql_mcp.services.health import HealthService
from mysql_mcp.services.query import QueryService
from mysql_mcp.services.schema import SchemaService
from mysql_mcp.tests.fixtures.rows import DB_PROFILES_JSON, TEST_PARAMS
from mysql_mcp.tools.health import register_health_tools
from mysql_mcp.tools.query import register_query_tools
from mysql_mcp.tools.schema import register_schema_tools


@pytest.fixture
def mock_client() -> AsyncMock:
    client = AsyncMock(spec=MySqlClient)
    client.params = TEST_PARAMS
    client.max_rows = 1000
    return client


@pytest.fixture
def query_service(mock_client: AsyncMock) -> QueryService:
    return QueryService(mock_client)


@pytest.fixture
def schema_service(mock_client: AsyncMock) -> SchemaService:
    return SchemaService(mock_client)


@pytest.fixture
def health_service(mock_client: AsyncMock) -> HealthService:
    return HealthService(mock_client)


def _mcp_fixture(register):
    """Build a FastMCP + patched-gate fixture for one tool registrar."""

    @pytest.fixture
    def _fixture():
        _mock_client = AsyncMock(spec=MySqlClient)
        _mock_client.params = TEST_PARAMS
        _mock_client.max_rows = 1000
        mcp = FastMCP("test-mysql-mcp")
        register(mcp)
        with (
            patch("mysql_mcp.tools._utils.settings") as mock_settings,
            patch("mysql_mcp.tools._utils._make_client", return_value=_mock_client),
        ):
            mock_settings.DB_PROFILES = DB_PROFILES_JSON
            mock_settings.get_profile.return_value = TEST_PARAMS
            mock_settings.default_params.return_value = TEST_PARAMS
            yield mcp, _mock_client, mock_settings

    return _fixture


query_mcp = _mcp_fixture(register_query_tools)
schema_mcp = _mcp_fixture(register_schema_tools)
health_mcp = _mcp_fixture(register_health_tools)


def tool_text(result) -> str:
    """Unwrap the text payload of a call_tool result."""
    return result.content[0].text
