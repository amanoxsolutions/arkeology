"""Unit tests for cairn_mcp.artifact — Artifact model, key generation, section parsing.

Written first (TDD Red state) before artifact.py exists.
All tests must fail with ImportError until the module is implemented.
"""

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
# generate_artifact_id — key generation
# ---------------------------------------------------------------------------


class TestGenerateArtifactIdTier2:
    def test_same_inputs_same_id(self) -> None:
        """Tier 2: identical type + date + title → same artifact id."""
        kwargs = dict(tier=2, type="code_review", date="2026-05-30", title="Fix auth bug")
        id1 = generate_artifact_id(**kwargs)
        id2 = generate_artifact_id(**kwargs)
        assert id1 == id2

    def test_different_date_different_id(self) -> None:
        """Tier 2: different date → different artifact id."""
        id1 = generate_artifact_id(
            tier=2, type="code_review", date="2026-05-30", title="Fix auth bug"
        )
        id2 = generate_artifact_id(
            tier=2, type="code_review", date="2026-05-31", title="Fix auth bug"
        )
        assert id1 != id2

    def test_different_title_different_id(self) -> None:
        """Tier 2: different title, same type + date → different artifact id."""
        id1 = generate_artifact_id(
            tier=2, type="code_review", date="2026-05-30", title="Fix auth bug"
        )
        id2 = generate_artifact_id(
            tier=2, type="code_review", date="2026-05-30", title="Fix login bug"
        )
        assert id1 != id2

    def test_date_included_in_id(self) -> None:
        """Tier 2: the date appears in the returned id (human readable)."""
        artifact_id = generate_artifact_id(
            tier=2, type="code_review", date="2026-05-30", title="Fix auth bug"
        )
        assert "2026-05-30" in artifact_id

    def test_type_included_in_id(self) -> None:
        """Tier 2: the type appears in the returned id."""
        artifact_id = generate_artifact_id(
            tier=2, type="code_review", date="2026-05-30", title="Fix auth bug"
        )
        assert "code-review" in artifact_id or "code_review" in artifact_id


class TestGenerateArtifactIdTier3:
    def test_same_type_title_different_dates_same_id(self) -> None:
        """Tier 3: date is not a factor — same type + title always gives the same id."""
        id1 = generate_artifact_id(tier=3, type="adr", date="2026-05-30", title="Use Postgres")
        id2 = generate_artifact_id(tier=3, type="adr", date="2026-06-15", title="Use Postgres")
        assert id1 == id2

    def test_different_title_different_id(self) -> None:
        """Tier 3: different title → different artifact id."""
        id1 = generate_artifact_id(tier=3, type="adr", date="2026-05-30", title="Use Postgres")
        id2 = generate_artifact_id(tier=3, type="adr", date="2026-05-30", title="Use MySQL")
        assert id1 != id2

    def test_date_not_included_in_id(self) -> None:
        """Tier 3: the date must not appear in the returned id."""
        artifact_id = generate_artifact_id(
            tier=3, type="adr", date="2026-05-30", title="Use Postgres"
        )
        assert "2026-05-30" not in artifact_id


class TestGenerateArtifactIdSafeChars:
    def test_no_illegal_s3_characters(self) -> None:
        """Artifact id must contain only S3-safe characters: alphanumeric, -, _, ."""
        artifact_id = generate_artifact_id(
            tier=2, type="code_review", date="2026-05-30", title="Fix auth bug"
        )
        import re
        assert re.fullmatch(r"[a-z0-9\-_.]+", artifact_id), f"Unsafe chars in: {artifact_id}"

    def test_does_not_start_or_end_with_slash(self) -> None:
        """Artifact id must not begin or end with '/'."""
        artifact_id = generate_artifact_id(
            tier=2, type="code_review", date="2026-05-30", title="Fix auth bug"
        )
        assert not artifact_id.startswith("/")
        assert not artifact_id.endswith("/")


class TestGenerateArtifactIdEdgeCases:
    def test_whitespace_only_title_produces_valid_id(self) -> None:
        """Title of only whitespace → fallback slug, resulting in a non-empty valid id."""
        artifact_id = generate_artifact_id(
            tier=2, type="code_review", date="2026-05-30", title="   "
        )
        assert len(artifact_id) > 0
        assert not artifact_id.endswith("-")
        assert not artifact_id.startswith("-")

    def test_unicode_title_produces_safe_id(self) -> None:
        """Title with accented characters → transliterated to ASCII in the id."""
        artifact_id = generate_artifact_id(
            tier=2, type="adr", date="2026-05-30", title="Réponse système"
        )
        import re
        assert re.fullmatch(r"[a-z0-9\-_.]+", artifact_id), f"Unsafe chars in: {artifact_id}"

    def test_punctuation_only_title_uses_fallback(self) -> None:
        """Title that is all punctuation → fallback slug 'artifact'."""
        artifact_id = generate_artifact_id(
            tier=2, type="code_review", date="2026-05-30", title="!!!"
        )
        assert "artifact" in artifact_id

    def test_long_title_is_truncated(self) -> None:
        """Title slug is truncated to 60 characters maximum."""
        long_title = "a" * 200
        artifact_id = generate_artifact_id(
            tier=2, type="code_review", date="2026-05-30", title=long_title
        )
        # Strip the prefix (type-date-) and check slug portion ≤ 60
        # The full id is type-date-slug; slug starts after the second '-YYYY-MM-DD-'
        parts = artifact_id.split("-")
        # slug is everything after type and date components
        # type = "code-review" (2 parts), date = "2026-05-30" (3 parts), rest is slug
        slug_part = "-".join(parts[5:])  # skip: code, review, 2026, 05, 30
        assert len(slug_part) <= 60


# ---------------------------------------------------------------------------
# section_slug
# ---------------------------------------------------------------------------


class TestSectionSlug:
    def test_lowercase(self) -> None:
        assert section_slug("My Heading") == "my-heading"

    def test_spaces_become_hyphens(self) -> None:
        assert section_slug("hello world") == "hello-world"

    def test_non_alphanumeric_replaced(self) -> None:
        slug = section_slug("Hello, World!")
        assert slug == "hello-world"

    def test_consecutive_hyphens_collapsed(self) -> None:
        slug = section_slug("a  --  b")
        assert slug == "a-b"

    def test_leading_trailing_hyphens_stripped(self) -> None:
        slug = section_slug("!!hello!!")
        assert slug == "hello"

    def test_empty_heading_returns_fallback(self) -> None:
        slug = section_slug("")
        assert len(slug) > 0
        assert slug == "section"

    def test_punctuation_only_returns_fallback(self) -> None:
        slug = section_slug("---")
        assert slug == "section"

    def test_unicode_transliterated(self) -> None:
        slug = section_slug("Résumé")
        assert "e" in slug
        import re
        assert re.fullmatch(r"[a-z0-9\-]+", slug), f"Unsafe chars in slug: {slug}"


# ---------------------------------------------------------------------------
# parse_sections
# ---------------------------------------------------------------------------


class TestParseSections:
    def test_no_h2_headings_returns_empty_list(self) -> None:
        content = "Some content without any headings.\n\nAnother paragraph."
        assert parse_sections(content) == []

    def test_one_h2_returns_one_section(self) -> None:
        content = "Preamble\n\n## My Heading\n\nBody text here."
        sections = parse_sections(content)
        assert len(sections) == 1
        assert sections[0].heading == "My Heading"
        assert "Body text here." in sections[0].body

    def test_three_h2_returns_three_sections_in_order(self) -> None:
        content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B.\n\n## Gamma\n\nBody C."
        sections = parse_sections(content)
        assert len(sections) == 3
        assert sections[0].heading == "Alpha"
        assert sections[1].heading == "Beta"
        assert sections[2].heading == "Gamma"

    def test_section_body_excludes_heading_line(self) -> None:
        content = "## My Heading\n\nBody text."
        sections = parse_sections(content)
        assert "## My Heading" not in sections[0].body

    def test_content_before_first_h2_excluded(self) -> None:
        content = "Preamble before any heading.\n\n## First Section\n\nBody."
        sections = parse_sections(content)
        assert len(sections) == 1
        assert "Preamble before any heading." not in sections[0].body

    def test_h2_with_trailing_whitespace_normalised(self) -> None:
        content = "## My Heading   \n\nBody text."
        sections = parse_sections(content)
        assert sections[0].heading == "My Heading"

    def test_h3_inside_section_is_not_a_boundary(self) -> None:
        content = "## Section One\n\n### Sub-heading\n\nMore text.\n\n## Section Two\n\nBody."
        sections = parse_sections(content)
        assert len(sections) == 2
        assert "### Sub-heading" in sections[0].body
        assert "More text." in sections[0].body

    def test_section_body_content_preserved(self) -> None:
        content = "## Heading\n\nLine one.\nLine two.\n"
        sections = parse_sections(content)
        assert "Line one." in sections[0].body
        assert "Line two." in sections[0].body

    def test_returns_artifact_section_objects(self) -> None:
        content = "## Only Section\n\nBody."
        sections = parse_sections(content)
        assert isinstance(sections[0], ArtifactSection)


# ---------------------------------------------------------------------------
# Artifact model validation
# ---------------------------------------------------------------------------

VALID_ARTIFACT_KWARGS: dict = {
    "type": "code_review",
    "team": "platform",
    "project": "cairn",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "title": "Fix auth bug",
    "description": "Review of the authentication module.",
    "content": "## Summary\n\nAll looks good.",
    "visibility": "shared",
}


class TestArtifactValidation:
    def test_valid_artifact_constructs_without_error(self) -> None:
        artifact = Artifact(**VALID_ARTIFACT_KWARGS)
        assert artifact.title == "Fix auth bug"

    def test_description_exactly_280_chars_is_valid(self) -> None:
        Artifact(**{**VALID_ARTIFACT_KWARGS, "description": "x" * 280})

    def test_description_over_280_chars_raises(self) -> None:
        with pytest.raises(ValidationError):
            Artifact(**{**VALID_ARTIFACT_KWARGS, "description": "x" * 281})

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            Artifact(**{**VALID_ARTIFACT_KWARGS, "type": "unknown_type"})

    def test_all_valid_types_accepted(self) -> None:
        valid_types = [
            "code_review",
            "session_summary",
            "implementation_note",
            "spec",
            "adr",
            "bug_report",
            "decision_note",
            "synthesis",
        ]
        for t in valid_types:
            Artifact(**{**VALID_ARTIFACT_KWARGS, "type": t})

    def test_invalid_tier_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            Artifact(**{**VALID_ARTIFACT_KWARGS, "tier": 0})

    def test_invalid_tier_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            Artifact(**{**VALID_ARTIFACT_KWARGS, "tier": 1})

    def test_invalid_tier_four_raises(self) -> None:
        with pytest.raises(ValidationError):
            Artifact(**{**VALID_ARTIFACT_KWARGS, "tier": 4})

    def test_valid_tiers_accepted(self) -> None:
        for tier in (2, 3):
            Artifact(**{**VALID_ARTIFACT_KWARGS, "tier": tier})

    def test_invalid_visibility_raises(self) -> None:
        with pytest.raises(ValidationError):
            Artifact(**{**VALID_ARTIFACT_KWARGS, "visibility": "public"})

    def test_valid_visibility_values(self) -> None:
        for vis in ("shared", "confidential"):
            Artifact(**{**VALID_ARTIFACT_KWARGS, "visibility": vis})

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            Artifact(**{**VALID_ARTIFACT_KWARGS, "status": "pending"})

    def test_valid_status_values(self) -> None:
        for status in ("active", "inactive"):
            Artifact(**{**VALID_ARTIFACT_KWARGS, "status": status})

    def test_feature_tags_defaults_to_empty_list(self) -> None:
        artifact = Artifact(**VALID_ARTIFACT_KWARGS)
        assert artifact.feature_tags == []

    def test_author_role_defaults_to_none(self) -> None:
        artifact = Artifact(**VALID_ARTIFACT_KWARGS)
        assert artifact.author_role is None

    def test_source_artifacts_defaults_to_empty_list(self) -> None:
        artifact = Artifact(**VALID_ARTIFACT_KWARGS)
        assert artifact.source_artifacts == []

    def test_synthesis_with_empty_source_artifacts_is_valid(self) -> None:
        Artifact(**{**VALID_ARTIFACT_KWARGS, "type": "synthesis", "source_artifacts": []})

    def test_tier3_with_source_artifacts_is_valid(self) -> None:
        Artifact(
            **{
                **VALID_ARTIFACT_KWARGS,
                "tier": 3,
                "source_artifacts": ["artifacts/adr-use-postgres"],
            }
        )
