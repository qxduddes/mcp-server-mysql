"""Configuration for mysql-mcp (pydantic-settings).

Credential model (audit P1-2: environment only, never tool parameters):

Multi-profile (shared HTTP server):
    DB_PROFILES='{"staging": {"host": "...", "port": 3306, "user": "mcp_ro",
                  "password": "...", "database": "app_db"}}'
    Tools select a profile with the ``db_id`` parameter; credentials never
    leave the server.

Single-connection (stdio fallback, used when db_id is empty):
    MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE
    Deliberately no default user (the TS original defaulted to root — audit
    LOW finding): an empty MYSQL_USER disables the fallback entirely.

Password material is SecretStr; the only unwrap points are get_profile() and
default_params() below, whose plain values flow straight into MySqlClient
construction and nowhere else.
"""

import functools
import json
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class ConnectionParams:
    """Resolved connection parameters for one MySQL target."""

    host: str
    port: int
    user: str
    password: str
    database: str


class MySqlSettings(BaseSettings):
    """All environment-derived configuration, read once at import."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=False)

    # Single-connection fallback (no default user by design)
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = ""
    MYSQL_PASSWORD: SecretStr = SecretStr("")
    MYSQL_DATABASE: str = ""

    # Multi-profile map (JSON), kept secret as a whole
    DB_PROFILES: SecretStr = SecretStr("{}")

    # TLS (audit P2-6) — verification is always required when enabled
    MYSQL_SSL: bool = False
    MYSQL_SSL_CA: str = ""

    # Safety limits (audit P3-10)
    MYSQL_MAX_ROWS: int = 1000
    MYSQL_QUERY_TIMEOUT_MS: int = 10_000
    MYSQL_CONNECT_TIMEOUT_S: int = 10

    @functools.cached_property
    def _profile_map(self) -> dict[str, dict[str, Any]]:
        return json.loads(self.DB_PROFILES.get_secret_value())  # type: ignore[no-any-return]

    def get_profile(self, db_id: str) -> ConnectionParams:
        """Single unwrap point for profile credentials. Raises KeyError if unknown."""
        profile = self._profile_map.get(db_id.lower())
        if not profile:
            raise KeyError(db_id)
        return ConnectionParams(
            host=str(profile["host"]),
            port=int(profile.get("port", 3306)),
            user=str(profile["user"]),
            password=str(profile["password"]),
            database=str(profile.get("database", "")),
        )

    def default_params(self) -> ConnectionParams | None:
        """Env-var fallback connection; None when MYSQL_USER is unset."""
        if not self.MYSQL_USER:
            return None
        return ConnectionParams(
            host=self.MYSQL_HOST,
            port=self.MYSQL_PORT,
            user=self.MYSQL_USER,
            password=self.MYSQL_PASSWORD.get_secret_value(),
            database=self.MYSQL_DATABASE,
        )


settings = MySqlSettings()
