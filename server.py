"""Thin shim for `python server.py` (Docker CMD, local runs).

The real entry point lives in mysql_mcp.server so the `mysql-mcp` console
script works when the package is installed from git/PyPI via uvx or pipx.
"""

from mysql_mcp.server import main, mcp

__all__ = ["main", "mcp"]

if __name__ == "__main__":
    main()
