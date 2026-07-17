"""Tests for the settings / credential model."""

import pytest
from pydantic import SecretStr

from mysql_mcp.config import MySqlSettings
from mysql_mcp.tests.fixtures.rows import DB_PROFILES_JSON


def _settings(**kwargs) -> MySqlSettings:
    return MySqlSettings(_env_file=None, **kwargs)


def test_get_profile_returns_connection_params() -> None:
    settings = _settings(DB_PROFILES=SecretStr(DB_PROFILES_JSON))
    params = settings.get_profile("staging")
    assert params.host == "db.test"
    assert params.port == 3306
    assert params.user == "mcp_ro"
    assert params.password == "secret-pw"
    assert params.database == "app_db"


def test_get_profile_is_case_insensitive() -> None:
    settings = _settings(DB_PROFILES=SecretStr(DB_PROFILES_JSON))
    assert settings.get_profile("STAGING").host == "db.test"


def test_get_profile_unknown_raises_key_error() -> None:
    settings = _settings(DB_PROFILES=SecretStr(DB_PROFILES_JSON))
    with pytest.raises(KeyError):
        settings.get_profile("ghost")


def test_get_profile_port_defaults_to_3306() -> None:
    settings = _settings(
        DB_PROFILES=SecretStr('{"x": {"host": "h", "user": "u", "password": "p"}}')
    )
    params = settings.get_profile("x")
    assert params.port == 3306
    assert params.database == ""


def test_default_params_requires_user() -> None:
    settings = _settings(MYSQL_USER="", MYSQL_PASSWORD=SecretStr("pw"))
    assert settings.default_params() is None


def test_default_params_from_env_fields() -> None:
    settings = _settings(
        MYSQL_HOST="h", MYSQL_PORT=3307, MYSQL_USER="u",
        MYSQL_PASSWORD=SecretStr("pw"), MYSQL_DATABASE="d",
    )
    params = settings.default_params()
    assert params is not None
    assert (params.host, params.port, params.user, params.password, params.database) == (
        "h", 3307, "u", "pw", "d",
    )


def test_secrets_not_exposed_in_repr() -> None:
    settings = _settings(
        MYSQL_PASSWORD=SecretStr("hunter2"), DB_PROFILES=SecretStr(DB_PROFILES_JSON)
    )
    dump = repr(settings) + str(settings.model_dump())
    assert "hunter2" not in dump
    assert "secret-pw" not in dump


def test_defaults_are_safe() -> None:
    settings = _settings()
    assert settings.MYSQL_USER == ""  # no root default (audit LOW finding)
    assert settings.MYSQL_MAX_ROWS == 1000
    assert settings.MYSQL_QUERY_TIMEOUT_MS == 10_000
    assert settings.MYSQL_CONNECT_TIMEOUT_S == 10
    assert settings.MYSQL_SSL is False
