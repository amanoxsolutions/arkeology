"""cairn_mcp.tools.write — write_artifact MCP tool implementation.

Stores an artifact to S3 and indexes its section vectors in S3 Vectors using
Bedrock embeddings. For tier-3 artifacts, orphaned section vectors from
previous writes are cleaned up automatically.
"""

import logging
from typing import Any

from pydantic import ValidationError

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
from cairn_mcp.errors import CredentialError

logger = logging.getLogger(__name__)


def _build_section_embedding_text(
    *,
    title: str,
    artifact_type: str,
    feature_tags: list[str],
    section_heading: str,
    section_body: str,
) -> str:
    """Build the embedding input text for a single section vector.

    Format::

        Title: {title}
        Type: {type}
        Tags: {tag1}, {tag2}    ← omitted when feature_tags is empty

        ## {section_heading}
        {section_body}

    Args:
        title: Artifact title.
        artifact_type: Artifact type string.
        feature_tags: List of tag strings (may be empty).
        section_heading: Heading text of this section.
        section_body: Body text of this section.

    Returns:
        Formatted embedding input string.
    """
    lines = [f"Title: {title}", f"Type: {artifact_type}"]
    if feature_tags:
        lines.append(f"Tags: {', '.join(feature_tags)}")
    lines.append("")
    lines.append(f"## {section_heading}")
    lines.append(section_body)
    return "\n".join(lines)


def _build_document_embedding_text(
    *,
    title: str,
    artifact_type: str,
    feature_tags: list[str],
    description: str,
) -> str:
    """Build the embedding input text for a document-level fallback vector.

    Format::

        Title: {title}
        Type: {type}
        Tags: {tag1}, {tag2}    ← omitted when feature_tags is empty
        Description: {description}

    Args:
        title: Artifact title.
        artifact_type: Artifact type string.
        feature_tags: List of tag strings (may be empty).
        description: Short artifact description.

    Returns:
        Formatted embedding input string.
    """
    lines = [f"Title: {title}", f"Type: {artifact_type}"]
    if feature_tags:
        lines.append(f"Tags: {', '.join(feature_tags)}")
    lines.append(f"Description: {description}")
    return "\n".join(lines)


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
    feature_tags: list[str] | None = None,
    author_role: str | None = None,
    source_artifacts: list[str] | None = None,
    status: str = "active",
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
        visibility: ``"shared"`` or ``"confidential"``.
        feature_tags: Optional list of tag strings.
        author_role: Optional author role.
        source_artifacts: Optional list of source artifact IDs.
        status: ``"active"`` (default) or ``"inactive"``.

    Returns:
        On success: ``{"artifact_id": str, "sections_indexed": int}``
        On error: ``{"error": str, "message": str}``
    """
    tags: list[str] = feature_tags if feature_tags is not None else []
    sources: list[str] = source_artifacts if source_artifacts is not None else []

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
            tags=tags,
            author_role=author_role,
            sources=sources,
            status=status,
        )
    except Exception as exc:
        logger.exception("Unexpected error in write_artifact")
        return {"error": "internal_error", "message": str(exc)}


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
    status: str,
) -> dict[str, Any]:
    """Inner implementation of write_artifact (separated to enable top-level catch-all).

    Note: partial-write error responses (after S3 success, before full vector indexing)
    include ``artifact_id`` alongside ``error`` and ``message`` so callers can identify
    which artifact was partially written and take remedial action.
    """
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
            feature_tags=tags,
            author_role=author_role,
            source_artifacts=sources,
        )
    except ValidationError as exc:
        return {"error": "validation_error", "message": str(exc)}

    # ── Step 2: Derive identifiers ────────────────────────────────────────────
    artifact_id = generate_artifact_id(tier=tier, type=type, date=date, title=title)
    s3_key = f"{settings.write_prefix}/{artifact_id}"

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
        "feature_tags": ",".join(tags),
        "author_role": author_role or "",
        "description": description,
        "source_artifacts": ",".join(sources),
    }

    # ── Step 4: Write to S3 ───────────────────────────────────────────────────
    try:
        s3.put_object(s3_key, content, s3_metadata)
    except CredentialError as exc:
        return {"error": "credential_error", "message": str(exc)}

    # ── Step 5: Parse sections ────────────────────────────────────────────────
    sections = parse_sections(content)

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
        "feature_tags": tags,  # stored as list for $eq filter compatibility
        "author_role": author_role or "",
        "description": description,
        "source_artifacts": sources,  # stored as list for $eq filter compatibility
    }

    # ── Step 7: Embed and index ───────────────────────────────────────────────
    new_keys: set[str] = set()

    if sections:
        for sec in sections:
            embed_text = _build_section_embedding_text(
                title=title,
                artifact_type=type,
                feature_tags=tags,
                section_heading=sec.heading,
                section_body=sec.body,
            )
            try:
                embedding = bedrock.embed(embed_text, settings.bedrock_embedding_model)
            except CredentialError as exc:
                return {"error": "credential_error", "message": str(exc), "artifact_id": s3_key}

            vec_key = f"{s3_key}#{section_slug(sec.heading)}"
            try:
                vectors.put_vector(vec_key, embedding, vector_metadata)
            except CredentialError as exc:
                return {"error": "credential_error", "message": str(exc), "artifact_id": s3_key}

            new_keys.add(vec_key)
    else:
        embed_text = _build_document_embedding_text(
            title=title,
            artifact_type=type,
            feature_tags=tags,
            description=description,
        )
        try:
            embedding = bedrock.embed(embed_text, settings.bedrock_embedding_model)
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc), "artifact_id": s3_key}

        try:
            vectors.put_vector(s3_key, embedding, vector_metadata)
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc), "artifact_id": s3_key}

        new_keys.add(s3_key)

    # ── Step 8: Orphan cleanup for tier 3 ────────────────────────────────────
    if tier == 3:
        try:
            existing_keys = vectors.list_vectors_by_metadata(
                {"artifact_id": {"$eq": s3_key}}
            )
        except CredentialError as exc:
            return {"error": "credential_error", "message": str(exc), "artifact_id": s3_key}

        orphan_keys = [k for k in existing_keys if k not in new_keys]
        if orphan_keys:
            try:
                vectors.delete_vectors(orphan_keys)
            except CredentialError as exc:
                return {
                    "error": "credential_error",
                    "message": str(exc),
                    "artifact_id": s3_key,
                }

    logger.info(
        "Artifact written: key=%s sections=%d tier=%d", s3_key, len(new_keys), tier
    )
    return {"artifact_id": s3_key, "sections_indexed": len(new_keys)}
