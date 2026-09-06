"""arkeology.tools.archive — archive_artifact MCP tool implementation.

Sets an artifact's status to "inactive" in both S3 object metadata and all
corresponding vector metadata entries. Scoped to the deployment's own prefix.
Before archiving, performs a unified own-scope referenced_by check (T50,
ADR-012 D13) — warn-but-don't-block, informational (reversible) phrasing.

As of T60, the referenced_by check covers `source_artifacts` only — `references` is
NOT checked. T58 stopped writing `references` into S3 Vectors metadata, so the
`references`-half of this check could no longer match anything; an unbounded
full-corpus S3-annotation scan was evaluated as a substitute and rejected (ADR
"vector-metadata-budget-hardening-and-self-heal" decision D6). An own-scope artifact
that references the archived artifact only via its `references` field will NOT
appear in the warning.

The status flip is an in-place S3 re-PUT, which clears the object's S3 annotations
(ADR-011). This tool therefore reads the current
commit_refs/references link fields forward from their sole source of truth, the
durable annotations (``annotations.read_link_annotations``), before the re-PUT and
re-applies them afterward (``annotations.apply_link_annotations``), mirroring write.py's
Step 4a/4b pattern — including its treatment of a failed annotation write as a partial
archive (failure-log entry, structured error) rather than a success.
"""

import asyncio
import logging
from typing import Any

from arkeology.annotations import (
    CAS_MAX_ATTEMPTS,
    apply_link_annotations,
    merge_link_field,
    read_link_annotations,
)
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ArtifactStatus, ErrorCode
from arkeology.errors import (
    AnnotationUnavailableError,
    ArtifactConflictError,
    CredentialError,
)
from arkeology.failure_log import (
    append_failure_entry,
    build_failure_entry,
    coerce_entry_tier,
)
from arkeology.tools._errors import credential_error_response
from arkeology.tools._scope import is_own_scope
from arkeology.tools._search_helper import fetch_vectors_by_metadata, find_referrers

logger = logging.getLogger(__name__)

# The steps a partial archive can fail at, after the status re-PUT is durable. Every one
# of them leaves the same repairable state, so they differ only in what they tell an
# operator reading the log — which is reason enough not to stamp them all as the flip.
_STEP_CAS_REREAD = "archive_cas_reread"
_STEP_ANNOTATION_READ = "annotation_read"
_STEP_CONTENT_FETCH = "archive_content_fetch"
_STEP_STATUS_REPUT = "archive_status_reput"
_STEP_ANNOTATION_WRITE = "annotation_write"
_STEP_VECTOR_FLIP = "archive_vector_flip"


def _record_partial_archive_failure(
    settings: Settings,
    *,
    artifact_id: str,
    s3_meta: dict[str, Any],
    failure_step: str,
    reason: str,
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
) -> None:
    """Append a failure-log entry for a partially completed archive.

    A partial archive is one where the S3 status flip has already succeeded
    (``s3.put_object`` returned) but something after it failed — the annotation
    re-apply, the per-vector status update loop, or any call on a later
    compare-and-swap attempt — credential error or otherwise. Without this, such a
    failure left no
    repairable trace: the S3 object already reports ``status: inactive`` so a
    retried ``archive_artifact`` call used to hit the ``already_archived``
    idempotency short-circuit forever (fixed alongside this by also checking
    vector status), and ``reconcile_index`` had no reason to touch an artifact
    it still considered fully indexed.

    A subsequent ``reconcile_index`` run replays this entry via the same
    failure-log mechanism used by ``write_artifact`` — ``_reindex_artifact``
    rebuilds vector metadata (including ``status``) from the S3 object, which
    already carries the correct ``inactive`` status, repairing the vector side.

    Args:
        settings: Server configuration (for ``failure_log_path``).
        artifact_id: S3 key of the partially archived artifact.
        s3_meta: The artifact's S3 object metadata (post status-flip), used to
            populate the failure-log entry's descriptive fields.
        failure_step: The step that actually failed, one of ``_STEP_*``. Nothing
            branches on it — it is operator diagnostics, and it contributes to the
            fingerprint ``reconcile_index`` prunes entries by — so it is stamped per
            call site rather than fixed at the vector flip, which is only one of the
            several steps that reach here.
        reason: Human-readable failure reason.
        commit_refs: The link fields read forward before the status re-PUT.
            Recorded because that re-PUT cleared the object's annotations: if the
            re-apply meant to restore them is what failed, this entry is the only
            place the values still exist. ``references`` is not in vector metadata
            at all and the vector ``commit_refs`` copy is capped, so whatever is not
            recorded here is lost for good. Omitted when empty; see
            :func:`~arkeology.failure_log.build_failure_entry`.
        references: As ``commit_refs``.
    """
    append_failure_entry(
        settings.failure_log_path,
        build_failure_entry(
            artifact_id=artifact_id,
            title=s3_meta.get("title", ""),
            artifact_type=s3_meta.get("type", ""),
            tier=coerce_entry_tier(s3_meta.get("tier", 2)),
            date=s3_meta.get("date", ""),
            failure_step=failure_step,
            reason=reason,
            commit_refs=commit_refs,
            references=references,
            # Archive preserves the artifact's ULID rather than regenerating it, so
            # this is the one it already carried. A write landing after this entry
            # moves it, and reconcile_index then discards the entry's references
            # rather than restoring them over what that write established.
            last_edited_ulid=s3_meta.get("last_edited_ulid"),
        ),
    )


async def archive_artifact(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_id: str,
) -> dict[str, Any]:
    """Archive an artifact by setting its status to 'inactive'.

    Args:
        settings: Server configuration.
        s3: S3 client.
        vectors: S3 Vectors client.
        bedrock: Bedrock client (unused; injected for interface consistency).
        artifact_id: Full S3 key of the artifact to archive.

    Returns:
        On success: ``{"artifact_id": str, "status": "inactive"}`` plus optional
            ``"referrers"`` (list of referring artifact ids) and ``"warning_message"``
            (informational, reversible-action phrasing) if own-scope referrers were
            found. As of T60, referrers are detected via ``source_artifacts`` only —
            ``references``-based referrers are not detected (see module docstring).
        On error: ``{"error": str, "message": str}``
    """
    try:
        return await _archive_artifact_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_id=artifact_id,
        )
    except Exception as exc:
        logger.exception("Unexpected error in archive_artifact")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _archive_artifact_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_id: str,
) -> dict[str, Any]:
    """Inner implementation of archive_artifact (separated to enable top-level catch-all)."""
    _ = bedrock

    # ── Step 1: Scope check ───────────────────────────────────────────────────
    if not is_own_scope(artifact_id, settings.write_prefix):
        return {
            "error": ErrorCode.ACCESS_DENIED,
            "message": (
                f"Artifact '{artifact_id}' is not in the write scope "
                f"'{settings.write_prefix}'. Only own-scope artifacts may be archived."
            ),
        }

    # ── Step 2: Verify existence and get current S3 metadata ─────────────────
    try:
        s3_meta = await asyncio.to_thread(s3.head_object, artifact_id)
    except CredentialError as exc:
        return credential_error_response(exc)
    except KeyError:
        return {
            "error": ErrorCode.NOT_FOUND,
            "message": f"Artifact '{artifact_id}' not found.",
        }

    # ── Step 2b: Idempotency — already fully archived → early return ─────────
    # A half-archived artifact (S3 status already flipped to inactive, but
    # one or more of its vectors are still status=active because a prior
    # vector-side flip attempt failed partway) must NOT be treated as fully
    # archived — an early return here would make every retry hit this
    # short-circuit forever and the vector side would never be repaired. Only
    # short-circuit when S3 is inactive AND every existing vector already agrees.
    if s3_meta.get("status") == ArtifactStatus.INACTIVE:
        try:
            existing_vec_items = await asyncio.to_thread(
                fetch_vectors_by_metadata,
                vectors,
                {"artifact_id": {"$eq": artifact_id}},
                include_data=False,
            )
            vectors_need_flip = any(
                item["metadata"].get("status") != ArtifactStatus.INACTIVE
                for item in existing_vec_items
            )
        except CredentialError as exc:
            return credential_error_response(exc)

        if not vectors_need_flip:
            return {
                "artifact_id": artifact_id,
                "status": ArtifactStatus.INACTIVE,
                "already_archived": True,
            }
        # Otherwise fall through: S3 already reports inactive but one or more
        # vectors do not — complete the interrupted vector-side flip (retry after
        # a partial archive).

    # ── Step 3: Unified own-scope referenced_by check (T50, ADR-012 D13) ─────
    try:
        referrers = await asyncio.to_thread(
            find_referrers, vectors=vectors, settings=settings, artifact_id=artifact_id
        )
    except CredentialError as exc:
        return credential_error_response(exc)

    def _conflict_response() -> dict[str, Any]:
        return {
            "error": ErrorCode.CONFLICT,
            "message": (
                f"Could not archive '{artifact_id}': a concurrent writer changed the "
                f"artifact {CAS_MAX_ATTEMPTS} times in a row while this call attempted "
                "its compare-and-swap retry cycle. Retry the archive."
            ),
            "artifact_id": artifact_id,
        }

    # ── Step 4: Fetch content, read-forward link fields, and flip S3 status —
    # guarded by an ETag compare-and-swap (ADR-011 decision 6) ────────────────
    # PutObject clears S3 annotations, so the in-place status re-PUT would otherwise
    # silently destroy the durable commit_refs/references annotation trail. Read the
    # current values forward from the annotations, their sole source of truth (see
    # ``annotations.read_link_annotations``), so they can be re-applied after the
    # re-PUT. Archive has no caller-supplied references to replace *from* — unlike
    # the overwrite path in ``tools/write.py``,
    # it must continue to read-forward and re-apply BOTH commit_refs and references
    # unconditionally; letting the write-path's replace semantics leak in here would
    # silently wipe references on every archive operation.
    #
    # This whole fetch-status-flip-reannotate cycle races every other read-modify-write
    # cycle on the same artifact's durable link-field state, so it is guarded by a
    # bounded ETag compare-and-swap retry, mirroring write.py's Step 4a/4b: the
    # object's ETag is captured on read (from the head_object already performed at
    # Step 2 for the first attempt) and the status re-PUT is conditional
    # (if_match=ETag0); the object's *new* ETag (ETag1) is used as if_match on the
    # following apply_link_annotations call. On ArtifactConflictError from either
    # call: re-read (fresh ETag, fresh metadata, fresh content, fresh link-field
    # state) and retry the whole cycle — for CAS_MAX_ATTEMPTS attempts, after which a
    # structured conflict error is returned.
    current_s3_meta: dict[str, Any] = s3_meta
    current_etag = s3_meta.get("ETag")
    updated_s3_meta: dict[str, str] = {}
    last_attempt_object_written = False
    # Bound before the loop so the retries-exhausted branch and the vector-flip
    # handlers below can also record the read-forward values, and so each attempt
    # *accumulates* into them rather than replacing them. This attempt's own status
    # re-PUT clears the object's annotations, so a retry after a failed re-apply reads
    # them back as absent — replacing here would silently archive away the link fields
    # the first attempt had already read.
    current_commit_refs: list[str] = []
    current_references: list[str] = []
    # The last_edited_ulid the accumulated `references` value was read under. The
    # accumulation exists only to survive *this* call's own status re-PUT clearing the
    # annotations; it must not outlive a concurrent write_artifact, which REPLACES
    # references. When a retry's re-read shows a different ULID, that write's value is
    # the authoritative one: references resets to exactly what was just read and that
    # ULID becomes the new baseline. commit_refs keeps accumulating across the same
    # boundary, being append-only and already carried forward by that write.
    accumulation_ulid = s3_meta.get("last_edited_ulid")
    # Distinct from last_attempt_object_written, which is reset per attempt: this one is
    # never reset. Reaching a retry attempt at all means an earlier attempt's status
    # re-PUT already landed durably and cleared the object's annotations, so any failure
    # from that point on — on the re-read, the annotation read, the content fetch, or
    # the re-PUT — leaves the same repairable partial-archive state as a failure on the
    # annotation re-apply itself, not a clean no-op failure.
    object_written = False
    # Reassigned as the guarded region advances, so the outer handlers can stamp the
    # entry with the step that actually raised rather than with the one the region ends
    # at. The first thing every attempt does is read the annotations.
    current_step = _STEP_ANNOTATION_READ

    def _record_if_durable(exc: Exception) -> None:
        """Record a partial archive for ``exc`` once the status flip is durable.

        Keyed on ``object_written`` and on nothing else: at that point S3 says
        `inactive`, the re-PUT has cleared the annotations, and the vectors still say
        `active`, so *every* failure from there on leaves the same repairable state —
        a credential expiry, an annotation-unavailable IAM drift, and a SlowDown on a
        retry's re-read alike. Without an entry, reconcile_index sees a fully indexed
        artifact and never touches it.
        """
        if object_written:
            _record_partial_archive_failure(
                settings,
                artifact_id=artifact_id,
                s3_meta=updated_s3_meta,
                failure_step=current_step,
                reason=str(exc),
                commit_refs=current_commit_refs,
                references=current_references,
            )

    try:
        for attempt in range(CAS_MAX_ATTEMPTS):
            last_attempt_object_written = False
            if attempt > 0:
                current_step = _STEP_CAS_REREAD
                try:
                    current_s3_meta = await asyncio.to_thread(s3.head_object, artifact_id)
                except KeyError:
                    # A concurrent caller deleted the object between attempts. There is
                    # nothing left to compare-and-swap against, and the vectors left
                    # behind are already reconcile_index's dangling-vector case, so say
                    # so plainly rather than letting the KeyError reach the catch-all.
                    return {
                        "error": ErrorCode.NOT_FOUND,
                        "message": (
                            f"Artifact '{artifact_id}' was deleted by a concurrent caller "
                            "while this archive was retrying its compare-and-swap cycle."
                        ),
                    }
                current_etag = current_s3_meta.get("ETag")

            current_step = _STEP_ANNOTATION_READ
            fresh_commit_refs, fresh_references = await asyncio.to_thread(
                read_link_annotations, s3, artifact_id
            )
            current_commit_refs = merge_link_field(current_commit_refs, fresh_commit_refs)
            attempt_ulid = current_s3_meta.get("last_edited_ulid")
            if attempt_ulid == accumulation_ulid:
                current_references = merge_link_field(current_references, fresh_references)
            else:
                # A write landed between attempts and replaced references; rebase.
                current_references = fresh_references
                accumulation_ulid = attempt_ulid

            # Strip the reserved "ETag" sentinel key (added by head_object for the CAS
            # token) before reusing this dict as the literal metadata for put_object —
            # it is not a real user-defined metadata field and must never be written as
            # one (which would also corrupt future ETag-capture calls).
            updated_s3_meta = {k: v for k, v in current_s3_meta.items() if k != "ETag"}
            updated_s3_meta["status"] = ArtifactStatus.INACTIVE

            current_step = _STEP_CONTENT_FETCH
            content = await asyncio.to_thread(s3.get_object, artifact_id)

            current_step = _STEP_STATUS_REPUT
            try:
                new_etag = await asyncio.to_thread(
                    s3.put_object, artifact_id, content, updated_s3_meta, if_match=current_etag
                )
            except ArtifactConflictError:
                # Someone else changed the object since we read its ETag — retry the
                # whole cycle (re-read, re-merge, re-write).
                continue
            last_attempt_object_written = True
            object_written = True

            current_step = _STEP_ANNOTATION_WRITE
            try:
                # Annotations are the sole durable store for commit_refs/references, so
                # a failed re-apply is a partial archive (status flipped, link fields
                # lost to the re-PUT), never a success: the guard below records a
                # failure-log entry for reconcile_index and surfaces a structured error.
                await asyncio.to_thread(
                    apply_link_annotations,
                    s3,
                    artifact_id,
                    commit_refs=current_commit_refs,
                    references=current_references,
                    if_match=new_etag,
                )
            except ArtifactConflictError:
                # Someone changed the object between our put_object and this annotation
                # write — retry the whole cycle, including a fresh status re-PUT.
                continue
            else:
                break
        else:
            # Retries exhausted — never a raw exception, never a silent partial archive.
            # If the status flip was durably written on the final attempt (only the
            # trailing annotation apply kept conflicting), record a failure-log entry so
            # reconcile_index can repair the link-field state later; a persistent
            # conflict on the status re-PUT itself never wrote anything durable, so no
            # entry is produced in that case.
            if last_attempt_object_written:
                _record_partial_archive_failure(
                    settings,
                    artifact_id=artifact_id,
                    s3_meta=updated_s3_meta,
                    failure_step=_STEP_ANNOTATION_WRITE,
                    reason=(
                        "Compare-and-swap retries exhausted while re-applying "
                        "commit_refs/references annotations after a durable status flip."
                    ),
                    commit_refs=current_commit_refs,
                    references=current_references,
                )
            return _conflict_response()

        # ── Steps 5–6: Flip all vector statuses ───────────────────────────────
        # Vector writes stay unconditional (no S3 Vectors CAS surface exists; ADR-011
        # decision 6) — vector metadata is the recoverable/derived copy. The S3
        # status flip above has already succeeded — any failure from this point on is a
        # *partial archive* (S3 inactive, vectors not yet fully flipped) and must leave
        # a repairable failure-log trace, credential error or otherwise, so
        # reconcile_index can find and repair it and a retried archive_artifact call is
        # not blocked by the Step 2b idempotency check.
        current_step = _STEP_VECTOR_FLIP
        vec_items = await asyncio.to_thread(
            fetch_vectors_by_metadata,
            vectors,
            {"artifact_id": {"$eq": artifact_id}},
            include_data=True,
        )
        for item in vec_items:
            key = item["key"]
            vector_data: list[float] = item["data"]["float32"]
            updated_meta: dict[str, Any] = {
                **item["metadata"],
                "status": ArtifactStatus.INACTIVE,
            }
            await asyncio.to_thread(vectors.put_vector, key, vector_data, updated_meta)
    except CredentialError as exc:
        _record_if_durable(exc)
        return credential_error_response(exc)
    except AnnotationUnavailableError as exc:
        # Diagnosable, so it takes its own code rather than internal_error: startup
        # check 8 proves annotations work before the server accepts a request, so at
        # runtime this can only be post-setup IAM drift, which has a known remedy.
        _record_if_durable(exc)
        return {"error": ErrorCode.ANNOTATION_UNAVAILABLE, "message": str(exc)}
    except Exception as exc:
        # A genuinely unknown failure is re-raised after recording — the catch-all
        # still logs the traceback and returns internal_error, but the repairable
        # trace now exists.
        _record_if_durable(exc)
        raise

    logger.info("Artifact archived: key=%s", artifact_id)
    result: dict[str, Any] = {"artifact_id": artifact_id, "status": ArtifactStatus.INACTIVE}
    if referrers:
        result["referrers"] = referrers
        result["warning_message"] = (
            f"'{artifact_id}' was archived, but it is referenced by {len(referrers)} other "
            f"artifact(s): {', '.join(referrers)}. Archiving is reversible, so those references "
            "remain valid unless this artifact is later permanently deleted."
        )
    return result
