"""arkeology.tools.purge — purge_archived MCP tool implementation.

Hard-deletes all inactive artifacts in the deployment's own scope, with cascade
deletion of synthesis artifacts whose every source_artifact is in the purge set.
"""

import logging
from typing import Any

from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ArtifactStatus, ErrorCode
from arkeology.errors import CredentialError
from arkeology.tools._errors import credential_error_response

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
        On success: ``{"purged_count": int, "purged_ids": [...],
            "cascade_deleted": [...], "failed": [...]}`` — ``purged_ids`` /
            ``purged_count`` reflect artifacts actually fully deleted (S3 object
            removed), ``cascade_deleted`` the cascade syntheses actually deleted,
            and ``failed`` the artifacts that could not be deleted (empty when all
            succeed). Each ``failed`` entry is
            ``{"artifact_id": str, "error": str, "message": str}``.
        On a systemic error (confirm gate, discovery-phase or mid-loop credential
            failure): ``{"error": str, "message": str}``, the latter case still
            carrying the artifacts purged so far in ``purged_ids``.
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
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


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
            "error": ErrorCode.CONFIRMATION_REQUIRED,
            "message": (
                "Purge requires explicit confirmation. "
                "Pass confirm=True to proceed with bulk deletion."
            ),
        }

    empty_result: dict[str, Any] = {
        "purged_count": 0,
        "purged_ids": [],
        "cascade_deleted": [],
        "failed": [],
    }

    # ── Steps 2–3: Find inactive vectors, fetch metadata, deduplicate by id ───
    own_scope = settings.write_prefix
    try:
        inactive_keys = vectors.list_vectors_by_metadata(
            {
                "$and": [
                    {"scope": {"$eq": own_scope}},
                    {"status": {"$eq": ArtifactStatus.INACTIVE}},
                ]
            }
        )
        if not inactive_keys:
            return empty_result

        inactive_items = vectors.get_vectors(inactive_keys, include_data=False)
    except CredentialError as exc:
        return credential_error_response(exc)

    purge_set: set[str] = set()
    for item in inactive_items:
        aid = str(item["metadata"].get("artifact_id", ""))
        if aid and aid.startswith(own_scope + "/"):
            purge_set.add(aid)

    if not purge_set:
        return empty_result

    # ── Step 4: Cascade check — active synthesis in own scope ────────────────
    cascade_set: set[str] = set()
    try:
        synthesis_keys = vectors.list_vectors_by_metadata(
            {
                "$and": [
                    {"scope": {"$eq": own_scope}},
                    {"type": {"$eq": "synthesis"}},
                    {"status": {"$eq": ArtifactStatus.ACTIVE}},
                ]
            }
        )
        if synthesis_keys:
            synthesis_items = vectors.get_vectors(synthesis_keys, include_data=False)

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
    except CredentialError as exc:
        return credential_error_response(exc)

    # ── Step 5: Best-effort deletion of purge_set + cascade_set ──────────────
    # The deletion phase is best-effort: a non-credential failure on one artifact
    # is recorded in ``failed`` and the loop continues. A CredentialError is
    # systemic and aborts the remaining deletions, still reporting what was purged.
    cascade_only = [c for c in cascade_set if c not in purge_set]
    all_to_delete = list(purge_set) + cascade_only

    purged_ids: list[str] = []
    cascade_deleted: list[str] = []
    failed: list[dict[str, str]] = []

    def _record_success(artifact_id: str) -> None:
        if artifact_id in cascade_set:
            cascade_deleted.append(artifact_id)
        else:
            purged_ids.append(artifact_id)

    def _record_failure(artifact_id: str, error: str, message: str) -> None:
        failed.append({"artifact_id": artifact_id, "error": error, "message": message})

    try:
        for artifact_id in all_to_delete:
            # Find this artifact's vector keys; a non-credential failure here
            # leaves the artifact fully intact — record and continue.
            try:
                artifact_vec_keys = vectors.list_vectors_by_metadata(
                    {"artifact_id": {"$eq": artifact_id}}
                )
            except CredentialError:
                raise
            except Exception as exc:
                _record_failure(artifact_id, ErrorCode.DELETE_VECTORS_FAILED, str(exc))
                continue

            # Delete vectors first; a non-credential failure leaves the artifact
            # fully intact (vectors + S3 both present) — record and continue.
            if artifact_vec_keys:
                try:
                    vectors.delete_vectors(artifact_vec_keys)
                except CredentialError:
                    raise
                except Exception as exc:
                    _record_failure(artifact_id, ErrorCode.DELETE_VECTORS_FAILED, str(exc))
                    continue

            # Delete the S3 object; a non-credential failure here leaves a
            # recoverable S3 orphan (per T12 / FR-17) — record and continue.
            try:
                s3.delete_object(artifact_id)
            except CredentialError:
                raise
            except Exception as exc:
                _record_failure(artifact_id, ErrorCode.PARTIAL_DELETE, str(exc))
                continue

            _record_success(artifact_id)
    except CredentialError as exc:
        logger.warning(
            "purge_archived aborted by credential error after purging %d artifact(s)",
            len(purged_ids),
        )
        return {
            "error": ErrorCode.CREDENTIAL_ERROR,
            "message": str(exc),
            "purged_count": len(purged_ids),
            "purged_ids": sorted(purged_ids),
            "cascade_deleted": sorted(cascade_deleted),
            "failed": failed,
        }

    logger.info(
        "purge_archived: purged=%d cascade=%d failed=%d",
        len(purged_ids),
        len(cascade_deleted),
        len(failed),
    )
    return {
        "purged_count": len(purged_ids),
        "purged_ids": sorted(purged_ids),
        "cascade_deleted": sorted(cascade_deleted),
        "failed": failed,
    }
