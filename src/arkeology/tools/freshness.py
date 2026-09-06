"""arkeology.tools.freshness — check_synthesis_freshness MCP tool implementation.

Audits synthesis artifacts for staleness (sources updated after synthesis),
archived sources, missing sources, and structurally malformed syntheses
(empty source_artifacts). Optionally hard-deletes malformed syntheses when
called with confirm=True.
"""

import asyncio
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
from arkeology.tools._scope import is_cross_scope_readable, is_own_scope
from arkeology.tools._search_helper import (
    fetch_vectors_by_artifact_ids,
    fetch_vectors_by_metadata,
)

logger = logging.getLogger(__name__)

# Bounded concurrency for the malformed-synthesis deletion loop (Step 8), mirroring
# write_artifacts.py's asyncio.Semaphore-gated asyncio.gather pattern.
_DELETE_CONCURRENCY = 5


async def check_synthesis_freshness(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Audit synthesis freshness and optionally delete malformed syntheses.

    Args:
        settings: Server configuration.
        s3: S3 client (used only during malformed-synthesis deletion).
        vectors: S3 Vectors client for all metadata lookups.
        bedrock: Unused — accepted for interface consistency.
        confirm: If ``True``, hard-delete malformed syntheses (vectors first,
            then S3 object). Default ``False``.

    Returns:
        On success: dict with keys ``stale``, ``archived_sources``,
            ``missing_sources``, ``malformed``, ``deleted_malformed``,
            ``total_checked``, ``all_fresh``.
        On error: ``{"error": "internal_error", "message": str(exc)}``.
    """
    try:
        return await _check_synthesis_freshness_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            confirm=confirm,
        )
    except Exception as exc:
        logger.exception("Unexpected error in check_synthesis_freshness")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _check_synthesis_freshness_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None,
    confirm: bool,
) -> dict[str, Any]:
    """Inner implementation of check_synthesis_freshness."""
    _ = bedrock  # unused — accepted for interface consistency

    # ── Step 1: List all active synthesis vectors in own scope ────────────────
    synth_filter: dict[str, Any] = {
        "$and": [
            {"type": {"$eq": "synthesis"}},
            {"status": {"$eq": ArtifactStatus.ACTIVE}},
            {"scope": {"$eq": settings.write_prefix}},
        ]
    }
    try:
        # ── Steps 1-2: list, then fetch vector metadata for all synthesis keys
        # (off the event loop) ─────────────────────────────────────────────────
        synth_items = await asyncio.to_thread(
            fetch_vectors_by_metadata, vectors, synth_filter, include_data=False
        )
    except CredentialError as exc:
        return credential_error_response(exc)

    if not synth_items:
        return {
            "stale": [],
            "archived_sources": [],
            "missing_sources": [],
            "malformed": [],
            "deleted_malformed": [],
            "delete_failed": [],
            "total_checked": 0,
            "all_fresh": True,
        }

    # ── Step 3: Deduplicate by artifact_id (first occurrence wins) ────────────
    syntheses: dict[str, dict[str, Any]] = {}
    for item in synth_items:
        aid = item["metadata"]["artifact_id"]
        if aid not in syntheses:
            syntheses[aid] = item["metadata"]

    # ── Step 4: Separate malformed from valid ────────────────────────────────
    malformed_ids: list[str] = []
    valid_syntheses: dict[str, dict[str, Any]] = {}
    for aid, meta in syntheses.items():
        source_arts = meta.get("source_artifacts")
        if not source_arts:
            malformed_ids.append(aid)
        else:
            valid_syntheses[aid] = meta

    # ── Step 5: Collect all unique source IDs across all valid syntheses ──────
    all_source_ids: set[str] = set()
    for meta in valid_syntheses.values():
        for src_id in meta.get("source_artifacts", []):
            all_source_ids.add(src_id)

    # ── Step 6: Fetch source metadata — one batched lookup for all unique sources ──
    # Batched $in queries rather than one list_vectors_by_metadata call per unique
    # source_id (which would be 1+N queries), mirroring the pattern already established
    # in _reference_filter.py::resolve_readable_targets. The number of syntheses, and so
    # the size of the id list, is unbounded, so the batching is chunked to the
    # filter-expression byte budget — see ``fetch_vectors_by_artifact_ids``.
    # Cross-scope gate: identical to list.py's Step 5 — own-scope sources are
    # always readable; a foreign-scope source is only readable when it is tier 3 AND
    # visibility="shared". A gated-out source is treated exactly as an unresolved
    # source (None) so it surfaces as missing and its date/status are never read or
    # reported — this must never leak whether a foreign artifact exists.
    own_scope = settings.write_prefix
    read_prefixes = settings.read_prefixes_list
    source_meta: dict[str, dict[str, Any] | None] = dict.fromkeys(all_source_ids)

    if all_source_ids:
        try:
            # Off the event loop — blocking boto3 calls.
            src_items = await asyncio.to_thread(
                fetch_vectors_by_artifact_ids, vectors, all_source_ids
            )
        except CredentialError as exc:
            return credential_error_response(exc)

        # No vector index entries for a given source → it stays missing (T22),
        # already defaulted to None above. Multi-section sources may yield
        # several keys per source_id — first occurrence wins.
        seen_source_ids: set[str] = set()
        for item in src_items:
            meta = item["metadata"]
            source_id = str(meta.get("artifact_id", ""))
            if source_id not in all_source_ids or source_id in seen_source_ids:
                continue
            seen_source_ids.add(source_id)

            if is_cross_scope_readable(meta, source_id, own_scope, read_prefixes):
                source_meta[source_id] = meta

    # ── Step 7: Build stale, archived_sources, missing_sources per synthesis ──
    stale: list[dict[str, Any]] = []
    archived_sources_report: list[dict[str, Any]] = []
    missing_sources_report: list[dict[str, Any]] = []

    # A source is stale when it was *written* after the synthesis was built, which is
    # what last_edited_ulid records: it is monotonic, it is bumped by every content
    # write, and it is left untouched by the operations that must not mark a synthesis
    # stale (a link-field backfill, an archive status flip, a reconcile re-index).
    # ``date`` is the artifact's subject date, not its write time, so comparing it both
    # misses a tier-3 source overwritten in place under an unchanged date and flags a
    # later-dated source that was written before the synthesis and is already in it.
    # Dates remain the fallback for either side missing a ULID — artifacts written
    # before it was recorded compare no worse than they did.
    for aid, meta in valid_syntheses.items():
        synthesis_date: str = meta.get("date", "")
        synthesis_ulid: str = str(meta.get("last_edited_ulid") or "")
        source_ids: list[str] = meta.get("source_artifacts", [])

        stale_srcs: list[str] = []
        archived_srcs: list[str] = []
        missing_srcs: list[str] = []

        for src_id in source_ids:
            src_m = source_meta.get(src_id)
            if src_m is None:
                missing_srcs.append(src_id)
            else:
                src_date: str = src_m.get("date", "")
                src_ulid: str = str(src_m.get("last_edited_ulid") or "")
                if (
                    src_ulid > synthesis_ulid
                    if src_ulid and synthesis_ulid
                    else src_date > synthesis_date
                ):
                    stale_srcs.append(src_id)
                if src_m.get("status") == ArtifactStatus.INACTIVE:
                    archived_srcs.append(src_id)

        if stale_srcs:
            stale.append(
                {
                    "artifact_id": aid,
                    "stale_sources": stale_srcs,
                }
            )
        if archived_srcs:
            archived_sources_report.append(
                {
                    "artifact_id": aid,
                    "archived_sources": archived_srcs,
                }
            )
        if missing_srcs:
            missing_sources_report.append(
                {
                    "artifact_id": aid,
                    "missing_sources": missing_srcs,
                }
            )

    # ── Step 8: Handle malformed — delete if confirm=True ────────────────────
    deleted: list[str] = []
    delete_failed: list[str] = []  # non-credential delete failures; always in response
    malformed_reported: list[str] = []

    if confirm:
        # Bounded concurrency: each malformed synthesis's vectors-first-then-S3
        # deletion is independent of every other's, mirroring write_artifacts.py's
        # asyncio.Semaphore-gated asyncio.gather pattern. Each task never raises — it
        # returns an outcome marker — so a credential failure on one task never leaves
        # concurrently-dispatched sibling tasks in an unobserved state.
        #
        # Accepted trade-off (reviewed, not a defect): the old sequential loop
        # aborted at a deterministic prefix on the first CredentialError; this one
        # may let up to _DELETE_CONCURRENCY in-flight deletions finish before the
        # abort is noticed. Low-risk: credential_error_response() never surfaced
        # which items succeeded in either version, and every completed deletion is
        # individually correct, so a retry after fixing credentials reprocesses
        # the same input to the same end state regardless of ordering.
        semaphore = asyncio.Semaphore(_DELETE_CONCURRENCY)

        async def _delete_one_malformed(aid: str) -> dict[str, Any]:
            if not is_own_scope(aid, settings.write_prefix):
                logger.warning("Skipping out-of-scope malformed synthesis: %s", aid)
                return {"artifact_id": aid, "outcome": "skipped"}
            async with semaphore:
                # Vectors-first, then S3 (same ordering as delete_artifact).
                # Non-credential errors at any step → report in delete_failed
                # (T22 Boundary: a partial delete leaves a recoverable S3 orphan).
                try:
                    # Off the event loop — blocking boto3 call.
                    vec_keys = await asyncio.to_thread(
                        vectors.list_vectors_by_metadata, {"artifact_id": {"$eq": aid}}
                    )
                except CredentialError as exc:
                    return {"artifact_id": aid, "outcome": "credential_error", "exc": exc}
                except Exception:
                    logger.warning(
                        "Failed to list vectors for malformed synthesis %s; "
                        "skipping deletion — recorded in delete_failed",
                        aid,
                        exc_info=True,
                    )
                    return {"artifact_id": aid, "outcome": "delete_failed"}

                if vec_keys:
                    try:
                        # Off the event loop — blocking boto3 call.
                        await asyncio.to_thread(vectors.delete_vectors, vec_keys)
                    except CredentialError as exc:
                        return {"artifact_id": aid, "outcome": "credential_error", "exc": exc}
                    except Exception:
                        logger.warning(
                            "Failed to delete vectors for malformed synthesis %s; "
                            "skipping deletion — recorded in delete_failed",
                            aid,
                            exc_info=True,
                        )
                        return {"artifact_id": aid, "outcome": "delete_failed"}

                try:
                    # Off the event loop — blocking boto3 call.
                    await asyncio.to_thread(s3.head_object, aid)
                except KeyError:
                    logger.warning(
                        "Malformed synthesis S3 object not found, skipping S3 delete: %s", aid
                    )
                    # vectors were already deleted above — artifact is fully gone
                    return {"artifact_id": aid, "outcome": "deleted"}
                except CredentialError as exc:
                    return {"artifact_id": aid, "outcome": "credential_error", "exc": exc}

                try:
                    # Off the event loop — blocking boto3 call.
                    await asyncio.to_thread(s3.delete_object, aid)
                except CredentialError as exc:
                    return {"artifact_id": aid, "outcome": "credential_error", "exc": exc}
                except Exception:
                    logger.warning(
                        "Failed to delete S3 object for malformed synthesis %s; "
                        "vectors already deleted — S3 orphan left; recorded in delete_failed",
                        aid,
                        exc_info=True,
                    )
                    return {"artifact_id": aid, "outcome": "delete_failed"}

                return {"artifact_id": aid, "outcome": "deleted"}

        delete_results = await asyncio.gather(
            *[_delete_one_malformed(aid) for aid in malformed_ids]
        )
        # A credential failure discards the whole audit (matching the original
        # sequential loop's immediate `return credential_error_response(exc)`, which
        # never reported partial deletion/audit progress either).
        for r in delete_results:
            if r["outcome"] == "credential_error":
                return credential_error_response(r["exc"])
        for r in delete_results:
            if r["outcome"] == "deleted":
                deleted.append(r["artifact_id"])
            elif r["outcome"] == "delete_failed":
                delete_failed.append(r["artifact_id"])
        malformed_reported = []
    else:
        malformed_reported = list(malformed_ids)
        deleted = []

    # ── Step 9: Build response ────────────────────────────────────────────────
    # all_fresh=True means no issues remain; it does NOT mean nothing was deleted.
    # A run with confirm=True that deletes all malformed syntheses yields all_fresh=True
    # if no stale/archived/missing issues remain after deletion.
    all_fresh = not (
        stale
        or archived_sources_report
        or missing_sources_report
        or malformed_reported
        or delete_failed
    )

    logger.info(
        "check_synthesis_freshness complete: checked=%d stale=%d archived=%d "
        "missing=%d malformed=%d deleted=%d",
        len(syntheses),
        len(stale),
        len(archived_sources_report),
        len(missing_sources_report),
        len(malformed_reported),
        len(deleted),
    )
    return {
        "stale": stale,
        "archived_sources": archived_sources_report,
        "missing_sources": missing_sources_report,
        "malformed": malformed_reported,
        "deleted_malformed": deleted,
        "delete_failed": delete_failed,
        "total_checked": len(syntheses),
        "all_fresh": all_fresh,
    }
