"""arkeology.tools.delete — delete_artifact MCP tool implementation.

Hard-deletes a single artifact (S3 object + all section vectors) from the
deployment's own scope. Requires explicit confirm=True. Deletion ordering is
vectors-first, S3-second to ensure worst-case partial failure leaves a
recoverable S3 orphan rather than orphaned vectors. Before deleting, performs
a unified own-scope referenced_by check (T50, ADR-012 D13) covering both
source_artifacts and references — warn-but-don't-block, permanent-action phrasing.
"""

import logging
from typing import Any

from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ErrorCode
from arkeology.errors import CredentialError
from arkeology.tools._errors import credential_error_response
from arkeology.tools._search_helper import find_referrers

logger = logging.getLogger(__name__)


async def delete_artifact(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_id: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Hard-delete an artifact from S3 and the vector index.

    Args:
        settings: Server configuration.
        s3: S3 client.
        vectors: S3 Vectors client.
        bedrock: Bedrock client (unused; injected for interface consistency).
        artifact_id: Full S3 key of the artifact to delete.
        confirm: Must be True to proceed; False returns a confirmation_required error.

    Returns:
        On success: ``{"artifact_id": str, "deleted": True}`` plus optional
            ``"warnings"`` (list of referring artifact ids) and ``"warning_message"``
            (stronger, permanent-action phrasing) if own-scope referrers were found.
        On error: ``{"error": str, "message": str}``
    """
    try:
        return await _delete_artifact_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_id=artifact_id,
            confirm=confirm,
        )
    except Exception as exc:
        logger.exception("Unexpected error in delete_artifact")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _delete_artifact_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_id: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Inner implementation of delete_artifact (separated to enable top-level catch-all)."""
    _ = bedrock

    # ── Step 1: Confirmation gate ─────────────────────────────────────────────
    if not confirm:
        return {
            "error": ErrorCode.CONFIRMATION_REQUIRED,
            "message": (
                "Deletion requires explicit confirmation. "
                "Pass confirm=True to proceed with hard deletion."
            ),
        }

    # ── Step 2: Scope check ───────────────────────────────────────────────────
    if not artifact_id.startswith(settings.write_prefix + "/"):
        return {
            "error": ErrorCode.ACCESS_DENIED,
            "message": (
                f"Artifact '{artifact_id}' is not in the write scope "
                f"'{settings.write_prefix}'. Only own-scope artifacts may be deleted."
            ),
        }

    # ── Step 3: Verify existence ──────────────────────────────────────────────
    try:
        s3.head_object(artifact_id)
    except CredentialError as exc:
        return credential_error_response(exc)
    except KeyError:
        return {
            "error": ErrorCode.NOT_FOUND,
            "message": f"Artifact '{artifact_id}' not found.",
        }

    # ── Step 4: Unified own-scope referenced_by check (T50, ADR-012 D13) ──────
    try:
        referrers = find_referrers(vectors=vectors, settings=settings, artifact_id=artifact_id)
    except CredentialError as exc:
        return credential_error_response(exc)

    # ── Step 5: Find all vector keys for this artifact ────────────────────────
    try:
        vec_keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    except CredentialError as exc:
        return credential_error_response(exc)

    # ── Step 6: Delete vectors first ─────────────────────────────────────────
    if vec_keys:
        try:
            vectors.delete_vectors(vec_keys)
        except CredentialError as exc:
            return credential_error_response(exc)
        except Exception as exc:
            return {"error": ErrorCode.DELETE_VECTORS_FAILED, "message": str(exc)}

    # ── Step 7: Delete S3 object ──────────────────────────────────────────────
    try:
        s3.delete_object(artifact_id)
    except CredentialError as exc:
        return {
            "error": ErrorCode.CREDENTIAL_ERROR,
            "message": str(exc),
            "artifact_id": artifact_id,
        }
    except Exception as exc:
        return {
            "error": ErrorCode.PARTIAL_DELETE,
            "message": str(exc),
            "artifact_id": artifact_id,
        }

    logger.info("Artifact deleted: key=%s", artifact_id)
    result: dict[str, Any] = {"artifact_id": artifact_id, "deleted": True}
    if referrers:
        result["warnings"] = referrers
        result["warning_message"] = (
            f"'{artifact_id}' was permanently deleted, but it is still referenced by "
            f"{len(referrers)} other artifact(s): {', '.join(referrers)}. This action cannot be "
            "undone — those references now point to a deleted artifact."
        )
    return result
