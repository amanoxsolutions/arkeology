"""cairn_mcp.tools.purge — purge_archived MCP tool implementation.

Hard-deletes all inactive artifacts in the deployment's own scope, with cascade
deletion of synthesis artifacts whose every source_artifact is in the purge set.
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


async def purge_archived(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Purge all archived (inactive) artifacts from the deployment's own scope.

    Cascade-deletes active synthesis artifacts whose every source_artifact is in
    the purge set. Never touches foreign-scope artifacts.

    Args:
        settings: Server configuration.
        s3: S3 client.
        vectors: S3 Vectors client.
        bedrock: Bedrock client (unused; injected for interface consistency).
        confirm: Must be True to proceed.

    Returns:
        On success: ``{"purged_count": int, "purged_ids": [...], "cascade_deleted": [...]}``
        On error: ``{"error": str, "message": str}``
    """
    try:
        return await _purge_archived_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            confirm=confirm,
        )
    except Exception as exc:
        logger.exception("Unexpected error in purge_archived")
        return {"error": "internal_error", "message": str(exc)}


async def _purge_archived_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Inner implementation of purge_archived (separated to enable top-level catch-all)."""
    _ = bedrock

    # ── Step 1: Confirmation gate ─────────────────────────────────────────────
    if not confirm:
        return {
            "error": "confirmation_required",
            "message": (
                "Purge requires explicit confirmation. "
                "Pass confirm=True to proceed with bulk deletion."
            ),
        }

    # ── Step 2: Find all inactive vectors in own scope ────────────────────────
    own_scope = settings.write_prefix
    try:
        inactive_keys = vectors.list_vectors_by_metadata(
            {
                "$and": [
                    {"scope": {"$eq": own_scope}},
                    {"status": {"$eq": "inactive"}},
                ]
            }
        )
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}

    if not inactive_keys:
        return {"purged_count": 0, "purged_ids": [], "cascade_deleted": []}

    # ── Step 3: Fetch metadata and deduplicate by artifact_id ─────────────────
    try:
        inactive_items = vectors.get_vectors(inactive_keys)
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}

    purge_set: set[str] = set()
    for item in inactive_items:
        aid = str(item["metadata"].get("artifact_id", ""))
        if aid and aid.startswith(own_scope + "/"):
            purge_set.add(aid)

    if not purge_set:
        return {"purged_count": 0, "purged_ids": [], "cascade_deleted": []}

    # ── Step 4: Cascade check — active synthesis in own scope ────────────────
    cascade_set: set[str] = set()
    try:
        synthesis_keys = vectors.list_vectors_by_metadata(
            {
                "$and": [
                    {"scope": {"$eq": own_scope}},
                    {"type": {"$eq": "synthesis"}},
                    {"status": {"$eq": "active"}},
                ]
            }
        )
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}

    if synthesis_keys:
        try:
            synthesis_items = vectors.get_vectors(synthesis_keys)
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc)}

        seen_synth: set[str] = set()
        for item in synthesis_items:
            meta = item["metadata"]
            synth_id: str = str(meta.get("artifact_id", ""))
            if synth_id in seen_synth:
                continue
            seen_synth.add(synth_id)
            source_arts = meta.get("source_artifacts", [])
            if not isinstance(source_arts, list) or not source_arts:
                continue
            # Cascade only when ALL sources are in the purge set
            if all(src in purge_set for src in source_arts):
                cascade_set.add(synth_id)

    # ── Step 5: Delete all artifacts in purge_set + cascade_set ─────────────
    all_to_delete = list(purge_set) + [c for c in cascade_set if c not in purge_set]

    for artifact_id in all_to_delete:
        # Find and delete vectors
        try:
            artifact_vec_keys = vectors.list_vectors_by_metadata(
                {"artifact_id": {"$eq": artifact_id}}
            )
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc)}

        if artifact_vec_keys:
            try:
                vectors.delete_vectors(artifact_vec_keys)
            except CredentialError as exc:
                return {"error": "credential_error", "message": str(exc)}
            except Exception as exc:
                return {"error": "delete_vectors_failed", "message": str(exc)}

        # Delete S3 object
        try:
            s3.delete_object(artifact_id)
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc), "artifact_id": artifact_id}
        except Exception as exc:
            return {
                "error": "partial_delete",
                "message": str(exc),
                "artifact_id": artifact_id,
            }

    purged_ids = sorted(purge_set)
    cascade_deleted = sorted(cascade_set)
    logger.info(
        "purge_archived: purged=%d cascade=%d",
        len(purged_ids),
        len(cascade_deleted),
    )
    return {
        "purged_count": len(purge_set),
        "purged_ids": purged_ids,
        "cascade_deleted": cascade_deleted,
    }
