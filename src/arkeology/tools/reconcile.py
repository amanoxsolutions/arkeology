"""arkeology.tools.reconcile — reconcile_index MCP tool implementation.

Replays the partial-write failure log and scans for orphaned S3 objects,
re-indexing any artifacts that are present in S3 but absent from the vector
index.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from arkeology.annotations import (
    CAS_MAX_ATTEMPTS,
    apply_link_annotations,
    merge_link_field,
    read_link_annotations,
)
from arkeology.artifact import (
    ARTIFACT_TYPES,
    cap_commit_refs_for_vectors,
    check_metadata_budgets,
)
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ArtifactStatus, ErrorCode
from arkeology.errors import CredentialError
from arkeology.failure_log import read_failure_entries, rewrite_failure_log
from arkeology.tools._errors import credential_error_response
from arkeology.tools._scope import is_own_scope
from arkeology.tools._search_helper import coerce_list_field
from arkeology.tools._section_pipeline import (
    build_document_embedding_text,
    disambiguate_section_slugs,
    prepare_sections_for_embedding,
)

logger = logging.getLogger(__name__)

# Bounded concurrency for each phase's per-artifact loop, mirroring write_artifacts.py's
# asyncio.Semaphore-gated asyncio.gather pattern. Each phase's per-artifact work is
# independent (re-indexing/pruning one artifact never depends on another's outcome).
_RECONCILE_CONCURRENCY = 5

# Reserved marker for throwaway connectivity-probe objects written into a deployment's own
# WRITE_PREFIX (the health-check probe in ``tools/health.py``, the startup probe in
# ``startup.py``, the setting-up-arkeology skill's annotation probe). Any key whose final
# path segment begins with this marker is a probe, never an artifact: no generated artifact
# id can collide with it, because every id starts with a type slug drawn from
# ``ARTIFACT_TYPES``, none of which begins with an underscore. Matching the marker rather
# than individual probe names means a future probe needs no change here.
_PROBE_KEY_MARKER = "_arkeology_"


def _entry_kind(entry: dict[str, Any]) -> str:
    """Classify a failure-log entry as ``"orphan_cleanup"`` or ``"reindex"`` (T67).

    A pure, no-persisted-field function of the entry's own shape: the presence of
    ``orphan_keys`` is both "this entry carries what the cheap repair needs" and "this
    is the cheap-repair kind" — the same guard serves both purposes, so nothing can
    drift out of sync the way an independent label field could. Used as (part of) the
    dedup/resolution key for Phase 1's failure-log replay, so a reindex-kind entry and
    an orphan-cleanup-kind entry for the same ``artifact_id`` are always processed and
    pruned independently.
    """
    return "orphan_cleanup" if "orphan_keys" in entry else "reindex"


def _restore_entry_link_fields(
    entry: dict[str, Any],
    artifact_id: str,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
) -> None:
    """Re-apply the link-field copy a failed annotation write recorded on ``entry``.

    The producers of that entry (the write path's overwrite cycle and the archive
    path's status flip) both re-PUT the object, which clears its annotations, and both
    record the values they were about to re-apply when the re-apply itself failed. The
    entry is then the only surviving source for them: ``references`` is not in vector
    metadata at all, and the vector ``commit_refs`` copy holds at most the most-recent
    :data:`~arkeology.artifact.COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES` entries, so
    everything past that window exists nowhere else.

    The restored value is the union of the entry's copy and whatever the artifact
    currently holds, never a replacement — a value re-added between the failure and
    this reconcile lives only in the current copy, and dropping it would trade one
    silent loss for another.

    An entry written before these fields existed carries neither, which means "nothing
    to restore" and not "clear the link fields": such an entry is a no-op here, leaving
    the object's annotations exactly as they are. Non-list values from a hand-edited log
    are ignored on the same terms.

    Args:
        entry: The failure-log entry being replayed.
        artifact_id: Full S3 key of the artifact.
        s3: S3 client.
        vectors: Vectors client, for the vector-metadata half of the current value.

    Raises:
        CredentialError: Propagated from either store.
    """
    entry_commit_refs = entry.get("commit_refs")
    entry_references = entry.get("references")
    recorded_commit_refs = (
        [str(ref) for ref in entry_commit_refs] if isinstance(entry_commit_refs, list) else []
    )
    recorded_references = (
        [str(ref) for ref in entry_references] if isinstance(entry_references, list) else []
    )
    if not (recorded_commit_refs or recorded_references):
        return

    current_commit_refs, current_references = read_link_annotations(s3, artifact_id)
    # ponytail: read-merge-write without compare-and-swap. A link_metadata call landing
    # between the read above and the write below is clobbered. The window is the two
    # calls' latency, against a repair path that only runs on an artifact already known
    # to be broken; add if_match plus ArtifactConflictError retry (as the write and
    # archive paths do) if that loss is ever observed.
    apply_link_annotations(
        s3,
        artifact_id,
        commit_refs=merge_link_field(recorded_commit_refs, current_commit_refs),
        references=merge_link_field(recorded_references, current_references),
    )


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
        vectors: Vectors client, used to upsert the rebuilt section vectors.
        bedrock: Bedrock client for embedding.

    Returns:
        Number of vectors written (one per section, or 1 for the fallback).

    Raises:
        CredentialError: If reading the durable link fields fails due to expired or
            invalid credentials — propagated to the caller rather than swallowed,
            aborting the reconcile run with a structured credential error instead of
            silently continuing without link fields.
        Exception: Any other failure reading the durable link annotations propagates
            too, failing this artifact rather than rebuilding its vector metadata from a
            spurious empty — which would write that emptiness over its real link fields.
            The caller converts it into a structured ``failed`` entry, so the run itself
            still completes.
        MetadataTooLargeError: If the rebuilt vector_metadata breaches any of the
            three metadata size budgets (T57) — propagated to the caller, which
            reports it as a structured `failed` entry (or, once an entry's
            reconcile_attempts crosses CAS_MAX_ATTEMPTS, `stuck_failures` — see T62)
            rather than crashing.
    """
    title = raw_s3_meta.get("title", "")
    artifact_type = raw_s3_meta.get("type", "")
    tier_raw = raw_s3_meta.get("tier", "2")
    tier = int(tier_raw)
    tags = coerce_list_field(raw_s3_meta, "tags")
    source_artifacts_list = coerce_list_field(raw_s3_meta, "source_artifacts")
    # references (second element) is read for backward-read compatibility only — T58
    # removes it from the rebuilt vector metadata below; it is never referenced again in
    # this function. Mirrors write.py's `_existing_references` naming for the same
    # deliberately-unused-tuple-element pattern.
    commit_refs_list, _references_list = read_link_annotations(s3, artifact_id)

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
    #
    # commit_refs is capped to the most-recently-appended
    # COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES entries for this vector-metadata copy only
    # (T58) — the annotation-backed commit_refs_list read above is already the complete,
    # uncapped value. The capped copy is a derived filter index, so the cap is a property
    # of the index rather than a limit on what is stored.
    #
    # references is never written to vector metadata (T58) — the annotation is its sole
    # durable store.
    if tags:
        vector_metadata["tags"] = tags
    if source_artifacts_list:
        vector_metadata["source_artifacts"] = source_artifacts_list
    if commit_refs_list:
        vector_metadata["commit_refs"] = cap_commit_refs_for_vectors(commit_refs_list)

    # T57: reject a rebuilt vector_metadata that would breach a metadata size budget
    # BEFORE any embed/put_vector call — otherwise an artifact stuck by an oversize
    # commit_refs/references payload (see the T57 spec's Problem Statement) would
    # never be self-healed by reconcile: it would re-derive the identical oversize
    # payload and fail identically on every replay. s3_metadata={} — this function
    # writes no S3 user-defined object metadata, so there is nothing to measure there.
    # Propagates MetadataTooLargeError to the caller unchanged; both call sites
    # (failure-log replay and orphan scan) already convert any exception raised here
    # into a structured `failed` entry via their generic except Exception handling.
    check_metadata_budgets(s3_metadata={}, vector_metadata=vector_metadata)

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
        "title": raw_meta.get("title", ""),
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
            auto-retried — and ``skipped_non_artifacts`` — own-scope keys the orphan
            scan found without vectors but declined to index, because their S3 object
            metadata carries no ``type`` in ``ARTIFACT_TYPES``. A skipped key still counts
            excluded from ``orphans_found``, which counts artifact orphans needing re-index —
        not every candidate key the scan examined. Probe keys are filtered out before the
        count for the same reason: a key that is not an artifact is not an orphan, and a
        permanent stray must not hold the count at a non-zero floor on every run.

            Every ``reconciled`` entry carries a ``source`` discriminator naming the
            mechanism that dealt with it: ``"failure_log"`` (replayed and re-indexed),
            ``"orphan_scan"`` (an S3 key found with no vectors and re-indexed),
            ``"orphan_vector_cleanup"`` (leftover orphan vector keys deleted, nothing
            re-indexed), or ``"failure_log_obsolete"`` (entry dropped because its
            artifact no longer exists, nothing re-indexed). ``reconciled`` therefore
            means "dealt with", not "re-indexed" — two of the four sources index
            nothing and carry no ``sections_indexed``, so a caller counting re-index
            work must filter on ``source`` rather than on the list's length.
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
            auto-retried — and ``skipped_non_artifacts`` — own-scope keys the orphan
            scan found without vectors but declined to index, because their S3 object
            metadata carries no ``type`` in ``ARTIFACT_TYPES``. A skipped key still counts
            excluded from ``orphans_found``, which counts artifact orphans needing re-index —
        not every candidate key the scan examined. Probe keys are filtered out before the
        count for the same reason: a key that is not an artifact is not an orphan, and a
        permanent stray must not hold the count at a non-zero floor on every run.
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
        entries: list[dict[str, Any]] = read_failure_entries(log_path)
        failure_log_entries_before = len(entries)

        # Deduplicate by (artifact_id, kind) — attempt re-processing once per unique
        # (id, kind) pair (T67). A bare artifact_id key would incorrectly collapse a
        # reindex-kind entry and an orphan-cleanup-kind entry for the same artifact_id
        # into one attempt, and later prune BOTH when either resolves — see
        # docs/specs/p13-t67-orphan-vector-retry-and-selfheal.md Problem Statement
        # point 5. Before T67, at most one entry per artifact_id existed, so this is
        # backward-compatible: the composite key is unique either way.
        seen_keys: set[tuple[str, str]] = set()
        unique_entries: list[dict[str, Any]] = []
        for entry in entries:
            aid = entry.get("artifact_id", "")
            key = (aid, _entry_kind(entry))
            if aid and key not in seen_keys:
                seen_keys.add(key)
                unique_entries.append(entry)

        resolved_keys: set[tuple[str, str]] = set()
        # New attempt counts to stamp onto retained entries, keyed the same way as
        # resolved_keys. Carried by key rather than mutated in place because the
        # end-of-run rewrite re-reads the log and works on fresh entry dicts.
        attempt_updates: dict[tuple[str, str], int] = {}

        # Bounded concurrency: each entry's head_object + re-index is independent
        # of every other's, mirroring write_artifacts.py's asyncio.Semaphore-gated
        # asyncio.gather pattern. Each task never raises — it returns an outcome
        # marker — so a credential failure on one entry never leaves
        # concurrently-dispatched sibling tasks in an unobserved state.
        #
        # Accepted trade-off (reviewed, not a defect), applies to all three phases'
        # asyncio.gather loops in this module: the old sequential loop aborted at a
        # deterministic prefix on the first CredentialError; concurrent loops may
        # let up to _RECONCILE_CONCURRENCY already-in-flight items finish before the
        # abort is noticed. Low-risk: credential_error_response() never reported
        # which items had already succeeded in either version (see the "discards
        # the whole reconcile_index run" comments below), and every completed item
        # is individually correct, so a retry after fixing credentials reprocesses
        # the full input idempotently regardless of completion order.
        semaphore = asyncio.Semaphore(_RECONCILE_CONCURRENCY)

        async def _process_failure_log_entry(entry: dict[str, Any]) -> dict[str, Any]:
            artifact_id = entry.get("artifact_id", "")
            if not artifact_id:
                return {"kind": "invalid"}
            if not is_own_scope(artifact_id, settings.write_prefix):
                logger.warning("Skipping out-of-scope failure log entry: %s", artifact_id)
                return {"kind": "invalid"}

            # T67: an orphan-cleanup-kind entry (Step 8's delete_vectors retry
            # exhausted) carries the exact orphan vector keys still needing deletion —
            # its repair is a direct delete_vectors call, never a re-index.
            orphan_keys: list[str] | None = (
                entry.get("orphan_keys") if _entry_kind(entry) == "orphan_cleanup" else None
            )

            # Bounded retry (T62, extended by T67 to the orphan-cleanup kind too): an
            # entry that has already failed to replay CAS_MAX_ATTEMPTS times is never
            # attempted again — it is reported once, loudly, in stuck_failures instead
            # of blending indistinguishably into failed. Its counter does not grow
            # further while stuck.
            prior_attempts = entry.get("reconcile_attempts", 0)
            if prior_attempts >= CAS_MAX_ATTEMPTS:
                result: dict[str, Any] = {
                    "kind": "stuck_already",
                    "artifact_id": artifact_id,
                    "reason": entry.get("reason", ""),
                    "reconcile_attempts": prior_attempts,
                }
                if orphan_keys is not None:
                    result["orphan_keys"] = orphan_keys
                return result

            async with semaphore:
                if orphan_keys is not None:
                    # T67: repair directly — no head_object, no get_object, no
                    # bedrock.embed, no _fetch_and_reindex/_reindex_artifact. Idempotent
                    # by the documented DeleteVectors API contract and moto's mock: a
                    # key already absent from the index is not an error (see the spec's
                    # Problem Statement point 4) — no pre-check needed.
                    try:
                        # Off the event loop — blocking boto3 call.
                        await asyncio.to_thread(vectors.delete_vectors, orphan_keys)
                    except CredentialError as exc:
                        return {"kind": "credential_error", "exc": exc}
                    except Exception as exc:
                        new_attempts = prior_attempts + 1
                        if new_attempts >= CAS_MAX_ATTEMPTS:
                            return {
                                "kind": "stuck_new",
                                "artifact_id": artifact_id,
                                "reason": str(exc),
                                "reconcile_attempts": new_attempts,
                                "orphan_keys": orphan_keys,
                            }
                        return {
                            "kind": "failed_new",
                            "artifact_id": artifact_id,
                            "reason": str(exc),
                            "reconcile_attempts": new_attempts,
                            "orphan_keys": orphan_keys,
                        }
                    else:
                        return {
                            "kind": "resolved",
                            "artifact_id": artifact_id,
                            "entry": {
                                "artifact_id": artifact_id,
                                "title": entry.get("title", ""),
                                "orphan_keys_deleted": len(orphan_keys),
                                "source": "orphan_vector_cleanup",
                            },
                        }

                try:
                    # Off the event loop — blocking boto3 call.
                    raw_meta = await asyncio.to_thread(s3.head_object, artifact_id)
                except CredentialError as exc:
                    return {"kind": "credential_error", "exc": exc}
                except KeyError:
                    # The artifact has been deleted since the entry was logged, so there
                    # is nothing left to reconcile — resolve the entry (pruning it from
                    # the log) rather than failing it. Classifying it `failed` would
                    # replay and re-report it on every run forever: `failed` entries are
                    # retained by the end-of-run rewrite and never increment
                    # reconcile_attempts, so they can never reach stuck_failures either.
                    # Deliberately not counter-bearing: stuck_failures asks an operator to
                    # fix an underlying cause, and a deleted artifact presents none. Only
                    # a genuine 404 reaches here — head_object raises CredentialError for
                    # a permission failure and re-raises every other error, both of which
                    # keep their existing paths. Any vectors the artifact left behind are
                    # pruned by Phase 3, and if the object reappears the orphan scan
                    # re-indexes it.
                    return {
                        "kind": "resolved",
                        "artifact_id": artifact_id,
                        "entry": {
                            "artifact_id": artifact_id,
                            # raw_meta is unavailable — the object is gone — so the title
                            # comes from the failure-log entry, as the orphan-cleanup
                            # producer above does. No sections_indexed: nothing was indexed.
                            "title": entry.get("title", ""),
                            "source": "failure_log_obsolete",
                        },
                    }
                except Exception as exc:
                    return {"kind": "failed", "artifact_id": artifact_id, "reason": str(exc)}

                try:
                    # Before the re-index, not after: the annotation copy is what the
                    # rebuilt vector metadata is derived from, so restoring it first is
                    # what puts the recorded commit_refs back into the index too.
                    # Off the event loop — blocking boto3 calls.
                    await asyncio.to_thread(
                        _restore_entry_link_fields, entry, artifact_id, s3, vectors
                    )
                    reconciled_entry = await _fetch_and_reindex(
                        artifact_id, raw_meta, "failure_log", settings, s3, vectors, bedrock
                    )
                    return {
                        "kind": "resolved",
                        "artifact_id": artifact_id,
                        "entry": reconciled_entry,
                    }
                except CredentialError as exc:
                    return {"kind": "credential_error", "exc": exc}
                except Exception as exc:
                    new_attempts = prior_attempts + 1
                    if new_attempts >= CAS_MAX_ATTEMPTS:
                        return {
                            "kind": "stuck_new",
                            "artifact_id": artifact_id,
                            "reason": str(exc),
                            "reconcile_attempts": new_attempts,
                        }
                    return {
                        "kind": "failed_new",
                        "artifact_id": artifact_id,
                        "reason": str(exc),
                        "reconcile_attempts": new_attempts,
                    }

        entry_results = await asyncio.gather(
            *[_process_failure_log_entry(entry) for entry in unique_entries]
        )

        # A credential failure discards the whole reconcile_index run (matching the
        # original sequential loop's immediate `return credential_error_response(exc)`,
        # which never reported partial progress from any phase either).
        for r in entry_results:
            if r["kind"] == "credential_error":
                return credential_error_response(r["exc"])

        for entry, r in zip(unique_entries, entry_results, strict=True):
            kind = r["kind"]
            if kind == "invalid":
                continue
            if kind == "resolved":
                reconciled.append(r["entry"])
                resolved_keys.add((r["artifact_id"], _entry_kind(entry)))
            elif kind == "failed":
                failed_entry: dict[str, Any] = {
                    "artifact_id": r["artifact_id"],
                    "reason": r["reason"],
                }
                if "orphan_keys" in r:
                    failed_entry["orphan_keys"] = r["orphan_keys"]
                failed.append(failed_entry)
                failed_ids.add(r["artifact_id"])
            elif kind == "stuck_already":
                stuck_entry: dict[str, Any] = {
                    "artifact_id": r["artifact_id"],
                    "reason": r["reason"],
                    "reconcile_attempts": r["reconcile_attempts"],
                }
                if "orphan_keys" in r:
                    stuck_entry["orphan_keys"] = r["orphan_keys"]
                stuck_failures.append(stuck_entry)
                failed_ids.add(r["artifact_id"])
            elif kind == "stuck_new":
                attempt_updates[(r["artifact_id"], _entry_kind(entry))] = r["reconcile_attempts"]
                stuck_entry = {
                    "artifact_id": r["artifact_id"],
                    "reason": r["reason"],
                    "reconcile_attempts": r["reconcile_attempts"],
                }
                if "orphan_keys" in r:
                    stuck_entry["orphan_keys"] = r["orphan_keys"]
                stuck_failures.append(stuck_entry)
                failed_ids.add(r["artifact_id"])
            elif kind == "failed_new":
                attempt_updates[(r["artifact_id"], _entry_kind(entry))] = r["reconcile_attempts"]
                failed_entry = {"artifact_id": r["artifact_id"], "reason": r["reason"]}
                if "orphan_keys" in r:
                    failed_entry["orphan_keys"] = r["orphan_keys"]
                failed.append(failed_entry)
                failed_ids.add(r["artifact_id"])

        def _prune(current: list[dict[str, Any]]) -> list[dict[str, Any]]:
            """Retain every entry whose (artifact_id, kind) was NOT resolved.

            T67: a co-existing reindex entry and orphan-cleanup entry for the same
            artifact_id are pruned independently, never as a side effect of the
            other's resolution. ``current`` is re-read under the log's lock, so an
            entry another writer appended during the replay above is present here and
            is retained — the run must not overwrite what it never processed.
            """
            kept: list[dict[str, Any]] = []
            for candidate in current:
                key = (candidate.get("artifact_id", ""), _entry_kind(candidate))
                if key in resolved_keys:
                    continue
                if key in attempt_updates:
                    candidate["reconcile_attempts"] = attempt_updates[key]
                kept.append(candidate)
            return kept

        failure_log_entries_after = len(rewrite_failure_log(log_path, _prune))

    # ── Phase 2: Orphan scan ──────────────────────────────────────────────────
    try:
        # Off the event loop — blocking boto3 calls.
        all_s3_keys = await asyncio.to_thread(s3.list_objects, settings.write_prefix)
        own_keys = [
            k
            for k in all_s3_keys
            if is_own_scope(k, settings.write_prefix)
            and not k.rsplit("/", 1)[-1].startswith(_PROBE_KEY_MARKER)
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

    # Bounded concurrency: each orphan's head_object + re-index is independent
    # of every other's. Each task never raises — it returns an outcome marker.
    # See the Phase 1 semaphore comment above for the accepted non-deterministic-
    # abort-prefix trade-off, which applies here too.
    orphan_semaphore = asyncio.Semaphore(_RECONCILE_CONCURRENCY)

    async def _process_orphan(orphan_key: str) -> dict[str, Any]:
        async with orphan_semaphore:
            try:
                # Off the event loop — see the equivalent failure-log-replay comment above.
                raw_meta = await asyncio.to_thread(s3.head_object, orphan_key)
                # Anything a tool other than Arkeology left under the write prefix — a
                # manual upload, a .DS_Store, a partial multipart artefact — is not an
                # artifact and must not be embedded and indexed as one. Discriminate on
                # the object's own metadata rather than on its key shape: a generated
                # artifact id starts with a type slug, but title slugs and the
                # configurable file extension make a key-shape match brittle, and a stray
                # file can begin with a type slug by coincidence. The head_object above
                # already has the metadata in hand, so this costs nothing and happens
                # before any embed or index work.
                if raw_meta.get("type") not in ARTIFACT_TYPES:
                    return {"kind": "skipped", "artifact_id": orphan_key}
                reconciled_entry = await _fetch_and_reindex(
                    orphan_key, raw_meta, "orphan_scan", settings, s3, vectors, bedrock
                )
                return {"kind": "resolved", "artifact_id": orphan_key, "entry": reconciled_entry}
            except CredentialError as exc:
                return {"kind": "credential_error", "exc": exc}
            except Exception as exc:
                return {"kind": "failed", "artifact_id": orphan_key, "reason": str(exc)}

    orphan_results = await asyncio.gather(*[_process_orphan(k) for k in orphans])

    # A credential failure discards the whole reconcile_index run, matching the
    # original sequential loop's immediate `return credential_error_response(exc)`.
    for r in orphan_results:
        if r["kind"] == "credential_error":
            return credential_error_response(r["exc"])
    skipped_non_artifacts: list[str] = []
    for r in orphan_results:
        if r["kind"] == "resolved":
            reconciled.append(r["entry"])
        elif r["kind"] == "skipped":
            skipped_non_artifacts.append(r["artifact_id"])
        else:
            failed.append({"artifact_id": r["artifact_id"], "reason": r["reason"]})

    # ── Phase 3: Dangling vector pruning ─────────────────────────────────────
    # Dangling vectors are index entries whose S3 object no longer exists.
    # own_keys is already filtered to own-scope; indexed_artifact_ids is also
    # own-scope (enforced by the list_vectors_by_metadata scope filter above).
    own_keys_set: set[str] = set(own_keys)
    dangling_artifact_ids = set(vectors_by_artifact.keys()) - own_keys_set

    dangling_artifacts: list[str] = []
    dangling_artifacts_found = 0
    dangling_vectors_pruned = 0

    # Bounded concurrency: each dangling artifact's race-recheck + prune is
    # independent of every other's. Each task never raises — it returns an outcome
    # marker. See the Phase 1 semaphore comment above for the accepted
    # non-deterministic-abort-prefix trade-off, which applies here too.
    dangling_semaphore = asyncio.Semaphore(_RECONCILE_CONCURRENCY)

    async def _process_dangling(dangling_id: str) -> dict[str, Any]:
        keys_to_delete = vectors_by_artifact[dangling_id]
        async with dangling_semaphore:
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
                    # A concurrent write raced the initial listings; not dangling
                    # after all. Leave its vectors untouched.
                    return {"kind": "race_not_dangling"}

                # Off the event loop — blocking boto3 call.
                await asyncio.to_thread(vectors.delete_vectors, keys_to_delete)
                return {
                    "kind": "pruned",
                    "artifact_id": dangling_id,
                    "count": len(keys_to_delete),
                }
            except CredentialError as exc:
                return {"kind": "credential_error", "exc": exc}
            except Exception as exc:
                return {"kind": "failed", "artifact_id": dangling_id, "reason": str(exc)}

    dangling_results = await asyncio.gather(*[_process_dangling(d) for d in dangling_artifact_ids])

    # A credential failure discards the whole reconcile_index run, matching the
    # original sequential loop's immediate `return credential_error_response(exc)`.
    for r in dangling_results:
        if r["kind"] == "credential_error":
            return credential_error_response(r["exc"])
    for r in dangling_results:
        if r["kind"] == "pruned":
            dangling_artifacts.append(r["artifact_id"])
            dangling_artifacts_found += 1
            dangling_vectors_pruned += r["count"]
        elif r["kind"] == "failed":
            failed.append({"artifact_id": r["artifact_id"], "reason": r["reason"]})

    logger.info(
        "reconcile_index complete: reconciled=%d failed=%d stuck=%d orphans=%d "
        "skipped_non_artifacts=%d dangling=%d",
        len(reconciled),
        len(failed),
        len(stuck_failures),
        orphans_found,
        len(skipped_non_artifacts),
        dangling_artifacts_found,
    )
    response: dict[str, Any] = {
        "reconciled": reconciled,
        "failed": failed,
        "failure_log_entries_before": failure_log_entries_before,
        "failure_log_entries_after": failure_log_entries_after,
        "orphans_found": orphans_found - len(skipped_non_artifacts),
        "total_reconciled": len(reconciled),
        "dangling_artifacts_found": dangling_artifacts_found,
        "dangling_vectors_pruned": dangling_vectors_pruned,
        "dangling_artifacts": dangling_artifacts,
    }
    if stuck_failures:
        response["stuck_failures"] = stuck_failures
    if skipped_non_artifacts:
        response["skipped_non_artifacts"] = skipped_non_artifacts
    return response
