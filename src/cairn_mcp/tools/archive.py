"""cairn_mcp.tools.archive — archive_artifact MCP tool implementation.

Sets an artifact's status to "inactive" in both S3 object metadata and all
corresponding vector metadata entries. Scoped to the deployment's own prefix.
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
        On success: ``{"artifact_id": str, "status": "inactive"}``
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
        return {"error": "internal_error", "message": str(exc)}


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
            "error": "access_denied",
            "message": (
                f"Artifact '{artifact_id}' is not in the write scope "
                f"'{settings.write_prefix}'. Only own-scope artifacts may be archived."
            ),
        }

    # ── Step 2: Verify existence and get current S3 metadata ─────────────────
    try:
        s3_meta = s3.head_object(artifact_id)
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}
    except KeyError:
        return {
            "error": "not_found",
            "message": f"Artifact '{artifact_id}' not found.",
        }

    # ── Step 3: Fetch current content ────────────────────────────────────────
    try:
        content = s3.get_object(artifact_id)
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}

    # ── Step 4: Write back with updated status ────────────────────────────────
    updated_s3_meta: dict[str, str] = {**s3_meta, "status": "inactive"}
    try:
        s3.put_object(artifact_id, content, updated_s3_meta)
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}

    # ── Step 5: Update all section vectors ───────────────────────────────────
    try:
        vec_keys = vectors.list_vectors_by_metadata(
            {"artifact_id": {"$eq": artifact_id}}
        )
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}

    if vec_keys:
        try:
            vec_items = vectors.get_vectors(vec_keys)
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc)}

        for item in vec_items:
            key = item["key"]
            vector_data: list[float] = item["data"]["float32"]
            updated_meta: dict[str, Any] = {**item["metadata"], "status": "inactive"}
            try:
                vectors.put_vector(key, vector_data, updated_meta)
            except CredentialError as exc:
                return {"error": "credential_error", "message": str(exc)}

    logger.info("Artifact archived: key=%s", artifact_id)
    return {"artifact_id": artifact_id, "status": "inactive"}
