"""cairn_mcp.tools.search — search_artifacts MCP tool implementation.

Embeds a natural-language query and retrieves the most semantically similar
artifacts from the S3 Vectors index, subject to scope and access-control gates.
"""

import asyncio
import logging
from typing import Any

from ulid import ULID

from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.constants import ArtifactStatus, ErrorCode
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools._search_helper import (
    build_user_filters,
    coerce_list_field,
    run_search_loop,
)

logger = logging.getLogger(__name__)


async def search_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface | None = None,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    query: str,
    top_k: int | None = None,
    type: str | None = None,  # noqa: A002
    tags: list[str] | None = None,
    team: str | None = None,
    project: str | None = None,
    tier: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Semantic search over the cairn artifact index.

    Embeds ``query`` with Bedrock, then calls S3 Vectors in a re-fetch loop
    to collect ``top_k`` distinct artifacts, applying scope and access-control
    gates at query time via metadata filters.

    Args:
        settings: Server configuration.
        s3: S3 client (unused; injected for interface consistency).
        vectors: S3 Vectors client.
        bedrock: Bedrock client for query embedding.
        query: Natural-language search query.
        top_k: Maximum number of distinct artifacts to return. Capped at 100.
            Defaults to ``settings.search_default_top_k``.
        type: Optional artifact type filter.
        tags: Optional list of tags; all must be present (AND semantics).
        team: Optional team filter.
        project: Optional project filter.
        tier: Optional tier filter (2 or 3).
        status: Optional status filter. Defaults to ``"active"``.

    Returns:
        On success: ``{"artifacts": [...]}`` or
        ``{"artifacts": [], "zero_results": True}`` when nothing matches.
        On error: ``{"error": str, "message": str}``
    """
    try:
        return await _search_artifacts_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            query=query,
            top_k=top_k,
            type=type,
            tags=tags,
            team=team,
            project=project,
            tier=tier,
            status=status,
        )
    except Exception as exc:
        logger.exception("Unexpected error in search_artifacts")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _search_artifacts_inner(  # noqa: PLR0913
    *,
    settings: Settings,
    s3: S3ClientInterface | None = None,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    query: str,
    top_k: int | None = None,
    type: str | None = None,  # noqa: A002
    tags: list[str] | None = None,
    team: str | None = None,
    project: str | None = None,
    tier: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Inner implementation of search_artifacts (separated to enable top-level catch-all)."""
    _ = s3

    # ── Step 1: Resolve top_k ─────────────────────────────────────────────────
    requested_top_k = top_k if top_k is not None else settings.search_default_top_k
    effective_top_k = min(requested_top_k, 100)
    clamped = effective_top_k < requested_top_k

    # ── Step 2: Embed the query (M-8: off the event loop — blocking boto3 call) ──
    try:
        query_vector = await asyncio.to_thread(
            bedrock.embed,
            query,
            settings.bedrock_embedding_model,
            settings.bedrock_embedding_dimensions,
        )
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    # ── Step 3: Build user filters ────────────────────────────────────────────
    user_filters = build_user_filters(type=type, team=team, project=project, tier=tier, tags=tags)

    # ── Step 4: Status gate ───────────────────────────────────────────────────
    status_filter: dict[str, Any] = {
        "status": {"$eq": status if status is not None else ArtifactStatus.ACTIVE}
    }

    # ── Step 5: Run shared re-fetch loop ──────────────────────────────────────
    loop_result = await run_search_loop(
        settings=settings,
        vectors=vectors,
        query_vector=query_vector,
        user_filters=user_filters,
        status_filter=status_filter,
        effective_top_k=effective_top_k,
    )

    # Propagate credential errors from the loop
    if isinstance(loop_result, dict):
        return loop_result

    raw_results: list[dict[str, Any]] = loop_result

    # ── Step 6: Build response entries ───────────────────────────────────────
    results: list[dict[str, Any]] = []
    for entry in raw_results:
        aid: str = entry["artifact_id"]
        score: float = entry["score"]
        meta: dict[str, Any] = entry["meta"]

        tags_val = coerce_list_field(meta, "tags")
        source_artifacts_val = coerce_list_field(meta, "source_artifacts")

        # Last-edited age transparency (CA-4 Option A): surface the raw ULID and a
        # derived ISO 8601 timestamp so agents can discount stale hits. This is
        # transparency only — it never influences result ordering.
        last_edited_ulid: str | None = meta.get("last_edited_ulid") or None
        last_edited_at: str | None = None
        if last_edited_ulid:
            try:
                last_edited_at = ULID.from_str(last_edited_ulid).datetime.isoformat()
            except Exception:
                logger.warning(
                    "Malformed last_edited_ulid %r — timestamp will be null", last_edited_ulid
                )
                last_edited_at = None

        results.append(
            {
                "artifact_id": aid,
                "score": score,
                "type": meta.get("type"),
                "team": meta.get("team"),
                "project": meta.get("project"),
                "tier": int(meta["tier"]),
                "date": meta.get("date"),
                "status": meta.get("status"),
                "title": meta.get("title"),
                "visibility": meta.get("visibility"),
                "tags": tags_val,
                "author_role": meta.get("author_role") or None,
                "description": meta.get("description"),
                "source_artifacts": source_artifacts_val,
                "last_edited_ulid": last_edited_ulid,
                "last_edited_at": last_edited_at,
            }
        )

    if not results:
        return {"artifacts": [], "zero_results": True}

    logger.info("Search returned %d artifacts for query=%r", len(results), query)
    response: dict[str, Any] = {"artifacts": results}
    if clamped:
        response["clamped"] = True
        response["effective_top_k"] = effective_top_k
    return response
