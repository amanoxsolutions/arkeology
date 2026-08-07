"""cairn_mcp.tools.link_metadata — link_metadata MCP tool.

Generalizes and supersedes ``link_commit`` (p10-t38): backfills ``commit_refs``
and/or ``references`` onto existing own-scope artifacts by fetching the current
vectors + embeddings, reading the current link-field state as the union of both
durable stores (``annotations.read_current_link_fields`` — Phase 12 review C3/C5;
neither the S3 annotation copy nor the vector-metadata copy is sole authority),
merging and deduplicating the supplied values into that union, and dual-writing
the result — durable S3 annotations first (``apply_link_annotations``), then
vector metadata second, reusing each vector's existing float32 embedding
unchanged (ADR-011, T49).

No Bedrock call is made, no artifact content is mutated, and
``last_edited_ulid`` is never touched. If the vector write fails after the
annotation write succeeds, the durable side is already correct and a later
``reconcile_index`` run (T48) rebuilds vector metadata from it.

If annotations are unavailable (unsupported region/bucket type) or access is
denied, the durable write is this tool's contract: it returns a structured
``annotation_unavailable`` error rather than reporting the artifact as linked
(ADR-011 decision 5, T52). This differs from the write path (``write.py``),
where the same condition degrades to a warning because the artifact's content
and vectors must never be lost.
"""

import logging
from typing import Any

from ulid import ULID

from cairn_mcp.annotations import (
    CAS_MAX_ATTEMPTS,
    apply_link_annotations,
    read_current_link_fields,
)
from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.constants import ErrorCode
from cairn_mcp.errors import AnnotationUnavailableError, ArtifactConflictError, CredentialError

logger = logging.getLogger(__name__)


def _apply_link_metadata_with_cas(
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    artifact_id: str,
    supplied_commit_refs: list[str],
    supplied_references: list[str],
) -> tuple[list[str], list[str]]:
    """Apply the CAS-guarded annotation dual-write for one artifact_id (ADR-011
    decision 6): capture the object's current ETag, read-forward + merge the current
    link-field state (union of both durable stores), and write the merged annotations
    conditionally on that ETag. On a detected concurrent change (``ArtifactConflictError``
    from the annotation write — a content-changing operation, e.g. an overwriting
    ``write_artifact`` call, changed the object between this call's read and its
    annotation write), re-read and retry the whole cycle for up to ``CAS_MAX_ATTEMPTS``
    attempts, re-merging this call's *original* supplied values into the fresh state each
    time (never a previous attempt's already-merged output).

    Accepted residual (ADR-011 decision 6): two concurrent calls touching the *same*
    field are not detected, because annotation writes are deliberately ETag-stable
    (decision 1) — this guard only detects a race against a content-changing write.

    Args:
        s3: S3 client.
        vectors: S3 Vectors client.
        artifact_id: The artifact's S3 key.
        supplied_commit_refs: This call's supplied commit_refs values (merged in).
        supplied_references: This call's supplied references values (merged in).

    Returns:
        The merged ``(commit_refs, references)`` actually written to the durable
        annotation store, for the caller to mirror into vector metadata.

    Raises:
        ArtifactConflictError: If retries are exhausted without a successful
            conditional write.
        AnnotationUnavailableError: As raised by the underlying annotation write.
        CredentialError: If credentials are invalid or expired.
    """
    current_etag = s3.head_object(artifact_id).get("ETag")
    for attempt in range(CAS_MAX_ATTEMPTS):
        if attempt > 0:
            current_etag = s3.head_object(artifact_id).get("ETag")

        existing_commit_refs, existing_references = read_current_link_fields(
            s3, vectors, artifact_id
        )
        merged_commit_refs = _merge_link_field(existing_commit_refs, supplied_commit_refs)
        merged_references = _merge_link_field(existing_references, supplied_references)

        try:
            apply_link_annotations(
                s3,
                artifact_id,
                commit_refs=merged_commit_refs,
                references=merged_references,
                if_match=current_etag,
            )
        except ArtifactConflictError:
            continue
        return merged_commit_refs, merged_references

    raise ArtifactConflictError(artifact_id)


def _merge_link_field(existing: list[str], supplied: list[str]) -> list[str]:
    """Merge ``supplied`` values into ``existing``, deduplicating and order-preserving.

    Args:
        existing: The current value of the field — the order-preserving dedup union
            of both durable stores (``annotations.read_current_link_fields``), so
            neither store is treated as sole authority (Phase 12 review C3/C5).
        supplied: The values requested by this call (may be empty, in which case
            the existing value is returned unchanged, only deduplicated).

    Returns:
        The merged, deduplicated, order-preserving list.
    """
    return list(dict.fromkeys(existing + supplied))


async def link_metadata(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_ids: list[str],
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
) -> dict[str, Any]:
    """Backfill ``commit_refs`` and/or ``references`` onto own-scope artifacts.

    Dual-writes the merged values: the durable S3 annotation first, then vector
    metadata second, reusing each vector's existing float32 embedding — no
    Bedrock call, no content mutation, no ``last_edited_ulid`` change.

    Args:
        settings: Server configuration.
        s3: S3 client, used for the durable annotation write.
        vectors: S3 Vectors client.
        bedrock: Bedrock client (unused in this tool; injected for interface
            consistency with the other MCP tools).
        artifact_ids: Artifact IDs to backfill. Foreign-scope IDs are skipped
            and counted, never linked.
        commit_refs: Optional list of commit SHAs to merge into each artifact's
            ``commit_refs``.
        references: Optional list of resolved artifact IDs to merge into each
            artifact's ``references``.

    Returns:
        On success::

            {
                "linked": int,
                "skipped": int,
                "next_since_ulid": str,
            }

        On error: ``{"error": str, "message": str}``
    """
    try:
        return await _link_metadata_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_ids=artifact_ids,
            commit_refs=commit_refs,
            references=references,
        )
    except Exception as exc:
        logger.exception("Unexpected error in link_metadata")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _link_metadata_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_ids: list[str],
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
) -> dict[str, Any]:
    """Inner implementation of link_metadata."""
    _ = bedrock

    supplied_commit_refs: list[str] = commit_refs if commit_refs is not None else []
    supplied_references: list[str] = references if references is not None else []

    if not supplied_commit_refs and not supplied_references:
        return {
            "error": ErrorCode.VALIDATION_ERROR,
            "message": "At least one of commit_refs or references must be non-empty",
        }

    write_prefix = settings.write_prefix
    linked = 0
    skipped = 0

    for artifact_id in artifact_ids:
        # ── Scope gate ────────────────────────────────────────────────────────
        if not artifact_id.startswith(write_prefix + "/"):
            logger.debug("link_metadata scope gate rejected artifact_id=%s", artifact_id)
            skipped += 1
            continue

        try:
            # ── Fetch all vector keys for this artifact ───────────────────────
            keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})

            if not keys:
                logger.debug("link_metadata no vectors found for artifact_id=%s", artifact_id)
                skipped += 1
                continue

            # ── Retrieve current vectors (metadata + float32 data) ────────────
            items = vectors.get_vectors(keys)
            if not items:
                skipped += 1
                continue

            # ── Read-forward + merge, guarded by an ETag compare-and-swap (ADR-011
            # decision 6) ─────────────────────────────────────────────────────────
            # Read-forward the current state as the union of BOTH durable stores
            # (Phase 12 review C3/C5) — never vector metadata alone. A vector-only
            # read misses a value that lives only in the S3 annotation (e.g. a prior
            # link_metadata call whose annotation write succeeded but whose vector
            # write failed), and merging supplied=[] against that missing value would
            # make the annotation write delete the annotation instead of healing it.
            # See ``annotations.read_current_link_fields``. The whole fetch-merge-reput
            # cycle races every other read-modify-write cycle on the same artifact's
            # durable link-field state, so it is guarded by a bounded ETag
            # compare-and-swap retry (``_apply_link_metadata_with_cas``): on a detected
            # concurrent change (a content-changing write altered the object between
            # this call's read and its annotation write), re-read and retry the whole
            # cycle, re-merging this call's *original* supplied values into the fresh
            # state — never a previous attempt's already-merged output.
            merged_commit_refs, merged_references = _apply_link_metadata_with_cas(
                s3, vectors, artifact_id, supplied_commit_refs, supplied_references
            )

            # ── Vector metadata write SECOND, reusing existing embeddings ─────
            batch: list[dict[str, Any]] = []
            for item in items:
                meta: dict[str, Any] = dict(item["metadata"])
                if merged_commit_refs:
                    meta["commit_refs"] = merged_commit_refs
                else:
                    meta.pop("commit_refs", None)
                if merged_references:
                    meta["references"] = merged_references
                else:
                    meta.pop("references", None)

                batch.append(
                    {
                        "key": item["key"],
                        "vector": item["data"]["float32"],
                        "metadata": meta,
                    }
                )

            vectors.put_vectors_batch(batch)
        except AnnotationUnavailableError as exc:
            # T52 / ADR-011 decision 5: the durable annotation write is link_metadata's
            # contract (it exists precisely to make commit_refs/references durable), so
            # unlike the write path's graceful degrade, this is not silently absorbed —
            # it is reported as a structured, actionable error and this artifact_id is
            # never counted as linked.
            return {"error": ErrorCode.ANNOTATION_UNAVAILABLE, "message": str(exc)}
        except ArtifactConflictError as exc:
            # ADR-011 decision 6: the bounded CAS retry cycle in
            # _apply_link_metadata_with_cas was exhausted without a successful
            # conditional write — never a raw exception, never a silent partial write.
            return {
                "error": ErrorCode.CONFLICT,
                "message": (
                    f"Could not link '{exc.key}': a concurrent writer changed the "
                    f"artifact {CAS_MAX_ATTEMPTS} times in a row while this call "
                    "attempted its compare-and-swap retry cycle. Retry the call."
                ),
                "artifact_id": exc.key,
            }
        except CredentialError as exc:
            return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

        linked += 1
        logger.info("link_metadata linked artifact_id=%s", artifact_id)

    # ── Generate cursor ONCE after processing all artifacts ──────────────────
    next_since_ulid = str(ULID())

    return {
        "linked": linked,
        "skipped": skipped,
        "next_since_ulid": next_since_ulid,
    }
