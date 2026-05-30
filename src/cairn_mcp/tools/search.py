"""cairn_mcp.tools.search — search_artifacts MCP tool implementation.

Embeds a natural-language query and retrieves the most semantically similar
artifacts from the S3 Vectors index, subject to scope and access-control gates.
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
    feature_tags: list[str] | None = None,
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
        feature_tags: Optional list of tags; all must be present (AND semantics).
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
            feature_tags=feature_tags,
            team=team,
            project=project,
            tier=tier,
            status=status,
        )
    except Exception as exc:
        logger.exception("Unexpected error in search_artifacts")
        return {"error": "internal_error", "message": str(exc)}


async def _search_artifacts_inner(  # noqa: PLR0913
    *,
    settings: Settings,
    s3: S3ClientInterface | None = None,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    query: str,
    top_k: int | None = None,
    type: str | None = None,  # noqa: A002
    feature_tags: list[str] | None = None,
    team: str | None = None,
    project: str | None = None,
    tier: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Inner implementation of search_artifacts (separated to enable top-level catch-all)."""
    # ── Step 1: Resolve top_k ─────────────────────────────────────────────────
    effective_top_k = min(top_k if top_k is not None else settings.search_default_top_k, 100)

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
    if tier is not None:
        user_filters.append({"tier": {"$eq": tier}})
    if feature_tags:
        for tag in feature_tags:
            user_filters.append({"feature_tags": {"$eq": tag}})

    # ── Step 4: Status gate ───────────────────────────────────────────────────
    status_filter: dict[str, Any] = {"status": {"$eq": status if status is not None else "active"}}

    # ── Step 5: Scope filter ──────────────────────────────────────────────────
    read_prefixes = settings.read_prefixes_list
    write_prefix = settings.write_prefix

    if read_prefixes:
        scope_filter: dict[str, Any] = {
            "$or": [
                {"scope": {"$eq": write_prefix}},
                {
                    "$and": [
                        {"scope": {"$in": read_prefixes}},
                        {"tier": {"$eq": 3}},
                        {"visibility": {"$eq": "shared"}},
                    ]
                },
            ]
        }
    else:
        scope_filter = {"scope": {"$eq": write_prefix}}

    # ── Step 6: Re-fetch loop ─────────────────────────────────────────────────
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []

    for _ in range(settings.search_max_iterations):
        # Build combined filter
        and_clauses: list[dict[str, Any]] = [*user_filters, status_filter, scope_filter]

        if seen_ids:
            and_clauses.append({"artifact_id": {"$nin": list(seen_ids)}})

        combined_filter: dict[str, Any] = (
            {"$and": and_clauses} if len(and_clauses) > 1 else and_clauses[0]
        )

        try:
            raw = vectors.query_vectors(query_vector, settings.search_fetch_top_k, combined_filter)
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc)}

        # Group by artifact_id, keep highest score per artifact
        best_by_id: dict[str, tuple[float, dict[str, Any]]] = {}
        for item in raw:
            item_meta: dict[str, Any] = item["metadata"]
            aid: str = str(item_meta["artifact_id"])
            score: float = float(item["score"])
            if aid not in best_by_id or score > best_by_id[aid][0]:
                best_by_id[aid] = (score, item_meta)

        new_entries = [
            (aid, data) for aid, data in best_by_id.items() if aid not in seen_ids
        ]

        if not new_entries:
            break

        for aid, data in new_entries:
            score, meta = data
            feature_tags_val: list[str] = (
                meta["feature_tags"]
                if isinstance(meta.get("feature_tags"), list)
                else [t for t in str(meta.get("feature_tags", "")).split(",") if t]
            )
            source_artifacts_val: list[str] = (
                meta["source_artifacts"]
                if isinstance(meta.get("source_artifacts"), list)
                else [s for s in str(meta.get("source_artifacts", "")).split(",") if s]
            )
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
                    "feature_tags": feature_tags_val,
                    "author_role": meta.get("author_role") or None,
                    "description": meta.get("description"),
                    "source_artifacts": source_artifacts_val,
                }
            )
            seen_ids.add(aid)

        if len(results) >= effective_top_k:
            break

    # ── Step 7: Sort and trim ─────────────────────────────────────────────────
    results.sort(key=lambda r: float(r["score"]), reverse=True)
    results = results[:effective_top_k]

    if not results:
        return {"artifacts": [], "zero_results": True}

    logger.info("Search returned %d artifacts for query=%r", len(results), query)
    return {"artifacts": results}
