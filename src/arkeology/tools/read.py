"""arkeology.tools.read — read_artifact MCP tool implementation.

Retrieves a single artifact from S3, applying scope and access-control gates
before fetching content.
"""

import asyncio
import logging
from typing import Any

from arkeology.annotations import read_link_annotations
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ErrorCode
from arkeology.errors import AnnotationUnavailableError, CredentialError
from arkeology.tools._errors import annotation_unavailable_response, credential_error_response
from arkeology.tools._reference_filter import resolve_readable_targets
from arkeology.tools._scope import is_cross_scope_readable, is_own_scope
from arkeology.tools._search_helper import coerce_list_field

logger = logging.getLogger(__name__)


async def read_artifact(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface | None = None,
    bedrock: BedrockClientInterface | None = None,
    artifact_id: str,
) -> dict[str, Any]:
    """Retrieve a single artifact from S3 with access-control enforcement.

    Access rules:
    - Own-scope artifacts (``artifact_id`` starts with ``write_prefix/``):
      always accessible.
    - Foreign-scope artifacts (``artifact_id`` starts with a known read prefix):
      accessible only when ``tier == 3`` **and** ``visibility == "shared"``.
    - All other artifact IDs: access denied.

    Args:
        settings: Server configuration.
        s3: S3 client for content and metadata retrieval.
        vectors: S3 Vectors client, used only for cross-scope reference filtering.
        bedrock: Bedrock client (unused; injected for interface consistency).
        artifact_id: Full S3 key of the artifact to retrieve.

    Returns:
        On success: dict with all artifact fields including ``content``.
        On error: ``{"error": str, "message": str}``
    """
    try:
        return await _read_artifact_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_id=artifact_id,
        )
    except AnnotationUnavailableError as exc:
        # One condition, one code, from every tool that reads the durable link fields:
        # startup check 8 proves the annotation store available before the server accepts
        # a request, so this is post-setup IAM drift, not "something unexpected".
        return annotation_unavailable_response(exc)
    except Exception as exc:
        logger.exception("Unexpected error in read_artifact")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _read_artifact_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface | None = None,
    bedrock: BedrockClientInterface | None = None,
    artifact_id: str,
) -> dict[str, Any]:
    """Inner implementation of read_artifact (separated to enable top-level catch-all)."""
    # Suppress "unused parameter" linting — injected for interface consistency.
    _ = bedrock

    # ── Step 1: Determine scope ───────────────────────────────────────────────
    own_scope = is_own_scope(artifact_id, settings.write_prefix)
    foreign_prefix: str | None = next(
        (p for p in settings.read_prefixes_list if is_own_scope(artifact_id, p)),
        None,
    )

    if not own_scope and foreign_prefix is None:
        return {
            "error": ErrorCode.ACCESS_DENIED,
            "message": f"Artifact '{artifact_id}' is not in any accessible scope.",
        }

    # ── Step 2: Fetch metadata and apply gate (off the event loop) ───────────
    try:
        meta = await asyncio.to_thread(s3.head_object, artifact_id)
    except CredentialError as exc:
        return credential_error_response(exc)
    except KeyError:
        return {
            "error": ErrorCode.NOT_FOUND,
            "message": f"Artifact '{artifact_id}' not found.",
        }

    # Foreign scope: gate on tier == 3 and visibility == "shared".
    # Own scope: no gate — existence is already confirmed above.
    if foreign_prefix is not None and not own_scope:
        readable = is_cross_scope_readable(
            meta, artifact_id, settings.write_prefix, settings.read_prefixes_list
        )
        if not readable:
            return {
                "error": ErrorCode.ACCESS_DENIED,
                "message": (
                    f"Artifact '{artifact_id}' is not accessible: "
                    "only tier-3 shared artifacts may be read from foreign scopes."
                ),
            }

    # ── Step 3: Fetch content (off the event loop) ────────────────────────────
    try:
        content = await asyncio.to_thread(s3.get_object, artifact_id)
    except CredentialError as exc:
        return credential_error_response(exc)

    # ── Step 4: Read commit_refs / references from the durable annotations ────
    # The S3 object annotations are the sole source of truth for both fields. The
    # vector-metadata copy of commit_refs is a derived filter index — capped, missing
    # references entirely, and only reachable by paginating the whole index, since S3
    # Vectors has no server-side filter for it — so it is never read back here. A
    # failure propagates rather than degrading to []: reporting "no links" for what is
    # really a transient failure is what a later read-modify-write cycle would write
    # back over good data.
    try:
        # Off the event loop — blocking boto3 calls.
        commit_refs, references = await asyncio.to_thread(read_link_annotations, s3, artifact_id)
    except CredentialError as exc:
        return credential_error_response(exc)

    # ── Step 4b: Cross-scope reference filtering (ADR-012) ────────────────────
    # Only foreign-scope reads need filtering: own-scope reads/entries are never
    # filtered (and thus never pay for the extra vector-client query).
    if foreign_prefix is not None and not own_scope and references and vectors is not None:
        try:
            readable_targets = await resolve_readable_targets(vectors, settings, set(references))
        except CredentialError as exc:
            return credential_error_response(exc)
        references = [r for r in references if r in readable_targets]

    # ── Step 5: Deserialise remaining S3 metadata ─────────────────────────────
    tags = coerce_list_field(meta, "tags")
    source_artifacts = coerce_list_field(meta, "source_artifacts")
    last_edited_ulid: str | None = meta.get("last_edited_ulid") or None

    logger.info("Artifact read: key=%s", artifact_id)
    return {
        "artifact_id": artifact_id,
        "content": content,
        "type": meta.get("type"),
        "team": meta.get("team"),
        "project": meta.get("project"),
        "tier": int(meta["tier"]),
        "date": meta.get("date"),
        "status": meta.get("status"),
        "title": meta.get("title"),
        "visibility": meta.get("visibility"),
        "tags": tags,
        "author_role": meta.get("author_role") or None,
        "description": meta.get("description"),
        "source_artifacts": source_artifacts,
        "commit_refs": commit_refs,
        "references": references,
        "last_edited_ulid": last_edited_ulid,
    }
