"""cairn_mcp.artifact — pure data types and ID/section utilities.

This module is AWS-free and client-free. It contains only in-process logic.

Normalisation rules for title_slug (used in generate_artifact_id) and
section_slug — applied in this order:
  1. Transliterate Unicode to ASCII via NFKD + encode/decode("ascii", "ignore").
  2. Lowercase.
  3. Replace runs of non-alphanumeric chars with a single '-'.
  4. Strip leading/trailing '-'.
  5. Truncate to 60 characters; re-strip trailing '-' after truncation.
  6. If empty after all steps → fallback ("artifact" for IDs, "section" for slugs).
"""

import datetime as _dt
import re
import unicodedata
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator

ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        "brainstorming",
        "changelog",
        "code_review",
        "session_summary",
        "implementation_note",
        "plan",
        "postmortem",
        "prd",
        "runbook",
        "spec",
        "adr",
        "bug_report",
        "decision_note",
        "synthesis",
        "learning",
    }
)

_MAX_SLUG_LEN = 60

# Patterns used by parse_sections — compiled once at module load.
_FENCE_RE: re.Pattern[str] = re.compile(r"^(`{3,}|~{3,})")
_H2_RE: re.Pattern[str] = re.compile(r"^## (.+)$")


def _slugify(text: str, fallback: str) -> str:
    """Normalise text into a URL/S3-safe slug.

    Args:
        text: Raw input string (may contain Unicode, punctuation, whitespace).
        fallback: Returned when the slug is empty after normalisation.

    Returns:
        Normalised slug string.
    """
    ascii_text = (
        unicodedata.normalize("NFKD", text).encode("ascii", errors="ignore").decode("ascii")
    )
    lower = ascii_text.lower()
    replaced = re.sub(r"[^a-z0-9]+", "-", lower)
    stripped = replaced.strip("-")
    truncated = stripped[:_MAX_SLUG_LEN].rstrip("-")
    return truncated if truncated else fallback


def generate_artifact_id(*, tier: int, type: str, date: str, title: str) -> str:  # noqa: A002
    """Generate a deterministic artifact ID from its key attributes.

    Tier 2 format: ``{type_slug}-{date}-{title_slug}``
    Tier 3 format: ``{type_slug}-{title_slug}`` (date excluded — stable across updates)

    Args:
        tier: Artifact tier (2 or 3).
        type: Artifact type string (underscores converted to hyphens).
        date: ISO-8601 date string (e.g. ``"2026-05-30"``). Unused for tier 3.
        title: Human-readable artifact title.

    Returns:
        Deterministic, S3-safe identifier string.
    """
    if type not in ARTIFACT_TYPES:
        raise ValueError(f"type must be one of {sorted(ARTIFACT_TYPES)}, got '{type}'")
    try:
        _dt.date.fromisoformat(date)
    except ValueError as exc:
        raise ValueError(f"date must be a valid ISO-8601 date string, got '{date}'") from exc
    if tier not in {2, 3}:
        raise ValueError(f"tier must be 2 or 3, got {tier}")
    type_slug = type.replace("_", "-")
    title_slug = _slugify(title, "artifact")
    if tier == 3:
        return f"{type_slug}-{title_slug}"
    return f"{type_slug}-{date}-{title_slug}"


def section_slug(heading: str) -> str:
    """Normalise a section heading into a URL/S3-safe slug.

    Uses the same rules as the title slug in :func:`generate_artifact_id`
    but with fallback ``"section"``.

    Args:
        heading: Section heading text (the text after ``## ``).

    Returns:
        Normalised slug string.
    """
    return _slugify(heading, "section")


@dataclass
class ArtifactSection:
    """A single H2 section extracted from artifact content.

    Attributes:
        heading: The section heading (text after ``## ``, whitespace-stripped).
        body: Everything between this heading and the next H2 (or end of content),
            whitespace-stripped.
    """

    heading: str
    body: str


def parse_sections(content: str) -> list[ArtifactSection]:
    """Split Markdown content on H2 (``##``) headings, respecting fenced code blocks.

    Only ``##`` headings that appear *outside* fenced code blocks (triple-backtick
    or triple-tilde) are treated as section boundaries.  ``###`` and deeper headings
    remain part of the section body.  Content before the first ``##`` is discarded.

    Fence tracking follows the opening marker character (`` ` `` or ``~``): the fence
    is closed by the next line that begins with three or more of the same character.
    An unclosed fence causes all remaining ``##`` lines to be treated as fence content.

    Args:
        content: Full artifact content string.

    Returns:
        List of :class:`ArtifactSection` objects in document order.
        Empty list if there are no ``##`` headings outside fenced code blocks.
    """
    in_fence = False
    fence_char = ""
    # Each entry: (offset of heading line start, offset just after heading line, heading text)
    boundaries: list[tuple[int, int, str]] = []

    pos = 0
    for line in content.splitlines(keepends=True):
        stripped = line.rstrip("\n\r")
        fence_m = _FENCE_RE.match(stripped)
        if fence_m:
            marker_char = fence_m.group(1)[0]
            if not in_fence:
                in_fence = True
                fence_char = marker_char
            elif marker_char == fence_char:
                in_fence = False
                fence_char = ""
        elif not in_fence:
            h2_m = _H2_RE.match(stripped)
            if h2_m:
                boundaries.append((pos, pos + len(line), h2_m.group(1).strip()))
        pos += len(line)

    if not boundaries:
        return []

    sections: list[ArtifactSection] = []
    for i, (heading_start, body_start, heading) in enumerate(boundaries):
        body_end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(content)
        body = content[body_start:body_end].strip()
        sections.append(ArtifactSection(heading=heading, body=body))
    return sections


class Artifact(BaseModel):
    """Structured representation of a cairn artifact.

    All field constraints are validated on construction — invalid inputs raise
    ``pydantic.ValidationError``.

    Attributes:
        type: One of the fifteen valid artifact types in :data:`ARTIFACT_TYPES`.
        team: Team that owns the artifact.
        project: Project the artifact belongs to.
        tier: 2 (session-scoped) or 3 (persistent/cross-session).
        date: ISO-8601 date string.
        status: ``"active"`` or ``"inactive"``.
        title: Human-readable title.
        description: Short summary (max 280 characters).
        content: Full Markdown content.
        visibility: ``"shared"`` or ``"hidden"``.
        tags: Optional list of tag strings.
        author_role: Optional role identifier of the author.
        source_artifacts: Optional list of artifact IDs that this synthesises.
        commit_refs: Optional list of git commit SHAs linked to this artifact.
    """

    type: str  # noqa: A003
    team: str
    project: str
    tier: int
    date: str
    status: str
    title: str
    description: str
    content: str
    visibility: str
    tags: list[str] = Field(default_factory=list)
    author_role: str | None = None
    source_artifacts: list[str] = Field(default_factory=list)
    commit_refs: list[str] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ARTIFACT_TYPES:
            raise ValueError(f"type must be one of {sorted(ARTIFACT_TYPES)}, got '{v}'")
        return v

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: int) -> int:
        if v not in {2, 3}:
            raise ValueError(f"tier must be 2 or 3, got {v}")
        return v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        if v not in {"shared", "hidden"}:
            raise ValueError(f"visibility must be 'shared' or 'hidden', got '{v}'")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in {"active", "inactive"}:
            raise ValueError(f"status must be 'active' or 'inactive', got '{v}'")
        return v

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            _dt.date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"date must be a valid ISO-8601 date string, got '{v}'") from exc
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if len(v) > 280:
            raise ValueError(f"description must be at most 280 characters, got {len(v)}")
        return v
