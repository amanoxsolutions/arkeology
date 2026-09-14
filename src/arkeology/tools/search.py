"""arkeology.tools.search — search_artifacts MCP tool implementation.

Embeds a natural-language query and retrieves the most semantically similar
artifacts from the S3 Vectors index, subject to scope and access-control gates.
"""

import asyncio
import logging
from typing import Any

from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ArtifactStatus, ErrorCode
from arkeology.errors import CredentialError, InvalidFilterValueError
from arkeology.tools._errors import credential_error_response
from arkeology.tools._search_helper import (
    build_artifact_summary,
    build_user_filters,
    clamp_top_k,
    coerce_list_field,
    derive_last_edited_at,
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
    """Semantic search over the arkeology artifact index.

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
        status: Optional status filter. Defaults to ``"active"``. Pass the explicit
            sentinel ``"all"`` (as ``list_artifacts`` accepts) to search regardless
            of status.

    Returns:
        On success: ``{"artifacts": [...]}`` or
        ``{"artifacts": [], "zero_results": True}`` when nothing matches.
        ``"clamped": True`` and ``"effective_top_k": int`` are also included when
        the requested ``top_k`` was capped at the 100 ceiling. ``"fetch_exhausted":
        True`` is included when the re-fetch loop's own fetch budget (not the true
        number of matching artifacts) is what limited the result count below
        ``top_k`` — more matches may exist beyond what was returned.
        ``"index_corruption_detected": True`` is included when the re-fetch loop
        stopped because a vector result was missing its ``distance`` field — a
        soft signal of possible S3 Vectors index corruption; whatever results
        were already collected are still returned, never a hard error.
        ``"skipped_malformed_count": int`` is included, only when non-zero, when a
        candidate was dropped because its stored metadata could not be read into a
        result — no usable ``artifact_id``, or a ``tier`` that will not coerce. A
        candidate the cross-scope gate denied is never counted there: counting it
        would disclose that a foreign artifact exists.
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
    clamp_result = clamp_top_k(requested_top_k)
    if isinstance(clamp_result, dict):
        return clamp_result
    effective_top_k, clamped = clamp_result

    # ── Step 2: Embed the query (off the event loop — blocking boto3 call) ───────
    try:
        query_vector = await asyncio.to_thread(
            bedrock.embed,
            query,
            settings.bedrock_embedding_model,
            settings.bedrock_embedding_dimensions,
        )
    except CredentialError as exc:
        return credential_error_response(exc)

    # ── Step 3: Build user filters ────────────────────────────────────────────
    try:
        user_filters = build_user_filters(
            type=type, team=team, project=project, tier=tier, tags=tags
        )
    except InvalidFilterValueError as exc:
        return {"error": ErrorCode.VALIDATION_ERROR, "message": str(exc)}

    # ── Step 4: Status gate ───────────────────────────────────────────────────
    # status="all" is the same explicit all-inclusive sentinel list_artifacts recognises:
    # drop the status clause entirely rather than filtering on the literal string "all",
    # which matches no stored status and would silently return zero results. Any other
    # value, including the "active" default, must be a recognised status — a typo must
    # not fall through to a clause that legitimately matches nothing.
    status_filter: dict[str, Any] | None = None
    if status != "all":
        if status is not None:
            try:
                ArtifactStatus(status)
            except ValueError:
                return {
                    "error": ErrorCode.VALIDATION_ERROR,
                    "message": f"invalid status filter value: {status!r}",
                }
        status_filter = {"status": {"$eq": status if status is not None else ArtifactStatus.ACTIVE}}

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

    raw_results, fetch_exhausted, index_corruption_detected, skipped_malformed = loop_result

    # ── Step 6: Build response entries ───────────────────────────────────────
    results: list[dict[str, Any]] = []
    for entry in raw_results:
        aid: str = entry["artifact_id"]
        score: float = entry["score"]
        meta: dict[str, Any] = entry["meta"]

        tags_val = coerce_list_field(meta, "tags")
        source_artifacts_val = coerce_list_field(meta, "source_artifacts")

        summary = build_artifact_summary(meta, aid, tags_val, source_artifacts_val)
        if summary is None:
            # Stored metadata this result shape cannot be read into. Dropped rather
            # than returned with a defaulted tier, and counted so the caller can tell
            # a short result set from an exhaustive one.
            skipped_malformed += 1
            continue
        summary["score"] = score
        # Last-edited age transparency: surface the raw ULID and a derived ISO 8601
        # timestamp so agents can discount stale hits themselves. This is transparency
        # only — age never influences result ordering, which stays purely semantic.
        summary["last_edited_at"] = derive_last_edited_at(summary["last_edited_ulid"])
        results.append(summary)

    if not results:
        zero_response: dict[str, Any] = {"artifacts": [], "zero_results": True}
        if index_corruption_detected:
            zero_response["index_corruption_detected"] = True
        if skipped_malformed:
            # Zero results reached because every candidate was unreadable is precisely
            # the case a caller must not mistake for "no such artifact exists".
            zero_response["skipped_malformed_count"] = skipped_malformed
        return zero_response

    logger.info("Search returned %d artifacts for query=%r", len(results), query)
    response: dict[str, Any] = {"artifacts": results}
    if clamped:
        response["clamped"] = True
        response["effective_top_k"] = effective_top_k
    if fetch_exhausted:
        response["fetch_exhausted"] = True
    if index_corruption_detected:
        response["index_corruption_detected"] = True
    if skipped_malformed:
        response["skipped_malformed_count"] = skipped_malformed
    return response
