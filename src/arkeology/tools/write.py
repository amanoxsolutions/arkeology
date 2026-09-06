"""arkeology.tools.write — write_artifact MCP tool implementation.

Stores an artifact to S3 and indexes its section vectors in S3 Vectors using
Bedrock embeddings. When an artifact already exists (any tier), orphaned section
vectors from the previous write are cleaned up automatically.
"""

import asyncio
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import botocore.exceptions
from pydantic import ValidationError
from ulid import ULID

from arkeology.annotations import (
    CAS_MAX_ATTEMPTS,
    apply_link_annotations,
    merge_link_field,
    read_link_annotations,
)
from arkeology.artifact import (
    Artifact,
    cap_commit_refs_for_vectors,
    check_metadata_budgets,
    encode_metadata_value,
    generate_artifact_id,
)
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ErrorCode
from arkeology.errors import (
    AnnotationUnavailableError,
    ArtifactCollisionError,
    ArtifactConflictError,
    CredentialError,
    MetadataTooLargeError,
)
from arkeology.failure_log import append_failure_entry, build_failure_entry
from arkeology.tools._errors import credential_error_response
from arkeology.tools._section_pipeline import (
    build_document_embedding_text,
    disambiguate_section_slugs,
    prepare_sections_for_embedding,
)

logger = logging.getLogger(__name__)

# The steps an overwriting write can fail at once its put_object is durable. Every one of
# them leaves the same repairable state — the content replaced, the object's annotations
# cleared by that put_object, and the vectors still on the previous version — so they
# differ only in what they tell an operator reading the log, which is reason enough not
# to stamp them all as the annotation write.
_STEP_CAS_REREAD = "write_cas_reread"
_STEP_ANNOTATION_READ = "annotation_read"
_STEP_BUDGET_RECHECK = "write_budget_recheck"
_STEP_CONTENT_PUT = "write_content_put"
_STEP_ANNOTATION_WRITE = "annotation_write"

# T67 — Step 8 delete_vectors bounded inline retry, mirroring bedrock.py's _invoke shape
# exactly: exactly one retry (2 total attempts), fixed sleep + jitter, retrying only the
# documented S3 Vectors DeleteVectors transient error codes.
_ORPHAN_DELETE_RETRY_ATTEMPTS = 2
_ORPHAN_DELETE_RETRY_SLEEP_SECONDS: float = 2.0
_ORPHAN_DELETE_TRANSIENT_ERROR_CODES = frozenset(
    {"RequestTimeoutException", "ServiceUnavailableException", "TooManyRequestsException"}
)

# Dedicated thread pool for Bedrock embed calls.  The default asyncio executor
# is sized at min(32, cpu_count + 4) — typically 8–16 threads — which can
# serialise embed calls below the configured SECTION_CONCURRENCY when multiple
# artifacts are written concurrently via write_artifacts.
#
# Sizing: artifact_concurrency_max (15, see _concurrency._ARTIFACT_CONCURRENCY_MAX)
# × EMBED_MAX_SECTIONS default (20) = 300.  All embed calls in this module use
# run_in_executor(_EMBED_EXECUTOR, ...) rather than asyncio.to_thread() so the
# pool is not shared with other blocking work on the default executor.
#
# Constructed lazily (module __getattr__ below) rather than at import time —
# importing this module must not itself spin up 300 OS threads.
_embed_executor: ThreadPoolExecutor | None = None


def _get_embed_executor() -> ThreadPoolExecutor:
    global _embed_executor
    if _embed_executor is None:
        _embed_executor = ThreadPoolExecutor(
            max_workers=300,  # 15 artifacts × 20 sections
            thread_name_prefix="arkeology-embed",
        )
    return _embed_executor


def __getattr__(name: str) -> Any:
    """Lazily materialise ``_EMBED_EXECUTOR`` on first external attribute access
    (e.g. ``write.py`` internals and tests referencing ``write_module._EMBED_EXECUTOR``)
    without constructing it merely from importing this module (PEP 562)."""
    if name == "_EMBED_EXECUTOR":
        return _get_embed_executor()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _log_partial_write_failure(
    settings: Settings,
    *,
    artifact_id: str,
    title: str,
    artifact_type: str,
    tier: int,
    date: str,
    failure_step: str,
    reason: str,
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
    last_edited_ulid: str | None = None,
    orphan_keys: list[str] | None = None,
) -> None:
    """Append a failure-log entry recording a partial write (S3 succeeded, a
    downstream step failed).

    Shared by the ``partial_write`` response path (:func:`_record_partial_write`)
    and the credential-error branches that occur after the S3 put has already
    succeeded: a credential failure is no less a partial write than any other kind
    of failure — the S3 object is durably written but the index does not yet
    reflect it (or, for an ``overwrite=True`` rewrite, still reflects the
    pre-overwrite version) — and only a failure-log entry lets ``reconcile_index``
    find and repair it. Skip the log on the credential branches and a credential
    failure after S3 success leaves no trace, so the stale or missing index state
    is never picked up by reconciliation.

    Args:
        settings: Server configuration (for ``failure_log_path``).
        artifact_id: S3 key of the partially written artifact.
        title: Artifact title.
        artifact_type: Artifact type string.
        tier: Artifact tier.
        date: ISO-8601 date string.
        failure_step: Stage that failed (e.g. ``"bedrock_embed"``, ``"put_vector"``,
            ``"annotation_write"``, ``"orphan_vector_cleanup"``).
        reason: Human-readable failure reason.
        commit_refs: The link-field value the failed annotation write was applying —
            passed on the ``annotation_write`` branches, where the preceding
            ``put_object`` has already cleared the object's annotations and the entry
            becomes the only source ``reconcile_index`` can restore from. Omitted from
            the entry when empty; see :func:`~arkeology.failure_log.build_failure_entry`.
        references: As ``commit_refs``. Note this is the value this write was applying
            (``references`` has replace semantics), not a read-forward of the prior one.
        last_edited_ulid: The ULID this write generated, passed on the same
            ``annotation_write`` branches. ``reconcile_index`` compares it against the
            artifact's current one to decide whether a later write has since superseded
            the entry's ``references``; without it the replay unions unconditionally.
        orphan_keys: When Step 8's ``delete_vectors`` retry is exhausted, the exact list
            of stale vector keys that still need deleting. See
            :func:`~arkeology.failure_log.build_failure_entry` for how it is used.
    """
    append_failure_entry(
        settings.failure_log_path,
        build_failure_entry(
            artifact_id=artifact_id,
            title=title,
            artifact_type=artifact_type,
            tier=tier,
            date=date,
            failure_step=failure_step,
            reason=reason,
            commit_refs=commit_refs,
            references=references,
            last_edited_ulid=last_edited_ulid,
            orphan_keys=orphan_keys,
        ),
    )


def _record_partial_write(
    settings: Settings,
    *,
    artifact_id: str,
    title: str,
    artifact_type: str,
    tier: int,
    date: str,
    failure_step: str,
    reason: str,
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
    last_edited_ulid: str | None = None,
) -> dict[str, Any]:
    """Append a failure-log entry and build the standard ``partial_write`` response.

    Centralises the failure-log-and-return shape used after S3 has been written
    durably but a vector embed/index step failed. The S3 object remains; the
    failure is recorded so ``reconcile_index`` can repair the index later.

    Args:
        settings: Server configuration (for ``failure_log_path``).
        artifact_id: S3 key of the partially written artifact.
        title: Artifact title.
        artifact_type: Artifact type string.
        tier: Artifact tier.
        date: ISO-8601 date string.
        failure_step: Stage that failed (e.g. ``"bedrock_embed"``, ``"put_vector"``).
        reason: Human-readable failure reason.
        commit_refs: Forwarded to :func:`_log_partial_write_failure`.
        references: Forwarded to :func:`_log_partial_write_failure`.
        last_edited_ulid: Forwarded to :func:`_log_partial_write_failure`.

    Returns:
        The ``partial_write`` error response dict (includes ``artifact_id``).
    """
    _log_partial_write_failure(
        settings,
        artifact_id=artifact_id,
        title=title,
        artifact_type=artifact_type,
        tier=tier,
        date=date,
        failure_step=failure_step,
        reason=reason,
        commit_refs=commit_refs,
        references=references,
        last_edited_ulid=last_edited_ulid,
    )
    return {
        "error": ErrorCode.PARTIAL_WRITE,
        "message": f"{reason} — failure recorded in {settings.failure_log_path}",
        "artifact_id": artifact_id,
    }


def _record_partial_write_credential_error(
    settings: Settings,
    *,
    artifact_id: str,
    title: str,
    artifact_type: str,
    tier: int,
    date: str,
    failure_step: str,
    exc: CredentialError,
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
) -> dict[str, Any]:
    """Append a failure-log entry and build the standard ``credential_error`` response
    for a ``CredentialError`` raised after S3 has already been written durably.

    Mirrors :func:`_record_partial_write` exactly, but for the credential-error case
    (which returns ``ErrorCode.CREDENTIAL_ERROR``, not ``ErrorCode.PARTIAL_WRITE`` —
    the CredentialError branches intentionally surface the credential failure itself
    to the caller rather than the generic partial-write message, even though both
    cases equally require a failure-log entry for ``reconcile_index`` to repair later).

    Args:
        settings: Server configuration (for ``failure_log_path``).
        artifact_id: S3 key of the partially written artifact.
        title: Artifact title.
        artifact_type: Artifact type string.
        tier: Artifact tier.
        date: ISO-8601 date string.
        failure_step: Stage that failed (e.g. ``"bedrock_embed"``, ``"put_vector"``,
            ``"annotation_write"``).
        exc: The ``CredentialError`` that was raised.
        commit_refs: Forwarded to :func:`_log_partial_write_failure`.
        references: Forwarded to :func:`_log_partial_write_failure`.

    Returns:
        The ``credential_error`` response dict (includes ``artifact_id``).
    """
    _log_partial_write_failure(
        settings,
        artifact_id=artifact_id,
        title=title,
        artifact_type=artifact_type,
        tier=tier,
        date=date,
        failure_step=failure_step,
        reason=str(exc),
        commit_refs=commit_refs,
        references=references,
    )
    return {
        "error": ErrorCode.CREDENTIAL_ERROR,
        "message": str(exc),
        "artifact_id": artifact_id,
    }


def _record_durable_write_failure(
    settings: Settings,
    *,
    artifact_id: str,
    title: str,
    artifact_type: str,
    tier: int,
    date: str,
    failure_step: str,
    exc: Exception,
    commit_refs: list[str],
    references: list[str],
    last_edited_ulid: str,
) -> dict[str, Any]:
    """Append the failure-log entry for a failure raised once the S3 object is already
    durable, and build its structured response.

    The entry is unconditional: the preceding ``put_object`` has cleared the object's
    annotations, so this entry is the only surviving source of the link fields the
    failed write was applying — whatever the failure's cause.

    The code, in contrast, names that cause where one is separately diagnosable — a
    credential expiry, an unavailable annotation store — and falls back to
    ``partial_write``, which names the residual state, where none is. Which of the
    three comes back never changes the durability facts.

    Args:
        settings: Server configuration (for ``failure_log_path``).
        artifact_id: S3 key of the artifact whose object is already durable.
        title: Artifact title.
        artifact_type: Artifact type string.
        tier: Artifact tier.
        date: ISO-8601 date string.
        failure_step: The step that actually failed, one of ``_STEP_*``. Nothing branches
            on it — it is operator diagnostics — so it is stamped per call site rather
            than fixed at the annotation write, which is only one of the several steps
            that reach here. A budget breach stamped ``annotation_write`` sends whoever
            reads the log after the oversize value's IAM permissions instead of after
            the oversize value.
        exc: The failure. Its type selects the error code; its text is the reason.
        commit_refs: The link-field value the failed write was applying.
        references: As ``commit_refs``.
        last_edited_ulid: The ULID this write generated, the supersession token
            ``reconcile_index`` decides the ``references`` restore on.

    Returns:
        The structured error response dict (includes ``artifact_id``).
    """
    _log_partial_write_failure(
        settings,
        artifact_id=artifact_id,
        title=title,
        artifact_type=artifact_type,
        tier=tier,
        date=date,
        failure_step=failure_step,
        reason=str(exc),
        commit_refs=commit_refs,
        references=references,
        last_edited_ulid=last_edited_ulid,
    )
    if isinstance(exc, CredentialError):
        return {
            "error": ErrorCode.CREDENTIAL_ERROR,
            "message": str(exc),
            "artifact_id": artifact_id,
        }
    if isinstance(exc, AnnotationUnavailableError):
        return {
            "error": ErrorCode.ANNOTATION_UNAVAILABLE,
            "message": str(exc),
            "artifact_id": artifact_id,
        }
    return {
        "error": ErrorCode.PARTIAL_WRITE,
        "message": f"{exc} — failure recorded in {settings.failure_log_path}",
        "artifact_id": artifact_id,
    }


def _delete_orphan_vectors_with_retry(
    vectors: VectorsClientInterface, orphan_keys: list[str]
) -> Exception | None:
    """Delete stale orphan vectors with one bounded retry on a transient failure.

    Mirrors ``bedrock.py``'s ``_invoke`` retry shape exactly: exactly one retry (2
    total attempts), sleeping ``_ORPHAN_DELETE_RETRY_SLEEP_SECONDS +
    random.uniform(0, 1)`` seconds between attempts, retrying only a
    ``ClientError`` whose code is in ``_ORPHAN_DELETE_TRANSIENT_ERROR_CODES``.
    ``CredentialError`` (already translated from a ``ClientError`` by
    ``VectorsClientImpl.delete_vectors``'s own ``wrap_credential_errors`` wrapper
    before it ever reaches this function) and any other exception are never
    retried.

    Synchronous and blocking (including its sleep) by design — the caller runs it
    via ``asyncio.to_thread`` so the retry never blocks the event loop.

    Returns:
        ``None`` on success. The final exception (never raised) if every attempt
        failed, so the async caller can log it without an extra try/except layer.
    """
    last_exc: Exception | None = None
    for attempt in range(_ORPHAN_DELETE_RETRY_ATTEMPTS):
        try:
            vectors.delete_vectors(orphan_keys)
        except CredentialError as exc:
            return exc
        except botocore.exceptions.ClientError as exc:
            last_exc = exc
            code = exc.response.get("Error", {}).get("Code", "")
            if code in _ORPHAN_DELETE_TRANSIENT_ERROR_CODES and attempt == 0:
                logger.warning(
                    "Orphan vector delete transient error %s on attempt 1; retrying after %.1fs",
                    code,
                    _ORPHAN_DELETE_RETRY_SLEEP_SECONDS,
                )
                time.sleep(_ORPHAN_DELETE_RETRY_SLEEP_SECONDS + random.uniform(0, 1))
                continue
            return exc
        except Exception as exc:  # noqa: BLE001 - returned, not swallowed
            return exc
        else:
            return None
    return last_exc


async def write_artifact(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    type: str,  # noqa: A002
    team: str,
    project: str,
    tier: int,
    date: str,
    title: str,
    description: str,
    content: str,
    visibility: str,
    tags: list[str] | None = None,
    author_role: str | None = None,
    source_artifacts: list[str] | None = None,
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
    status: str = "active",
    file_extension: str = ".md",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Store an artifact to S3 and index its sections in S3 Vectors.

    Args:
        settings: Server configuration (used for prefixes and model IDs).
        s3: S3 client for content storage.
        vectors: S3 Vectors client for semantic index.
        bedrock: Bedrock client for embedding generation.
        type: Artifact type (must be in ARTIFACT_TYPES).
        team: Owning team identifier.
        project: Project identifier.
        tier: 2 (session) or 3 (persistent).
        date: ISO-8601 date string.
        title: Human-readable artifact title.
        description: Short summary (max 280 chars).
        content: Full Markdown content.
        visibility: ``"shared"`` or ``"hidden"``.
        tags: Optional list of tag strings.
        author_role: Optional author role.
        source_artifacts: Optional list of source artifact IDs.
        commit_refs: Optional list of git commit SHAs to pre-link this artifact.
            Stored as ``list[str]`` in vector metadata and as a comma-joined S3
            object annotation (ADR-011) — never in S3 user-defined object metadata.
        references: Optional list of resolved artifact IDs this artifact points at
            (ADR-012 D2). Each element is a full operative ``artifact_id`` — scope prefix
            and file extension included, exactly as this tool returns it — with the
            ``arkeology://`` scheme and any repository path text stripped, but NOT the
            scope prefix. Stored only as a comma-joined S3 object annotation (ADR-011):
            never in S3 user-defined object metadata, and, as of T58, never in S3 Vectors
            metadata under any code path.
        status: ``"active"`` (default) or ``"inactive"``.
        file_extension: File extension for the S3 key, including the leading dot
            (e.g. ``".md"``, ``".txt"``). Defaults to ``".md"``. Must start with
            ``"."``.
        overwrite: If ``False`` (default) and the generated key already exists,
            the write is rejected with a ``validation_error`` and the existing
            artifact/vectors are left untouched. Set ``True`` to intentionally
            replace an existing artifact in place (tier 3 living-doc updates,
            corrections). Never implied — collisions are always explicit. The
            guard is enforced atomically: the S3 write itself is a conditional
            create (``IfNoneMatch``) when ``overwrite=False``, so two concurrent
            same-key writes cannot both succeed — a preceding existence check is
            only a friendly fast path, not the authoritative guard.

    Returns:
        On success: ``{"artifact_id": str, "sections_indexed": int, "last_edited_ulid": str}``
        On error: ``{"error": str, "message": str}``
    """
    normalized_tags: list[str] = tags if tags is not None else []
    sources: list[str] = source_artifacts if source_artifacts is not None else []
    refs: list[str] = commit_refs if commit_refs is not None else []
    refs2: list[str] = references if references is not None else []

    try:
        return await _write_artifact_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            type=type,
            team=team,
            project=project,
            tier=tier,
            date=date,
            title=title,
            description=description,
            content=content,
            visibility=visibility,
            tags=normalized_tags,
            author_role=author_role,
            sources=sources,
            refs=refs,
            references=refs2,
            status=status,
            file_extension=file_extension,
            overwrite=overwrite,
        )
    except Exception as exc:
        logger.exception("Unexpected error in write_artifact")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _write_artifact_inner(  # noqa: PLR0913
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    type: str,  # noqa: A002
    team: str,
    project: str,
    tier: int,
    date: str,
    title: str,
    description: str,
    content: str,
    visibility: str,
    tags: list[str],
    author_role: str | None,
    sources: list[str],
    refs: list[str],
    references: list[str],
    status: str,
    file_extension: str = ".md",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Inner implementation of write_artifact (separated to enable top-level catch-all).

    Note: partial-write error responses (after S3 success, before full vector indexing)
    include ``artifact_id`` alongside ``error`` and ``message`` so callers can identify
    which artifact was partially written and take remedial action.
    """
    # Validate here (not only in the public wrapper) so the bulk write_artifacts path,
    # which calls this inner directly, enforces the same guard and cannot produce a
    # malformed S3 key (e.g. ``...-titletxt``).
    if not file_extension.startswith("."):
        return {
            "error": ErrorCode.VALIDATION_ERROR,
            "message": "file_extension must start with '.'",
        }

    try:
        artifact = Artifact(
            type=type,
            team=team,
            project=project,
            tier=tier,
            date=date,
            status=status,
            title=title,
            description=description,
            content=content,
            visibility=visibility,
            tags=tags,
            author_role=author_role,
            source_artifacts=sources,
            commit_refs=refs,
            references=references,
        )
    except ValidationError as exc:
        return {"error": ErrorCode.VALIDATION_ERROR, "message": str(exc)}

    # ── Step 2: Derive identifiers ────────────────────────────────────────────
    artifact_id = generate_artifact_id(tier=tier, type=type, date=date, title=title)
    s3_key = f"{settings.write_prefix}/{artifact_id}{file_extension}"
    last_edited_ulid = str(ULID())

    # ── Step 3: Build S3 metadata (string-only) ───────────────────────────────
    s3_metadata: dict[str, str] = {
        "type": artifact.type,
        "team": artifact.team,
        "project": artifact.project,
        "tier": str(artifact.tier),
        "date": artifact.date,
        "status": artifact.status,
        "title": artifact.title,
        "visibility": artifact.visibility,
        "tags": ",".join(tags),
        "author_role": author_role or "",
        "description": description,
        "source_artifacts": ",".join(sources),
        "last_edited_ulid": last_edited_ulid,
    }

    # ── Step 3b: Build vector metadata (types match filter requirements) ─────
    # Built here — before the collision check and any write — so the T55 budget check
    # below can validate the actual representations about to be written before any
    # head_object/put_object/put_vectors_batch call.
    vector_metadata: dict[str, Any] = {
        "artifact_id": s3_key,
        "scope": settings.write_prefix,
        "type": artifact.type,
        "team": artifact.team,
        "project": artifact.project,
        "tier": artifact.tier,  # stored as int for filter compatibility
        "date": artifact.date,
        "status": artifact.status,
        "title": artifact.title,
        "visibility": artifact.visibility,
        "author_role": author_role or "",
        "description": description,
        "last_edited_ulid": last_edited_ulid,
    }
    # S3 Vectors rejects empty arrays in metadata — omit list fields when empty.
    # Non-empty lists are stored as list[str] so $eq filters can match individual elements.
    #
    # commit_refs is capped to the most-recently-appended
    # COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES entries for the vector-metadata copy only
    # (T58) — the S3 annotation write below always carries the complete, uncapped list.
    #
    # references is never written to vector metadata (T58) — the S3 annotation copy
    # (apply_link_annotations below) is its sole durable store and sole read surface.
    if tags:
        vector_metadata["tags"] = tags
    if sources:
        vector_metadata["source_artifacts"] = sources
    if refs:
        vector_metadata["commit_refs"] = cap_commit_refs_for_vectors(refs)

    # ── Step 3c: Metadata size budgets — fail fast, before any write ─────────
    # Measures the actual assembled representations: the S3 aggregate against the
    # transport-encoded s3_metadata dict, and the vector filterable/total budgets against
    # vector_metadata. A breach here means NO head_object, NO put_object, NO
    # put_vectors_batch, and NO failure-log append — an oversize write must never produce
    # a partial write that reconcile_index replays forever.
    encoded_s3_metadata = {key: encode_metadata_value(value) for key, value in s3_metadata.items()}
    try:
        check_metadata_budgets(encoded_s3_metadata, vector_metadata)
    except MetadataTooLargeError as exc:
        return {"error": ErrorCode.VALIDATION_ERROR, "message": str(exc)}

    # ── Step 4: Check existing before writing (collision guard + orphan detection) ──
    # A write whose generated key already exists is rejected by default — silent
    # overwrite-by-collision is the worst failure mode for a store whose purpose is
    # never losing memory. The caller must pass overwrite=True to intentionally
    # replace an existing artifact (tier 3 living-doc updates, corrections).
    #
    # head_object here is a *friendly fast path* only — check-then-act is racy
    # (two concurrent same-key writes can both pass this check). The authoritative,
    # atomic guard is the conditional put_object(if_none_match=True) below, which
    # closes the race by making the existence check and the write a single S3-side
    # atomic operation.
    def _collision_response() -> dict[str, Any]:
        return {
            "error": ErrorCode.VALIDATION_ERROR,
            "message": (
                f"An artifact already exists at key '{s3_key}'. The write was rejected "
                "to avoid a silent overwrite-by-collision. Pass overwrite=True to "
                "intentionally replace this artifact in place."
            ),
            "artifact_id": s3_key,
        }

    def _conflict_response() -> dict[str, Any]:
        return {
            "error": ErrorCode.CONFLICT,
            "message": (
                f"Could not write '{s3_key}': a concurrent writer changed the artifact "
                f"{CAS_MAX_ATTEMPTS} times in a row while this write attempted its "
                "compare-and-swap retry cycle. Retry the write."
            ),
            "artifact_id": s3_key,
        }

    is_existing = False
    initial_etag: str | None = None
    try:
        head_meta = await asyncio.to_thread(s3.head_object, s3_key)
        is_existing = True
        initial_etag = head_meta.get("ETag")
    except KeyError:
        pass
    except CredentialError as exc:
        return credential_error_response(exc)

    if is_existing and not overwrite:
        return _collision_response()

    # ── Step 4a/4b: Read-forward + merge commit_refs; replace references (ADR-011 decision 4);
    # optimistic-concurrency compare-and-swap around both writes (ADR-011 decision 6) ──
    #
    # PutObject clears S3 annotations, so an in-place re-PUT (a tier-3 living-document
    # update, or an explicit tier-2 replacement) would otherwise silently lose the
    # accumulated commit_refs trail. commit_refs is a durable, backfill-only audit trail
    # with no frontmatter counterpart: read its current value forward from the durable
    # annotations, its sole source of truth (see ``annotations.read_link_annotations``),
    # and merge it with the value supplied to this write (union, dedup, order-preserving)
    # before either store is touched.
    #
    # references mirrors the artifact's frontmatter ``references:`` list — a claim about
    # the artifact's *current* outbound links, not an audit trail. It is REPLACED
    # outright on every write: final_references is exactly the value supplied to this
    # call (including ``[]``), with no read-forward and no merge against the prior stored
    # value — a write supplying no references clears the field (operator-confirmed
    # intended). vector_metadata's
    # "references" key was already set/omitted from the supplied value at Step 3b, and
    # ``apply_link_annotations`` already deletes the annotation when its input list is
    # empty, so no further adjustment to either store is needed here for this field.
    #
    # An overwriting write on an existing artifact races the object-body writers on the
    # same artifact, so it is guarded by a bounded ETag compare-and-swap retry (ADR-011
    # decision 6). The object ETag serialises annotation writers against object-body
    # writers only; annotation-only writers to the same field are not serialised against
    # each other — the accepted residual stated in that decision. The object's ETag is
    # captured on read (above, from the head_object already performed for the existence
    # check) and the subsequent put_object is conditional (if_match=ETag0); the object's
    # *new* ETag (ETag1, from that put_object's response) is used as if_match on the
    # apply_link_annotations call that follows. On ArtifactConflictError from either
    # call: re-read (fresh ETag, fresh link-field state) and retry the WHOLE cycle,
    # re-merging the caller's *original* supplied refs/references (never a previous
    # attempt's already-merged output, to avoid compounding) — for CAS_MAX_ATTEMPTS
    # attempts, after which a structured error is returned: conflict while nothing is
    # durable, partial_write once the final attempt's put_object has landed. A fresh write
    # (is_existing is False) has nothing to race against and is unaffected — its
    # if_none_match="*" guard addresses a different race (the create-collision guard).
    final_commit_refs = refs
    final_references = references

    if is_existing and overwrite:
        current_etag = initial_etag
        last_attempt_object_written = False
        # Distinct from last_attempt_object_written, which is reset per attempt: this one
        # is never reset. Reaching a retry attempt at all means an earlier attempt's
        # put_object already wrote the content durably and cleared the object's
        # annotations, so any failure from that point on — on the re-read, the
        # annotation read, or the re-PUT — leaves the same repairable partial state as a
        # failure on the annotation write itself, not a clean no-op failure.
        object_written = False
        # Reassigned as the guarded region advances, so _cas_failure_response can stamp
        # the entry with the step that actually raised rather than with the annotation
        # write the region happens to end at. Every attempt starts at the read-forward.
        current_step = _STEP_ANNOTATION_READ

        def _cas_failure_response(exc: Exception) -> dict[str, Any]:
            """Response for a CAS-loop failure, keyed on whether content is durable.

            Reaching a retry at all means an earlier attempt's put_object already
            replaced the content and cleared the object's annotations, so every failure
            from that point on leaves the same repairable partial write — a SlowDown on
            the re-read, a budget breach on the re-merge, and a credential expiry
            alike. Recording only the credential case let the others escape to the
            catch-all with nothing logged, leaving S3 holding this write's content, the
            link fields gone, and the index still on the previous version: a state
            reconcile_index cannot see, because the artifact still has vectors and so
            the orphan scan skips it.

            While nothing is durable the failure is still the clean one it always was —
            a budget breach rejects with no write and no entry, and an unknown error
            stays an internal_error.
            """
            if object_written:
                return _record_durable_write_failure(
                    settings,
                    artifact_id=s3_key,
                    title=title,
                    artifact_type=type,
                    tier=tier,
                    date=date,
                    failure_step=current_step,
                    exc=exc,
                    commit_refs=final_commit_refs,
                    references=final_references,
                    last_edited_ulid=last_edited_ulid,
                )
            if isinstance(exc, MetadataTooLargeError):
                return {"error": ErrorCode.VALIDATION_ERROR, "message": str(exc)}
            if isinstance(exc, CredentialError):
                return {
                    "error": ErrorCode.CREDENTIAL_ERROR,
                    "message": str(exc),
                    "artifact_id": s3_key,
                }
            if isinstance(exc, AnnotationUnavailableError):
                return {
                    "error": ErrorCode.ANNOTATION_UNAVAILABLE,
                    "message": str(exc),
                    "artifact_id": s3_key,
                }
            raise exc

        # Accumulated across attempts rather than replaced. This attempt's own
        # put_object clears the object's annotations, so a retry after a failed
        # annotation apply reads them back as absent — re-reading into a fresh variable
        # would drop the commit_refs trail the first attempt had already read forward.
        carried_commit_refs: list[str] = []
        for attempt in range(CAS_MAX_ATTEMPTS):
            last_attempt_object_written = False
            if attempt > 0:
                current_step = _STEP_CAS_REREAD
                try:
                    head_meta_retry = await asyncio.to_thread(s3.head_object, s3_key)
                    current_etag = head_meta_retry.get("ETag")
                except KeyError:
                    # A concurrent caller deleted the object between attempts. There is
                    # nothing left to compare-and-swap against, and the vectors left
                    # behind are already reconcile_index's dangling-vector case, so say
                    # so plainly rather than letting the KeyError reach the catch-all.
                    return {
                        "error": ErrorCode.NOT_FOUND,
                        "message": (
                            f"Artifact '{s3_key}' was deleted by a concurrent caller "
                            "while this write was retrying its compare-and-swap cycle."
                        ),
                        "artifact_id": s3_key,
                    }
                except Exception as exc:
                    return _cas_failure_response(exc)

            current_step = _STEP_ANNOTATION_READ
            try:
                existing_commit_refs, _existing_references = await asyncio.to_thread(
                    read_link_annotations, s3, s3_key
                )
            except Exception as exc:
                return _cas_failure_response(exc)
            carried_commit_refs = merge_link_field(carried_commit_refs, existing_commit_refs)
            final_commit_refs = merge_link_field(carried_commit_refs, refs)

            if final_commit_refs:
                vector_metadata["commit_refs"] = cap_commit_refs_for_vectors(final_commit_refs)
            else:
                vector_metadata.pop("commit_refs", None)

            # Re-check budgets after the merge enlarges vector_metadata: Step 3c only
            # measured the *supplied* commit_refs. This read-forward merge can union it
            # with the value already indexed in vector metadata and push the vector
            # filterable/total budgets over their limits even though references and the
            # s3_metadata side are unaffected (commit_refs lives in annotations, not S3
            # user metadata, post-T47). Re-check here — before any put_object or
            # put_vectors_batch — rather than reintroducing the deterministic
            # partial-write / reconcile-replay loop T55 exists to prevent. On attempt 0
            # that rejection is the clean no-op the Step 3c guard is; on a retry the
            # previous attempt's put_object has already landed, so it is a durable
            # partial write and _cas_failure_response records it as one.
            current_step = _STEP_BUDGET_RECHECK
            try:
                check_metadata_budgets(encoded_s3_metadata, vector_metadata)
            except MetadataTooLargeError as exc:
                return _cas_failure_response(exc)

            current_step = _STEP_CONTENT_PUT
            try:
                new_etag = await asyncio.to_thread(
                    s3.put_object, s3_key, content, s3_metadata, if_match=current_etag
                )
            except ArtifactConflictError:
                # Someone else changed the object since we read its ETag — retry the
                # whole cycle (re-read, re-merge, re-write).
                continue
            except Exception as exc:
                return _cas_failure_response(exc)
            last_attempt_object_written = True
            object_written = True

            current_step = _STEP_ANNOTATION_WRITE
            try:
                await asyncio.to_thread(
                    apply_link_annotations,
                    s3,
                    s3_key,
                    commit_refs=final_commit_refs,
                    references=final_references,
                    if_match=new_etag,
                )
            except ArtifactConflictError:
                # Someone changed the object between our put_object and this annotation
                # write — retry the whole cycle, including a fresh put_object.
                continue
            except Exception as exc:
                # The S3 put above has already succeeded, so this is a partial write,
                # not a clean failure — whatever the cause. _cas_failure_response
                # records the entry that lets reconcile_index repair the link-field
                # state later and picks the code that names the cause.
                return _cas_failure_response(exc)
            else:
                break
        else:
            # Retries exhausted — never a raw exception, never a silent partial write.
            # If the object body was durably written on the final attempt (only the
            # trailing annotation apply kept conflicting), the content landed and that
            # put cleared the annotations: the same repairable state as any other
            # post-PUT failure, so it returns partial_write with the failure-log entry
            # reconcile_index replays. A persistent conflict on put_object itself never
            # wrote anything durable, so it returns conflict with no entry.
            if last_attempt_object_written:
                return _record_partial_write(
                    settings,
                    artifact_id=s3_key,
                    title=title,
                    artifact_type=type,
                    tier=tier,
                    date=date,
                    failure_step=_STEP_ANNOTATION_WRITE,
                    reason=(
                        "Compare-and-swap retries exhausted while re-applying "
                        "commit_refs/references annotations after a durable content "
                        "write."
                    ),
                    commit_refs=final_commit_refs,
                    references=final_references,
                    last_edited_ulid=last_edited_ulid,
                )
            return _conflict_response()
    else:
        # Fresh create (or overwrite=True on a not-yet-existing key) — nothing to race
        # against (ADR-011 decision 6): the create-collision guard below is the only
        # concurrency concern, and it is already atomic via if_none_match.
        try:
            new_etag = await asyncio.to_thread(
                s3.put_object, s3_key, content, s3_metadata, if_none_match=not overwrite
            )
        except ArtifactCollisionError:
            # The fast-path check above missed a concurrent writer that created the key
            # between the head_object call and this put_object call — the atomic
            # conditional put is what actually caught the collision.
            return _collision_response()
        except CredentialError as exc:
            return credential_error_response(exc)

        # ── Durable annotation write (ADR-011) ────────────────────────────────
        # Written after PutObject (annotations cannot be set during PutObject — they
        # are set only after upload) and before put_vectors_batch, so that if the
        # vector write fails below, the durable annotation side is already correct
        # and a later reconcile_index run rebuilds vectors from it (T48).
        # Metadata-only: never triggers a re-embed.
        #
        # Annotations are the sole durable store for commit_refs/references, so a
        # failed annotation write is never reported as a successful write: every
        # failure below records a failure-log entry (the repair path reconcile_index
        # replays) and returns a structured error naming the cause where one is
        # diagnosable. An annotation-unavailable failure is post-startup IAM drift —
        # the startup gate already rejects a deployment that never had annotations.
        _ = new_etag  # no CAS token needed — nothing preceded this write to race
        # This is a fresh create (atomic if_none_match put above), so the
        # key had zero prior annotations a moment ago. When neither field was supplied,
        # there is nothing to write and nothing to clear — skip the call entirely
        # rather than issuing two pointless delete_object_annotation round trips (and,
        # on a deployment whose annotation permissions have since drifted, a spurious
        # partial_write for a no-op).
        try:
            if final_commit_refs or final_references:
                await asyncio.to_thread(
                    apply_link_annotations,
                    s3,
                    s3_key,
                    commit_refs=final_commit_refs,
                    references=final_references,
                )
        except Exception as exc:
            # The S3 put above has already succeeded — this is a partial write, not a
            # clean failure, whatever the cause. Without a failure-log entry here the
            # failure leaves no repairable trace, and for an overwrite=True rewrite the
            # pre-overwrite vectors would silently survive forever (reconcile never
            # sees a reason to touch this artifact).
            return _record_durable_write_failure(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step=_STEP_ANNOTATION_WRITE,
                exc=exc,
                commit_refs=final_commit_refs,
                references=final_references,
                last_edited_ulid=last_edited_ulid,
            )

    # ── Step 5: Parse, filter, cap, and truncate sections (shared pipeline) ─────
    # Delegates to the same helper reconcile_index uses, so a section that write-time
    # drops (min-length), caps (max-sections), or truncates (max-section-length) is
    # dropped/capped/truncated identically on a later reconcile replay.
    prepared_sections = prepare_sections_for_embedding(
        content,
        title=title,
        artifact_type=type,
        tags=tags,
        settings=settings,
    )

    # ── Step 7: Embed and index ───────────────────────────────────────────────
    new_keys: set[str] = set()

    if prepared_sections:
        # Concurrent embedding with bounded semaphore
        semaphore = asyncio.Semaphore(settings.section_concurrency)

        section_slugs = disambiguate_section_slugs(prepared_sections)
        sections_to_embed: list[tuple[str, str]] = [
            (f"{s3_key}#{slug}", p.embed_text)
            for p, slug in zip(prepared_sections, section_slugs, strict=True)
        ]

        async def embed_section(vec_key: str, text: str) -> tuple[str, list[float]]:
            async with semaphore:
                embedding = await asyncio.get_running_loop().run_in_executor(
                    _get_embed_executor(),
                    bedrock.embed,
                    text,
                    settings.bedrock_embedding_model,
                    settings.bedrock_embedding_dimensions,
                )
                return vec_key, embedding

        results = await asyncio.gather(
            *[embed_section(k, t) for k, t in sections_to_embed],
            return_exceptions=True,
        )

        # Check results for errors before any vector writes
        first_cred_error: CredentialError | None = None
        first_other_error: BaseException | None = None
        for r in results:
            if isinstance(r, CredentialError):
                first_cred_error = r
                break
            if isinstance(r, BaseException):
                first_other_error = r

        if first_cred_error is not None:
            return _record_partial_write_credential_error(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="bedrock_embed",
                exc=first_cred_error,
            )

        if first_other_error is not None:
            return _record_partial_write(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="bedrock_embed",
                reason=str(first_other_error),
            )

        # All succeeded — batch put. Filter out any BaseException entries (already checked above).
        successful: list[tuple[str, list[float]]] = [
            r for r in results if not isinstance(r, BaseException)
        ]
        items = [
            {"key": vec_key, "vector": embedding, "metadata": vector_metadata}
            for vec_key, embedding in successful
        ]
        try:
            await asyncio.to_thread(vectors.put_vectors_batch, items)
        except CredentialError as exc:
            return _record_partial_write_credential_error(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="put_vector",
                exc=exc,
            )
        except Exception as exc:
            return _record_partial_write(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="put_vector",
                reason=str(exc),
            )

        new_keys = {vec_key for vec_key, _ in successful}
    else:
        embed_text = build_document_embedding_text(
            title=title,
            artifact_type=type,
            tags=tags,
            description=description,
        )
        try:
            doc_embedding = await asyncio.get_running_loop().run_in_executor(
                _get_embed_executor(),
                bedrock.embed,
                embed_text,
                settings.bedrock_embedding_model,
                settings.bedrock_embedding_dimensions,
            )
        except CredentialError as exc:
            return _record_partial_write_credential_error(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="bedrock_embed",
                exc=exc,
            )
        except Exception as exc:
            return _record_partial_write(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="bedrock_embed",
                reason=str(exc),
            )

        doc_item = [{"key": s3_key, "vector": doc_embedding, "metadata": vector_metadata}]
        try:
            await asyncio.to_thread(vectors.put_vectors_batch, doc_item)
        except CredentialError as exc:
            return _record_partial_write_credential_error(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="put_vector",
                exc=exc,
            )
        except Exception as exc:
            return _record_partial_write(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="put_vector",
                reason=str(exc),
            )

        new_keys.add(s3_key)

    # ── Step 8: Orphan cleanup for existing artifacts (any tier) ────────────
    # Best-effort: by this point the artifact is durably written to S3 and its new
    # section vectors are indexed and searchable. Deleting stale vectors from a previous
    # version is a tidy-up, not part of the write's success contract — a failure here
    # (credential or otherwise) must NOT invert the result to an error, which would make
    # callers (including the bulk write_artifacts path) treat a fully written artifact as
    # failed and leave the orphans uncollected. Log and proceed; reconcile_index can
    # collect any leftover orphan vectors later.
    if is_existing:
        try:
            existing_keys = await asyncio.to_thread(
                vectors.list_vectors_by_metadata, {"artifact_id": {"$eq": s3_key}}
            )
            orphan_keys = [k for k in existing_keys if k not in new_keys]
            if orphan_keys:
                # T67: bounded inline retry (mirrors bedrock.py's _invoke shape), routed
                # through asyncio.to_thread since it may block on a retry sleep and this
                # call runs directly on the event loop.
                delete_failure = await asyncio.to_thread(
                    _delete_orphan_vectors_with_retry, vectors, orphan_keys
                )
                if delete_failure is not None:
                    _log_partial_write_failure(
                        settings,
                        artifact_id=s3_key,
                        title=title,
                        artifact_type=type,
                        tier=tier,
                        date=date,
                        failure_step="orphan_vector_cleanup",
                        reason=str(delete_failure),
                        orphan_keys=orphan_keys,
                    )
                    logger.warning(
                        "Orphan vector cleanup failed for key=%s; the artifact is written "
                        "and searchable but stale section vectors from a prior version "
                        "may remain (reconcile_index will repair them from the failure "
                        "log).",
                        s3_key,
                    )
        except Exception:
            logger.warning(
                "Orphan vector cleanup failed for key=%s; the artifact is written and "
                "searchable but stale section vectors from a prior version may remain "
                "(run reconcile_index to collect them).",
                s3_key,
                exc_info=True,
            )

    logger.info("Artifact written: key=%s sections=%d tier=%d", s3_key, len(new_keys), tier)
    result: dict[str, Any] = {
        "artifact_id": s3_key,
        "sections_indexed": len(new_keys),
        "last_edited_ulid": last_edited_ulid,
    }
    return result
