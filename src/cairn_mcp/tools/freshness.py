"""cairn_mcp.tools.freshness — check_synthesis_freshness MCP tool implementation.

Audits synthesis artifacts for staleness (sources updated after synthesis),
archived sources, missing sources, and structurally malformed syntheses
(empty source_artifacts). Optionally hard-deletes malformed syntheses when
called with confirm=True.
"""

import asyncio
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

logger = logging.getLogger(__name__)


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
        # M-8: off the event loop — blocking boto3 call.
        synth_keys = await asyncio.to_thread(vectors.list_vectors_by_metadata, synth_filter)

        if not synth_keys:
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

        # ── Step 2: Fetch vector metadata for all synthesis keys (M-8: off loop) ──
        synth_items = await asyncio.to_thread(vectors.get_vectors, synth_keys, False)
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

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
    # 07-02 #17: previously one list_vectors_by_metadata call per unique source_id
    # (1+N queries total). Batched into a single $in query, mirroring the pattern
    # already established in _reference_filter.py::resolve_readable_targets.
    # Cross-scope gate (C-5): identical to list.py's Step 5 — own-scope sources are
    # always readable; a foreign-scope source is only readable when it is tier 3 AND
    # visibility="shared". A gated-out source is treated exactly as an unresolved
    # source (None) so it surfaces as missing and its date/status are never read or
    # reported — this must never leak whether a foreign artifact exists.
    own_scope = settings.write_prefix
    read_prefixes = settings.read_prefixes_list
    source_meta: dict[str, dict[str, Any] | None] = dict.fromkeys(all_source_ids)

    if all_source_ids:
        try:
            # M-8: off the event loop — blocking boto3 call.
            src_keys = await asyncio.to_thread(
                vectors.list_vectors_by_metadata,
                {"artifact_id": {"$in": sorted(all_source_ids)}},
            )
        except CredentialError as exc:
            return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

        if src_keys:
            try:
                # M-8: off the event loop — blocking boto3 call.
                src_items = await asyncio.to_thread(vectors.get_vectors, src_keys, False)
            except CredentialError as exc:
                return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

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

                if source_id.startswith(own_scope + "/"):
                    source_meta[source_id] = meta  # own scope — always allowed
                    continue

                is_foreign_readable = any(source_id.startswith(p + "/") for p in read_prefixes)
                item_tier = int(meta.get("tier", 0))
                item_visibility = str(meta.get("visibility", ""))
                if is_foreign_readable and item_tier == 3 and item_visibility == "shared":
                    source_meta[source_id] = meta

    # ── Step 7: Build stale, archived_sources, missing_sources per synthesis ──
    stale: list[dict[str, Any]] = []
    archived_sources_report: list[dict[str, Any]] = []
    missing_sources_report: list[dict[str, Any]] = []

    for aid, meta in valid_syntheses.items():
        synthesis_date: str = meta.get("date", "")
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
                if src_date > synthesis_date:
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
        for aid in malformed_ids:
            if not aid.startswith(settings.write_prefix + "/"):
                logger.warning("Skipping out-of-scope malformed synthesis: %s", aid)
                continue
            # Vectors-first, then S3 (same ordering as delete_artifact).
            # Non-credential errors at any step → report in delete_failed and continue
            # (T22 Boundary: a partial delete leaves a recoverable S3 orphan).
            try:
                # M-8: off the event loop — blocking boto3 call.
                vec_keys = await asyncio.to_thread(
                    vectors.list_vectors_by_metadata, {"artifact_id": {"$eq": aid}}
                )
            except CredentialError as exc:
                return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}
            except Exception:
                logger.warning(
                    "Failed to list vectors for malformed synthesis %s; "
                    "skipping deletion — recorded in delete_failed",
                    aid,
                    exc_info=True,
                )
                delete_failed.append(aid)
                continue
            if vec_keys:
                try:
                    # M-8: off the event loop — blocking boto3 call.
                    await asyncio.to_thread(vectors.delete_vectors, vec_keys)
                except CredentialError as exc:
                    return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}
                except Exception:
                    logger.warning(
                        "Failed to delete vectors for malformed synthesis %s; "
                        "skipping deletion — recorded in delete_failed",
                        aid,
                        exc_info=True,
                    )
                    delete_failed.append(aid)
                    continue
            try:
                # M-8: off the event loop — blocking boto3 call.
                await asyncio.to_thread(s3.head_object, aid)
            except KeyError:
                logger.warning(
                    "Malformed synthesis S3 object not found, skipping S3 delete: %s", aid
                )
                # vectors were already deleted above — artifact is fully gone
                deleted.append(aid)  # still report in deleted_malformed
                continue
            except CredentialError as exc:
                return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}
            try:
                # M-8: off the event loop — blocking boto3 call.
                await asyncio.to_thread(s3.delete_object, aid)
            except CredentialError as exc:
                return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}
            except Exception:
                logger.warning(
                    "Failed to delete S3 object for malformed synthesis %s; "
                    "vectors already deleted — S3 orphan left; recorded in delete_failed",
                    aid,
                    exc_info=True,
                )
                delete_failed.append(aid)
                continue
            deleted.append(aid)
        malformed_reported = []
    else:
        malformed_reported = list(malformed_ids)
        deleted = []

    # ── Step 9: Build response ────────────────────────────────────────────────
    # all_fresh=True means no issues remain; it does NOT mean nothing was deleted.
    # A run with confirm=True that deletes all malformed syntheses yields all_fresh=True
    # if no stale/archived/missing issues remain after deletion.
    all_fresh = not (
        stale or archived_sources_report or missing_sources_report or malformed_reported
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
