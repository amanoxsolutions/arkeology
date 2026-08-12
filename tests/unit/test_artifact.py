"""Unit tests for arkeology.artifact."""

import json
import re

import pytest
from pydantic import ValidationError

from arkeology.artifact import (
    NON_FILTERABLE_METADATA_KEYS,
    S3_USER_METADATA_MAX_BYTES,
    TITLE_MAX_LENGTH,
    VECTOR_FILTERABLE_METADATA_MAX_BYTES,
    VECTOR_TOTAL_METADATA_MAX_BYTES,
    Artifact,
    ArtifactSection,
    check_metadata_budgets,
    decode_metadata_value,
    encode_metadata_value,
    generate_artifact_id,
    parse_sections,
    section_slug,
)
from arkeology.errors import MetadataTooLargeError

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

VALID_ARTIFACT_KWARGS: dict = {
    "type": "code_review",
    "team": "platform",
    "project": "arkeology",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "title": "Fix auth bug",
    "description": "Review of the auth module.",
    "content": "## Summary\n\nAll looks good.",
    "visibility": "shared",
}

_S3_SAFE_PATTERN = re.compile(r"^[a-z0-9\-_.]+$")


# ---------------------------------------------------------------------------
# generate_artifact_id — Tier 2
# ---------------------------------------------------------------------------


def test_generate_artifact_id_invalid_type_raises_value_error() -> None:
    """Invalid artifact type → ValueError."""
    with pytest.raises(ValueError, match="type"):
        generate_artifact_id(
            type="not_a_valid_type", title="Fix auth bug", tier=2, date="2026-05-30"
        )


def test_generate_artifact_id_invalid_date_raises_value_error() -> None:
    """Invalid date string → ValueError for tier 2."""
    with pytest.raises(ValueError, match="date"):
        generate_artifact_id(type="code_review", title="Fix auth bug", tier=2, date="not-a-date")


def test_generate_artifact_id_invalid_date_tier3_raises_value_error() -> None:
    """Invalid date string → ValueError for tier 3 (date is always validated)."""
    with pytest.raises(ValueError, match="date"):
        generate_artifact_id(type="adr", title="Use postgres", tier=3, date="not-a-date")


def test_tier2_same_inputs_same_id() -> None:
    """Tier 2: same type + date + title → deterministic, same id."""
    id1 = generate_artifact_id(type="code_review", title="Fix auth bug", tier=2, date="2026-05-30")
    id2 = generate_artifact_id(type="code_review", title="Fix auth bug", tier=2, date="2026-05-30")
    assert id1 == id2


def test_tier2_different_date_different_id() -> None:
    """Tier 2: different date → different id."""
    id1 = generate_artifact_id(type="code_review", title="Fix auth bug", tier=2, date="2026-05-30")
    id2 = generate_artifact_id(type="code_review", title="Fix auth bug", tier=2, date="2026-06-01")
    assert id1 != id2


def test_tier2_different_title_different_id() -> None:
    """Tier 2: different title → different id."""
    id1 = generate_artifact_id(type="code_review", title="Fix auth bug", tier=2, date="2026-05-30")
    id2 = generate_artifact_id(type="code_review", title="Add logging", tier=2, date="2026-05-30")
    assert id1 != id2


def test_tier2_date_appears_in_id() -> None:
    """Tier 2: the date appears literally in the generated id."""
    artifact_id = generate_artifact_id(
        type="code_review", title="Fix auth bug", tier=2, date="2026-05-30"
    )
    assert "2026-05-30" in artifact_id


def test_tier2_type_appears_in_id() -> None:
    """Tier 2: a slug derived from the type appears in the generated id."""
    artifact_id = generate_artifact_id(
        type="code_review", title="Fix auth bug", tier=2, date="2026-05-30"
    )
    # type slug converts underscores to hyphens
    assert "code-review" in artifact_id or "code_review" in artifact_id


# ---------------------------------------------------------------------------
# generate_artifact_id — Tier 3
# ---------------------------------------------------------------------------


def test_tier3_same_inputs_same_id() -> None:
    """Tier 3: same type + title → deterministic, same id (date ignored)."""
    id1 = generate_artifact_id(type="adr", title="Use postgres", tier=3, date="2026-05-30")
    id2 = generate_artifact_id(type="adr", title="Use postgres", tier=3, date="2026-05-30")
    assert id1 == id2


def test_tier3_date_not_a_factor() -> None:
    """Tier 3: different dates → same id (date is irrelevant for tier 3)."""
    id1 = generate_artifact_id(type="adr", title="Use postgres", tier=3, date="2026-05-30")
    id2 = generate_artifact_id(type="adr", title="Use postgres", tier=3, date="2026-06-15")
    assert id1 == id2


def test_tier3_different_title_different_id() -> None:
    """Tier 3: different title → different id."""
    id1 = generate_artifact_id(type="adr", title="Use postgres", tier=3, date="2026-05-30")
    id2 = generate_artifact_id(type="adr", title="Use mysql", tier=3, date="2026-05-30")
    assert id1 != id2


def test_tier3_date_not_in_id() -> None:
    """Tier 3: the date does NOT appear literally in the generated id."""
    artifact_id = generate_artifact_id(type="adr", title="Use postgres", tier=3, date="2026-05-30")
    assert "2026-05-30" not in artifact_id
    assert "2026" not in artifact_id


def test_tier3_learning_id_is_date_independent() -> None:
    """Tier 3 'learning': id is the date-independent {type_slug}-{title_slug}-{hash} form."""
    artifact_id = generate_artifact_id(
        type="learning", title="Project Learnings", tier=3, date="2026-06-15"
    )
    assert artifact_id.startswith("learning-project-learnings-")
    suffix = artifact_id.removeprefix("learning-project-learnings-")
    assert re.fullmatch(r"[0-9a-f]{8}", suffix), f"unexpected hash suffix: {suffix!r}"
    assert "2026" not in artifact_id


# ---------------------------------------------------------------------------
# Deterministic hash suffix disambiguates slug collisions
# ---------------------------------------------------------------------------


def test_cjk_titles_with_empty_slug_produce_distinct_ids() -> None:
    """Two titles with no Latin/digit content both fall back to 'artifact' slug,
    but the hash suffix (derived from the full original title) makes the ids distinct.
    """
    id1 = generate_artifact_id(type="adr", title="日本語のタイトル", tier=3, date="2026-05-30")
    id2 = generate_artifact_id(type="adr", title="中文标题", tier=3, date="2026-05-30")
    assert "artifact" in id1
    assert "artifact" in id2
    assert id1 != id2


def test_long_titles_differing_past_truncation_point_produce_distinct_ids() -> None:
    """Two >60-char titles differing only after the truncation point → distinct ids."""
    title1 = "a" * 60 + "one"
    title2 = "a" * 60 + "two"
    id1 = generate_artifact_id(type="adr", title=title1, tier=3, date="2026-05-30")
    id2 = generate_artifact_id(type="adr", title=title2, tier=3, date="2026-05-30")
    assert id1 != id2


def test_punctuation_collapse_titles_produce_distinct_ids() -> None:
    """Titles that normalise to the same slug via punctuation collapse → distinct ids."""
    id1 = generate_artifact_id(
        type="code_review", title="Auth: Module Review", tier=2, date="2026-05-30"
    )
    id2 = generate_artifact_id(
        type="code_review", title="Auth module (review)", tier=2, date="2026-05-30"
    )
    assert id1 != id2


def test_hash_suffix_is_deterministic_across_calls() -> None:
    """Same title → same hash suffix (and same id) across repeated calls."""
    id1 = generate_artifact_id(type="adr", title="Determinism check", tier=3, date="2026-05-30")
    id2 = generate_artifact_id(type="adr", title="Determinism check", tier=3, date="2026-05-30")
    assert id1 == id2


def test_tier2_id_ends_with_eight_char_hex_hash_suffix() -> None:
    """Tier 2 id format is {type_slug}-{date}-{title_slug}-{hash}; hash is 8 hex chars."""
    artifact_id = generate_artifact_id(
        type="code_review", title="Fix auth bug", tier=2, date="2026-05-30"
    )
    suffix = artifact_id.rsplit("-", 1)[-1]
    assert re.fullmatch(r"[0-9a-f]{8}", suffix), f"unexpected hash suffix: {suffix!r}"


# ---------------------------------------------------------------------------
# generate_artifact_id — format invariants
# ---------------------------------------------------------------------------


def test_id_is_s3_safe_characters() -> None:
    """Generated id contains only S3-safe characters: alphanumeric, -, _, ."""
    artifact_id = generate_artifact_id(
        type="code_review", title="Fix auth bug!", tier=2, date="2026-05-30"
    )
    assert _S3_SAFE_PATTERN.match(artifact_id), f"Unsafe chars in id: {artifact_id!r}"


def test_id_does_not_start_with_slash() -> None:
    """Generated id does not start with /."""
    artifact_id = generate_artifact_id(
        type="code_review", title="Fix auth bug", tier=2, date="2026-05-30"
    )
    assert not artifact_id.startswith("/")


def test_id_does_not_end_with_slash() -> None:
    """Generated id does not end with /."""
    artifact_id = generate_artifact_id(
        type="code_review", title="Fix auth bug", tier=2, date="2026-05-30"
    )
    assert not artifact_id.endswith("/")


def test_whitespace_only_title_produces_valid_id() -> None:
    """Title with only whitespace → fallback id is a non-empty string."""
    artifact_id = generate_artifact_id(type="adr", title="   ", tier=2, date="2026-05-30")
    assert isinstance(artifact_id, str)
    assert len(artifact_id) > 0
    assert _S3_SAFE_PATTERN.match(artifact_id), f"Unsafe chars in id: {artifact_id!r}"


def test_unicode_title_produces_ascii_safe_id() -> None:
    """Title with Unicode accented chars → id is ASCII-safe."""
    artifact_id = generate_artifact_id(
        type="spec", title="Réponse système", tier=2, date="2026-05-30"
    )
    # All characters should be ASCII (no accented chars in id)
    artifact_id.encode("ascii")  # raises UnicodeEncodeError if non-ASCII
    assert _S3_SAFE_PATTERN.match(artifact_id), f"Unsafe chars in id: {artifact_id!r}"


def test_punctuation_only_title_uses_fallback() -> None:
    """Title that is all punctuation → id contains the fallback word 'artifact'."""
    artifact_id = generate_artifact_id(type="spec", title="!!!", tier=2, date="2026-05-30")
    assert "artifact" in artifact_id


def test_long_title_slug_is_truncated() -> None:
    """Long title (200 chars) → the title slug portion is ≤ 60 characters.

    Tier-3 format: {type_slug}-{title_slug}-{hash}. The hash suffix is a fixed-width
    8-hex-char segment separated by its own hyphen, so it is stripped from the end
    before isolating the title slug for the length assertion.
    """
    long_title = "a" * 200
    artifact_id = generate_artifact_id(type="adr", title=long_title, tier=3, date="2026-05-30")
    without_hash = artifact_id.rsplit("-", 1)[0]
    # Strip the type prefix to isolate the title slug
    parts = without_hash.split("-", 1)
    title_slug_part = parts[1] if len(parts) > 1 else without_hash
    assert len(title_slug_part) <= 60


# ---------------------------------------------------------------------------
# section_slug
# ---------------------------------------------------------------------------


def test_section_slug_lowercase() -> None:
    """section_slug lowercases the heading."""
    assert section_slug("Summary") == "summary"


def test_section_slug_spaces_to_hyphens() -> None:
    """section_slug converts spaces to hyphens."""
    assert section_slug("Root Cause") == "root-cause"


def test_section_slug_non_alphanumeric_to_hyphens() -> None:
    """section_slug replaces non-alphanumeric chars with hyphens."""
    result = section_slug("Fix: auth bug!")
    assert re.match(r"^[a-z0-9-]+$", result)


def test_section_slug_collapses_consecutive_hyphens() -> None:
    """section_slug collapses consecutive hyphens into one."""
    result = section_slug("Fix -- auth -- bug")
    assert "--" not in result


def test_section_slug_strips_leading_trailing_hyphens() -> None:
    """section_slug strips leading and trailing hyphens."""
    result = section_slug("  --hello--  ")
    assert not result.startswith("-")
    assert not result.endswith("-")


def test_section_slug_empty_string_fallback() -> None:
    """section_slug on empty string → fallback 'section'."""
    assert section_slug("") == "section"


def test_section_slug_punctuation_only_fallback() -> None:
    """section_slug on punctuation-only input → fallback 'section'."""
    assert section_slug("!!!") == "section"


def test_section_slug_unicode_transliterated() -> None:
    """section_slug transliterates unicode to ASCII."""
    result = section_slug("Résumé")
    result.encode("ascii")  # raises if non-ASCII
    assert len(result) > 0


# ---------------------------------------------------------------------------
# parse_sections
# ---------------------------------------------------------------------------


def test_parse_sections_no_headings_returns_empty() -> None:
    """Content with no ## headings → empty list."""
    result = parse_sections("Just some text without headings.\n\nMore text.")
    assert result == []


def test_parse_sections_one_heading() -> None:
    """Content with one ## heading → one ArtifactSection with correct heading and body."""
    content = "## Summary\n\nAll looks good."
    result = parse_sections(content)
    assert len(result) == 1
    assert result[0].heading == "Summary"
    assert "All looks good." in result[0].body


def test_parse_sections_three_headings_in_order() -> None:
    """Content with three ## headings → three sections returned in document order."""
    content = "## First\n\nbody one\n\n## Second\n\nbody two\n\n## Third\n\nbody three"
    result = parse_sections(content)
    assert len(result) == 3
    assert result[0].heading == "First"
    assert result[1].heading == "Second"
    assert result[2].heading == "Third"


def test_parse_sections_body_excludes_heading_line() -> None:
    """Section body does NOT include the ## heading line itself."""
    content = "## Summary\n\nBody content here."
    result = parse_sections(content)
    assert "## Summary" not in result[0].body
    assert "Summary" not in result[0].body.split("\n")[0]


def test_parse_sections_content_before_first_heading_excluded() -> None:
    """Content before the first ## heading is NOT included in any section."""
    content = "Preamble text.\n\n## Summary\n\nBody content."
    result = parse_sections(content)
    assert len(result) == 1
    assert "Preamble" not in result[0].body


def test_parse_sections_heading_trailing_whitespace_stripped() -> None:
    """## heading with trailing whitespace → heading is stripped in result."""
    content = "## Summary   \n\nBody."
    result = parse_sections(content)
    assert result[0].heading == "Summary"


def test_parse_sections_deeper_headings_not_section_boundaries() -> None:
    """### and deeper headings inside a section body are NOT treated as boundaries."""
    content = "## Summary\n\n### Sub\n\nSub body.\n\n## Next\n\nNext body."
    result = parse_sections(content)
    assert len(result) == 2
    assert "### Sub" in result[0].body
    assert "Sub body." in result[0].body


def test_parse_sections_multiline_body_preserved() -> None:
    """Section body content is preserved across multiple lines."""
    body_lines = "Line one.\nLine two.\nLine three."
    content = f"## Section\n\n{body_lines}"
    result = parse_sections(content)
    assert "Line one." in result[0].body
    assert "Line two." in result[0].body
    assert "Line three." in result[0].body


def test_parse_sections_returns_artifact_section_instances() -> None:
    """parse_sections returns ArtifactSection objects."""
    content = "## Section\n\nBody."
    result = parse_sections(content)
    assert len(result) == 1
    assert isinstance(result[0], ArtifactSection)


def test_parse_sections_h2_inside_backtick_fence_not_treated_as_boundary() -> None:
    """## line inside a triple-backtick fence is NOT a section boundary."""
    content = "## Real\n\nText.\n\n```python\n## fake heading\ncode\n```\n\n## Also Real\n\nMore."
    result = parse_sections(content)
    assert len(result) == 2
    assert result[0].heading == "Real"
    assert result[1].heading == "Also Real"
    # The fake heading should appear in the body of the "Real" section (as fence content)
    assert "## fake heading" in result[0].body


def test_parse_sections_h2_inside_tilde_fence_not_treated_as_boundary() -> None:
    """## line inside a triple-tilde fence is NOT a section boundary."""
    content = "## Section\n\n~~~\n## not a heading\n~~~\n\n## Next\n\nContent."
    result = parse_sections(content)
    assert len(result) == 2
    assert result[0].heading == "Section"
    assert result[1].heading == "Next"


def test_parse_sections_fence_closed_restores_h2_detection() -> None:
    """## lines after a closed fence ARE treated as section boundaries."""
    content = "## Before\n\n```\n## inside fence\n```\n\n## After\n\ntext."
    result = parse_sections(content)
    assert len(result) == 2
    assert result[0].heading == "Before"
    assert result[1].heading == "After"
    # Fence content is part of "Before"'s body
    assert "## inside fence" in result[0].body


def test_parse_sections_unclosed_fence_suppresses_h2_inside() -> None:
    """## lines after an unclosed fence (no closing ```) are not section boundaries."""
    content = "## Before\n\n```\n## inside unclosed fence\n\n## also inside\n"
    result = parse_sections(content)
    assert len(result) == 1
    assert result[0].heading == "Before"


# ---------------------------------------------------------------------------
# Artifact model validation
# ---------------------------------------------------------------------------


def test_artifact_valid_constructs() -> None:
    """Valid kwargs → Artifact constructs without error."""
    artifact = Artifact(**VALID_ARTIFACT_KWARGS)
    assert artifact.title == "Fix auth bug"


def test_artifact_description_exactly_280_chars_valid() -> None:
    """Description exactly 280 chars → valid."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "description": "x" * 280}
    Artifact(**kwargs)  # must not raise


def test_artifact_description_281_chars_invalid() -> None:
    """Description 281 chars → ValidationError."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "description": "x" * 281}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


def test_artifact_unknown_type_invalid() -> None:
    """Unknown type 'unknown_type' → ValidationError."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "type": "unknown_type"}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


@pytest.mark.parametrize(
    "artifact_type",
    [
        "brainstorming",
        "code_review",
        "session_summary",
        "implementation_note",
        "spec",
        "adr",
        "bug_report",
        "decision_note",
        "synthesis",
        "changelog",
        "plan",
        "postmortem",
        "prd",
        "runbook",
        "learning",
    ],
)
def test_artifact_all_valid_types_accepted(artifact_type: str) -> None:
    """All 15 valid artifact types are accepted."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "type": artifact_type}
    artifact = Artifact(**kwargs)
    assert artifact.type == artifact_type


def test_artifact_tier_0_invalid() -> None:
    """tier=0 → ValidationError."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "tier": 0}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


def test_artifact_tier_1_invalid() -> None:
    """tier=1 → ValidationError."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "tier": 1}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


def test_artifact_tier_4_invalid() -> None:
    """tier=4 → ValidationError."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "tier": 4}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


def test_artifact_tier_2_valid() -> None:
    """tier=2 → accepted."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "tier": 2}
    artifact = Artifact(**kwargs)
    assert artifact.tier == 2


def test_artifact_tier_3_valid() -> None:
    """tier=3 → accepted."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "tier": 3}
    artifact = Artifact(**kwargs)
    assert artifact.tier == 3


def test_artifact_tier_bool_invalid() -> None:
    """tier=True (bool, not int) → ValidationError.

    ``tier`` uses ``Field(strict=True)`` so non-int types are rejected
    outright rather than silently coerced. ``bool`` is a subclass of ``int`` in
    Python, so this specifically exercises that pydantic's strict-int mode still
    rejects it (bools are excluded from strict-int coercion).
    """
    kwargs = {**VALID_ARTIFACT_KWARGS, "tier": True}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


def test_artifact_tier_float_invalid() -> None:
    """tier=2.0 (float, not int) → ValidationError.

    ``Field(strict=True)`` on ``tier`` rejects a float even when its
    value would otherwise be a valid tier — the type itself must be int.
    """
    kwargs = {**VALID_ARTIFACT_KWARGS, "tier": 2.0}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


def test_artifact_tier_numeric_string_invalid() -> None:
    """tier="2" (numeric string, not int) → ValidationError.

    Root cause: pydantic's default lax mode would silently coerce this
    to the valid int 2, masking a caller's type mistake. ``Field(strict=True)``
    rejects it instead.
    """
    kwargs = {**VALID_ARTIFACT_KWARGS, "tier": "2"}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


def test_artifact_visibility_public_invalid() -> None:
    """visibility='public' → ValidationError."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "visibility": "public"}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


def test_artifact_visibility_shared_valid() -> None:
    """visibility='shared' → accepted."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "visibility": "shared"}
    artifact = Artifact(**kwargs)
    assert artifact.visibility == "shared"


def test_artifact_visibility_hidden_valid() -> None:
    """visibility='hidden' → accepted."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "visibility": "hidden"}
    artifact = Artifact(**kwargs)
    assert artifact.visibility == "hidden"


def test_artifact_visibility_confidential_invalid() -> None:
    """visibility='confidential' → ValidationError (renamed to 'hidden')."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "visibility": "confidential"}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


def test_artifact_status_pending_invalid() -> None:
    """status='pending' → ValidationError."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "status": "pending"}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


def test_artifact_status_active_valid() -> None:
    """status='active' → accepted."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "status": "active"}
    artifact = Artifact(**kwargs)
    assert artifact.status == "active"


def test_artifact_status_inactive_valid() -> None:
    """status='inactive' → accepted."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "status": "inactive"}
    artifact = Artifact(**kwargs)
    assert artifact.status == "inactive"


def test_artifact_tags_defaults_to_empty_list() -> None:
    """tags absent → defaults to []."""
    artifact = Artifact(**VALID_ARTIFACT_KWARGS)
    assert artifact.tags == []


def test_artifact_author_role_defaults_to_none() -> None:
    """author_role absent → defaults to None."""
    artifact = Artifact(**VALID_ARTIFACT_KWARGS)
    assert artifact.author_role is None


def test_artifact_source_artifacts_defaults_to_empty_list() -> None:
    """source_artifacts absent → defaults to []."""
    artifact = Artifact(**VALID_ARTIFACT_KWARGS)
    assert artifact.source_artifacts == []


def test_artifact_synthesis_with_empty_source_artifacts_valid() -> None:
    """synthesis type with source_artifacts=[] → valid (not required to be non-empty)."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "type": "synthesis", "source_artifacts": []}
    Artifact(**kwargs)  # must not raise


def test_artifact_tier3_with_source_artifacts_valid() -> None:
    """tier=3 with source_artifacts set → valid."""
    kwargs = {
        **VALID_ARTIFACT_KWARGS,
        "tier": 3,
        "source_artifacts": ["artifacts/some-other-artifact"],
    }
    artifact = Artifact(**kwargs)
    assert len(artifact.source_artifacts) == 1


# ---------------------------------------------------------------------------
# Spec 16 — Date field validation
# ---------------------------------------------------------------------------


def test_artifact_valid_iso_date_accepted() -> None:
    """Valid ISO-8601 date '2026-05-31' → constructs without error."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "date": "2026-05-31"}
    Artifact(**kwargs)  # must not raise


def test_artifact_invalid_date_string_rejected() -> None:
    """Invalid date string 'not-a-date' → ValidationError."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "date": "not-a-date"}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


def test_artifact_invalid_month_rejected() -> None:
    """Month 13 in date → ValidationError."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "date": "2026-13-01"}
    with pytest.raises(ValidationError):
        Artifact(**kwargs)


# ---------------------------------------------------------------------------
# T36 — commit_refs field
# ---------------------------------------------------------------------------


def test_artifact_commit_refs_with_values_stored_correctly() -> None:
    """commit_refs=["abc1234"] → stored as ["abc1234"] on the model."""
    artifact = Artifact(**{**VALID_ARTIFACT_KWARGS, "commit_refs": ["abc1234"]})
    assert artifact.commit_refs == ["abc1234"]


def test_artifact_commit_refs_defaults_to_empty_list() -> None:
    """commit_refs absent → defaults to []."""
    artifact = Artifact(**VALID_ARTIFACT_KWARGS)
    assert artifact.commit_refs == []


# ---------------------------------------------------------------------------
# T55 — TITLE_MAX_LENGTH
# ---------------------------------------------------------------------------


def test_title_at_max_length_valid() -> None:
    """title exactly TITLE_MAX_LENGTH chars → constructs without error."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "title": "x" * TITLE_MAX_LENGTH}
    artifact = Artifact(**kwargs)
    assert len(artifact.title) == TITLE_MAX_LENGTH


def test_title_over_max_length_rejected() -> None:
    """title one char over TITLE_MAX_LENGTH → ValidationError naming the bound and length."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "title": "x" * (TITLE_MAX_LENGTH + 1)}
    with pytest.raises(ValidationError, match=str(TITLE_MAX_LENGTH)):
        Artifact(**kwargs)


# ---------------------------------------------------------------------------
# T55 — control-character rejection (reject, not strip)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("control_char", ["\n", "\t", "\r", "\x00", "\x7f"])
def test_title_with_control_char_rejected(control_char: str) -> None:
    """A control character (newline, tab, CR, NUL, DEL) in title → ValidationError."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "title": f"Bad{control_char}title"}
    with pytest.raises(ValidationError, match="title"):
        Artifact(**kwargs)


def test_description_with_control_char_rejected() -> None:
    """A control character in description → ValidationError naming the field."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "description": "Bad\ndescription"}
    with pytest.raises(ValidationError, match="description"):
        Artifact(**kwargs)


def test_author_role_with_control_char_rejected() -> None:
    """A control character in author_role → ValidationError naming the field."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "author_role": "dev\x00eloper"}
    with pytest.raises(ValidationError, match="author_role"):
        Artifact(**kwargs)


def test_author_role_none_with_no_control_char_check_error() -> None:
    """author_role=None is unaffected by the control-char validator."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "author_role": None}
    artifact = Artifact(**kwargs)
    assert artifact.author_role is None


def test_tags_element_with_control_char_rejected() -> None:
    """A control character in a tags element → ValidationError naming the field."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "tags": ["auth", "sec\nurity"]}
    with pytest.raises(ValidationError, match="tags"):
        Artifact(**kwargs)


def test_source_artifacts_element_with_control_char_rejected() -> None:
    """A control character in a source_artifacts element → ValidationError naming the field."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "source_artifacts": ["adr-\x01one"]}
    with pytest.raises(ValidationError, match="source_artifacts"):
        Artifact(**kwargs)


def test_commit_refs_element_with_control_char_rejected() -> None:
    """A control character in a commit_refs element → ValidationError naming the field."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "commit_refs": ["abc1234\t"]}
    with pytest.raises(ValidationError, match="commit_refs"):
        Artifact(**kwargs)


def test_commit_refs_element_with_comma_rejected() -> None:
    """A literal comma in a commit_refs element diverges the two link-field
    stores — the S3 annotation payload comma-joins list elements (encode_link_list),
    so a comma inside an element would decode back into extra elements. Rejected at
    validation time rather than switching the encoding."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "commit_refs": ["abc,1234"]}
    with pytest.raises(ValidationError, match="commit_refs"):
        Artifact(**kwargs)


# ---------------------------------------------------------------------------
# T46 — references field
# ---------------------------------------------------------------------------


def test_artifact_references_with_values_stored_correctly() -> None:
    """references=["adr-use-postgres-abc12345"] → stored as-is on the model."""
    artifact = Artifact(**{**VALID_ARTIFACT_KWARGS, "references": ["adr-use-postgres-abc12345"]})
    assert artifact.references == ["adr-use-postgres-abc12345"]


def test_artifact_references_defaults_to_empty_list() -> None:
    """references absent → defaults to []."""
    artifact = Artifact(**VALID_ARTIFACT_KWARGS)
    assert artifact.references == []


def test_references_element_with_control_char_rejected() -> None:
    """A control character in a references element → ValidationError naming the field."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "references": ["adr-one\t"]}
    with pytest.raises(ValidationError, match="references"):
        Artifact(**kwargs)


def test_references_element_with_comma_rejected() -> None:
    """A literal comma in a references element diverges the two link-field
    stores — mirrors the commit_refs comma rejection."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "references": ["adr-one,adr-two"]}
    with pytest.raises(ValidationError, match="references"):
        Artifact(**kwargs)


# ---------------------------------------------------------------------------
# T55 — non-Latin title accepted and preserved (Story 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "non_latin_title",
    ["日本語のタイトル", "Заголовок на русском", "عنوان عربي"],
)
def test_non_latin_title_accepted_and_preserved(non_latin_title: str) -> None:
    """Non-Latin titles (Japanese, Cyrillic, Arabic) are accepted and stored verbatim."""
    kwargs = {**VALID_ARTIFACT_KWARGS, "title": non_latin_title}
    artifact = Artifact(**kwargs)
    assert artifact.title == non_latin_title


# ---------------------------------------------------------------------------
# T55 — encode_metadata_value / decode_metadata_value (lossless transport encoding)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "café",
        "A title — with em dash",
        "日本語のタイトル",
        "Заголовок",
        "100% done",
        "plain ascii, no surprises",
        "",
    ],
)
def test_encode_decode_metadata_value_round_trips(value: str) -> None:
    """decode_metadata_value(encode_metadata_value(x)) == x for any input, including
    non-ASCII text and literal '%' characters."""
    assert decode_metadata_value(encode_metadata_value(value)) == value


def test_encode_metadata_value_output_is_header_safe_ascii() -> None:
    """encode_metadata_value output contains only printable ASCII — safe for an HTTP header
    value — even when the input has non-ASCII and control characters."""
    encoded = encode_metadata_value("日本語\n\x00タイトル")
    encoded.encode("ascii")  # raises UnicodeEncodeError if non-ASCII
    assert all(0x20 <= ord(ch) <= 0x7E for ch in encoded)


def test_encode_metadata_value_leaves_plain_ascii_unchanged() -> None:
    """Plain ASCII text without '%' passes through encode_metadata_value unchanged."""
    value = "Plain ASCII Title, with punctuation!"
    assert encode_metadata_value(value) == value


def test_decode_metadata_value_legacy_literal_percent_sequence_is_an_accepted_ambiguity() -> None:
    """A legacy (pre-T55) value stored raw — before
    encode_metadata_value existed — can legitimately contain a literal '%' followed by
    hex-like characters (e.g. a title mentioning "%25" as literal text). Naively, this
    looks fixable by having decode_metadata_value skip values that were never encoded.
    It is not: encode_metadata_value("Q3 % growth report") also produces the exact
    stored string "Q3 %25 growth report" (because '%' is itself always escaped, per
    its docstring), so decode_metadata_value cannot distinguish "legacy raw text
    containing a literal %25" from "T55-encoded text whose original had a literal %"
    — the two possible original values are genuinely indistinguishable from the stored
    byte string alone. Resolving this would require a persistent per-object encoding-
    version marker (an ADR-level schema decision, out of scope for this fix cycle) —
    not a decode.py-local heuristic. This is accepted as a documented limitation:
    decode_metadata_value keeps unconditionally percent-decoding, which is correct for
    every T55+-written value and only mis-decodes the narrow legacy case above."""
    legacy_raw_value = "Q3 %25 growth report"

    # Documents current (accepted) behaviour, not a fix: this corrupts the legacy
    # literal "%25" to "%", which is the same output encode_metadata_value("Q3 %
    # growth report") would also decode back to correctly (see docstring above).
    assert decode_metadata_value(legacy_raw_value) == "Q3 % growth report"


# ---------------------------------------------------------------------------
# T55 — check_metadata_budgets: three byte budgets, representation-driven
# ---------------------------------------------------------------------------

_MINIMAL_S3_METADATA: dict[str, str] = {"title": "ok", "type": "adr"}
_MINIMAL_VECTOR_METADATA: dict[str, object] = {"title": "ok", "type": "adr"}


def test_check_metadata_budgets_passes_within_all_three_budgets() -> None:
    """Small, well-within-budget metadata dicts → no exception raised."""
    check_metadata_budgets(_MINIMAL_S3_METADATA, _MINIMAL_VECTOR_METADATA)


def test_check_metadata_budgets_s3_budget_exceeded_raises() -> None:
    """s3_metadata aggregate > S3_USER_METADATA_MAX_BYTES → MetadataTooLargeError naming
    the s3_user_metadata budget."""
    oversize_s3 = {"description": "x" * (S3_USER_METADATA_MAX_BYTES + 1)}
    with pytest.raises(MetadataTooLargeError) as exc_info:
        check_metadata_budgets(oversize_s3, _MINIMAL_VECTOR_METADATA)
    assert exc_info.value.budget == "s3_user_metadata"


def test_check_metadata_budgets_s3_budget_just_under_passes() -> None:
    """s3_metadata aggregate exactly at the budget boundary → no exception."""
    # Single key "d" (1 byte) + value sized so total == S3_USER_METADATA_MAX_BYTES exactly.
    value_len = S3_USER_METADATA_MAX_BYTES - 1
    s3_meta = {"d": "x" * value_len}
    check_metadata_budgets(s3_meta, _MINIMAL_VECTOR_METADATA)


def test_check_metadata_budgets_vector_filterable_exceeded_raises() -> None:
    """A large filterable vector field (not in NON_FILTERABLE_METADATA_KEYS) pushing the
    filterable JSON past VECTOR_FILTERABLE_METADATA_MAX_BYTES → MetadataTooLargeError naming
    the vector_filterable_metadata budget, even though the S3 dict is tiny."""
    oversize_vector = {
        "title": "ok",  # non-filterable — must NOT count toward the filterable budget
        "tags": ["x" * (VECTOR_FILTERABLE_METADATA_MAX_BYTES + 1)],
    }
    with pytest.raises(MetadataTooLargeError) as exc_info:
        check_metadata_budgets(_MINIMAL_S3_METADATA, oversize_vector)
    assert exc_info.value.budget == "vector_filterable_metadata"


def test_check_metadata_budgets_non_filterable_fields_excluded_from_filterable_budget() -> None:
    """A huge NON_FILTERABLE_METADATA_KEYS field (e.g. description) does not, by itself,
    breach the filterable budget — only the total budget is representation-driven over
    the full dict."""
    huge_description = "x" * (VECTOR_FILTERABLE_METADATA_MAX_BYTES + 500)
    vector_meta = {"title": "ok", "description": huge_description}
    assert "description" in NON_FILTERABLE_METADATA_KEYS
    # Must not raise for the filterable budget (total budget is also not breached at this size).
    check_metadata_budgets(_MINIMAL_S3_METADATA, vector_meta)


def test_check_metadata_budgets_vector_total_exceeded_raises() -> None:
    """Full vector metadata JSON > VECTOR_TOTAL_METADATA_MAX_BYTES → MetadataTooLargeError
    naming the vector_total_metadata budget."""
    oversize_vector = {
        "title": "ok",
        "description": "x" * (VECTOR_TOTAL_METADATA_MAX_BYTES + 1),
    }
    with pytest.raises(MetadataTooLargeError) as exc_info:
        check_metadata_budgets(_MINIMAL_S3_METADATA, oversize_vector)
    assert exc_info.value.budget == "vector_total_metadata"


def test_check_metadata_budgets_vector_total_just_under_passes() -> None:
    """Full vector metadata JSON just under VECTOR_TOTAL_METADATA_MAX_BYTES → no exception."""
    # Account for JSON overhead (quotes, braces, key names) by leaving headroom.
    vector_meta = {"title": "ok", "description": "x" * (VECTOR_TOTAL_METADATA_MAX_BYTES - 100)}
    check_metadata_budgets(_MINIMAL_S3_METADATA, vector_meta)


def test_check_metadata_budgets_cjk_filterable_field_under_true_byte_budget_passes() -> None:
    """json.dumps defaults to ensure_ascii=True, which escapes every
    non-ASCII character to a 6-byte \\uXXXX sequence before UTF-8 encoding — measuring
    the size of the *escaped* JSON representation, not the real UTF-8 byte size of the
    content. A CJK-heavy filterable field (e.g. tags) can be well under the true
    VECTOR_FILTERABLE_METADATA_MAX_BYTES budget yet still get rejected purely due to
    this escaping over-count. This value is deliberately picked so the escaped size
    exceeds the budget while the true UTF-8 size does not — it must be accepted."""
    cjk_tag = "日本語" * 150
    filterable_true_utf8_bytes = len(
        json.dumps({"type": "adr", "tags": [cjk_tag]}, ensure_ascii=False).encode("utf-8")
    )
    assert filterable_true_utf8_bytes < VECTOR_FILTERABLE_METADATA_MAX_BYTES, (
        "test fixture must be under the true UTF-8 budget to prove the over-count bug"
    )
    vector_meta = {"title": "ok", "type": "adr", "tags": [cjk_tag]}

    check_metadata_budgets(_MINIMAL_S3_METADATA, vector_meta)
