"""Database I/O boundary — the ONLY module that imports aiomysql.

Design (see docs/ARCHITECTURE.md and docs/SECURITY.md):
- Per-call short-lived connections: no shared pool, no cross-request state,
  no credential bleed between profiles.
- CLIENT.MULTI_STATEMENTS stays off: no ``client_flag`` is ever passed, and
  the SQL policy layer independently rejects multi-statement input.
- Timeouts (audit P3-10): TCP connect timeout plus a per-session
  MAX_EXECUTION_TIME cap that bounds runaway SELECTs.
- TLS (audit P2-6): build_ssl_context() only produces verifying contexts —
  there is no way to disable certificate/hostname verification.
- Row capping: results are sliced post-fetch to ``max_rows`` (faithful to the
  TS original: when truncated, rowCount reports the cap, not the true total).
- Errors: driver exceptions are translated to the sanitized
  mysql_mcp.errors.MySQLError (errno + sqlstate + driver message, never
  credentials) so upper layers never touch pymysql types.
"""

import ssl
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import aiomysql
import pymysql

from mysql_mcp.config import ConnectionParams
from mysql_mcp.errors import MySQLError


@dataclass(frozen=True)
class QueryResult:
    """Rows plus truncation metadata for one executed statement."""

    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    max_rows: int


def build_ssl_context(enabled: bool, ca_path: str = "") -> ssl.SSLContext | None:
    """TLS context with certificate + hostname verification REQUIRED.

    There is deliberately no verify-off option (audit P2-6).
    """
    if not enabled:
        return None
    context = ssl.create_default_context(cafile=ca_path or None)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


class MySqlClient:
    """Thin async client executing one statement per short-lived connection."""

    def __init__(
        self,
        params: ConnectionParams,
        *,
        connect_timeout: int = 10,
        query_timeout_ms: int = 10_000,
        max_rows: int = 1000,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.params = params
        self._connect_timeout = connect_timeout
        self._query_timeout_ms = query_timeout_ms
        self._max_rows = max_rows
        self._ssl_context = ssl_context

    @property
    def max_rows(self) -> int:
        return self._max_rows

    async def _connect(self) -> Any:
        try:
            return await aiomysql.connect(
                host=self.params.host,
                port=self.params.port,
                user=self.params.user,
                password=self.params.password,
                db=self.params.database or None,
                charset="utf8mb4",
                connect_timeout=self._connect_timeout,
                ssl=self._ssl_context,
                autocommit=True,
                cursorclass=aiomysql.DictCursor,
            )
        except pymysql.err.MySQLError as exc:
            raise _translate(exc) from exc
        except OSError as exc:
            raise MySQLError(
                f"Cannot connect to MySQL at {self.params.host}:{self.params.port}: "
                f"{exc.__class__.__name__}"
            ) from exc

    async def execute(self, sql: str, params: Sequence[Any] | None = None) -> QueryResult:
        """Execute one statement and return capped rows.

        ``params`` are bound with pymysql ``%s`` placeholders. When no params
        are supplied, the SQL is executed without interpolation so literal
        ``%`` characters are safe.
        """
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                if self._query_timeout_ms > 0:
                    await cur.execute(
                        f"SET SESSION MAX_EXECUTION_TIME = {int(self._query_timeout_ms)}"
                    )
                if params:
                    await cur.execute(sql, tuple(params))
                else:
                    await cur.execute(sql)
                fetched = await cur.fetchall()
        except pymysql.err.MySQLError as exc:
            raise _translate(exc) from exc
        finally:
            conn.close()
        rows: list[dict[str, Any]] = list(fetched or [])
        truncated = self._max_rows > 0 and len(rows) > self._max_rows
        if truncated:
            rows = rows[: self._max_rows]
        return QueryResult(
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            max_rows=self._max_rows,
        )

    async def ping(self) -> float:
        """Connect + ping; returns round-trip latency in milliseconds."""
        start = time.monotonic()
        conn = await self._connect()
        try:
            await conn.ping()
        except pymysql.err.MySQLError as exc:
            raise _translate(exc) from exc
        finally:
            conn.close()
        return (time.monotonic() - start) * 1000.0


def _translate(exc: pymysql.err.MySQLError) -> MySQLError:
    """Convert a driver error into the sanitized typed error."""
    errno: int | None = None
    sqlstate: str | None = None
    message = str(exc)
    args: tuple[Any, ...] = exc.args
    if len(args) >= 2 and isinstance(args[0], int):
        errno = args[0]
        message = str(args[1])
    sqlstate_attr = getattr(exc, "sqlstate", None)
    if isinstance(sqlstate_attr, str):
        sqlstate = sqlstate_attr
    return MySQLError(message, errno=errno, sqlstate=sqlstate)
