"""arkeology.tools.link_metadata — link_metadata MCP tool.

Generalizes and supersedes ``link_commit`` (p10-t38): backfills ``commit_refs``
and/or ``references`` onto existing own-scope artifacts by fetching the current
vectors + embeddings, reading the current link-field state from the durable S3
annotations (``annotations.read_link_annotations`` — the sole source of truth for
both link fields), merging and deduplicating the supplied values into that state,
and writing the result to the annotations first (``apply_link_annotations``), then
to vector metadata second as a derived filter index, reusing each vector's existing
float32 embedding unchanged (ADR-011, T49).

No Bedrock call is made, no artifact content is mutated, and
``last_edited_ulid`` is never touched. If the vector write fails after the
annotation write succeeds, the durable side is already correct but the two copies
have diverged, so a failure-log entry is written carrying the values that were
applied. That entry is the trigger: ``reconcile_index``'s failure-log replay
re-indexes the artifact from the annotation copy and the two converge. Without
it nothing would ever revisit the artifact — it still has vectors, so the orphan
scan does not see it — and the vector copy would stay stale indefinitely, silently
omitting the artifact from every server-side filter on the linked field.

If annotations are unavailable (unsupported region/bucket type) or access is
denied, this tool returns a structured ``annotation_unavailable`` error rather
than reporting the artifact as linked. At runtime that condition means post-setup
IAM drift: the startup gate refuses to start a deployment that cannot use
annotations at all.
"""

import asyncio
import logging
from typing import Any

from ulid import ULID

from arkeology.annotations import (
    CAS_MAX_ATTEMPTS,
    apply_link_annotations,
    merge_link_field,
    read_link_annotations,
)
from arkeology.artifact import Artifact, cap_commit_refs_for_vectors, check_metadata_budgets
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ErrorCode
from arkeology.errors import (
    AnnotationUnavailableError,
    ArtifactConflictError,
    CredentialError,
    MetadataTooLargeError,
)
from arkeology.failure_log import append_failure_entry, build_failure_entry
from arkeology.tools._errors import credential_error_response
from arkeology.tools._scope import is_own_scope
from arkeology.tools._search_helper import fetch_vectors_by_metadata

logger = logging.getLogger(__name__)

# Bounded concurrency for the per-artifact_id loop, mirroring write_artifacts.py's
# asyncio.Semaphore-gated asyncio.gather pattern. Each artifact_id's CAS-guarded
# annotation + vector dual-write is independent of every other's.
_LINK_CONCURRENCY = 5


def _apply_link_metadata_with_cas(
    s3: S3ClientInterface,
    artifact_id: str,
    supplied_commit_refs: list[str],
    supplied_references: list[str],
    existing_vector_metadata: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Apply the CAS-guarded annotation dual-write for one artifact_id (ADR-011
    decision 6): capture the object's current ETag, read-forward + merge the current
    link-field state from the durable annotations, check the merged state against
    the write-path metadata size budgets (T57), and write the merged annotations
    conditionally on that ETag. On a detected concurrent change (``ArtifactConflictError``
    from the annotation write — a content-changing operation, e.g. an overwriting
    ``write_artifact`` call, changed the object between this call's read and its
    annotation write), re-read and retry the whole cycle for up to ``CAS_MAX_ATTEMPTS``
    attempts, re-merging this call's *original* supplied values into the fresh state each
    time (never a previous attempt's already-merged output) — the budget check re-runs
    against the freshly merged state on every attempt.

    Accepted residual (ADR-011 decision 6): two concurrent calls touching the *same*
    field are not detected, because annotation writes are deliberately ETag-stable
    (decision 1) — this guard only detects a race against a content-changing write.

    Args:
        s3: S3 client.
        artifact_id: The artifact's S3 key.
        supplied_commit_refs: This call's supplied commit_refs values (merged in).
        supplied_references: This call's supplied references values (merged in).
        existing_vector_metadata: The currently indexed vector metadata for one
            representative vector of this artifact — all of an artifact's vectors
            carry identical metadata content apart from the vector key, so any one
            is an accurate base for the candidate budget check. Already fetched by
            the caller (``vectors.get_vectors``); no new vector fetch is introduced.

    Returns:
        The merged ``(commit_refs, references)`` actually written to the durable
        annotation store, for the caller to mirror into vector metadata.

    Raises:
        ArtifactConflictError: If retries are exhausted without a successful
            conditional write.
        AnnotationUnavailableError: As raised by the underlying annotation write.
        CredentialError: If credentials are invalid or expired.
        MetadataTooLargeError: If the merged commit_refs/references would breach any
            of the three metadata size budgets — raised BEFORE the annotation write,
            so nothing is left durably half-written (T57).
    """
    current_etag = s3.head_object(artifact_id).get("ETag")
    for attempt in range(CAS_MAX_ATTEMPTS):
        if attempt > 0:
            current_etag = s3.head_object(artifact_id).get("ETag")

        existing_commit_refs, existing_references = read_link_annotations(s3, artifact_id)
        merged_commit_refs = merge_link_field(existing_commit_refs, supplied_commit_refs)
        merged_references = merge_link_field(existing_references, supplied_references)

        # The pre-check must measure exactly what the real write assembles (T58 batch
        # loop in _link_metadata_inner below): commit_refs capped to the most-recent
        # COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES entries, references never written to
        # vector metadata at all. Measuring the uncapped merged_commit_refs here would
        # spuriously reject a write that the real, correctly-capped write would pass.
        candidate_metadata: dict[str, Any] = dict(existing_vector_metadata)
        if merged_commit_refs:
            candidate_metadata["commit_refs"] = cap_commit_refs_for_vectors(merged_commit_refs)
        else:
            candidate_metadata.pop("commit_refs", None)
        candidate_metadata.pop("references", None)
        check_metadata_budgets(s3_metadata={}, vector_metadata=candidate_metadata)

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


def _record_vector_write_failure(
    settings: Settings,
    *,
    artifact_id: str,
    vector_metadata: dict[str, Any],
    reason: str,
    commit_refs: list[str],
    references: list[str],
) -> None:
    """Append a failure-log entry for a vector write that failed after the annotation
    write succeeded.

    Without it, the divergence is permanent and invisible: the artifact still has
    vectors, so ``reconcile_index``'s orphan scan never revisits it, and nothing else
    ever compares the two stores. A stale vector copy means the field is missing from
    every server-side metadata filter, so a search or list filtered on the linked value
    silently omits the artifact while ``read_artifact`` (which reads the annotation) shows it.

    The entry makes the artifact a failure-log replay candidate, which is what turns
    the annotation-first write order into an actual repair: Phase 1 re-applies the
    recorded link fields and re-indexes from the annotation copy, converging the two.

    Args:
        settings: Server configuration (for ``failure_log_path``).
        artifact_id: S3 key of the artifact whose vector copy is now stale.
        vector_metadata: The artifact's currently indexed vector metadata, the source of
            the descriptive fields the entry carries. Taken from the vectors already
            fetched by this call — no extra AWS round trip on a failure path.
        reason: Human-readable failure reason.
        commit_refs: The merged value the annotation write persisted, recorded so the
            replay restores it even if the annotation copy is cleared before reconcile
            runs (an overwriting ``write_artifact`` re-PUT does exactly that).
        references: As ``commit_refs``.
    """
    tier_raw = vector_metadata.get("tier", 2)
    try:
        tier = int(tier_raw)
    except TypeError, ValueError:
        tier = 2
    append_failure_entry(
        settings.failure_log_path,
        build_failure_entry(
            artifact_id=artifact_id,
            title=str(vector_metadata.get("title", "")),
            artifact_type=str(vector_metadata.get("type", "")),
            tier=tier,
            date=str(vector_metadata.get("date", "")),
            failure_step="put_vector",
            reason=reason,
            commit_refs=commit_refs,
            references=references,
        ),
    )


def _validate_supplied_link_values(values: list[str], field: str) -> str | None:
    """Reject empty/whitespace-only elements, then delegate the control-character and
    comma checks to ``Artifact.validate_commit_refs`` / ``validate_references`` — the
    same per-element constraints the Artifact model enforces on every other write
    path (T57). Delegating directly, rather than re-implementing
    ``_require_no_control_chars``/``_require_no_comma`` a second time, closes the
    exact drift risk a hand-rolled parallel implementation carries: this function
    previously never checked for control characters, letting one bypass the Artifact
    model's invariant entirely via link_metadata.

    Args:
        values: The supplied ``commit_refs`` or ``references`` list for this call.
        field: The field being checked — ``"commit_refs"`` or ``"references"``,
            selects which Artifact classmethod to delegate to and is used in the
            empty/whitespace-only message.

    Returns:
        A validation-error message if any element is empty, whitespace-only,
        contains a control character, or contains a comma; ``None`` when every
        element is acceptable.
    """
    for item in values:
        if not item.strip():
            return f"{field} elements must not be empty or whitespace-only, found {item!r}"

    validator = (
        Artifact.validate_commit_refs if field == "commit_refs" else Artifact.validate_references
    )
    try:
        validator(values)
    except ValueError as exc:
        return str(exc)
    return None


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
                # only when non-empty:
                "vector_write_failed": list[str],
            }

        ``vector_write_failed`` lists the artifact_ids whose annotation write
        succeeded but whose vector write did not. They are counted in neither
        ``linked`` nor ``skipped``, and each has a failure-log entry queued for
        ``reconcile_index`` to replay.

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

    # Reject empty/whitespace/comma-bearing values up front, before any artifact
    # is touched — mirrors the per-element constraints Artifact.validate_commit_refs /
    # validate_references enforce on write.
    for values, field in (
        (supplied_commit_refs, "commit_refs"),
        (supplied_references, "references"),
    ):
        message = _validate_supplied_link_values(values, field)
        if message is not None:
            return {"error": ErrorCode.VALIDATION_ERROR, "message": message}

    write_prefix = settings.write_prefix

    # Bounded concurrency: each artifact_id's fetch-merge-CAS-reput cycle is
    # independent of every other's, mirroring write_artifacts.py's
    # asyncio.Semaphore-gated asyncio.gather pattern. Each task never raises — it
    # returns an outcome marker — so one artifact_id's failure never leaves
    # concurrently-dispatched sibling tasks in an unobserved state.
    #
    # Accepted trade-off (reviewed, not a defect): the prior sequential loop
    # stopped at a deterministic prefix on the first CredentialError; here up to
    # _LINK_CONCURRENCY already-in-flight artifact_ids may complete before the
    # abort is noticed. Low-risk: credential_error_response() never reported
    # which artifact_ids had already succeeded in either version, and each
    # completed link is individually correct (CAS-guarded), so retrying the same
    # call after fixing credentials reprocesses the full input idempotently.
    semaphore = asyncio.Semaphore(_LINK_CONCURRENCY)

    async def _process_one(artifact_id: str) -> dict[str, Any]:
        # ── Scope gate ────────────────────────────────────────────────────────
        if not is_own_scope(artifact_id, write_prefix):
            logger.debug("link_metadata scope gate rejected artifact_id=%s", artifact_id)
            return {"kind": "skip"}

        async with semaphore:
            try:
                # ── Fetch all vector keys + current vectors (metadata + float32 data) ──
                items = await asyncio.to_thread(
                    fetch_vectors_by_metadata,
                    vectors,
                    {"artifact_id": {"$eq": artifact_id}},
                    include_data=True,
                )

                if not items:
                    logger.debug("link_metadata no vectors found for artifact_id=%s", artifact_id)
                    return {"kind": "skip"}

                # ── Read-forward + merge, guarded by an ETag compare-and-swap (ADR-011
                # decision 6) ─────────────────────────────────────────────────────────
                # Read-forward the current state from the durable annotations, their
                # sole source of truth — never vector metadata, which holds a capped,
                # derived filter copy of commit_refs and no references at all. Merging
                # supplied=[] against a vector-only read would make the annotation write
                # delete the annotation instead of healing it.
                # See ``annotations.read_link_annotations``. The whole fetch-merge-reput
                # cycle races every other read-modify-write cycle on the same artifact's
                # durable link-field state, so it is guarded by a bounded ETag
                # compare-and-swap retry (``_apply_link_metadata_with_cas``): on a detected
                # concurrent change (a content-changing write altered the object between
                # this call's read and its annotation write), re-read and retry the whole
                # cycle, re-merging this call's *original* supplied values into the fresh
                # state — never a previous attempt's already-merged output.
                merged_commit_refs, merged_references = await asyncio.to_thread(
                    _apply_link_metadata_with_cas,
                    s3,
                    artifact_id,
                    supplied_commit_refs,
                    supplied_references,
                    items[0]["metadata"],
                )

                # ── Vector metadata write SECOND, reusing existing embeddings ─────
                # commit_refs is capped to the most-recently-appended
                # COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES entries for this vector-metadata
                # copy only (T58) — the annotation write above already carried the
                # complete, uncapped merged_commit_refs. references is never written to
                # vector metadata (T58) — the annotation write above is its sole durable
                # store; unconditionally drop any stale pre-T58 key here.
                batch: list[dict[str, Any]] = []
                for item in items:
                    meta: dict[str, Any] = dict(item["metadata"])
                    if merged_commit_refs:
                        meta["commit_refs"] = cap_commit_refs_for_vectors(merged_commit_refs)
                    else:
                        meta.pop("commit_refs", None)
                    meta.pop("references", None)

                    batch.append(
                        {
                            "key": item["key"],
                            "vector": item["data"]["float32"],
                            "metadata": meta,
                        }
                    )

                try:
                    await asyncio.to_thread(vectors.put_vectors_batch, batch)
                except Exception as exc:
                    # The annotation write above already succeeded, so the two durable
                    # copies are now divergent. Record it before deciding how to report
                    # it — including on the credential branch, where the divergence is
                    # no less real than on any other failure — so reconcile_index has
                    # something to replay. Re-raised credential errors keep their
                    # existing abort-the-whole-call handling below.
                    _record_vector_write_failure(
                        settings,
                        artifact_id=artifact_id,
                        vector_metadata=items[0]["metadata"],
                        reason=str(exc),
                        commit_refs=merged_commit_refs,
                        references=merged_references,
                    )
                    if isinstance(exc, CredentialError):
                        raise
                    logger.warning(
                        "link_metadata vector write failed for artifact_id=%s: %s — "
                        "annotation copy is correct, recorded for reconcile_index",
                        artifact_id,
                        exc,
                    )
                    return {"kind": "vector_write_failed", "artifact_id": artifact_id}
            except KeyError:
                # M10: the vector index still carries this artifact_id (an orphaned
                # vector — e.g. a prior write's S3 put succeeded but a later delete or a
                # failed reconcile left the S3 object gone) but head_object/put_object_annotation
                # inside _apply_link_metadata_with_cas found no matching S3 object. This is
                # skip-and-continue, not an aborting internal_error: the rest of this call's
                # artifact_ids must still be processed.
                logger.debug(
                    "link_metadata skipped orphaned-vector artifact_id=%s (S3 object missing)",
                    artifact_id,
                )
                return {"kind": "skip"}
            except AnnotationUnavailableError as exc:
                return {"kind": "annotation_unavailable", "exc": exc}
            except MetadataTooLargeError as exc:
                return {"kind": "metadata_too_large", "exc": exc}
            except ArtifactConflictError as exc:
                return {"kind": "conflict", "exc": exc}
            except CredentialError as exc:
                return {"kind": "credential_error", "exc": exc}

            logger.info("link_metadata linked artifact_id=%s", artifact_id)
            return {"kind": "linked"}

    results = await asyncio.gather(*[_process_one(aid) for aid in artifact_ids])

    linked = sum(1 for r in results if r["kind"] == "linked")
    skipped = sum(1 for r in results if r["kind"] == "skip")
    # Neither linked (the vector copy is stale) nor skipped (the artifact was very much
    # touched — its annotation copy was written): reported on its own key so the caller
    # can see that reconcile_index owes it a repair.
    vector_write_failed = [r["artifact_id"] for r in results if r["kind"] == "vector_write_failed"]

    # ── Abort-worthy outcomes take priority over the normal linked/skipped summary,
    # decided deterministically in original artifact_ids order (matches the exact
    # response a single such failure would have produced; only relevant as a
    # tie-breaker in the pathological case of two DIFFERENT abort-worthy outcomes
    # occurring in the same concurrent batch) ─────────────────────────────────────
    for r in results:
        kind = r["kind"]
        if kind == "credential_error":
            return credential_error_response(r["exc"])
        if kind == "annotation_unavailable":
            # The durable annotation write is link_metadata's contract (it exists
            # precisely to make commit_refs/references durable), so this is never
            # absorbed — it is reported as a structured, actionable error and this
            # artifact_id is never counted as linked.
            #
            # linked/skipped progress accumulated on other artifact_ids in this same
            # call must not be discarded — only included when non-zero, so a call
            # where nothing else succeeded keeps the response shape unchanged.
            error_response: dict[str, Any] = {
                "error": ErrorCode.ANNOTATION_UNAVAILABLE,
                "message": str(r["exc"]),
            }
            if linked or skipped:
                error_response["linked"] = linked
                error_response["skipped"] = skipped
            return error_response
        if kind == "metadata_too_large":
            # T57: the merged commit_refs/references would breach a metadata size
            # budget — rejected before the annotation write, so nothing durable is
            # left half-written. Same partial-progress convention as
            # annotation_unavailable above: linked/skipped only when non-zero.
            budget_error_response: dict[str, Any] = {
                "error": ErrorCode.VALIDATION_ERROR,
                "message": str(r["exc"]),
            }
            if linked or skipped:
                budget_error_response["linked"] = linked
                budget_error_response["skipped"] = skipped
            return budget_error_response
        if kind == "conflict":
            # ADR-011 decision 6: the bounded CAS retry cycle in
            # _apply_link_metadata_with_cas was exhausted without a successful
            # conditional write — never a raw exception, never a silent partial write.
            exc = r["exc"]
            return {
                "error": ErrorCode.CONFLICT,
                "message": (
                    f"Could not link '{exc.key}': a concurrent writer changed the "
                    f"artifact {CAS_MAX_ATTEMPTS} times in a row while this call "
                    "attempted its compare-and-swap retry cycle. Retry the call."
                ),
                "artifact_id": exc.key,
            }

    # ── Generate cursor ONCE after processing all artifacts ──────────────────
    next_since_ulid = str(ULID())

    response: dict[str, Any] = {
        "linked": linked,
        "skipped": skipped,
        "next_since_ulid": next_since_ulid,
    }
    if vector_write_failed:
        response["vector_write_failed"] = vector_write_failed
    return response
