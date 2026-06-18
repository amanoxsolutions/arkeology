"""cairn_mcp.tools.read — read_artifact MCP tool implementation.

Retrieves a single artifact from S3, applying scope and access-control gates
before fetching content.
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
        vectors: S3 Vectors client for reading commit_refs from vector metadata.
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
    except Exception as exc:
        logger.exception("Unexpected error in read_artifact")
        return {"error": "internal_error", "message": str(exc)}


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
    own_scope = artifact_id.startswith(settings.write_prefix + "/")
    foreign_prefix: str | None = next(
        (p for p in settings.read_prefixes_list if artifact_id.startswith(p + "/")),
        None,
    )

    if not own_scope and foreign_prefix is None:
        return {
            "error": "access_denied",
            "message": f"Artifact '{artifact_id}' is not in any accessible scope.",
        }

    # ── Step 2: Fetch metadata and apply gate ─────────────────────────────────
    if foreign_prefix is not None and not own_scope:
        # Foreign scope: gate on tier == 3 and visibility == "shared"
        try:
            meta = s3.head_object(artifact_id)
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc)}
        except KeyError:
            return {
                "error": "not_found",
                "message": f"Artifact '{artifact_id}' not found.",
            }

        if int(meta["tier"]) != 3 or meta.get("visibility") != "shared":
            return {
                "error": "access_denied",
                "message": (
                    f"Artifact '{artifact_id}' is not accessible: "
                    "only tier-3 shared artifacts may be read from foreign scopes."
                ),
            }
    else:
        # Own scope: no gate — just verify it exists
        try:
            meta = s3.head_object(artifact_id)
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc)}
        except KeyError:
            return {
                "error": "not_found",
                "message": f"Artifact '{artifact_id}' not found.",
            }

    # ── Step 3: Fetch content ─────────────────────────────────────────────────
    try:
        content = s3.get_object(artifact_id)
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}

    # ── Step 4: Read commit_refs from vector metadata ─────────────────────────
    # commit_refs are stored in vector metadata only — link_commit appends SHAs
    # there without touching S3 object metadata.  Reading from vectors ensures
    # post-link_commit SHAs are surfaced.
    commit_refs: list[str] = []
    if vectors is not None:
        try:
            keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
            if keys:
                entries = vectors.get_vectors([keys[0]])
                if entries:
                    raw = entries[0].get("metadata", {}).get("commit_refs", [])
                    if isinstance(raw, list):
                        commit_refs = raw
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc)}

    # ── Step 5: Deserialise remaining S3 metadata ─────────────────────────────
    tags: list[str] = [t for t in str(meta.get("tags", "")).split(",") if t]
    source_artifacts: list[str] = [s for s in str(meta.get("source_artifacts", "")).split(",") if s]
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
        "last_edited_ulid": last_edited_ulid,
    }
