"""arkeology.tools.list — list_artifacts MCP tool implementation.

Returns metadata-only listings from the vector index with metadata filtering
and cross-scope gate enforcement. Vector metadata supplies every field except
commit_refs/references, which are read via the union-of-both-durable-stores
model (``annotations.read_current_link_fields``) so a multi-section artifact
never surfaces an arbitrary single section vector's possibly-stale copy.
"""

import asyncio
import logging
from typing import Any

from arkeology.annotations import read_current_link_fields
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ArtifactStatus, ErrorCode
from arkeology.errors import CredentialError, InvalidFilterValueError
from arkeology.tools._errors import credential_error_response
from arkeology.tools._reference_filter import resolve_readable_targets
from arkeology.tools._scope import build_scope_filter, is_cross_scope_readable, is_own_scope
from arkeology.tools._search_helper import (
    build_artifact_summary,
    build_user_filters,
    coerce_list_field,
    fetch_vectors_by_metadata,
)

logger = logging.getLogger(__name__)


async def list_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    type: str | None = None,  # noqa: A002
    tags: list[str] | None = None,
    commit_refs: list[str] | None = None,
    team: str | None = None,
    project: str | None = None,
    tier: int | None = None,
    status: str = "active",
) -> dict[str, Any]:
    """List artifacts from the vector index with metadata filtering.

    Applies cross-scope gate: own-scope artifacts always visible; foreign-scope
    artifacts only when tier=3 AND visibility="shared".

    Args:
        settings: Server configuration.
        s3: S3 client, used to read the durable commit_refs/references
            annotation copy per distinct artifact in the page (see
            annotations.read_current_link_fields).
        vectors: S3 Vectors client.
        bedrock: Bedrock client (unused; injected for interface consistency).
        type: Optional artifact type filter.
        tags: Optional list of tags; all must match (AND semantics).
        commit_refs: Optional list of commit refs; all must match (AND semantics).
            Filters the capped most-recent-20 vector-metadata copy, not the full
            durable list, so an artifact with more than 20 linked commits is not
            matched on its oldest SHAs.
        team: Optional team filter.
        project: Optional project filter.
        tier: Optional tier filter.
        status: Status filter (default "active"). Pass "all" to return
            artifacts regardless of status — the status clause is omitted
            entirely rather than matched literally, since "all" is not a
            stored status. It is the only sentinel recognised; any other
            value must be a valid status, and an unrecognised one returns
            a validation error rather than silently matching nothing.

    Returns:
        On success: ``{"artifacts": [...]}``
        On error: ``{"error": str, "message": str}``
    """
    try:
        return await _list_artifacts_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            type=type,
            tags=tags,
            commit_refs=commit_refs,
            team=team,
            project=project,
            tier=tier,
            status=status,
        )
    except Exception as exc:
        logger.exception("Unexpected error in list_artifacts")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _list_artifacts_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    type: str | None = None,  # noqa: A002
    tags: list[str] | None = None,
    commit_refs: list[str] | None = None,
    team: str | None = None,
    project: str | None = None,
    tier: int | None = None,
    status: str = "active",
) -> dict[str, Any]:
    """Inner implementation of list_artifacts (separated to enable top-level catch-all)."""
    # Suppress "unused parameter" linting
    _ = bedrock

    # ── Step 1: Build metadata filter ────────────────────────────────────────
    # status="all" is an explicit all-inclusive sentinel — omit the status
    # clause entirely rather than filtering on the literal string "all" (which would
    # never match a stored status and always return zero results). Any other value,
    # including the "active" default, filters normally — but it must be a
    # recognised status value, not a silently-empty-matching typo.
    clauses: list[dict[str, Any]] = []
    if status != "all":
        try:
            ArtifactStatus(status)
        except ValueError:
            return {
                "error": ErrorCode.VALIDATION_ERROR,
                "message": f"invalid status filter value: {status!r}",
            }
        clauses.append({"status": {"$eq": status}})
    try:
        clauses.extend(
            build_user_filters(type=type, team=team, project=project, tier=tier, tags=tags)
        )
    except InvalidFilterValueError as exc:
        return {"error": ErrorCode.VALIDATION_ERROR, "message": str(exc)}
    if commit_refs:
        for ref in commit_refs:
            clauses.append({"commit_refs": {"$eq": ref}})

    # ── Step 1b: Scope filter (shared with search.py / synthesise.py) ─────────
    clauses.append(build_scope_filter(settings.write_prefix, settings.read_prefixes_list))

    combined_filter: dict[str, Any] = {"$and": clauses} if len(clauses) > 1 else clauses[0]

    # ── Steps 2-3: Query vector index, then fetch vector metadata (the client
    # chunks to the GetVectors limit; off the event loop) ─────────────────────
    try:
        items = await asyncio.to_thread(
            fetch_vectors_by_metadata, vectors, combined_filter, include_data=False
        )
    except CredentialError as exc:
        return credential_error_response(exc)

    if not items:
        return {"artifacts": []}

    # ── Step 4: Deduplicate by artifact_id (first occurrence wins) and apply the
    # cross-scope gate ──────────────────────────────────────────────────────────
    own_scope = settings.write_prefix
    read_prefixes = settings.read_prefixes_list
    seen_ids: set[str] = set()
    gated_entries: list[tuple[str, bool, dict[str, Any]]] = []

    for item in items:
        meta = item["metadata"]
        artifact_id: str = str(meta.get("artifact_id", ""))

        if artifact_id in seen_ids:
            continue
        seen_ids.add(artifact_id)

        is_own = is_own_scope(artifact_id, own_scope)
        if not is_own and not is_cross_scope_readable(meta, artifact_id, own_scope, read_prefixes):
            continue

        gated_entries.append((artifact_id, is_own, meta))

    # ── Step 4b: commit_refs/references — union of both durable stores ────────
    # Fetched only for entries that survived the cross-scope gate above (never
    # for foreign-scope entries that failed it) and only once per distinct
    # artifact_id (gated_entries is already deduplicated). Each fetch is a
    # blocking S3 + S3 Vectors round trip via read_current_link_fields, so this
    # is N sequential-cost lookups for a page of N distinct artifacts — there is
    # no batched alternative (unlike the single-query resolve_readable_targets
    # below), so they run off the event loop and in parallel via asyncio.gather
    # rather than one at a time. No new bounded-concurrency setting (compare
    # write.py's SECTION_CONCURRENCY): a listing page is small relative to a
    # single artifact's section count, so an unbounded gather is the
    # proportionate choice here.
    async def _fetch_link_fields(artifact_id: str) -> tuple[list[str], list[str]]:
        return await asyncio.to_thread(read_current_link_fields, s3, vectors, artifact_id)

    distinct_ids = [artifact_id for artifact_id, _, _ in gated_entries]
    link_fields_by_id: dict[str, tuple[list[str], list[str]]] = {}
    if distinct_ids:
        link_field_results = await asyncio.gather(
            *(_fetch_link_fields(artifact_id) for artifact_id in distinct_ids),
            return_exceptions=True,
        )
        for artifact_id, result in zip(distinct_ids, link_field_results, strict=True):
            if isinstance(result, CredentialError):
                return credential_error_response(result)
            if isinstance(result, BaseException):
                # commit_refs / references are supplementary — degrade this one
                # artifact to [] rather than aborting the whole page on a
                # transient per-artifact vector/annotation error.
                logger.warning(
                    "Failed to read commit_refs/references for %s; degrading to []",
                    artifact_id,
                    exc_info=result,
                )
                link_fields_by_id[artifact_id] = ([], [])
            else:
                link_fields_by_id[artifact_id] = result

    # ── Step 5: Cross-scope reference filtering (ADR-012) ─────────────────────
    # Own-scope entries are never filtered. Foreign entries' references are
    # resolved with a single batched query covering the whole page, regardless
    # of how many distinct foreign entries or reference ids are involved.
    candidate_ids: set[str] = set()
    for artifact_id, is_own, _meta in gated_entries:
        if not is_own:
            candidate_ids.update(link_fields_by_id[artifact_id][1])

    readable_targets: set[str] = set()
    if candidate_ids:
        try:
            readable_targets = await resolve_readable_targets(vectors, settings, candidate_ids)
        except CredentialError as exc:
            return credential_error_response(exc)

    # ── Step 6: Build result dicts ──────────────────────────────────────────
    artifacts: list[dict[str, Any]] = []
    for artifact_id, is_own, meta in gated_entries:
        tags_val = coerce_list_field(meta, "tags")
        source_artifacts_val = coerce_list_field(meta, "source_artifacts")
        commit_refs_val, references_val = link_fields_by_id[artifact_id]
        if not is_own:
            references_val = [r for r in references_val if r in readable_targets]

        summary = build_artifact_summary(meta, artifact_id, tags_val, source_artifacts_val)
        summary["commit_refs"] = commit_refs_val
        summary["references"] = references_val
        artifacts.append(summary)

    logger.info("list_artifacts returned %d artifacts", len(artifacts))
    return {"artifacts": artifacts}
