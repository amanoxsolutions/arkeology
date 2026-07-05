"""cairn_mcp.tools.archive — archive_artifact MCP tool implementation.

Sets an artifact's status to "inactive" in both S3 object metadata and all
corresponding vector metadata entries. Scoped to the deployment's own prefix.
Before archiving, performs a unified own-scope referenced_by check (T50,
ADR-012 D13) covering both source_artifacts and references — warn-but-don't-block,
informational (reversible) phrasing.

The status flip is an in-place S3 re-PUT, which clears the object's S3 annotations
(ADR-011). Per Phase 12 review finding C2, this tool reads the current
commit_refs/references link fields forward (via the union-of-both-stores authority
model, ``annotations.read_current_link_fields``) before the re-PUT and re-applies
them afterward (``annotations.apply_link_annotations``), mirroring write.py's
Step 4a/4b pattern — including its ``AnnotationUnavailableError`` graceful degrade
(warn, don't fail the archive) while still aborting on ``CredentialError``.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from cairn_mcp.annotations import apply_link_annotations, read_current_link_fields
from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.constants import ArtifactStatus, ErrorCode
from cairn_mcp.errors import AnnotationUnavailableError, CredentialError
from cairn_mcp.failure_log import append_failure_entry
from cairn_mcp.tools._search_helper import find_referrers

logger = logging.getLogger(__name__)


def _record_partial_archive_failure(
    settings: Settings, *, artifact_id: str, s3_meta: dict[str, Any], reason: str
) -> None:
    """Append a failure-log entry for a partially completed archive.

    A partial archive is one where the S3 status flip has already succeeded
    (``s3.put_object`` returned) but the vector-side flip (annotation re-apply
    and/or the per-vector status update loop) failed — credential error or
    otherwise (Phase 12 review M-1). Without this, a vector-side failure left no
    repairable trace: the S3 object already reports ``status: inactive`` so a
    retried ``archive_artifact`` call used to hit the ``already_archived``
    idempotency short-circuit forever (fixed alongside this by also checking
    vector status), and ``reconcile_index`` had no reason to touch an artifact
    it still considered fully indexed.

    A subsequent ``reconcile_index`` run replays this entry via the same
    failure-log mechanism used by ``write_artifact`` — ``_reindex_artifact``
    rebuilds vector metadata (including ``status``) from the S3 object, which
    already carries the correct ``inactive`` status, repairing the vector side.

    Args:
        settings: Server configuration (for ``failure_log_path``).
        artifact_id: S3 key of the partially archived artifact.
        s3_meta: The artifact's S3 object metadata (post status-flip), used to
            populate the failure-log entry's descriptive fields.
        reason: Human-readable failure reason.
    """
    tier_raw = s3_meta.get("tier", "2")
    try:
        tier = int(tier_raw)
    except TypeError, ValueError:
        tier = 2
    append_failure_entry(
        settings.failure_log_path,
        {
            "artifact_id": artifact_id,
            "title": s3_meta.get("title", ""),
            "type": s3_meta.get("type", ""),
            "tier": tier,
            "date": s3_meta.get("date", ""),
            "failure_step": "archive_vector_flip",
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


async def archive_artifact(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_id: str,
) -> dict[str, Any]:
    """Archive an artifact by setting its status to 'inactive'.

    Args:
        settings: Server configuration.
        s3: S3 client.
        vectors: S3 Vectors client.
        bedrock: Bedrock client (unused; injected for interface consistency).
        artifact_id: Full S3 key of the artifact to archive.

    Returns:
        On success: ``{"artifact_id": str, "status": "inactive"}`` plus optional
            ``"warning"`` (list of referring artifact ids) and ``"warning_message"``
            (informational, reversible-action phrasing) if own-scope referrers were
            found.
        On error: ``{"error": str, "message": str}``
    """
    try:
        return await _archive_artifact_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_id=artifact_id,
        )
    except Exception as exc:
        logger.exception("Unexpected error in archive_artifact")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _archive_artifact_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_id: str,
) -> dict[str, Any]:
    """Inner implementation of archive_artifact (separated to enable top-level catch-all)."""
    _ = bedrock

    # ── Step 1: Scope check ───────────────────────────────────────────────────
    if not artifact_id.startswith(settings.write_prefix + "/"):
        return {
            "error": ErrorCode.ACCESS_DENIED,
            "message": (
                f"Artifact '{artifact_id}' is not in the write scope "
                f"'{settings.write_prefix}'. Only own-scope artifacts may be archived."
            ),
        }

    # ── Step 2: Verify existence and get current S3 metadata ─────────────────
    try:
        s3_meta = s3.head_object(artifact_id)
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}
    except KeyError:
        return {
            "error": ErrorCode.NOT_FOUND,
            "message": f"Artifact '{artifact_id}' not found.",
        }

    # ── Step 2b: Idempotency — already fully archived → early return ─────────
    # M-1: a half-archived artifact (S3 status already flipped to inactive, but
    # one or more of its vectors are still status=active because a prior
    # vector-side flip attempt failed partway) must NOT be treated as fully
    # archived — an early return here would make every retry hit this
    # short-circuit forever and the vector side would never be repaired. Only
    # short-circuit when S3 is inactive AND every existing vector already agrees.
    if s3_meta.get("status") == ArtifactStatus.INACTIVE:
        try:
            existing_vec_keys = vectors.list_vectors_by_metadata(
                {"artifact_id": {"$eq": artifact_id}}
            )
            vectors_need_flip = False
            if existing_vec_keys:
                existing_vec_items = vectors.get_vectors(existing_vec_keys)
                vectors_need_flip = any(
                    item["metadata"].get("status") != ArtifactStatus.INACTIVE
                    for item in existing_vec_items
                )
        except CredentialError as exc:
            return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

        if not vectors_need_flip:
            return {
                "artifact_id": artifact_id,
                "status": ArtifactStatus.INACTIVE,
                "already_archived": True,
            }
        # Otherwise fall through: S3 already reports inactive but one or more
        # vectors do not — complete the interrupted vector-side flip (retry after
        # a partial archive).

    # ── Step 3: Unified own-scope referenced_by check (T50, ADR-012 D13) ─────
    try:
        referrers = find_referrers(vectors=vectors, settings=settings, artifact_id=artifact_id)
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    # ── Step 3b: Read-forward link fields before the status re-PUT (ADR-011, C2) ──
    # PutObject clears S3 annotations, so the in-place status re-PUT below would
    # otherwise silently destroy the durable commit_refs/references annotation trail.
    # Read the current values forward as the union of both durable stores (Phase 12
    # review C5/M6 — neither the annotation copy nor the vector-metadata copy is sole
    # authority; see ``annotations.read_current_link_fields``) so they can be
    # re-applied after the re-PUT.
    try:
        current_commit_refs, current_references = read_current_link_fields(s3, vectors, artifact_id)
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    # ── Step 4: Fetch content and flip S3 status ──────────────────────────────
    # Kept as its own try/except, separate from the vector-side flip below: a
    # failure here means the S3 object was never durably changed, so there is no
    # partial archive to record (M-1) — nothing has been written yet.
    updated_s3_meta: dict[str, str] = {**s3_meta, "status": ArtifactStatus.INACTIVE}
    try:
        content = s3.get_object(artifact_id)
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    try:
        s3.put_object(artifact_id, content, updated_s3_meta)
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    # ── Steps 4b–6: Re-apply link annotations and flip all vector statuses ────
    # M-1: the S3 status flip above has already succeeded — any failure from this
    # point on (annotation re-apply or the per-vector status update loop) is a
    # *partial archive* (S3 inactive, vectors not yet fully flipped) and must
    # leave a repairable failure-log trace, credential error or otherwise, so
    # reconcile_index can find and repair it and a retried archive_artifact call
    # is not blocked by the Step 2b idempotency check.
    annotation_warning: str | None = None
    try:
        # T52 / ADR-011 decision 5: annotation availability is a feature-level
        # concern, not a hard failure — the archive itself must still succeed.
        try:
            apply_link_annotations(
                s3, artifact_id, commit_refs=current_commit_refs, references=current_references
            )
        except AnnotationUnavailableError as exc:
            logger.warning(
                "Annotation re-apply unavailable for key=%s after archive status update; "
                "the durable commit_refs/references copy may be stale until the next "
                "reconcile_index run: %s",
                artifact_id,
                exc,
            )
            annotation_warning = str(exc)

        vec_keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        if vec_keys:
            vec_items = vectors.get_vectors(vec_keys)
            for item in vec_items:
                key = item["key"]
                vector_data: list[float] = item["data"]["float32"]
                updated_meta: dict[str, Any] = {
                    **item["metadata"],
                    "status": ArtifactStatus.INACTIVE,
                }
                vectors.put_vector(key, vector_data, updated_meta)
    except CredentialError as exc:
        _record_partial_archive_failure(
            settings, artifact_id=artifact_id, s3_meta=updated_s3_meta, reason=str(exc)
        )
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}
    except Exception as exc:
        _record_partial_archive_failure(
            settings, artifact_id=artifact_id, s3_meta=updated_s3_meta, reason=str(exc)
        )
        raise

    logger.info("Artifact archived: key=%s", artifact_id)
    result: dict[str, Any] = {"artifact_id": artifact_id, "status": ArtifactStatus.INACTIVE}
    if referrers:
        result["warning"] = referrers
        result["warning_message"] = (
            f"'{artifact_id}' was archived, but it is referenced by {len(referrers)} other "
            f"artifact(s): {', '.join(referrers)}. Archiving is reversible, so those references "
            "remain valid unless this artifact is later permanently deleted."
        )
    if annotation_warning is not None:
        result["annotation_warning"] = annotation_warning
    return result
