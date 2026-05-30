"""cairn_mcp.artifact — Artifact model, key generation, and section parsing.

This module is the single source of truth for:
- The canonical set of artifact types and valid metadata values.
- Deterministic artifact ID (S3 key suffix) generation from artifact attributes.
- Markdown section parsing (split on ## headings).
- Section slug generation for vector key suffixes.

No AWS calls are made here. All functions are pure Python.

Key generation rules
--------------------
Tier 2 (project-local, date-anchored):
    {type_slug}-{date}-{title_slug}
    e.g. "code-review-2026-05-30-fix-auth-bug"

Tier 3 (shared, living document — date-independent):
    {type_slug}-{title_slug}
    e.g. "adr-use-postgres-for-sessions"

Title slug normalisation rules:
1. Transliterate Unicode characters to their closest ASCII equivalent using
   unicodedata NFKD decomposition; drop characters with no ASCII equivalent.
2. Lowercase the result.
3. Replace any run of non-alphanumeric characters with a single "-".
4. Strip leading and trailing "-".
5. Truncate to 60 characters.
6. If the result is empty after all transformations, use the fallback "artifact".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Constants — single source of truth for valid values
# ---------------------------------------------------------------------------

ARTIFACT_TYPES = frozenset(
    {
        "code_review",
        "session_summary",
        "implementation_note",
        "spec",
        "adr",
        "bug_report",
        "decision_note",
        "synthesis",
    }
)

VALID_TIERS: frozenset[int] = frozenset({2, 3})
VALID_VISIBILITIES = frozenset({"shared", "confidential"})
VALID_STATUSES = frozenset({"active", "inactive"})

_TITLE_SLUG_MAX_LEN = 60
_TITLE_SLUG_FALLBACK = "artifact"
_SECTION_SLUG_FALLBACK = "section"


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------


def _to_ascii(text: str) -> str:
    """Transliterate Unicode to ASCII; drop characters with no equivalent."""
    normalised = unicodedata.normalize("NFKD", text)
    return normalised.encode("ascii", errors="ignore").decode("ascii")


def _slugify(text: str, max_len: int, fallback: str) -> str:
    """Convert *text* to a URL-safe, lowercase slug.

    Steps:
    1. Transliterate to ASCII.
    2. Lowercase.
    3. Replace runs of non-alphanumeric characters with a single "-".
    4. Strip leading/trailing "-".
    5. Truncate to *max_len*.
    6. Return *fallback* if the result is empty.
    """
    ascii_text = _to_ascii(text)
    lower = ascii_text.lower()
    dashed = re.sub(r"[^a-z0-9]+", "-", lower)
    stripped = dashed.strip("-")
    truncated = stripped[:max_len]
    # Truncation may leave a trailing "-" if the cut point fell on one
    truncated = truncated.strip("-")
    return truncated if truncated else fallback


def section_slug(heading: str) -> str:
    """Return a URL-safe slug for a markdown section heading.

    Used as the suffix after the ``#`` separator in S3 Vectors keys.

    >>> section_slug("My Heading")
    'my-heading'
    >>> section_slug("")
    'section'
    >>> section_slug("---")
    'section'
    """
    return _slugify(heading, max_len=_TITLE_SLUG_MAX_LEN, fallback=_SECTION_SLUG_FALLBACK)


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


def _type_slug(artifact_type: str) -> str:
    """Convert an artifact type like 'code_review' to 'code-review'."""
    return artifact_type.replace("_", "-")


def generate_artifact_id(*, tier: int, type: str, date: str, title: str) -> str:  # noqa: A002
    """Return a deterministic artifact identifier derived from the artifact's own attributes.

    The returned string is suitable for use as the suffix of an S3 key (the full key is
    ``{write_prefix}/{artifact_id}``).

    Parameters
    ----------
    tier:
        2 for project-local (date-anchored), 3 for shared living document.
    type:
        Artifact type string, e.g. ``"code_review"``.
    date:
        ISO date string (YYYY-MM-DD).  Used only for tier 2.
    title:
        Human-readable artifact title.  Normalised into a slug.
    """
    type_part = _type_slug(type)
    title_part = _slugify(title, max_len=_TITLE_SLUG_MAX_LEN, fallback=_TITLE_SLUG_FALLBACK)

    if tier == 2:
        return f"{type_part}-{date}-{title_part}"
    else:
        # Tier 3: date is not a factor
        return f"{type_part}-{title_part}"


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------


@dataclass
class ArtifactSection:
    """A single ``##`` section extracted from artifact content."""

    heading: str
    body: str


def parse_sections(content: str) -> list[ArtifactSection]:
    """Split *content* into sections delimited by ``##`` headings.

    Only top-level H2 headings (``##``) are treated as section boundaries.
    H3 and deeper headings (``###``, etc.) inside a section are preserved as-is
    in the section body.

    Content before the first ``##`` heading is discarded.

    Returns an empty list if the content contains no ``##`` headings.
    """
    # Match lines that start with exactly "## " (and not "### " or deeper)
    pattern = re.compile(r"^## (.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))

    if not matches:
        return []

    sections: list[ArtifactSection] = []
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        # Body starts immediately after the heading line
        body_start = match.end()
        # Body ends at the start of the next ## heading (or end of content)
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[body_start:body_end].strip()
        sections.append(ArtifactSection(heading=heading, body=body))

    return sections


# ---------------------------------------------------------------------------
# Artifact model
# ---------------------------------------------------------------------------


class Artifact(BaseModel):
    """Validated artifact metadata and content.

    This is an internal data class — it is never serialised directly to MCP
    output.  Tools convert it to dicts for responses.
    """

    type: str
    team: str
    project: str
    tier: int
    date: str
    status: str
    title: str
    description: str
    content: str
    visibility: str
    feature_tags: list[str] = Field(default_factory=list)
    author_role: str | None = None
    source_artifacts: list[str] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ARTIFACT_TYPES:
            valid = sorted(ARTIFACT_TYPES)
            raise ValueError(f"Invalid artifact type '{v}'. Valid types: {valid}")
        return v

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: int) -> int:
        if v not in VALID_TIERS:
            raise ValueError(f"Invalid tier '{v}'. Must be one of: {sorted(VALID_TIERS)}")
        return v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        if v not in VALID_VISIBILITIES:
            raise ValueError(
                f"Invalid visibility '{v}'. Must be one of: {sorted(VALID_VISIBILITIES)}"
            )
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{v}'. Must be one of: {sorted(VALID_STATUSES)}"
            )
        return v

    @field_validator("description")
    @classmethod
    def validate_description_length(cls, v: str) -> str:
        if len(v) > 280:
            raise ValueError(
                f"Description must not exceed 280 characters (got {len(v)})."
            )
        return v
