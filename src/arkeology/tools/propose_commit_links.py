"""arkeology.tools.propose_commit_links — propose_commit_links MCP tool.

Read-only discovery tool: returns own-scope artifacts that have no commit_refs,
optionally bounded to those written since a given session-start ULID.

Makes no writes to S3 or the vector index. Eligibility (``commit_refs`` empty or not)
is decided from ``annotations.read_current_link_fields`` — the union-of-both-stores
helper ``read.py``/``list.py`` already use — rather than a single vector's ``meta``, so
a multi-section artifact whose ``commit_refs`` live on a section vector other than the
one the initial dedup keeps is never silently re-proposed as unlinked (T58).
"""

import asyncio
import logging
from typing import Any

from ulid import ULID

from arkeology.annotations import read_current_link_fields
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ErrorCode
from arkeology.errors import CredentialError
from arkeology.tools._errors import credential_error_response

logger = logging.getLogger(__name__)


async def propose_commit_links(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    commit_sha: str,
    since_ulid: str | None = None,
) -> dict[str, Any]:
    """Discover own-scope artifacts with no commit_refs, optionally since a session ULID.

    Args:
        settings: Server configuration.
        s3: S3 client, used to resolve each candidate's current commit_refs via the
            union-of-both-stores helper (``annotations.read_current_link_fields``).
        vectors: S3 Vectors client.
        bedrock: Bedrock client (unused; injected for interface consistency).
        commit_sha: The commit SHA to associate (echoed in the response).
        since_ulid: Optional lower-bound ULID; only artifacts written at or after
            this ULID are included.

    Returns:
        On success: ``{"proposed": [...], "commit_sha": "<commit_sha>"}``
        On error: ``{"error": str, "message": str}``
    """
    try:
        return await _propose_commit_links_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            commit_sha=commit_sha,
            since_ulid=since_ulid,
        )
    except Exception as exc:
        logger.exception("Unexpected error in propose_commit_links")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _propose_commit_links_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    commit_sha: str,
    since_ulid: str | None = None,
) -> dict[str, Any]:
    """Inner implementation of propose_commit_links."""
    _ = bedrock

    own_scope = settings.write_prefix

    # ── Step 1: Build metadata filter (own-scope only) ────────────────────────
    scope_clause: dict[str, Any] = {"scope": {"$eq": own_scope}}

    if since_ulid is not None:
        # Artifacts without last_edited_ulid are intentionally excluded when since_ulid is
        # set — the $gte filter only matches artifacts that carry a ULID, which is consistent
        # with the frozen requirement that session-bounded proposals apply only to artifacts
        # written during the current session (which always have last_edited_ulid set).
        combined_filter: dict[str, Any] = {
            "$and": [
                scope_clause,
                {"last_edited_ulid": {"$gte": since_ulid}},
            ]
        }
    else:
        combined_filter = scope_clause

    # ── Steps 2–3: List matching vector keys, then fetch their metadata ───────
    try:
        keys = vectors.list_vectors_by_metadata(combined_filter)

        if not keys:
            return {"proposed": [], "commit_sha": commit_sha}

        items = vectors.get_vectors(keys, include_data=False)
    except CredentialError as exc:
        return credential_error_response(exc)

    # ── Step 4: Deduplicate by artifact_id ────────────────────────────────────
    seen_ids: set[str] = set()
    base_entries: list[tuple[str, dict[str, Any]]] = []

    for item in items:
        meta = item["metadata"]
        artifact_id: str = str(meta.get("artifact_id", ""))

        if artifact_id in seen_ids:
            continue
        seen_ids.add(artifact_id)
        base_entries.append((artifact_id, meta))

    # ── Step 5: Resolve each candidate's current commit_refs from the union of both
    # durable stores ────────────────────────────────────────────────────────────────
    # A single vector's `meta.get("commit_refs")` misses a value set (via link_metadata)
    # on a different section vector, and — after T58's vector-metadata entry cap — can
    # also miss a value that aged out of that one vector's capped window. Resolving via
    # read_current_link_fields (annotation ∪ every section vector) closes both gaps.
    # These are additional round trips beyond the single batched list_vectors_by_metadata
    # + get_vectors fetch above — the same accepted cost list.py/read.py already carry
    # for the identical fix — so they run off the event loop and in parallel via
    # asyncio.gather, mirroring list.py's _fetch_link_fields pattern exactly. No new
    # bounded-concurrency setting: a candidate page is small relative to a single
    # artifact's section count, so an unbounded gather is the proportionate choice here.
    async def _fetch_commit_refs(artifact_id: str) -> list[str]:
        commit_refs, _references = await asyncio.to_thread(
            read_current_link_fields, s3, vectors, artifact_id
        )
        return commit_refs

    distinct_ids = [artifact_id for artifact_id, _meta in base_entries]
    commit_refs_by_id: dict[str, list[str]] = {}
    if distinct_ids:
        results = await asyncio.gather(
            *(_fetch_commit_refs(artifact_id) for artifact_id in distinct_ids),
            return_exceptions=True,
        )
        for artifact_id, result in zip(distinct_ids, results, strict=True):
            if isinstance(result, CredentialError):
                return credential_error_response(result)
            if isinstance(result, BaseException):
                # commit_refs is supplementary to this discovery — degrade this one
                # candidate to [] (treated as not-yet-linked) rather than aborting the
                # whole call on a transient per-artifact vector/annotation error,
                # mirroring list.py's existing degrade-on-error behaviour for the same
                # helper.
                logger.warning(
                    "Failed to read commit_refs for %s; degrading to []",
                    artifact_id,
                    exc_info=result,
                )
                commit_refs_by_id[artifact_id] = []
            else:
                commit_refs_by_id[artifact_id] = result

    # ── Step 6: Filter already-linked candidates, build response entries ──────
    candidates: list[dict[str, Any]] = []
    for artifact_id, meta in base_entries:
        if commit_refs_by_id.get(artifact_id):
            # Already linked — skip
            continue

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

        candidates.append(
            {
                "artifact_id": artifact_id,
                "title": meta.get("title"),
                "type": meta.get("type"),
                "last_edited_ulid": last_edited_ulid,
                "last_edited_at": last_edited_at,
            }
        )

    logger.info("propose_commit_links found %d candidates", len(candidates))
    return {"proposed": candidates, "commit_sha": commit_sha}
