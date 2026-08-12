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
with ``{"write_prefix": …, "artifacts": […], "total_count": int}`` so non-supporting
clients receive the artifact listing without requiring a separate ``list_artifacts``
call. That listing is bounded by :data:`FALLBACK_LISTING_CAP` — it is destined for an
agent's context window, and an unbounded store would fill it — with ``total_count``
carrying the full pre-cap match count so a truncated listing is never mistaken for a
complete one.

If the inner ``list_artifacts`` call itself fails (e.g. expired credentials), the
result is a structured error (``is_error=True``, ``structured_content={"error": ...,
"message": ...}``) — never a coerced empty listing, and never capped or reordered.
"""

import logging
from typing import Any

from fastmcp.apps.config import UI_EXTENSION_ID
from fastmcp.server.context import Context
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from arkeology.clients.interfaces import VectorsClientInterface
from arkeology.config import Settings
from arkeology.tools.list import _list_artifacts_inner

logger = logging.getLogger(__name__)

# Maximum artifacts included in the non-supporting-host fallback listing. Deliberately a
# module constant, not a setting or tool parameter: it bounds one tool's response for one
# consumer (an agent's context window), and ``list_artifacts`` — which stays uncapped —
# is the documented way to retrieve the remainder.
FALLBACK_LISTING_CAP = 50


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
        # An error dict from the inner list call (e.g. expired credentials)
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

    # Newest first, ties broken by artifact_id ascending, so the cap below keeps the head
    # of a stable order — the most recent artifacts — rather than an arbitrary slice.
    # Two passes because the tie-break runs ascending while the date runs descending.
    artifacts: list[dict[str, Any]] = sorted(
        listing.get("artifacts", []), key=lambda a: str(a.get("artifact_id") or "")
    )
    artifacts.sort(key=lambda a: str(a.get("date") or ""), reverse=True)
    total_count = len(artifacts)
    truncated = total_count > FALLBACK_LISTING_CAP

    text = (
        "Arkeology Studio is not supported by this host. "
        "The artifact listing is available in structured_content."
    )
    if truncated:
        text += (
            f" Showing the {FALLBACK_LISTING_CAP} most recent of {total_count} artifacts; "
            "call list_artifacts with filters to retrieve the rest."
        )

    return ToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content={
            "write_prefix": settings.write_prefix,
            "artifacts": artifacts[:FALLBACK_LISTING_CAP],
            "total_count": total_count,
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
      extension; contains ``{"write_prefix": …, "artifacts": […], "total_count": int}``
      so the client has the listing without a separate tool call. ``artifacts`` holds
      at most :data:`FALLBACK_LISTING_CAP` entries, newest first; ``total_count`` is
      the pre-cap match count. If the inner listing call fails, ``is_error=True`` and
      ``structured_content`` instead carries ``{"error": ..., "message": ...}`` — never
      a coerced empty listing.

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
