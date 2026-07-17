import logging
import os
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from mysql_mcp import register_all_tools

logger = logging.getLogger("mysql_mcp.server")

mcp = FastMCP(
    "mysql-mcp",
    version="0.1.0",
    instructions=(
        "When answering users with data from this server, present results "
        "naturally in plain language. Never mention internal tool or function "
        "names (e.g. 'sample_rows'), never describe which tool you are calling "
        "or about to call, and never paste raw JSON unless the user explicitly "
        "asks for it. Just answer with the information. Format answers "
        "professionally using Markdown: start with a one-line summary, present "
        "query results and schema details as compact Markdown tables, and use "
        "bold labels for key facts. Render dates, numbers, and durations in "
        "human-readable form, mention when a result was truncated by the row "
        "cap, and omit internal fields the user did not ask about. This server "
        "is strictly read-only: politely refuse requests to modify data or "
        "schema and explain that only read operations are available."
    ),
)
register_all_tools(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Unauthenticated liveness probe for load-balancer health checks.

    Deliberately shallow: reports only that the process is up and serving
    HTTP — no MySQL probing, so a database outage can't make a load balancer
    recycle a healthy instance. Exposes no data and bypasses bearer auth by
    design (custom routes sit outside RequireAuthMiddleware; only /mcp is
    token-protected). Inert in stdio mode.
    """
    return JSONResponse({"status": "ok"})


def _parse_port(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"ERROR: MCP_PORT must be an integer, got {raw!r}.") from None


def _build_http_auth() -> Any:
    """Build the bearer-token verifier for HTTP mode.

    Fail closed: HTTP refuses to start without MCP_AUTH_TOKEN. Anonymous access
    must be opted into explicitly with MCP_ALLOW_ANON=1 (isolated/trusted
    networks only). stdio mode never reaches this function.
    """
    token = os.environ.get("MCP_AUTH_TOKEN", "")
    if not token:
        if os.environ.get("MCP_ALLOW_ANON") == "1":
            logger.warning(
                "MCP_ALLOW_ANON=1 — HTTP server starting WITHOUT authentication. "
                "Anyone who can reach the port can query all configured database "
                "profiles."
            )
            return None
        raise SystemExit(
            "ERROR: HTTP transport requires MCP_AUTH_TOKEN. Clients must send "
            "'Authorization: Bearer <token>'. Set MCP_ALLOW_ANON=1 to run without "
            "authentication on an isolated, trusted network only."
        )

    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    class _AuditedTokenVerifier(StaticTokenVerifier):
        async def verify_token(self, token: str) -> Any:
            result = await super().verify_token(token)
            if result is None:
                logger.warning("HTTP authentication failure: invalid bearer token presented")
            return result

    return _AuditedTokenVerifier(tokens={token: {"client_id": "mysql-mcp"}})


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport == "http":
        mcp.auth = _build_http_auth()
        host = os.environ.get("MCP_HOST", "0.0.0.0")
        port = _parse_port(os.environ.get("MCP_PORT", "8004"))
        mcp.run(transport="http", host=host, port=port)
    elif transport == "sse":
        raise SystemExit(
            "ERROR: The SSE transport is not supported. Set MCP_TRANSPORT=http — "
            "the server uses the streamable-HTTP transport; clients connect to "
            "http://<host>:<port>/mcp."
        )
    else:
        mcp.run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    main()
