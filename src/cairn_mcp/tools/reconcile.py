"""cairn_mcp.tools.reconcile — reconcile_index MCP tool implementation.

Replays the partial-write failure log and scans for orphaned S3 objects,
re-indexing any artifacts that are present in S3 but absent from the vector
index.
"""

import json
import logging
from pathlib import Path
from typing import Any

from cairn_mcp.artifact import parse_sections, section_slug
from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools.write import (
    _build_document_embedding_text,
    _build_section_embedding_text,
)

logger = logging.getLogger(__name__)


def _reindex_artifact(
    artifact_id: str,
    content: str,
    raw_s3_meta: dict[str, Any],
    settings: Settings,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> int:
    """Re-index a single artifact into the vector store.

    Reads content and S3 metadata already retrieved by the caller, reconstructs
    vector metadata (mirrors write_artifact's format), parses sections, embeds
    each section (or uses a document-level fallback), and upserts into the
    vector index.

    Args:
        artifact_id: Full S3 key of the artifact (includes write_prefix).
        content: Artifact body text.
        raw_s3_meta: Metadata dict returned by ``head_object`` (string values).
        settings: Server configuration.
        vectors: Vectors client for upsert.
        bedrock: Bedrock client for embedding.

    Returns:
        Number of vectors written (one per section, or 1 for the fallback).
    """
    title = raw_s3_meta.get("title", "")
    artifact_type = raw_s3_meta.get("type", "")
    tier_raw = raw_s3_meta.get("tier", "2")
    tier = int(tier_raw)
    tags = [t for t in raw_s3_meta.get("tags", "").split(",") if t]
    source_artifacts_list = [s for s in raw_s3_meta.get("source_artifacts", "").split(",") if s]
    commit_refs_list = [r for r in raw_s3_meta.get("commit_refs", "").split(",") if r]

    vector_metadata: dict[str, Any] = {
        "artifact_id": artifact_id,
        "scope": settings.write_prefix,
        "type": artifact_type,
        "team": raw_s3_meta.get("team", ""),
        "project": raw_s3_meta.get("project", ""),
        "tier": tier,
        "date": raw_s3_meta.get("date", ""),
        "status": raw_s3_meta.get("status", "active"),
        "title": title,
        "visibility": raw_s3_meta.get("visibility", "shared"),
        "author_role": raw_s3_meta.get("author_role", ""),
        "description": raw_s3_meta.get("description", ""),
        # Mirror write_artifact: last_edited_ulid is always present in vector metadata.
        "last_edited_ulid": raw_s3_meta.get("last_edited_ulid", ""),
    }
    # S3 Vectors rejects empty arrays — omit list fields when empty.
    if tags:
        vector_metadata["tags"] = tags
    if source_artifacts_list:
        vector_metadata["source_artifacts"] = source_artifacts_list
    if commit_refs_list:
        vector_metadata["commit_refs"] = commit_refs_list

    sections = parse_sections(content)
    new_keys: set[str] = set()

    if sections:
        for sec in sections:
            embed_text = _build_section_embedding_text(
                title=title,
                artifact_type=artifact_type,
                tags=tags,
                section_heading=sec.heading,
                section_body=sec.body,
            )
            try:
                embedding = bedrock.embed(
                    embed_text,
                    settings.bedrock_embedding_model,
                    settings.bedrock_embedding_dimensions,
                )
            except CredentialError:
                raise
            vec_key = f"{artifact_id}#{section_slug(sec.heading)}"
            try:
                vectors.put_vector(vec_key, embedding, vector_metadata)
            except CredentialError:
                raise
            new_keys.add(vec_key)
    else:
        embed_text = _build_document_embedding_text(
            title=title,
            artifact_type=artifact_type,
            tags=tags,
            description=raw_s3_meta.get("description", ""),
        )
        try:
            embedding = bedrock.embed(
                embed_text,
                settings.bedrock_embedding_model,
                settings.bedrock_embedding_dimensions,
            )
        except CredentialError:
            raise
        try:
            vectors.put_vector(artifact_id, embedding, vector_metadata)
        except CredentialError:
            raise
        new_keys.add(artifact_id)

    return len(new_keys)


async def reconcile_index(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> dict[str, Any]:
    """Replay the failure log and scan for orphaned S3 objects, re-indexing any found.

    Args:
        settings: Server configuration.
        s3: S3 client for content and metadata retrieval.
        vectors: S3 Vectors client for index queries and upserts.
        bedrock: Bedrock client for embedding generation.

    Returns:
        On success: dict with keys ``reconciled``, ``failed``,
            ``failure_log_entries_before``, ``failure_log_entries_after``,
            ``orphans_found``, ``total_reconciled``, ``dangling_artifacts_found``,
            ``dangling_vectors_pruned``, ``dangling_artifacts``.
        On error: ``{"error": "credential_error" | "internal_error", "message": str(exc)}``.
    """
    try:
        return await _reconcile_index_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
        )
    except Exception as exc:
        logger.exception("Unexpected error in reconcile_index")
        return {"error": "internal_error", "message": str(exc)}


async def _reconcile_index_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> dict[str, Any]:
    """Inner implementation of reconcile_index.

    Returns:
        On success: dict with keys ``reconciled``, ``failed``,
            ``failure_log_entries_before``, ``failure_log_entries_after``,
            ``orphans_found``, ``total_reconciled``, ``dangling_artifacts_found``,
            ``dangling_vectors_pruned``, ``dangling_artifacts``.
        On error: ``{"error": "credential_error" | "internal_error", "message": str(exc)}``.
    """
    reconciled: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    failed_ids: set[str] = set()

    # ── Phase 1: Failure log replay ───────────────────────────────────────────
    log_path: Path = settings.failure_log_path
    failure_log_entries_before = 0
    failure_log_entries_after = 0

    if log_path.exists():
        raw_lines = log_path.read_text(encoding="utf-8").splitlines()
        entries: list[dict[str, Any]] = []
        for raw_line in raw_lines:
            entry_line = raw_line.strip()
            if entry_line:
                try:
                    entries.append(json.loads(entry_line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed failure log line: %s", entry_line)

        failure_log_entries_before = len(entries)

        # Deduplicate by artifact_id — attempt re-index once per unique ID.
        seen_ids: set[str] = set()
        unique_entries: list[dict[str, Any]] = []
        for entry in entries:
            aid = entry.get("artifact_id", "")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                unique_entries.append(entry)

        resolved_ids: set[str] = set()

        for entry in unique_entries:
            artifact_id = entry.get("artifact_id", "")
            if not artifact_id:
                continue
            if not artifact_id.startswith(settings.write_prefix + "/"):
                logger.warning("Skipping out-of-scope failure log entry: %s", artifact_id)
                continue
            try:
                raw_meta = s3.head_object(artifact_id)
            except CredentialError as exc:
                return {"error": "credential_error", "message": str(exc)}
            except KeyError:
                failed.append({"artifact_id": artifact_id, "reason": "S3 object not found"})
                failed_ids.add(artifact_id)
                continue
            except Exception as exc:
                failed.append({"artifact_id": artifact_id, "reason": str(exc)})
                failed_ids.add(artifact_id)
                continue

            try:
                content = s3.get_object(artifact_id)
                n = _reindex_artifact(
                    artifact_id,
                    content,
                    raw_meta,
                    settings,
                    vectors,
                    bedrock,
                )
                reconciled.append(
                    {
                        "artifact_id": artifact_id,
                        "title": raw_meta.get("title", ""),
                        "sections_indexed": n,
                        "source": "failure_log",
                    }
                )
                resolved_ids.add(artifact_id)
            except CredentialError as exc:
                return {"error": "credential_error", "message": str(exc)}
            except Exception as exc:
                failed.append({"artifact_id": artifact_id, "reason": str(exc)})
                failed_ids.add(artifact_id)

        # Rewrite the failure log — retain only entries whose artifact_id was NOT resolved.
        remaining_entries = [e for e in entries if e.get("artifact_id", "") not in resolved_ids]
        failure_log_entries_after = len(remaining_entries)

        if remaining_entries:
            log_path.write_text(
                "".join(json.dumps(e) + "\n" for e in remaining_entries),
                encoding="utf-8",
            )
        else:
            log_path.unlink(missing_ok=True)
    else:
        failure_log_entries_before = 0
        failure_log_entries_after = 0

    # ── Phase 2: Orphan scan ──────────────────────────────────────────────────
    own_prefix = settings.write_prefix + "/"
    try:
        all_s3_keys = s3.list_objects(settings.write_prefix)
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}
    own_keys = [
        k
        for k in all_s3_keys
        if k.startswith(own_prefix)
        and "_cairn_health_probe" not in k
        and "_cairn_mcp_startup_probe" not in k
    ]

    try:
        indexed_keys_raw = vectors.list_vectors_by_metadata(
            {"scope": {"$eq": settings.write_prefix}}
        )
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}
    # Build vectors_by_artifact: maps artifact_id → list of its vector keys.
    # Splitting on '#' extracts the artifact_id from keys like "{artifact_id}#{section_slug}".
    # This single pass serves both Scenario 2 (indexed_artifact_ids) and
    # Scenario 3 (dangling vector pruning) without iterating indexed_keys_raw twice.
    vectors_by_artifact: dict[str, list[str]] = {}
    for vk in indexed_keys_raw:
        artifact_id = vk.split("#")[0]
        vectors_by_artifact.setdefault(artifact_id, []).append(vk)
    indexed_artifact_ids: set[str] = set(vectors_by_artifact.keys())

    orphans = [k for k in own_keys if k not in indexed_artifact_ids and k not in failed_ids]
    orphans_found = len(orphans)

    for orphan_key in orphans:
        try:
            content = s3.get_object(orphan_key)
            raw_meta = s3.head_object(orphan_key)
            n = _reindex_artifact(
                orphan_key,
                content,
                raw_meta,
                settings,
                vectors,
                bedrock,
            )
            reconciled.append(
                {
                    "artifact_id": orphan_key,
                    "title": raw_meta.get("title", ""),
                    "sections_indexed": n,
                    "source": "orphan_scan",
                }
            )
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc)}
        except Exception as exc:
            failed.append({"artifact_id": orphan_key, "reason": str(exc)})

    # ── Phase 3: Dangling vector pruning ─────────────────────────────────────
    # Dangling vectors are index entries whose S3 object no longer exists.
    # own_keys is already filtered to own-scope; indexed_artifact_ids is also
    # own-scope (enforced by the list_vectors_by_metadata scope filter above).
    own_keys_set: set[str] = set(own_keys)
    dangling_artifact_ids = set(vectors_by_artifact.keys()) - own_keys_set

    dangling_artifacts: list[str] = []
    dangling_artifacts_found = 0
    dangling_vectors_pruned = 0

    for dangling_id in dangling_artifact_ids:
        keys_to_delete = vectors_by_artifact[dangling_id]
        try:
            vectors.delete_vectors(keys_to_delete)
            dangling_artifacts.append(dangling_id)
            dangling_artifacts_found += 1
            dangling_vectors_pruned += len(keys_to_delete)
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc)}
        except Exception as exc:
            failed.append({"artifact_id": dangling_id, "reason": str(exc)})

    logger.info(
        "reconcile_index complete: reconciled=%d failed=%d orphans=%d dangling=%d",
        len(reconciled),
        len(failed),
        orphans_found,
        dangling_artifacts_found,
    )
    return {
        "reconciled": reconciled,
        "failed": failed,
        "failure_log_entries_before": failure_log_entries_before,
        "failure_log_entries_after": failure_log_entries_after,
        "orphans_found": orphans_found,
        "total_reconciled": len(reconciled),
        "dangling_artifacts_found": dangling_artifacts_found,
        "dangling_vectors_pruned": dangling_vectors_pruned,
        "dangling_artifacts": dangling_artifacts,
    }
