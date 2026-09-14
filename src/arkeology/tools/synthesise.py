"""arkeology.tools.synthesise — synthesise_artifacts MCP tool implementation.

Combines semantic search with batch S3 content retrieval. Returns full content
for the top-k matching artifacts in a single call. The synthesis itself is the
caller's responsibility — this tool assembles source material only.
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
            fields plus ``content``, ``score`` (the same ``1.0 - cosine_distance``
            value ``search_artifacts`` reports) and ``last_edited_at``.
            ``"fetch_exhausted": True`` is included when the re-fetch loop ran out
            of candidates before filling ``top_k``, so a budget-limited result set
            is distinguishable from an exhaustive one.
            ``"index_corruption_detected": True`` is
            included when the re-fetch loop stopped because a vector result was
            missing its ``distance`` field — a soft signal of possible S3
            Vectors index corruption; whatever results were already collected
            are still returned, never a hard error.
            ``"skipped_malformed_count": int`` is included, only when non-zero, when
            a candidate was dropped because its stored *metadata* could not be read
            into a result — a second counter alongside ``skipped_count``, which
            counts content-read failures against S3, because the two point an
            operator at different repairs.
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
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


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
    clamp_result = clamp_top_k(top_k)
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

    # ── Step 3: Build user filters (no tier filter for synthesise) ────────────
    try:
        user_filters = build_user_filters(type=type, team=team, project=project, tags=tags)
    except InvalidFilterValueError as exc:
        return {"error": ErrorCode.VALIDATION_ERROR, "message": str(exc)}

    # ── Step 4: Status gate — always "active" for synthesis ───────────────────
    status_filter: dict[str, Any] = {"status": {"$eq": ArtifactStatus.ACTIVE}}

    # ── Step 5: Run shared re-fetch loop (no tier filter for synthesise) ──────
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

    # Both flags are surfaced, for the same reason: each is an observability signal the
    # caller needs regardless of which tool triggered the re-fetch loop. Dropping
    # fetch_exhausted would silently convert an incomplete result set into one
    # indistinguishable from an exhaustive one.
    search_results, fetch_exhausted, index_corruption_detected, skipped_malformed = loop_result

    if not search_results:
        zero_response: dict[str, Any] = {"artifacts": [], "zero_results": True}
        if index_corruption_detected:
            zero_response["index_corruption_detected"] = True
        if skipped_malformed:
            # On the short-circuit list deliberately: a zero result reached because
            # every candidate was unreadable is precisely the case a caller must not
            # mistake for "no such artifact exists".
            zero_response["skipped_malformed_count"] = skipped_malformed
        return zero_response

    # ── Step 6: Fetch content for each result, budget-aware ────────────────────
    # Track a running total of assembled response bytes — measured as the
    # UTF-8-encoded byte length of each result's `content` field only, per the
    # frozen decision (per-entry metadata is small, fixed overhead and is not
    # counted). Candidates arrive already rank-ordered by the search loop, so
    # stopping as soon as the next candidate would exceed the budget preserves
    # the highest-ranked results. The single-oversized-first-result edge case
    # (no results assembled yet) is always included regardless of its size, so
    # a single relevant oversized hit is never dropped entirely.
    max_response_bytes = settings.synthesise_max_response_bytes
    artifacts: list[dict[str, Any]] = []
    total_content_bytes = 0
    truncated = False
    skipped_count = 0
    for entry in search_results:
        artifact_id: str = entry["artifact_id"]
        meta: dict[str, Any] = entry["meta"]

        # The same summary search_artifacts builds, from the same helper, so the two
        # tools cannot drift into reporting different fields for the same artifact —
        # plus this tool's own additions below: the content that is its whole point, and
        # the score the search loop already computed for the ranking it returned.
        #
        # Built before the content fetch, deliberately: a candidate whose stored
        # metadata cannot be read into a result is dropped before it costs an S3 read,
        # which is also what keeps it out of skipped_count. The two counters are
        # disjoint because they send an operator to two different repairs — a transient
        # or permissions failure against S3, versus corrupt index metadata reconcile
        # rebuilds.
        summary = build_artifact_summary(
            meta,
            artifact_id,
            coerce_list_field(meta, "tags"),
            coerce_list_field(meta, "source_artifacts"),
        )
        if summary is None:
            skipped_malformed += 1
            continue

        try:
            content = await asyncio.to_thread(s3.get_object, artifact_id)
        except CredentialError as exc:
            return credential_error_response(exc)
        except Exception:
            logger.warning("Skipping artifact '%s': S3 read failed", artifact_id)
            skipped_count += 1
            continue

        content_bytes = len(content.encode("utf-8"))
        if artifacts and total_content_bytes + content_bytes > max_response_bytes:
            truncated = True
            break

        summary["content"] = content
        summary["score"] = entry["score"]
        summary["last_edited_at"] = derive_last_edited_at(summary["last_edited_ulid"])
        artifacts.append(summary)
        total_content_bytes += content_bytes
        if total_content_bytes > max_response_bytes:
            # The single oversized-first-result edge case: this one result already
            # exceeds the budget alone, but it is included anyway — mark truncated
            # and stop rather than fetching any further candidates.
            truncated = True
            break

    logger.info(
        "synthesise_artifacts returned %d artifacts for query=%r",
        len(artifacts),
        query,
    )
    response: dict[str, Any] = {"artifacts": artifacts}
    if clamped:
        response["clamped"] = True
        response["effective_top_k"] = effective_top_k
    if truncated:
        response["truncated"] = True
        response["included"] = len(artifacts)
    if skipped_count:
        response["skipped_count"] = skipped_count
    if skipped_malformed:
        response["skipped_malformed_count"] = skipped_malformed
    if fetch_exhausted:
        response["fetch_exhausted"] = True
    if index_corruption_detected:
        response["index_corruption_detected"] = True
    return response
