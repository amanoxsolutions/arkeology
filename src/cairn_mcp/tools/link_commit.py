"""cairn_mcp.tools.link_commit — link_commit MCP tool.

Appends a commit SHA to the ``commit_refs`` vector metadata of confirmed
own-scope artifacts without re-embedding them. Returns a fresh ULID cursor
(``next_since_ulid``) so the agent advances its session-start pointer after
each commit.

**V1 known limitation:** ``commit_refs`` is stored in vector metadata only.
``reconcile_index`` rebuilds vector metadata from S3 object metadata, which
does not carry ``commit_refs`` in V1. A reconcile run will therefore drop all
commit links. Re-run the post-commit protocol after any reconcile to restore
them.
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


async def link_commit(
    *,
    settings: Settings,
    s3: S3ClientInterface | None = None,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_ids: list[str],
    commit_sha: str,
) -> dict[str, Any]:
    """Link a commit SHA to the vector metadata of confirmed own-scope artifacts.

    Args:
        settings: Server configuration.
        s3: S3 client (unused in V1; injected for interface consistency).
        vectors: S3 Vectors client.
        bedrock: Bedrock client (unused; injected for interface consistency).
        artifact_ids: List of artifact IDs to associate with the commit.
        commit_sha: The commit SHA to append to each artifact's ``commit_refs``.

    Returns:
        On success::

            {
                "linked": int,
                "skipped": int,
                "commit_sha": str,
                "next_since_ulid": str,
            }

        On credential error: ``{"error": "credential_error", "message": str}``
    """
    try:
        return await _link_commit_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_ids=artifact_ids,
            commit_sha=commit_sha,
        )
    except Exception as exc:
        logger.exception("Unexpected error in link_commit")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _link_commit_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface | None = None,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_ids: list[str],
    commit_sha: str,
) -> dict[str, Any]:
    """Inner implementation of link_commit."""
    _ = s3
    _ = bedrock

    commit_sha = commit_sha.strip()
    if not commit_sha:
        return {"error": ErrorCode.VALIDATION_ERROR, "message": "commit_sha must not be empty"}

    write_prefix = settings.write_prefix
    linked = 0
    skipped = 0

    for artifact_id in artifact_ids:
        # ── Scope gate ────────────────────────────────────────────────────────
        if not artifact_id.startswith(write_prefix + "/"):
            logger.debug("link_commit scope gate rejected artifact_id=%s", artifact_id)
            skipped += 1
            continue

        try:
            # ── Fetch all vector keys for this artifact ───────────────────────
            keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})

            if not keys:
                logger.debug("link_commit no vectors found for artifact_id=%s", artifact_id)
                skipped += 1
                continue

            # ── Retrieve current vectors (metadata + float32 data) ────────────
            items = vectors.get_vectors(keys)

            # ── Build updated batch ───────────────────────────────────────────
            batch: list[dict[str, Any]] = []
            for item in items:
                meta: dict[str, Any] = dict(item["metadata"])
                existing_refs = meta.get("commit_refs")
                if isinstance(existing_refs, list):
                    current: list[str] = [str(r) for r in existing_refs]
                elif existing_refs:
                    current = [r for r in str(existing_refs).split(",") if r]
                else:
                    current = []

                # Append + deduplicate, preserving order
                merged = list(dict.fromkeys(current + [commit_sha]))
                meta["commit_refs"] = merged

                batch.append(
                    {
                        "key": item["key"],
                        "vector": item["data"]["float32"],
                        "metadata": meta,
                    }
                )

            # ── Write updated vectors back ────────────────────────────────────
            if not batch:
                skipped += 1
                continue
            vectors.put_vectors_batch(batch)
        except CredentialError as exc:
            return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

        linked += 1
        logger.info("link_commit linked artifact_id=%s sha=%s", artifact_id, commit_sha)

    # ── Generate cursor ONCE after processing all artifacts ──────────────────
    next_since_ulid = str(ULID())

    return {
        "linked": linked,
        "skipped": skipped,
        "commit_sha": commit_sha,
        "next_since_ulid": next_since_ulid,
    }
