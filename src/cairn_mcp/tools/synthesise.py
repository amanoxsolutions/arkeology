"""cairn_mcp.tools.synthesise — synthesise_artifacts MCP tool implementation.

Combines semantic search with batch S3 content retrieval. Returns full content
for the top-k matching artifacts in a single call. The synthesis itself is the
caller's responsibility — this tool assembles source material only.
"""

import logging
from typing import Any

from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools._search_helper import run_search_loop

logger = logging.getLogger(__name__)


async def synthesise_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    query: str,
    top_k: int = 10,
    type: str | None = None,  # noqa: A002
    tags: list[str] | None = None,
    team: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Search artifacts semantically and return full content for the top results.

    Args:
        settings: Server configuration.
        s3: S3 client for content retrieval.
        vectors: S3 Vectors client.
        bedrock: Bedrock client for query embedding.
        query: Natural-language search query.
        top_k: Maximum results to return. Capped at 100. Defaults to 10.
        type: Optional artifact type filter.
        tags: Optional list of tags.
        team: Optional team filter.
        project: Optional project filter.

    Returns:
        On success: ``{"artifacts": [...]}`` — each entry includes all metadata
            fields plus ``content``.
        On error: ``{"error": str, "message": str}``
    """
    try:
        return await _synthesise_artifacts_inner(
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
        )
    except Exception as exc:
        logger.exception("Unexpected error in synthesise_artifacts")
        return {"error": "internal_error", "message": str(exc)}


async def _synthesise_artifacts_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    query: str,
    top_k: int = 10,
    type: str | None = None,  # noqa: A002
    tags: list[str] | None = None,
    team: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Inner implementation of synthesise_artifacts (separated to enable top-level catch-all)."""
    # ── Step 1: Clamp top_k ───────────────────────────────────────────────────
    effective_top_k = min(top_k, 100)
    clamped = effective_top_k < top_k

    # ── Step 2: Embed the query ───────────────────────────────────────────────
    try:
        query_vector = bedrock.embed(
            query,
            settings.bedrock_embedding_model,
            settings.bedrock_embedding_dimensions,
        )
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}

    # ── Step 3: Build user filters ────────────────────────────────────────────
    user_filters: list[dict[str, Any]] = []
    if type is not None:
        user_filters.append({"type": {"$eq": type}})
    if team is not None:
        user_filters.append({"team": {"$eq": team}})
    if project is not None:
        user_filters.append({"project": {"$eq": project}})
    if tags:
        for tag in tags:
            user_filters.append({"tags": {"$eq": tag}})

    # ── Step 4: Status gate — always "active" for synthesis ───────────────────
    status_filter: dict[str, Any] = {"status": {"$eq": "active"}}

    # ── Step 5: Run shared re-fetch loop (no tier filter for synthesise) ──────
    loop_result = run_search_loop(
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

    search_results: list[dict[str, Any]] = loop_result

    if not search_results:
        return {"artifacts": []}

    # ── Step 6: Fetch content for each result ─────────────────────────────────
    artifacts: list[dict[str, Any]] = []
    for entry in search_results:
        artifact_id: str = entry["artifact_id"]
        meta: dict[str, Any] = entry["meta"]

        try:
            content = s3.get_object(artifact_id)
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc)}
        except Exception:
            logger.warning("Skipping artifact '%s': S3 read failed", artifact_id)
            continue

        tags_val: list[str] = (
            meta["tags"]
            if isinstance(meta.get("tags"), list)
            else [t for t in str(meta.get("tags", "")).split(",") if t]
        )

        artifacts.append(
            {
                "artifact_id": artifact_id,
                "content": content,
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
            }
        )

    logger.info(
        "synthesise_artifacts returned %d artifacts for query=%r",
        len(artifacts),
        query,
    )
    response: dict[str, Any] = {"artifacts": artifacts}
    if clamped:
        response["clamped"] = True
        response["effective_top_k"] = effective_top_k
    return response
