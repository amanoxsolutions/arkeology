"""cairn_mcp.tools.write — write_artifact MCP tool implementation.

Stores an artifact to S3 and indexes its section vectors in S3 Vectors using
Bedrock embeddings. When an artifact already exists (any tier), orphaned section
vectors from the previous write are cleaned up automatically.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from ulid import ULID

from cairn_mcp.annotations import apply_link_annotations, read_current_link_fields
from cairn_mcp.artifact import (
    Artifact,
    check_metadata_budgets,
    encode_metadata_value,
    generate_artifact_id,
    section_slug,
)
from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.constants import ErrorCode
from cairn_mcp.errors import (
    AnnotationUnavailableError,
    ArtifactCollisionError,
    CredentialError,
    MetadataTooLargeError,
)
from cairn_mcp.failure_log import append_failure_entry
from cairn_mcp.tools._section_pipeline import (
    build_document_embedding_text,
    prepare_sections_for_embedding,
)

logger = logging.getLogger(__name__)

# Dedicated thread pool for Bedrock embed calls.  The default asyncio executor
# is sized at min(32, cpu_count + 4) — typically 8–16 threads — which can
# serialise embed calls below the configured SECTION_CONCURRENCY when multiple
# artifacts are written concurrently via write_artifacts.
#
# Sizing: artifact_concurrency_max (15, see write_artifacts._ARTIFACT_CONCURRENCY_MAX)
# × EMBED_MAX_SECTIONS default (20) = 300.  All embed calls in this module use
# run_in_executor(_EMBED_EXECUTOR, ...) rather than asyncio.to_thread() so the
# pool is not shared with other blocking work on the default executor.
_EMBED_EXECUTOR: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=300,  # 15 artifacts × 20 sections
    thread_name_prefix="cairn-embed",
)


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
) -> None:
    """Append a failure-log entry recording a partial write (S3 succeeded, a
    downstream step failed).

    Shared by the ``partial_write`` response path (:func:`_record_partial_write`)
    and the credential-error branches that occur after the S3 put has already
    succeeded (Phase 12 review M-4): a credential failure is no less a partial
    write than any other kind of failure — the S3 object is durably written but
    the index does not yet reflect it (or, for an ``overwrite=True`` rewrite,
    still reflects the pre-overwrite version) — and only a failure-log entry lets
    ``reconcile_index`` find and repair it. Without this, a retried credential
    failure after S3 success left no trace, so the stale or missing index state
    was never picked up by reconciliation.

    Args:
        settings: Server configuration (for ``failure_log_path``).
        artifact_id: S3 key of the partially written artifact.
        title: Artifact title.
        artifact_type: Artifact type string.
        tier: Artifact tier.
        date: ISO-8601 date string.
        failure_step: Stage that failed (e.g. ``"bedrock_embed"``, ``"put_vector"``,
            ``"annotation_write"``).
        reason: Human-readable failure reason.
    """
    append_failure_entry(
        settings.failure_log_path,
        {
            "artifact_id": artifact_id,
            "title": title,
            "type": artifact_type,
            "tier": tier,
            "date": date,
            "failure_step": failure_step,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        },
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
    )
    return {
        "error": ErrorCode.PARTIAL_WRITE,
        "message": f"{reason} — failure recorded in {settings.failure_log_path}",
        "artifact_id": artifact_id,
    }


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
        references: Optional list of resolved bare artifact IDs this artifact points
            at (ADR-012 D2). Stored as ``list[str]`` in vector metadata and as a
            comma-joined S3 object annotation (ADR-011) — never in S3 user-defined
            object metadata.
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
    if tags:
        vector_metadata["tags"] = tags
    if sources:
        vector_metadata["source_artifacts"] = sources
    if refs:
        vector_metadata["commit_refs"] = refs
    if references:
        vector_metadata["references"] = references

    # ── Step 3c: Metadata size budgets (M-5) — fail fast, before any write ───
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
    # C-3: a write whose generated key already exists is rejected by default — silent
    # overwrite-by-collision is the worst failure mode for a store whose purpose is
    # never losing memory. The caller must pass overwrite=True to intentionally
    # replace an existing artifact (tier 3 living-doc updates, corrections).
    #
    # A-2: head_object here is a *friendly fast path* only — check-then-act is racy
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

    is_existing = False
    try:
        s3.head_object(s3_key)
        is_existing = True
    except KeyError:
        pass
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    if is_existing and not overwrite:
        return _collision_response()

    # ── Step 4a: Read-forward + merge link fields on an overwriting write (ADR-011 D4) ──
    # PutObject clears S3 annotations, so an in-place re-PUT (a tier-3 living-document
    # update, or an explicit tier-2 replacement) would otherwise silently lose the
    # accumulated commit_refs/references trail. Read the current values forward as the
    # union of both durable stores (Phase 12 review C5/M6 — neither the annotation copy
    # nor the vector-metadata copy is sole authority; see
    # ``annotations.read_current_link_fields``) and merge them with the values supplied
    # to this write (union, dedup, order-preserving) before either store is touched. A
    # fresh write (is_existing is False) or a rejected overwrite has nothing to merge.
    final_commit_refs = refs
    final_references = references
    if is_existing and overwrite:
        try:
            existing_commit_refs, existing_references = read_current_link_fields(
                s3, vectors, s3_key
            )
        except CredentialError as exc:
            return {
                "error": ErrorCode.CREDENTIAL_ERROR,
                "message": str(exc),
                "artifact_id": s3_key,
            }
        final_commit_refs = list(dict.fromkeys(existing_commit_refs + refs))
        final_references = list(dict.fromkeys(existing_references + references))

        if final_commit_refs:
            vector_metadata["commit_refs"] = final_commit_refs
        else:
            vector_metadata.pop("commit_refs", None)
        if final_references:
            vector_metadata["references"] = final_references
        else:
            vector_metadata.pop("references", None)

        # ── Step 4a (cont.): re-check budgets after the merge enlarges vector_metadata ──
        # Step 3c only measured the *supplied* commit_refs/references. The read-forward
        # merge above can union them with values already indexed in vector metadata and
        # push the vector filterable/total budgets over their limits even though the
        # s3_metadata side is unaffected (commit_refs/references live in annotations, not
        # S3 user metadata, post-T47). Re-check here — before any put_object or
        # put_vectors_batch — so a breach is rejected with NO write and NO failure-log
        # entry, matching the Step 3c guard exactly rather than reintroducing the
        # deterministic partial-write / reconcile-replay loop T55 exists to prevent.
        try:
            check_metadata_budgets(encoded_s3_metadata, vector_metadata)
        except MetadataTooLargeError as exc:
            return {"error": ErrorCode.VALIDATION_ERROR, "message": str(exc)}

    try:
        s3.put_object(s3_key, content, s3_metadata, if_none_match=not overwrite)
    except ArtifactCollisionError:
        # The fast-path check above missed a concurrent writer that created the key
        # between the head_object call and this put_object call — the atomic
        # conditional put is what actually caught the collision.
        return _collision_response()
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    # ── Step 4b: Durable annotation write (ADR-011) ──────────────────────────
    # Written after PutObject (annotations cannot be set during PutObject — they are
    # set only after upload) and before put_vectors_batch, so that if the vector write
    # fails below, the durable annotation side is already correct and a later
    # reconcile_index run rebuilds vectors from it (T48). Metadata-only: never
    # triggers a re-embed.
    #
    # T52 / ADR-011 decision 5: annotation availability is a feature-level concern,
    # not a hard failure. When annotations are unavailable (unsupported region/bucket
    # type) or access is denied, the content and vectors already written (or about to
    # be written below) must never be lost — record a warning and keep going, rather
    # than aborting like the CredentialError branch below (a real credential failure
    # is very likely to also break the upcoming Bedrock/vector calls, so aborting
    # there remains correct).
    annotation_warning: str | None = None
    try:
        apply_link_annotations(
            s3, s3_key, commit_refs=final_commit_refs, references=final_references
        )
    except AnnotationUnavailableError as exc:
        logger.warning(
            "Annotation write unavailable for key=%s; content and vectors will still "
            "be persisted without a durable commit_refs/references copy: %s",
            s3_key,
            exc,
        )
        annotation_warning = str(exc)
    except CredentialError as exc:
        # M-4: the S3 put above has already succeeded — this is a partial write,
        # not a clean failure. Without a failure-log entry here, a retried
        # credential failure after S3 success left no repairable trace, and for
        # an overwrite=True rewrite the pre-overwrite vectors would silently
        # survive forever (reconcile never sees a reason to touch this artifact).
        _log_partial_write_failure(
            settings,
            artifact_id=s3_key,
            title=title,
            artifact_type=type,
            tier=tier,
            date=date,
            failure_step="annotation_write",
            reason=str(exc),
        )
        return {
            "error": ErrorCode.CREDENTIAL_ERROR,
            "message": str(exc),
            "artifact_id": s3_key,
        }

    # ── Step 5: Parse, filter, cap, and truncate sections (M-3 shared pipeline) ──
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

        sections_to_embed: list[tuple[str, str]] = [
            (f"{s3_key}#{section_slug(p.heading)}", p.embed_text) for p in prepared_sections
        ]

        async def embed_section(vec_key: str, text: str) -> tuple[str, list[float]]:
            async with semaphore:
                embedding = await asyncio.get_running_loop().run_in_executor(
                    _EMBED_EXECUTOR,
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
            _log_partial_write_failure(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="bedrock_embed",
                reason=str(first_cred_error),
            )
            return {
                "error": ErrorCode.CREDENTIAL_ERROR,
                "message": str(first_cred_error),
                "artifact_id": s3_key,
            }

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
            vectors.put_vectors_batch(items)
        except CredentialError as exc:
            _log_partial_write_failure(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="put_vector",
                reason=str(exc),
            )
            return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc), "artifact_id": s3_key}
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
                _EMBED_EXECUTOR,
                bedrock.embed,
                embed_text,
                settings.bedrock_embedding_model,
                settings.bedrock_embedding_dimensions,
            )
        except CredentialError as exc:
            _log_partial_write_failure(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="bedrock_embed",
                reason=str(exc),
            )
            return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc), "artifact_id": s3_key}
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
            vectors.put_vectors_batch(doc_item)
        except CredentialError as exc:
            _log_partial_write_failure(
                settings,
                artifact_id=s3_key,
                title=title,
                artifact_type=type,
                tier=tier,
                date=date,
                failure_step="put_vector",
                reason=str(exc),
            )
            return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc), "artifact_id": s3_key}
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
            existing_keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": s3_key}})
            orphan_keys = [k for k in existing_keys if k not in new_keys]
            if orphan_keys:
                vectors.delete_vectors(orphan_keys)
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
    if annotation_warning is not None:
        result["warning"] = annotation_warning
    return result
