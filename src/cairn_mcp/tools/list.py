"""cairn_mcp.tools.list — list_artifacts MCP tool implementation.

Returns metadata-only listings from the vector index with metadata filtering
and cross-scope gate enforcement. No S3 reads — all data comes from vector metadata.
"""

import asyncio
import logging
from typing import Any

from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.constants import ErrorCode
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools._search_helper import (
    build_scope_filter,
    build_user_filters,
    coerce_list_field,
)

logger = logging.getLogger(__name__)


async def list_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface | None = None,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    type: str | None = None,  # noqa: A002
    tags: list[str] | None = None,
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
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
            s3: S3 client (unused; injected for interface consistency).
            vectors: S3 Vectors client.
            bedrock: Bedrock client (unused; injected for interface consistency).
            type: Optional artifact type filter.
            tags: Optional list of tags; all must match (AND semantics).
            commit_refs: Optional list of commit refs; all must match (AND semantics).
            references: Optional list of resolved bare artifact IDs; all must be
                present on the artifact's references field (AND semantics).
            team: Optional team filter.
        project: Optional project filter.
        tier: Optional tier filter.
        status: Status filter (default "active"). Pass "all" (M-11d) to return
            artifacts regardless of status — this is the only sentinel value
            recognised; any other string is matched literally against the
            stored status.

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
            references=references,
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
    s3: S3ClientInterface | None = None,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    type: str | None = None,  # noqa: A002
    tags: list[str] | None = None,
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
    team: str | None = None,
    project: str | None = None,
    tier: int | None = None,
    status: str = "active",
) -> dict[str, Any]:
    """Inner implementation of list_artifacts (separated to enable top-level catch-all)."""
    # Suppress "unused parameter" linting
    _ = s3
    _ = bedrock

    # ── Step 1: Build metadata filter ────────────────────────────────────────
    # M-11(d): status="all" is an explicit all-inclusive sentinel — omit the status
    # clause entirely rather than filtering on the literal string "all" (which would
    # never match a stored status and always return zero results). Any other value,
    # including the "active" default, filters normally.
    clauses: list[dict[str, Any]] = []
    if status != "all":
        clauses.append({"status": {"$eq": status}})
    clauses.extend(build_user_filters(type=type, team=team, project=project, tier=tier, tags=tags))
    if commit_refs:
        for ref in commit_refs:
            clauses.append({"commit_refs": {"$eq": ref}})
    if references:
        for ref in references:
            clauses.append({"references": {"$eq": ref}})

    # ── Step 1b: Scope filter (shared with search.py / synthesise.py) ─────────
    clauses.append(build_scope_filter(settings))

    combined_filter: dict[str, Any] = {"$and": clauses} if len(clauses) > 1 else clauses[0]

    # ── Step 2: Query vector index (M-8: off the event loop) ──────────────────
    try:
        keys = await asyncio.to_thread(vectors.list_vectors_by_metadata, combined_filter)
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    if not keys:
        return {"artifacts": []}

    # ── Step 3: Fetch vector metadata (the client chunks to the GetVectors limit;
    # M-8: off the event loop) ─────────────────────────────────────────────────
    try:
        items = await asyncio.to_thread(vectors.get_vectors, keys)
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    # ── Step 4: Deduplicate by artifact_id (first occurrence wins) ────────────
    own_scope = settings.write_prefix
    read_prefixes = settings.read_prefixes_list
    seen_ids: set[str] = set()
    artifacts: list[dict[str, Any]] = []

    for item in items:
        meta = item["metadata"]
        artifact_id: str = str(meta.get("artifact_id", ""))

        if artifact_id in seen_ids:
            continue
        seen_ids.add(artifact_id)

        # ── Step 5: Cross-scope gate ──────────────────────────────────────────
        if artifact_id.startswith(own_scope + "/"):
            pass  # own scope — always allowed
        else:
            is_foreign = any(artifact_id.startswith(p + "/") for p in read_prefixes)
            item_tier = int(meta.get("tier", 0))
            item_visibility = str(meta.get("visibility", ""))
            if not (is_foreign and item_tier == 3 and item_visibility == "shared"):
                continue

        # ── Step 6: Build result dict ─────────────────────────────────────────
        tags_val = coerce_list_field(meta, "tags")
        source_artifacts_val = coerce_list_field(meta, "source_artifacts")
        commit_refs_val = coerce_list_field(meta, "commit_refs")
        references_val = coerce_list_field(meta, "references")
        last_edited_ulid_val: str | None = meta.get("last_edited_ulid") or None

        artifacts.append(
            {
                "artifact_id": artifact_id,
                "type": meta.get("type"),
                "team": meta.get("team"),
                "project": meta.get("project"),
                "tier": int(meta.get("tier", 0)),
                "date": meta.get("date"),
                "status": meta.get("status"),
                "title": meta.get("title"),
                "visibility": meta.get("visibility"),
                "tags": tags_val,
                "author_role": meta.get("author_role") or None,
                "description": meta.get("description"),
                "source_artifacts": source_artifacts_val,
                "commit_refs": commit_refs_val,
                "references": references_val,
                "last_edited_ulid": last_edited_ulid_val,
            }
        )

    logger.info("list_artifacts returned %d artifacts", len(artifacts))
    return {"artifacts": artifacts}
