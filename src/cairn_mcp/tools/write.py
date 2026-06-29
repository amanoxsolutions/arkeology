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

from cairn_mcp.artifact import (
    Artifact,
    generate_artifact_id,
    parse_sections,
    section_slug,
)
from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.constants import ErrorCode
from cairn_mcp.errors import CredentialError
from cairn_mcp.failure_log import append_failure_entry

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


def _build_section_embedding_text(
    *,
    title: str,
    artifact_type: str,
    tags: list[str],
    section_heading: str,
    section_body: str,
) -> str:
    """Build the embedding input text for a single section vector.

    Format::

        Title: {title}
        Type: {type}
        Tags: {tag1}, {tag2}    ← omitted when tags is empty

        ## {section_heading}
        {section_body}

    Args:
        title: Artifact title.
        artifact_type: Artifact type string.
        tags: List of tag strings (may be empty).
        section_heading: Heading text of this section.
        section_body: Body text of this section.

    Returns:
        Formatted embedding input string.
    """
    lines = [f"Title: {title}", f"Type: {artifact_type}"]
    if tags:
        lines.append(f"Tags: {', '.join(tags)}")
    lines.append("")
    lines.append(f"## {section_heading}")
    lines.append(section_body)
    return "\n".join(lines)


def _build_document_embedding_text(
    *,
    title: str,
    artifact_type: str,
    tags: list[str],
    description: str,
) -> str:
    """Build the embedding input text for a document-level fallback vector.

    Format::

        Title: {title}
        Type: {type}
        Tags: {tag1}, {tag2}    ← omitted when tags is empty
        Description: {description}

    Args:
        title: Artifact title.
        artifact_type: Artifact type string.
        tags: List of tag strings (may be empty).
        description: Short artifact description.

    Returns:
        Formatted embedding input string.
    """
    lines = [f"Title: {title}", f"Type: {artifact_type}"]
    if tags:
        lines.append(f"Tags: {', '.join(tags)}")
    lines.append(f"Description: {description}")
    return "\n".join(lines)


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
    status: str = "active",
    file_extension: str = ".md",
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
        status: ``"active"`` (default) or ``"inactive"``.
        file_extension: File extension for the S3 key, including the leading dot
            (e.g. ``".md"``, ``".txt"``). Defaults to ``".md"``. Must start with
            ``"."``.

    Returns:
        On success: ``{"artifact_id": str, "sections_indexed": int, "last_edited_ulid": str}``
        On error: ``{"error": str, "message": str}``
    """
    normalized_tags: list[str] = tags if tags is not None else []
    sources: list[str] = source_artifacts if source_artifacts is not None else []
    refs: list[str] = commit_refs if commit_refs is not None else []

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
            status=status,
            file_extension=file_extension,
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
    status: str,
    file_extension: str = ".md",
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
        "commit_refs": ",".join(refs),
        "last_edited_ulid": last_edited_ulid,
    }

    # ── Step 4: Write to S3 (check existence first for orphan cleanup) ───────
    is_existing = False
    try:
        s3.head_object(s3_key)
        is_existing = True
    except KeyError:
        pass
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    try:
        s3.put_object(s3_key, content, s3_metadata)
    except CredentialError as exc:
        return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

    # ── Step 5: Parse sections ────────────────────────────────────────────────
    sections = parse_sections(content)

    # ── Step 5a: Length filter ────────────────────────────────────────────────
    if settings.embed_min_section_length > 0:
        dropped = [s for s in sections if len(s.body.strip()) < settings.embed_min_section_length]
        if dropped:
            logger.debug(
                "Dropping %d sections below min length %d",
                len(dropped),
                settings.embed_min_section_length,
            )
        sections = [s for s in sections if len(s.body.strip()) >= settings.embed_min_section_length]

    # ── Step 5b: Cap sections ─────────────────────────────────────────────────
    if len(sections) > settings.embed_max_sections:
        logger.debug("Capping sections from %d to %d", len(sections), settings.embed_max_sections)
        sections = sections[: settings.embed_max_sections]

    # ── Step 6: Build vector metadata (types match filter requirements) ───────
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

    # ── Step 7: Embed and index ───────────────────────────────────────────────
    new_keys: set[str] = set()

    if sections:
        # Concurrent embedding with bounded semaphore
        semaphore = asyncio.Semaphore(settings.section_concurrency)

        sections_to_embed: list[tuple[str, str]] = []
        limit = settings.embed_max_section_length
        for sec in sections:
            vec_key = f"{s3_key}#{section_slug(sec.heading)}"
            if limit > 0 and len(sec.body) > limit:
                logger.debug(
                    "Section '%s' body truncated from %d to %d chars for embedding",
                    sec.heading,
                    len(sec.body),
                    limit,
                )
                embed_body = sec.body[:limit]
            else:
                embed_body = sec.body
            sections_to_embed.append(
                (
                    vec_key,
                    _build_section_embedding_text(
                        title=title,
                        artifact_type=type,
                        tags=tags,
                        section_heading=sec.heading,
                        section_body=embed_body,
                    ),
                )
            )

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
        embed_text = _build_document_embedding_text(
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
    return {
        "artifact_id": s3_key,
        "sections_indexed": len(new_keys),
        "last_edited_ulid": last_edited_ulid,
    }
