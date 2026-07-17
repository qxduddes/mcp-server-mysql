"""Tests for the server entry point: transport dispatch and fail-closed auth."""

import logging
from unittest.mock import patch

import pytest

import server


def test_build_http_auth_fails_closed_without_token() -> None:
    with patch.dict("os.environ", {}, clear=True), pytest.raises(SystemExit) as exc_info:
        server._build_http_auth()
    assert "MCP_AUTH_TOKEN" in str(exc_info.value)


def test_build_http_auth_anon_escape_hatch_warns(caplog: pytest.LogCaptureFixture) -> None:
    with patch.dict("os.environ", {"MCP_ALLOW_ANON": "1"}, clear=True):
        with caplog.at_level(logging.WARNING, logger="mysql_mcp.server"):
            result = server._build_http_auth()
    assert result is None
    assert any("WITHOUT authentication" in record.message for record in caplog.records)


def test_build_http_auth_anon_requires_literal_one() -> None:
    with patch.dict("os.environ", {"MCP_ALLOW_ANON": "true"}, clear=True):
        with pytest.raises(SystemExit):
            server._build_http_auth()


def test_build_http_auth_returns_verifier_with_token() -> None:
    with patch.dict("os.environ", {"MCP_AUTH_TOKEN": "tok-123"}, clear=True):
        verifier = server._build_http_auth()
    assert verifier is not None


async def test_audited_verifier_logs_invalid_token(caplog: pytest.LogCaptureFixture) -> None:
    with patch.dict("os.environ", {"MCP_AUTH_TOKEN": "tok-123"}, clear=True):
        verifier = server._build_http_auth()
    with caplog.at_level(logging.WARNING, logger="mysql_mcp.server"):
        result = await verifier.verify_token("wrong-token")
    assert result is None
    assert any("authentication failure" in record.message for record in caplog.records)


async def test_audited_verifier_accepts_valid_token() -> None:
    with patch.dict("os.environ", {"MCP_AUTH_TOKEN": "tok-123"}, clear=True):
        verifier = server._build_http_auth()
    assert await verifier.verify_token("tok-123") is not None


def test_parse_port_rejects_non_integer() -> None:
    with pytest.raises(SystemExit):
        server._parse_port("eighty")


def test_sse_transport_exits_with_migration_error() -> None:
    with patch.dict("os.environ", {"MCP_TRANSPORT": "sse"}), pytest.raises(SystemExit) as exc_info:
        server.main()
    assert "http" in str(exc_info.value)


def test_http_transport_without_token_exits() -> None:
    with patch.dict("os.environ", {"MCP_TRANSPORT": "http"}, clear=True):
        with pytest.raises(SystemExit) as exc_info:
            server.main()
    assert "MCP_AUTH_TOKEN" in str(exc_info.value)
