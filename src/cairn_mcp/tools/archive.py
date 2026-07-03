"""cairn_mcp.tools.archive — archive_artifact MCP tool implementation.

Sets an artifact's status to "inactive" in both S3 object metadata and all
corresponding vector metadata entries. Scoped to the deployment's own prefix.
Before archiving, performs a unified own-scope referenced_by check (T50,
ADR-012 D13) covering both source_artifacts and references — warn-but-don't-block,
informational (reversible) phrasing.
"""

import logging
from typing import Any

from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.constants import ArtifactStatus, ErrorCode
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools._search_helper import find_referrers

logger = logging.getLogger(__name__)


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

    # ── Step 2b: Idempotency — already inactive → early return ───────────────
    if s3_meta.get("status") == ArtifactStatus.INACTIVE:
        return {
            "artifact_id": artifact_id,
            "status": ArtifactStatus.INACTIVE,
            "already_archived": True,
        }

    # ── Step 3: Unified own-scope referenced_by check (T50, ADR-012 D13) ─────
    try:
        referrers = find_referrers(vectors=vectors, settings=settings, artifact_id=artifact_id)
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    # ── Steps 4–6: Fetch content, write back status, update all vectors ───────
    updated_s3_meta: dict[str, str] = {**s3_meta, "status": ArtifactStatus.INACTIVE}
    try:
        content = s3.get_object(artifact_id)
        s3.put_object(artifact_id, content, updated_s3_meta)

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
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    logger.info("Artifact archived: key=%s", artifact_id)
    result: dict[str, Any] = {"artifact_id": artifact_id, "status": ArtifactStatus.INACTIVE}
    if referrers:
        result["warning"] = referrers
        result["warning_message"] = (
            f"'{artifact_id}' was archived, but it is referenced by {len(referrers)} other "
            f"artifact(s): {', '.join(referrers)}. Archiving is reversible, so those references "
            "remain valid unless this artifact is later permanently deleted."
        )
    return result
