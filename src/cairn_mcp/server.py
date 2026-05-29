"""FastMCP server instance and transport configuration for cairn-mcp."""

import importlib.metadata
import logging

import fastmcp

logger = logging.getLogger(__name__)

# Tools registered in Phase 2+

_version = importlib.metadata.version("cairn-mcp")
_app = fastmcp.FastMCP(name="cairn-mcp", version=_version)


def run() -> None:
    """Start the cairn-mcp MCP server using stdio transport.

    Logs startup and delegates to FastMCP's stdio run loop.
    FastMCP handles SIGTERM/SIGINT natively via its event loop.
    """
    logger.info("cairn-mcp v%s starting", _version)
    _app.run(transport="stdio")
    logger.info("cairn-mcp shutting down")
