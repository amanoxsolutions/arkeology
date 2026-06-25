"""cairn_mcp.tools.studio — cairn_studio MCP tool implementation.

Triggers the inline MCP Apps visual browser in supporting hosts; falls back to a
plain-text artifact listing in non-supporting hosts.

Return value design
-------------------
``cairn_studio`` returns a :class:`fastmcp.tools.base.ToolResult` with two
independent payloads:

* ``content`` — a short human-readable sentence for the LLM.  The model sees
  this and does not need to describe or summarise the raw data, because the
  host UI widget handles rendering.
* ``structured_content`` — the full ``{"write_prefix": …, "artifacts": […]}``
  dict consumed by the iframe's ``app.ontoolresult`` handler (which reads
  ``structuredContent`` first, falling back to ``content``).

Keeping these payloads separate prevents the model from generating a verbose
JSON description below the rendered widget.
"""

import logging

from fastmcp.apps.config import UI_EXTENSION_ID
from fastmcp.server.context import Context
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from cairn_mcp.config import Settings

logger = logging.getLogger(__name__)


async def cairn_studio(
    *,
    settings: Settings,
    ctx: Context,
) -> ToolResult:
    """Browse cairn artifacts using Cairn Studio — triggers the inline MCP
    App browser.

    Returns a :class:`~fastmcp.tools.base.ToolResult` with:

    * ``content`` — a one-line confirmation for the LLM so it does not
      attempt to describe the raw artifact data.

    Args:
        settings: Validated server configuration.
        ctx: FastMCP request context — used to log extension support status.

    Returns:
        A :class:`~fastmcp.tools.base.ToolResult`.
        On unexpected error, returns an error ``ToolResult``.
    """
    try:
        is_ui = ctx.client_supports_extension(UI_EXTENSION_ID)
        logger.debug(
            "cairn_studio: UI extension %s by client",
            "supported" if is_ui else "not announced",
        )
        text = "Cairn studio opened. Use the UI widget to browse artifacts."
        return ToolResult(
            content=[TextContent(type="text", text=text)],
        )
    except Exception as exc:
        logger.exception("Unexpected error in cairn_studio")
        return ToolResult(
            content=[TextContent(type="text", text=f"Error opening cairn studio: {exc}")],
            is_error=True,
        )
