"""cairn_mcp.tools.propose_commit_links — propose_commit_links MCP tool.

Read-only discovery tool: returns own-scope artifacts that have no commit_refs,
optionally bounded to those written since a given session-start ULID.

Makes no writes to S3 or the vector index.
"""

import logging
from typing import Any

from ulid import ULID

from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.constants import ErrorCode
from cairn_mcp.errors import CredentialError

logger = logging.getLogger(__name__)


async def propose_commit_links(
    *,
    settings: Settings,
    s3: S3ClientInterface | None = None,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    commit_sha: str,
    since_ulid: str | None = None,
) -> dict[str, Any]:
    """Discover own-scope artifacts with no commit_refs, optionally since a session ULID.

    Args:
        settings: Server configuration.
        s3: S3 client (unused; injected for interface consistency).
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
    s3: S3ClientInterface | None = None,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    commit_sha: str,
    since_ulid: str | None = None,
) -> dict[str, Any]:
    """Inner implementation of propose_commit_links."""
    _ = s3
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

        items = vectors.get_vectors(keys)
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    # ── Step 4: Deduplicate by artifact_id ────────────────────────────────────
    seen_ids: set[str] = set()
    candidates: list[dict[str, Any]] = []

    for item in items:
        meta = item["metadata"]
        artifact_id: str = str(meta.get("artifact_id", ""))

        if artifact_id in seen_ids:
            continue
        seen_ids.add(artifact_id)

        # ── Step 5: Client-side commit_refs filter ────────────────────────────
        raw_commit_refs = meta.get("commit_refs")
        if isinstance(raw_commit_refs, list):
            commit_refs_val: list[str] = raw_commit_refs
        elif raw_commit_refs:
            commit_refs_val = [r for r in str(raw_commit_refs).split(",") if r]
        else:
            commit_refs_val = []

        if commit_refs_val:
            # Already linked — skip
            continue

        # ── Step 6: Build candidate entry ────────────────────────────────────
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
