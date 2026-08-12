"""arkeology.tools._section_pipeline — shared write-path section embedding pipeline.

Centralises the section-level embedding pipeline applied on every artifact write:
min-length filtering, max-sections capping, per-section truncation, and
embedding-text construction. Both ``write.py`` and ``reconcile.py`` call
``prepare_sections_for_embedding`` so a section that is dropped, capped, or
truncated at write time is dropped, capped, or truncated *identically* when
``reconcile_index`` later re-embeds the same artifact (Phase 12 review M-3).

Before this module existed, ``reconcile.py::_reindex_artifact`` parsed sections and
embedded each one directly, sharing only the ``_build_*_embedding_text`` formatting
helpers with ``write.py`` — it never applied the min-length filter, the
``EMBED_MAX_SECTIONS`` cap, or ``EMBED_MAX_SECTION_LENGTH`` truncation. A section
that write-time truncated to fit Titan's input limit was therefore re-submitted
full-length on every reconcile replay, permanently failing and leaving a stuck
failure-log entry that reconcile could never actually clear.
"""

import logging
from dataclasses import dataclass

from arkeology.artifact import ArtifactSection, parse_sections, section_slug
from arkeology.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedSection:
    """A section that survived the write-path filtering pipeline, ready to embed.

    Attributes:
        heading: Original section heading — callers derive the vector key suffix
            from this via ``arkeology.artifact.section_slug``.
        embed_text: Fully-formatted embedding input text (title/type/tags header,
            heading, and the possibly-truncated body), ready to pass to
            ``bedrock.embed``.
    """

    heading: str
    embed_text: str


def build_section_embedding_text(
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
        section_body: Body text of this section (already truncated by the caller
            if it exceeds ``embed_max_section_length``).

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


def build_document_embedding_text(
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


def prepare_sections_for_embedding(
    content: str,
    *,
    title: str,
    artifact_type: str,
    tags: list[str],
    settings: Settings,
) -> list[PreparedSection]:
    """Parse, filter, cap, truncate, and format sections exactly as write_artifact does.

    Applies the write path's section-pipeline steps, in order:

    1. Parse ``##`` sections from ``content`` (:func:`arkeology.artifact.parse_sections`).
    2. Drop sections whose stripped body is shorter than
       ``settings.embed_min_section_length`` (0 disables this filter).
    3. Cap the remaining sections to ``settings.embed_max_sections``.
    4. Truncate each surviving section's body to
       ``settings.embed_max_section_length`` chars before building its embedding
       text (0 disables truncation) — the full, untruncated body is always stored
       in S3; only the text sent to Bedrock is shortened.

    Args:
        content: Full artifact Markdown content.
        title: Artifact title (embedding-text header).
        artifact_type: Artifact type string (embedding-text header).
        tags: Tag list (embedding-text header, omitted when empty).
        settings: Server configuration supplying the three pipeline thresholds.

    Returns:
        Ordered list of :class:`PreparedSection`, one per section that survives
        filtering and capping, each carrying its final (possibly truncated)
        embedding text. Empty when the artifact has no ``##`` sections, or when
        every section was filtered out — callers fall back to
        :func:`build_document_embedding_text` for a document-level vector in
        both cases.
    """
    sections: list[ArtifactSection] = parse_sections(content)

    if settings.embed_min_section_length > 0:
        dropped = [s for s in sections if len(s.body.strip()) < settings.embed_min_section_length]
        if dropped:
            logger.debug(
                "Dropping %d sections below min length %d",
                len(dropped),
                settings.embed_min_section_length,
            )
        sections = [s for s in sections if len(s.body.strip()) >= settings.embed_min_section_length]

    if len(sections) > settings.embed_max_sections:
        logger.debug("Capping sections from %d to %d", len(sections), settings.embed_max_sections)
        sections = sections[: settings.embed_max_sections]

    limit = settings.embed_max_section_length
    prepared: list[PreparedSection] = []
    for sec in sections:
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
        prepared.append(
            PreparedSection(
                heading=sec.heading,
                embed_text=build_section_embedding_text(
                    title=title,
                    artifact_type=artifact_type,
                    tags=tags,
                    section_heading=sec.heading,
                    section_body=embed_body,
                ),
            )
        )
    return prepared


def disambiguate_section_slugs(sections: list[PreparedSection]) -> list[str]:
    """Return one vector-key-safe slug per section, disambiguating slug collisions.

    ``section_slug`` normalises heading text (case-folds, strips punctuation), so
    distinct headings can legitimately collapse to the same base slug (e.g.
    ``"Notes"`` and ``"Notes!"`` both normalise to ``"notes"``). Using the bare
    slug as a vector key suffix (``f"{s3_key}#{slug}"``) would then collide: the
    second section's vector would silently overwrite the first's, and the write
    path's ``sections_indexed`` count would under-report the true section count
    (07-02 #2). Repeat occurrences of the same base slug within one artifact get
    a numeric suffix (``-2``, ``-3``, ...) appended, in document order, so every
    section is guaranteed a distinct vector key.

    Shared by ``write.py`` and ``reconcile.py`` (Phase 12 review M-3 convention)
    so a collision is disambiguated identically on both the initial write and any
    later ``reconcile_index`` replay of the same artifact.

    Args:
        sections: Prepared sections in document order.

    Returns:
        One disambiguated slug per section, same order and length as ``sections``.
    """
    occurrence_counts: dict[str, int] = {}
    slugs: list[str] = []
    for sec in sections:
        base_slug = section_slug(sec.heading)
        occurrence_counts[base_slug] = occurrence_counts.get(base_slug, 0) + 1
        occurrence = occurrence_counts[base_slug]
        slugs.append(base_slug if occurrence == 1 else f"{base_slug}-{occurrence}")
    return slugs
