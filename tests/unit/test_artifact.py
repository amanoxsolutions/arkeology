"""Unit tests for cairn_mcp.artifact (TDD Red phase — module does not exist yet).

All tests in this file are expected to fail with ImportError until the
implementation is created.
"""

import re

import pytest
from pydantic import ValidationError

from cairn_mcp.artifact import (
    Artifact,
    ArtifactSection,
    generate_artifact_id,
    parse_sections,
    section_slug,
)

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

VALID_ARTIFACT_KWARGS: dict = {
    "type": "code_review",
    "team": "platform",
    "project": "cairn",
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
    """Long title (200 chars) → the title slug portion is ≤ 60 characters."""
    long_title = "a" * 200
    artifact_id = generate_artifact_id(type="adr", title=long_title, tier=3, date="2026-05-30")
    # Strip the type prefix to isolate the title slug
    # Tier-3 format: {type_slug}-{title_slug}
    parts = artifact_id.split("-", 1)
    title_slug_part = parts[1] if len(parts) > 1 else artifact_id
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
        "code_review",
        "session_summary",
        "implementation_note",
        "spec",
        "adr",
        "bug_report",
        "decision_note",
        "synthesis",
    ],
)
def test_artifact_all_valid_types_accepted(artifact_type: str) -> None:
    """All 8 valid artifact types are accepted."""
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


def test_artifact_feature_tags_defaults_to_empty_list() -> None:
    """feature_tags absent → defaults to []."""
    artifact = Artifact(**VALID_ARTIFACT_KWARGS)
    assert artifact.feature_tags == []


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
