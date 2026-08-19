"""arkeology.tools.reconcile — reconcile_index MCP tool implementation.

Replays the partial-write failure log and scans for orphaned S3 objects,
re-indexing any artifacts that are present in S3 but absent from the vector
index.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from arkeology.annotations import CAS_MAX_ATTEMPTS, read_current_link_fields
from arkeology.artifact import decode_metadata_value
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ArtifactStatus, ErrorCode
from arkeology.errors import CredentialError
from arkeology.tools._errors import credential_error_response
from arkeology.tools._search_helper import coerce_list_field
from arkeology.tools._section_pipeline import (
    build_document_embedding_text,
    disambiguate_section_slugs,
    prepare_sections_for_embedding,
)

logger = logging.getLogger(__name__)

# Reserved marker for throwaway connectivity-probe objects written into a deployment's own
# WRITE_PREFIX (the health-check probe in ``tools/health.py``, the startup probe in
# ``startup.py``, the setting-up-arkeology skill's annotation probe). Any key whose final
# path segment begins with this marker is a probe, never an artifact: no generated artifact
# id can collide with it, because every id starts with a type slug drawn from
# ``ARTIFACT_TYPES``, none of which begins with an underscore. Matching the marker rather
# than individual probe names means a future probe needs no change here.
_PROBE_KEY_MARKER = "_arkeology_"


def _reindex_artifact(
    artifact_id: str,
    content: str,
    raw_s3_meta: dict[str, Any],
    settings: Settings,
    s3: S3ClientInterface,
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
        s3: S3 client, used to read the durable commit_refs/references annotations
            (ADR-011).
        vectors: Vectors client, used both for upsert and to read the existing indexed
            vector-metadata copy of commit_refs/references before it is overwritten,
            so the union-of-both-stores authority model
            (``read_current_link_fields``) never loses a value that lives only in the
            vector copy (e.g. an annotation-unavailable deployment).
        bedrock: Bedrock client for embedding.

    Returns:
        Number of vectors written (one per section, or 1 for the fallback).

    Raises:
        CredentialError: If reading the durable link fields fails due to expired or
            invalid credentials — propagated to the caller rather than swallowed,
            aborting the reconcile run with a structured credential error instead of
            silently continuing without link fields.
    """
    # Decode transport-encoded S3 user-metadata values (see
    # arkeology.artifact.encode_metadata_value) so a non-ASCII title (and any other
    # metadata value) is rebuilt into vector metadata as the original Unicode text, not
    # the percent-encoded transport form. Plain ASCII values decode to themselves.
    raw_s3_meta = {key: decode_metadata_value(value) for key, value in raw_s3_meta.items()}
    title = raw_s3_meta.get("title", "")
    artifact_type = raw_s3_meta.get("type", "")
    tier_raw = raw_s3_meta.get("tier", "2")
    tier = int(tier_raw)
    tags = coerce_list_field(raw_s3_meta, "tags")
    source_artifacts_list = coerce_list_field(raw_s3_meta, "source_artifacts")
    commit_refs_list, references_list = read_current_link_fields(s3, vectors, artifact_id)

    vector_metadata: dict[str, Any] = {
        "artifact_id": artifact_id,
        "scope": settings.write_prefix,
        "type": artifact_type,
        "team": raw_s3_meta.get("team", ""),
        "project": raw_s3_meta.get("project", ""),
        "tier": tier,
        "date": raw_s3_meta.get("date", ""),
        "status": raw_s3_meta.get("status", ArtifactStatus.ACTIVE),
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
    if references_list:
        vector_metadata["references"] = references_list

    # Use the same shared pipeline write_artifact uses — min-length filtering,
    # max-sections capping, and per-section truncation — so a section that write-time
    # truncates (or drops, or caps) is truncated (or dropped, or capped) identically on
    # reconcile. Before this shared helper existed, reconcile embedded every parsed
    # section verbatim, so a section truncated at write time was resubmitted
    # full-length on every reconcile replay and failed Titan's input limit forever.
    prepared_sections = prepare_sections_for_embedding(
        content,
        title=title,
        artifact_type=artifact_type,
        tags=tags,
        settings=settings,
    )
    new_keys: set[str] = set()

    if prepared_sections:
        section_slugs = disambiguate_section_slugs(prepared_sections)
        for prepared, slug in zip(prepared_sections, section_slugs, strict=True):
            embedding = bedrock.embed(
                prepared.embed_text,
                settings.bedrock_embedding_model,
                settings.bedrock_embedding_dimensions,
            )
            vec_key = f"{artifact_id}#{slug}"
            vectors.put_vector(vec_key, embedding, vector_metadata)
            new_keys.add(vec_key)
    else:
        embed_text = build_document_embedding_text(
            title=title,
            artifact_type=artifact_type,
            tags=tags,
            description=raw_s3_meta.get("description", ""),
        )
        embedding = bedrock.embed(
            embed_text,
            settings.bedrock_embedding_model,
            settings.bedrock_embedding_dimensions,
        )
        vectors.put_vector(artifact_id, embedding, vector_metadata)
        new_keys.add(artifact_id)

    return len(new_keys)


async def _fetch_and_reindex(
    artifact_id: str,
    raw_meta: dict[str, Any],
    source: str,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> dict[str, Any]:
    """Fetch an artifact's content and re-index it into the vector store.

    Shared by Phase 1 (failure-log replay) and Phase 2 (orphan scan), both of which
    already have ``raw_meta`` fetched via ``head_object`` before calling this helper —
    it never re-fetches it. Exceptions from ``get_object`` or ``_reindex_artifact``
    (including ``CredentialError``) propagate unchanged to the caller: this helper only
    fetches and re-indexes, it never classifies a failure — Phase 1 keeps its
    ``reconcile_attempts``/``stuck_failures`` routing and Phase 2 keeps its existing
    generic ``failed`` handling, both in their own call sites.

    Args:
        artifact_id: Full S3 key of the artifact.
        raw_meta: Metadata dict already fetched by the caller via ``head_object``.
        source: Label recorded on the returned entry — ``"failure_log"`` or
            ``"orphan_scan"``.
        settings: Server configuration.
        s3: S3 client.
        vectors: Vectors client.
        bedrock: Bedrock client for embedding.

    Returns:
        The ``reconciled``-list entry: ``{"artifact_id", "title", "sections_indexed",
        "source"}``.

    Raises:
        CredentialError: Propagated unchanged from ``get_object`` or
            ``_reindex_artifact``.
    """
    # Off the event loop — both the S3 read and _reindex_artifact (which embeds via
    # bedrock.embed, including its blocking retry sleep, and writes vectors) are
    # blocking; run each via asyncio.to_thread.
    content = await asyncio.to_thread(s3.get_object, artifact_id)
    n = await asyncio.to_thread(
        _reindex_artifact,
        artifact_id,
        content,
        raw_meta,
        settings,
        s3,
        vectors,
        bedrock,
    )
    return {
        "artifact_id": artifact_id,
        "title": decode_metadata_value(raw_meta.get("title", "")),
        "sections_indexed": n,
        "source": source,
    }


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
            ``dangling_vectors_pruned``, ``dangling_artifacts``, and, only when
            non-empty, ``stuck_failures`` — failure-log entries whose
            ``reconcile_attempts`` has reached ``CAS_MAX_ATTEMPTS`` and are no longer
            auto-retried.
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
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


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
            ``dangling_vectors_pruned``, ``dangling_artifacts``, and, only when
            non-empty, ``stuck_failures`` — failure-log entries whose
            ``reconcile_attempts`` has reached ``CAS_MAX_ATTEMPTS`` and are no longer
            auto-retried.
        On error: ``{"error": "credential_error" | "internal_error", "message": str(exc)}``.
    """
    reconciled: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    failed_ids: set[str] = set()
    stuck_failures: list[dict[str, Any]] = []

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

            # Bounded retry (T62): an entry that has already failed to replay
            # CAS_MAX_ATTEMPTS times is never attempted again — it is reported once,
            # loudly, in stuck_failures instead of blending indistinguishably into
            # failed. Its counter does not grow further while stuck.
            prior_attempts = entry.get("reconcile_attempts", 0)
            if prior_attempts >= CAS_MAX_ATTEMPTS:
                stuck_failures.append(
                    {
                        "artifact_id": artifact_id,
                        "reason": entry.get("reason", ""),
                        "reconcile_attempts": prior_attempts,
                    }
                )
                failed_ids.add(artifact_id)
                continue

            try:
                # Off the event loop — blocking boto3 call.
                raw_meta = await asyncio.to_thread(s3.head_object, artifact_id)
            except CredentialError as exc:
                return credential_error_response(exc)
            except KeyError:
                failed.append({"artifact_id": artifact_id, "reason": "S3 object not found"})
                failed_ids.add(artifact_id)
                continue
            except Exception as exc:
                failed.append({"artifact_id": artifact_id, "reason": str(exc)})
                failed_ids.add(artifact_id)
                continue

            try:
                reconciled_entry = await _fetch_and_reindex(
                    artifact_id, raw_meta, "failure_log", settings, s3, vectors, bedrock
                )
                reconciled.append(reconciled_entry)
                resolved_ids.add(artifact_id)
            except CredentialError as exc:
                return credential_error_response(exc)
            except Exception as exc:
                entry["reconcile_attempts"] = prior_attempts + 1
                failed_ids.add(artifact_id)
                if entry["reconcile_attempts"] >= CAS_MAX_ATTEMPTS:
                    stuck_failures.append(
                        {
                            "artifact_id": artifact_id,
                            "reason": str(exc),
                            "reconcile_attempts": entry["reconcile_attempts"],
                        }
                    )
                else:
                    failed.append({"artifact_id": artifact_id, "reason": str(exc)})

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

    # ── Phase 2: Orphan scan ──────────────────────────────────────────────────
    own_prefix = settings.write_prefix + "/"
    try:
        # Off the event loop — blocking boto3 calls.
        all_s3_keys = await asyncio.to_thread(s3.list_objects, settings.write_prefix)
        own_keys = [
            k
            for k in all_s3_keys
            if k.startswith(own_prefix) and not k.rsplit("/", 1)[-1].startswith(_PROBE_KEY_MARKER)
        ]
        indexed_keys_raw = await asyncio.to_thread(
            vectors.list_vectors_by_metadata, {"scope": {"$eq": settings.write_prefix}}
        )
    except CredentialError as exc:
        return credential_error_response(exc)
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
            # Off the event loop — see the equivalent failure-log-replay comment above.
            raw_meta = await asyncio.to_thread(s3.head_object, orphan_key)
            reconciled_entry = await _fetch_and_reindex(
                orphan_key, raw_meta, "orphan_scan", settings, s3, vectors, bedrock
            )
            reconciled.append(reconciled_entry)
        except CredentialError as exc:
            return credential_error_response(exc)
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
            # An artifact fully written between the S3 listing and the vector
            # listing above would otherwise be misclassified dangling here and have
            # its brand-new vectors pruned. Re-confirm S3 absence immediately before
            # deleting — only prune when the object is actually gone right now.
            # Off the event loop — blocking boto3 call.
            try:
                await asyncio.to_thread(s3.head_object, dangling_id)
            except KeyError:
                pass  # confirmed absent at prune time — safe to prune
            else:
                # A concurrent write raced the initial listings; not dangling after
                # all. Leave its vectors untouched.
                continue

            # Off the event loop — blocking boto3 call.
            await asyncio.to_thread(vectors.delete_vectors, keys_to_delete)
            dangling_artifacts.append(dangling_id)
            dangling_artifacts_found += 1
            dangling_vectors_pruned += len(keys_to_delete)
        except CredentialError as exc:
            return credential_error_response(exc)
        except Exception as exc:
            failed.append({"artifact_id": dangling_id, "reason": str(exc)})

    logger.info(
        "reconcile_index complete: reconciled=%d failed=%d stuck=%d orphans=%d dangling=%d",
        len(reconciled),
        len(failed),
        len(stuck_failures),
        orphans_found,
        dangling_artifacts_found,
    )
    response: dict[str, Any] = {
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
    if stuck_failures:
        response["stuck_failures"] = stuck_failures
    return response
