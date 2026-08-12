"""arkeology.artifact — pure data types and ID/section utilities.

This module is AWS-free and client-free. It contains only in-process logic.

Normalisation rules for title_slug (used in generate_artifact_id) and
section_slug — applied in this order:
  1. Transliterate Unicode to ASCII via NFKD + encode/decode("ascii", "ignore").
  2. Lowercase.
  3. Replace runs of non-alphanumeric chars with a single '-'.
  4. Strip leading/trailing '-'.
  5. Truncate to 60 characters; re-strip trailing '-' after truncation.
  6. If empty after all steps → fallback ("artifact" for IDs, "section" for slugs).

``generate_artifact_id`` additionally appends a short deterministic hash suffix
(see ``_title_hash``) derived from the full, untruncated, un-normalised title to
every generated ID. This guarantees distinct titles always produce distinct keys,
even when the normalisation pipeline above would otherwise collapse them to the
same slug (empty-slug fallback, 60-char truncation, or punctuation collapse) —
see ADR-005's ``revised`` entry.
"""

import datetime as _dt
import hashlib
import json
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator

from arkeology.constants import ArtifactStatus
from arkeology.errors import MetadataTooLargeError

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

# Single source of truth for valid tier values, mirroring ARTIFACT_TYPES: never
# duplicate {2, 3} elsewhere.
VALID_TIERS: frozenset[int] = frozenset({2, 3})

# Write-path metadata size + charset validation constants. Single source of
# truth, mirroring ARTIFACT_TYPES: never duplicate these elsewhere.
#
# TITLE_MAX_LENGTH is a coarse model-level sanity bound (headline-length); the three byte
# budgets below are the authoritative whole-payload guards, checked by
# check_metadata_budgets() against the actual assembled S3 and vector metadata dicts
# immediately before any storage write.
TITLE_MAX_LENGTH = 256

# S3 user-defined object metadata is capped at 2 KB aggregate (sum of UTF-8 bytes of every
# key plus its transport-encoded value) — verified against the AWS S3 user guide.
S3_USER_METADATA_MAX_BYTES = 2048

# S3 Vectors caps filterable metadata (the subset of keys usable in a query filter) at 2 KB
# and total per-vector metadata at 40 KB — see
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html.
VECTOR_FILTERABLE_METADATA_MAX_BYTES = 2048
VECTOR_TOTAL_METADATA_MAX_BYTES = 40960

# Vector-metadata keys that are NOT filterable (must match the externally-created S3
# Vectors index's declared non-filterable slots exactly — see the PRD Deployment
# Prerequisites). Every other vector-metadata key counts against the filterable budget.
NON_FILTERABLE_METADATA_KEYS: tuple[str, ...] = (
    "description",
    "source_artifacts",
    "title",
    "author_role",
)

# Single source of truth for reverse-lookup-bearing metadata fields
# consumed by the unified own-scope referenced_by check on delete_artifact and
# archive_artifact (see find_referrers in tools/_search_helper.py). Never duplicate this
# list elsewhere. The filterable/non-filterable branch of that check is driven by each
# field's membership in NON_FILTERABLE_METADATA_KEYS above, not hardcoded per tool.
REFERENCE_FIELDS: tuple[str, ...] = ("source_artifacts", "references")

# Printable ASCII characters (space through tilde) that pass through
# encode_metadata_value() unchanged. '%' is excluded because it is the escape character
# used for percent-encoding and must itself be encoded to keep the transform reversible.
_TRANSPORT_SAFE_CHARS = "".join(chr(code) for code in range(0x20, 0x7F) if chr(code) != "%")


def encode_metadata_value(value: str) -> str:
    """Percent-encode a metadata value for lossless, header-safe S3 transport.

    S3 user-defined object metadata is transmitted as HTTP headers, which only support
    ASCII and reject raw control characters. This encodes every character outside the
    printable-ASCII-minus-percent safe set (non-ASCII text, control characters, and
    literal '%') as its UTF-8 byte sequence in ``%XX`` form; everything else passes
    through unchanged. Unlike the previous NFKD-ASCII-strip, this is fully reversible via
    :func:`decode_metadata_value` — no non-Latin content is ever silently discarded.

    Args:
        value: The raw metadata value (may contain any Unicode text).

    Returns:
        An ASCII-only, HTTP-header-safe string. Percent-decoding it with
        :func:`decode_metadata_value` recovers ``value`` exactly.
    """
    return urllib.parse.quote(value, safe=_TRANSPORT_SAFE_CHARS)


def decode_metadata_value(value: str) -> str:
    """Reverse :func:`encode_metadata_value`, recovering the original Unicode text.

    Args:
        value: A string previously produced by :func:`encode_metadata_value` (or any
            plain string with no ``%XX`` escapes, which passes through unchanged).

    Returns:
        The original, decoded Unicode string.
    """
    return urllib.parse.unquote(value)


def _require_no_control_chars(field: str, value: str) -> None:
    """Raise ``ValueError`` if ``value`` contains a Unicode category ``Cc`` control
    character (U+0000-U+001F or U+007F-U+009F).

    Reject, not strip (Open Question, resolved): a control character in a short,
    human-authored identity field is a mistake or injection, and silently stripping it
    would mutate the stored value — directly undermining Story 4's requirement that
    ``title`` round-trip identically.

    Args:
        field: Name of the field being validated (used in the error message).
        value: The string to check.

    Raises:
        ValueError: naming the field and the offending character.
    """
    for ch in value:
        if unicodedata.category(ch) == "Cc":
            raise ValueError(
                f"{field} must not contain control characters, found {ch!r} in {value!r}"
            )


def _require_no_comma(field: str, value: str) -> None:
    """Raise ``ValueError`` if ``value`` contains a literal comma.

    ``commit_refs``/``references`` are comma-joined into a single string for their
    S3 annotation payload (:func:`arkeology.annotations.encode_link_list`), while
    vector metadata stores each as a native ``list[str]``. A literal comma inside one
    element would decode back into extra elements on the annotation side
    (:func:`arkeology.annotations.decode_link_list`) while the vector-metadata side
    keeps it as a single element, silently diverging the two stores. Reject rather
    than escape/encode — the comma-join encoding itself stays untouched.

    Args:
        field: Name of the field being validated (used in the error message).
        value: The string to check.

    Raises:
        ValueError: naming the field and the offending value.
    """
    if "," in value:
        raise ValueError(f"{field} must not contain a comma, found {value!r}")


def check_metadata_budgets(
    s3_metadata: dict[str, str],
    vector_metadata: dict[str, Any],
) -> None:
    """Validate assembled write-path metadata against the three byte budgets.

    Representation-driven, not field-list-driven: this measures the actual assembled
    dicts about to be written, so it stays correct regardless of which fields later move
    between S3 user-metadata and vector metadata (see ADR-011). Call this BEFORE issuing
    any ``head_object``/``put_object``/``put_vectors_batch`` call and before any
    failure-log append, so a rejected write touches neither S3, vectors, nor the failure
    log.

    Args:
        s3_metadata: The S3 user-metadata dict with values already transport-encoded
            (see :func:`encode_metadata_value`) exactly as they will be transmitted.
        vector_metadata: The vector metadata dict exactly as it will be written to
            S3 Vectors.

    Raises:
        MetadataTooLargeError: if the S3 aggregate, the vector filterable subset, or the
            full vector metadata breaches its respective budget.
    """
    s3_bytes = sum(
        len(key.encode("utf-8")) + len(value.encode("utf-8")) for key, value in s3_metadata.items()
    )
    if s3_bytes > S3_USER_METADATA_MAX_BYTES:
        raise MetadataTooLargeError(
            budget="s3_user_metadata",
            actual_bytes=s3_bytes,
            max_bytes=S3_USER_METADATA_MAX_BYTES,
        )

    filterable_metadata = {
        key: value
        for key, value in vector_metadata.items()
        if key not in NON_FILTERABLE_METADATA_KEYS
    }
    filterable_bytes = len(json.dumps(filterable_metadata, ensure_ascii=False).encode("utf-8"))
    if filterable_bytes > VECTOR_FILTERABLE_METADATA_MAX_BYTES:
        raise MetadataTooLargeError(
            budget="vector_filterable_metadata",
            actual_bytes=filterable_bytes,
            max_bytes=VECTOR_FILTERABLE_METADATA_MAX_BYTES,
        )

    total_bytes = len(json.dumps(vector_metadata, ensure_ascii=False).encode("utf-8"))
    if total_bytes > VECTOR_TOTAL_METADATA_MAX_BYTES:
        raise MetadataTooLargeError(
            budget="vector_total_metadata",
            actual_bytes=total_bytes,
            max_bytes=VECTOR_TOTAL_METADATA_MAX_BYTES,
        )


_MAX_SLUG_LEN = 60

# Length (in hex characters) of the deterministic title-hash suffix appended to every
# generated artifact ID. 8 hex chars = 32 bits of a SHA-256 digest. The relevant
# collision population is NOT the full per-type/date artifact corpus: two titles with
# different title_slug values already produce distinct IDs from the slug alone, hash or
# no hash. The hash only has to disambiguate the much smaller subset of titles that
# already collide on type + date + title_slug (empty-slug fallback, 60-char truncation
# matches, punctuation-collapse matches) — in practice a handful of titles per
# type/date, not the whole corpus. Against that small a population, the birthday-bound
# collision probability at 32 bits is negligible, while keeping the suffix short and
# readable in the S3 console alongside the slug it disambiguates.
_TITLE_HASH_LEN = 8

# Patterns used by parse_sections — compiled once at module load.
_FENCE_RE: re.Pattern[str] = re.compile(r"^(`{3,}|~{3,})")
_H2_RE: re.Pattern[str] = re.compile(r"^## (.+)$")


def _require_valid_type(value: str) -> None:
    """Raise ``ValueError`` unless ``value`` is a known artifact type."""
    if value not in ARTIFACT_TYPES:
        raise ValueError(f"type must be one of {sorted(ARTIFACT_TYPES)}, got '{value}'")


def _require_valid_date(value: str) -> None:
    """Raise ``ValueError`` unless ``value`` is a valid ISO-8601 date string."""
    try:
        _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"date must be a valid ISO-8601 date string, got '{value}'") from exc


def _require_valid_tier(value: int) -> None:
    """Raise ``ValueError`` unless ``value`` is tier 2 or 3."""
    if value not in VALID_TIERS:
        raise ValueError(f"tier must be 2 or 3, got {value}")


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


def _title_hash(title: str) -> str:
    """Return a short, deterministic hex digest of the full, original title.

    Args:
        title: The raw (un-normalised, un-truncated) artifact title.

    Returns:
        The first ``_TITLE_HASH_LEN`` hex characters of the title's SHA-256 digest.
        Deterministic — the same title always yields the same suffix. Never random
        or UUID-based (project rule): two writes of the same title always collide
        on this suffix too, which is required for tier 2/3 idempotency.
    """
    return hashlib.sha256(title.encode("utf-8")).hexdigest()[:_TITLE_HASH_LEN]


def generate_artifact_id(*, tier: int, type: str, date: str, title: str) -> str:  # noqa: A002
    """Generate a deterministic artifact ID from its key attributes.

    Tier 2 format: ``{type_slug}-{date}-{title_slug}-{hash}``
    Tier 3 format: ``{type_slug}-{title_slug}-{hash}`` (date excluded — stable across updates)

    ``hash`` is a deterministic 8-hex-char SHA-256 prefix of the full, original title
    (see ``_title_hash``) and is *always* appended, regardless of whether the slug
    normalisation above collided or not. This structurally eliminates three collision
    classes that used to silently destroy artifacts: titles with no Latin/digit
    content (which all fell back to the constant ``"artifact"`` slug), two titles that
    differ only after the 60-character truncation point, and titles that differ only
    in punctuation stripped by the slug normalisation (e.g. ``"Auth: Module Review"``
    vs. ``"Auth module (review)"``). The slug portion is kept alongside the hash for
    human readability in the S3 console; the hash alone is what guarantees uniqueness.

    Args:
        tier: Artifact tier (2 or 3).
        type: Artifact type string (underscores converted to hyphens).
        date: ISO-8601 date string (e.g. ``"2026-05-30"``). Unused for tier 3.
        title: Human-readable artifact title.

    Returns:
        Deterministic, S3-safe identifier string.
    """
    _require_valid_type(type)
    _require_valid_date(date)
    _require_valid_tier(tier)
    type_slug = type.replace("_", "-")
    title_slug = _slugify(title, "artifact")
    title_hash = _title_hash(title)
    if tier == 3:
        return f"{type_slug}-{title_slug}-{title_hash}"
    return f"{type_slug}-{date}-{title_slug}-{title_hash}"


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
    """Structured representation of an arkeology artifact.

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
        commit_refs: Optional list of git commit SHAs linked to this artifact. A
            durable, backfill-only audit trail with no frontmatter counterpart: on an
            overwriting write, the supplied value is MERGED (union, dedup) with the
            artifact's existing commit_refs rather than replacing it — accretive by
            design, since the append-only link trail must never be silently dropped
            (ADR-011 decision 4).
        references: Optional list of resolved bare artifact IDs this artifact points
            at (ADR-012 D2). Holds only resolved identifiers — no ``arkeology://`` prefix,
            no path text. Mirrors the artifact's frontmatter ``references:`` list — a
            claim about the artifact's *current* outbound links, not an audit trail.
            On an overwriting write, the supplied value REPLACES the artifact's
            existing references outright (no merge, no read-forward): additions,
            removals, and swaps in the frontmatter are all reflected one-for-one, and
            a write supplying no references clears the field (ADR-011 decision 4).
    """

    type: str  # noqa: A003
    team: str
    project: str
    # strict=True: tier must be a real int, not a numeric string. Pydantic's default
    # lax coercion would silently accept "2" and convert it to 2 *before* the
    # validate_tier field_validator below ever runs — masking a caller's type mistake
    # instead of rejecting it, and leaving the raw, un-coerced string to
    # blow up downstream in generate_artifact_id's _require_valid_tier as an
    # unhandled ValueError.
    tier: int = Field(strict=True)
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
    references: list[str] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        _require_valid_type(v)
        return v

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: int) -> int:
        _require_valid_tier(v)
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
        if v not in {ArtifactStatus.ACTIVE, ArtifactStatus.INACTIVE}:
            raise ValueError(f"status must be 'active' or 'inactive', got '{v}'")
        return v

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        _require_valid_date(v)
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if len(v) > 280:
            raise ValueError(f"description must be at most 280 characters, got {len(v)}")
        _require_no_control_chars("description", v)
        return v

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        if len(v) > TITLE_MAX_LENGTH:
            raise ValueError(f"title must be at most {TITLE_MAX_LENGTH} characters, got {len(v)}")
        _require_no_control_chars("title", v)
        return v

    @field_validator("author_role")
    @classmethod
    def validate_author_role(cls, v: str | None) -> str | None:
        if v is not None:
            _require_no_control_chars("author_role", v)
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        for item in v:
            _require_no_control_chars("tags", item)
        return v

    @field_validator("source_artifacts")
    @classmethod
    def validate_source_artifacts(cls, v: list[str]) -> list[str]:
        for item in v:
            _require_no_control_chars("source_artifacts", item)
        return v

    @field_validator("commit_refs")
    @classmethod
    def validate_commit_refs(cls, v: list[str]) -> list[str]:
        for item in v:
            _require_no_control_chars("commit_refs", item)
            _require_no_comma("commit_refs", item)
        return v

    @field_validator("references")
    @classmethod
    def validate_references(cls, v: list[str]) -> list[str]:
        for item in v:
            _require_no_control_chars("references", item)
            _require_no_comma("references", item)
        return v
