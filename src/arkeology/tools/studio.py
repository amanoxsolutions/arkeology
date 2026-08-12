"""arkeology.tools.studio — arkeology_studio MCP tool implementation.

Triggers the inline MCP Apps visual browser in supporting hosts; falls back to a
plain-text artifact listing in non-supporting hosts.

Return value design
-------------------
``arkeology_studio`` always returns a :class:`fastmcp.tools.base.ToolResult` with a
short ``content`` block for the LLM.

When the host supports the UI extension the iframe loads the artifact list itself
on mount — ``structured_content`` is omitted to keep the tool result lean.

When the host does NOT support the UI extension ``structured_content`` is populated
with ``{"write_prefix": …, "artifacts": […]}`` so non-supporting clients receive the
artifact listing without requiring a separate ``list_artifacts`` call.

If the inner ``list_artifacts`` call itself fails (e.g. expired credentials), the
result is a structured error (``is_error=True``, ``structured_content={"error": ...,
"message": ...}``) — never a coerced empty listing (Phase 12 review M-11a).
"""

import logging

from fastmcp.apps.config import UI_EXTENSION_ID
from fastmcp.server.context import Context
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from arkeology.clients.interfaces import VectorsClientInterface
from arkeology.config import Settings
from arkeology.tools.list import _list_artifacts_inner

logger = logging.getLogger(__name__)


async def _arkeology_studio_inner(
    *,
    settings: Settings,
    vectors: VectorsClientInterface,
    ctx: Context,
) -> ToolResult:
    """Inner implementation of arkeology_studio (separated to enable top-level catch-all)."""
    is_ui = ctx.client_supports_extension(UI_EXTENSION_ID)
    logger.debug(
        "arkeology_studio: UI extension %s by client",
        "supported" if is_ui else "not announced",
    )
    if is_ui:
        # Supporting host: the iframe loads artifacts on mount; no structured_content needed.
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text="Arkeology Studio opened. Use the UI widget to browse artifacts.",
                )
            ],
        )

    # Non-supporting host: include the artifact listing so the client has the data.
    listing = await _list_artifacts_inner(settings=settings, vectors=vectors)
    if "error" in listing:
        # M-11(a): an error dict from the inner list call (e.g. expired credentials)
        # must never be coerced into a successful empty listing — that would read as
        # "the store is empty" instead of "the store could not be reached" (PRD FR-12).
        # Propagate it as a structured error so the caller can distinguish the two.
        logger.warning(
            "arkeology_studio: inner list_artifacts call failed (%s); propagating a "
            "structured error instead of an empty listing",
            listing.get("error"),
        )
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Failed to list artifacts: {listing.get('message', listing['error'])}",
                )
            ],
            structured_content={
                "error": listing["error"],
                "message": listing.get("message", ""),
            },
            is_error=True,
        )

    return ToolResult(
        content=[
            TextContent(
                type="text",
                text=(
                    "Arkeology Studio is not supported by this host. "
                    "The artifact listing is available in structured_content."
                ),
            )
        ],
        structured_content={
            "write_prefix": settings.write_prefix,
            "artifacts": listing.get("artifacts", []),
        },
    )


async def arkeology_studio(
    *,
    settings: Settings,
    vectors: VectorsClientInterface,
    ctx: Context,
) -> ToolResult:
    """Browse arkeology artifacts using Arkeology Studio — triggers the inline MCP App browser.

    Returns a :class:`~fastmcp.tools.base.ToolResult` with:

    * ``content`` — a one-line confirmation for the LLM.
    * ``structured_content`` — only present when the host does not support the UI
      extension; contains ``{"write_prefix": …, "artifacts": […]}`` so the client
      has the full listing without a separate tool call. If the inner listing call
      fails, ``is_error=True`` and ``structured_content`` instead carries
      ``{"error": ..., "message": ...}`` (M-11a) — never a coerced empty listing.

    Args:
        settings: Validated server configuration.
        vectors: S3 Vectors client — used to fetch the artifact list for the
            non-UI fallback path.
        ctx: FastMCP request context — used to detect UI extension support.

    Returns:
        A :class:`~fastmcp.tools.base.ToolResult`.
        On unexpected error, returns an error ``ToolResult``.
    """
    try:
        return await _arkeology_studio_inner(settings=settings, vectors=vectors, ctx=ctx)
    except Exception as exc:
        logger.exception("Unexpected error in arkeology_studio")
        return ToolResult(
            content=[TextContent(type="text", text=f"Error opening arkeology studio: {exc}")],
            is_error=True,
        )
