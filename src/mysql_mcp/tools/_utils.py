"""Shared tool plumbing: the centralized policy/credential/audit gate.

Audit P2-7 (centralize policy enforcement) and P3-9 (audit logging) are
implemented here: every tool body delegates to execute_tool(), so no tool can
bypass credential resolution, error sanitization, or audit logging by
omission.

The audit logger emits one structured JSON record per tool call to stderr
(timestamp, tool, db_id, operation, target, rowCount, durationMs, ok) — never
credentials, SQL text, or parameter values.
"""

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from datetime import time as time_of_day
from decimal import Decimal
from typing import Any

from mysql_mcp.config import ConnectionParams, settings
from mysql_mcp.db import MySqlClient, build_ssl_context
from mysql_mcp.errors import MySqlMcpError, QueryPolicyError

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("mysql_mcp.audit")

_DB_ID_RE = re.compile(r"[a-z0-9_\-]{1,64}")

_MISSING_CREDS_MSG = (
    "ERROR: MISSING_CREDENTIALS: No database connection is configured. "
    "Set DB_PROFILES (multi-profile) or MYSQL_USER/MYSQL_PASSWORD (single connection) "
    "on the server. Credentials are never accepted as tool parameters."
)
_UNKNOWN_PROFILE_MSG = (
    "ERROR: UNKNOWN_PROFILE: No database profile named '{db_id}' is configured on this server. "
    "Omit db_id to use the default connection, or ask the operator which profiles exist."
)
_INVALID_DB_ID_MSG = (
    "ERROR: INVALID_DB_ID: db_id must be 1-64 characters of lowercase letters, "
    "digits, hyphens, or underscores."
)


def _json_default(obj: Any) -> str:
    """JSON fallback for MySQL result values."""
    if isinstance(obj, datetime | date | time_of_day):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


def parse_params_json(raw: str) -> list[Any]:
    """Parse the params_json tool parameter into a list of scalar bind values.

    Accepts "" (no params) or a JSON array of scalars (string, number,
    boolean, null). Anything else raises INVALID_PARAMS.
    """
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QueryPolicyError(
            "INVALID_PARAMS", f"params_json is not valid JSON: {exc.msg}."
        ) from exc
    if not isinstance(parsed, list):
        raise QueryPolicyError(
            "INVALID_PARAMS", "params_json must be a JSON array of scalar values."
        )
    for item in parsed:
        if item is not None and not isinstance(item, str | int | float | bool):
            raise QueryPolicyError(
                "INVALID_PARAMS",
                "params_json elements must be scalars (string, number, boolean, or null).",
            )
    return parsed


def _resolve_params(db_id: str) -> ConnectionParams | None:
    """Resolve connection parameters: profile map first, env fallback second.

    Returns None when the profile is unknown or no fallback is configured
    (the caller distinguishes the two cases by whether db_id was given).
    """
    if db_id:
        try:
            return settings.get_profile(db_id)
        except KeyError:
            return None
    return settings.default_params()


def _make_client(params: ConnectionParams) -> MySqlClient:
    """Module-level factory so tests can patch client construction."""
    return MySqlClient(
        params,
        connect_timeout=settings.MYSQL_CONNECT_TIMEOUT_S,
        query_timeout_ms=settings.MYSQL_QUERY_TIMEOUT_MS,
        max_rows=settings.MYSQL_MAX_ROWS,
        ssl_context=build_ssl_context(settings.MYSQL_SSL, settings.MYSQL_SSL_CA),
    )


def _audit(record: dict[str, Any]) -> None:
    audit_logger.info(json.dumps(record, default=_json_default))


async def execute_tool(
    tool_name: str,
    db_id: str,
    action: Callable[[MySqlClient], Awaitable[dict[str, Any]]],
    *,
    operation: str = "",
    target: str = "",
) -> str:
    """The single gate every tool call routes through.

    Validates db_id, resolves credentials, constructs the client, runs the
    action, emits the audit record, and formats the response envelope
    (JSON on success, "ERROR: <CODE>: <message>" on failure). Unexpected
    exceptions are logged with traceback and returned as a generic message —
    raw exception text is never echoed to the caller.
    """
    if db_id and not _DB_ID_RE.fullmatch(db_id.lower()):
        return _INVALID_DB_ID_MSG
    params = _resolve_params(db_id)
    if params is None:
        if db_id:
            return _UNKNOWN_PROFILE_MSG.format(db_id=db_id)
        return _MISSING_CREDS_MSG
    started = time.monotonic()
    record: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "tool": tool_name,
        "db_id": db_id or "-",
        "operation": operation,
        "target": target,
    }
    try:
        client = _make_client(params)
        result = await action(client)
    except MySqlMcpError as exc:
        record.update(
            ok=False,
            errorCode=exc.code,
            durationMs=round((time.monotonic() - started) * 1000, 1),
        )
        _audit(record)
        return f"ERROR: {exc.code}: {exc}"
    except Exception:
        record.update(
            ok=False,
            errorCode="INTERNAL_ERROR",
            durationMs=round((time.monotonic() - started) * 1000, 1),
        )
        _audit(record)
        logger.exception("Unexpected failure in tool %s", tool_name)
        return f"ERROR: Unexpected internal failure in {tool_name}. Check server logs."
    record.update(
        ok=True,
        rowCount=result.get("rowCount"),
        durationMs=round((time.monotonic() - started) * 1000, 1),
    )
    _audit(record)
    return json.dumps(result, indent=2, default=_json_default)
