"""Unit tests for arkeology.resources.

All tests verify the five schema resources are correctly registered and that
their content functions return accurate, current information derived live from
ARTIFACT_TYPES.
"""

import asyncio

import fastmcp
import pytest

import arkeology.artifact as artifact_module
from arkeology.artifact import ARTIFACT_TYPES
from arkeology.resources import (
    _BROWSER_CDN_ORIGINS,
    artifact_schema_content,
    query_strategy_content,
    register_resources,
    register_ui_resource,
    tiers_schema_content,
    types_schema_content,
    visibility_schema_content,
)

# ---------------------------------------------------------------------------
# Registration — all five URIs present after register_resources(app)
# ---------------------------------------------------------------------------

_EXPECTED_URIS = {
    "arkeology://schema/artifact",
    "arkeology://schema/tiers",
    "arkeology://schema/visibility",
    "arkeology://schema/types",
    "arkeology://schema/query-strategy",
}


def test_register_resources_all_five_uris_present() -> None:
    """After register_resources(app), all five arkeology:// URIs are accessible."""
    # Arrange
    app = fastmcp.FastMCP(name="test-arkeology", version="0.0.0")

    # Act
    register_resources(app)

    # Assert — inspect registered resource URIs via asyncio list call
    resources = asyncio.run(app._list_resources())  # type: ignore[attr-defined]  # FastMCP 3.x exposes resources via _list_resources(); no public enumeration API exists
    registered_uris = {str(r.uri) for r in resources}
    for expected_uri in _EXPECTED_URIS:
        assert expected_uri in registered_uris, (
            f"Expected URI {expected_uri!r} not found in registered resources: {registered_uris}"
        )


# ---------------------------------------------------------------------------
# Content correctness — arkeology://schema/artifact
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = [
    "type",
    "team",
    "project",
    "tier",
    "date",
    "status",
    "title",
    "visibility",
    "description",
]
_OPTIONAL_FIELDS = ["tags", "author_role", "source_artifacts"]


def test_artifact_schema_content_is_nonempty() -> None:
    """artifact_schema_content() returns a non-empty string."""
    # Arrange / Act
    content = artifact_schema_content()

    # Assert
    assert isinstance(content, str)
    assert len(content) > 0


def test_artifact_schema_content_contains_required_fields() -> None:
    """artifact_schema_content() mentions every required field name."""
    # Arrange
    content = artifact_schema_content()

    # Assert — each required field name appears in the content
    for field in _REQUIRED_FIELDS:
        assert field in content, f"Required field {field!r} missing from artifact schema content"


def test_artifact_schema_content_contains_optional_fields() -> None:
    """artifact_schema_content() mentions every optional field name."""
    # Arrange
    content = artifact_schema_content()

    # Assert — each optional field name appears in the content
    for field in _OPTIONAL_FIELDS:
        assert field in content, f"Optional field {field!r} missing from artifact schema content"


def test_artifact_schema_content_contains_description_length_constraint() -> None:
    """artifact_schema_content() mentions the 280-character description constraint."""
    # Arrange
    content = artifact_schema_content()

    # Assert
    assert "280" in content, "Description length constraint (280) missing from artifact schema"


def test_artifact_schema_content_contains_all_artifact_types() -> None:
    """artifact_schema_content() includes every type from ARTIFACT_TYPES."""
    # Arrange
    content = artifact_schema_content()

    # Assert — every type in the live frozenset appears in the content
    for artifact_type in ARTIFACT_TYPES:
        assert artifact_type in content, (
            f"Artifact type {artifact_type!r} missing from artifact schema content"
        )


# ---------------------------------------------------------------------------
# Content correctness — arkeology://schema/tiers
# ---------------------------------------------------------------------------


def test_tiers_schema_content_is_nonempty() -> None:
    """tiers_schema_content() returns a non-empty string."""
    # Arrange / Act
    content = tiers_schema_content()

    # Assert
    assert isinstance(content, str)
    assert len(content) > 0


def test_tiers_schema_content_mentions_tier_2_and_tier_3() -> None:
    """tiers_schema_content() references both tier 2 and tier 3 (case-insensitive)."""
    # Arrange
    content = tiers_schema_content().lower()

    # Assert
    assert "tier 2" in content, "Tier 2 not mentioned in tiers schema content"
    assert "tier 3" in content, "Tier 3 not mentioned in tiers schema content"


def test_tiers_schema_content_mentions_immutable() -> None:
    """tiers_schema_content() uses the word 'immutable' (tier 2 append-only contract)."""
    # Arrange
    content = tiers_schema_content()

    # Assert
    assert "immutable" in content.lower(), "'immutable' missing from tiers schema content"


def test_tiers_schema_content_tier2_key_format_mentions_date() -> None:
    """tiers_schema_content() describes the tier 2 key format and mentions 'date'."""
    # Arrange
    content = tiers_schema_content()

    # Assert — tier 2 key format is date-anchored: {type_slug}-{date}-{title_slug}
    assert "date" in content, "Tier 2 key format ('date') missing from tiers schema content"


def test_tiers_schema_content_tier3_key_format_is_date_independent() -> None:
    """tiers_schema_content() indicates tier 3 key format is date-independent."""
    # Arrange
    content = tiers_schema_content().lower()

    # Assert — tier 3 omits date from key; content must communicate date-independence
    # Accept "date-independent", "no date", "without date", or "date-free"
    date_independent_signals = [
        "date-independent",
        "no date",
        "without date",
        "date free",
        "date_independent",
        "omits date",
        "excludes date",
        "independent of date",
    ]
    assert any(sig in content for sig in date_independent_signals), (
        "Tier 3 date-independence not expressed in tiers schema content"
    )


# ---------------------------------------------------------------------------
# Content correctness — arkeology://schema/visibility
# ---------------------------------------------------------------------------


def test_visibility_schema_content_is_nonempty() -> None:
    """visibility_schema_content() returns a non-empty string."""
    # Arrange / Act
    content = visibility_schema_content()

    # Assert
    assert isinstance(content, str)
    assert len(content) > 0


def test_visibility_schema_content_mentions_shared_and_hidden() -> None:
    """visibility_schema_content() describes both 'shared' and 'hidden' values."""
    # Arrange
    content = visibility_schema_content()

    # Assert
    assert "shared" in content, "'shared' missing from visibility schema content"
    assert "hidden" in content, "'hidden' missing from visibility schema content"


def test_visibility_schema_content_mentions_tier3_cross_scope_gate() -> None:
    """visibility_schema_content() names tier 3 as the cross-scope access gate."""
    # Arrange
    content = visibility_schema_content().lower()

    # Assert — only tier 3 shared artifacts cross scope boundaries
    assert "tier 3" in content, (
        "Cross-scope gate (tier 3) not mentioned in visibility schema content"
    )


# ---------------------------------------------------------------------------
# Content correctness — arkeology://schema/types
# ---------------------------------------------------------------------------


def test_types_schema_content_is_nonempty() -> None:
    """types_schema_content() returns a non-empty string."""
    # Arrange / Act
    content = types_schema_content()

    # Assert
    assert isinstance(content, str)
    assert len(content) > 0


def test_types_schema_content_contains_all_artifact_types() -> None:
    """types_schema_content() includes every type from ARTIFACT_TYPES."""
    # Arrange
    content = types_schema_content()

    # Assert — every live type appears in the catalogue
    for artifact_type in ARTIFACT_TYPES:
        assert artifact_type in content, (
            f"Artifact type {artifact_type!r} missing from types schema content"
        )


def test_types_schema_content_each_type_has_description() -> None:
    """types_schema_content() provides at least a one-line description per type."""
    # Arrange
    content = types_schema_content()

    # Assert — each type appears on a distinct line with surrounding text (not bare substring)
    for artifact_type in ARTIFACT_TYPES:
        # Find lines that contain this type; at least one line must have more than just the type
        lines_with_type = [line for line in content.splitlines() if artifact_type in line]
        assert len(lines_with_type) > 0, f"No line contains type {artifact_type!r}"
        # At least one such line should have other content too (description present)
        assert any(len(line.strip()) > len(artifact_type) for line in lines_with_type), (
            f"Type {artifact_type!r} appears without a description in types schema"
        )


# ---------------------------------------------------------------------------
# Content correctness — arkeology://schema/query-strategy
# ---------------------------------------------------------------------------


def test_query_strategy_content_is_nonempty() -> None:
    """query_strategy_content() returns a non-empty string."""
    # Arrange / Act
    content = query_strategy_content()

    # Assert
    assert isinstance(content, str)
    assert len(content) > 0


def test_query_strategy_content_mentions_type_filter() -> None:
    """query_strategy_content() mentions filtering by 'type'."""
    # Arrange
    content = query_strategy_content()

    # Assert
    assert "type" in content, "'type' filter guidance missing from query-strategy content"


def test_query_strategy_content_mentions_tags() -> None:
    """query_strategy_content() mentions 'tags' filtering."""
    # Arrange
    content = query_strategy_content()

    # Assert
    assert "tags" in content, "'tags' guidance missing from query-strategy content"


def test_query_strategy_content_mentions_synthesise_artifacts() -> None:
    """query_strategy_content() references the synthesise_artifacts tool."""
    # Arrange
    content = query_strategy_content()

    # Assert
    assert "synthesise_artifacts" in content, (
        "'synthesise_artifacts' missing from query-strategy content"
    )


def test_query_strategy_content_mentions_narrow_before_broad() -> None:
    """query_strategy_content() advises starting narrow and broadening when needed."""
    # Arrange
    content = query_strategy_content().lower()

    # Assert — look for 'narrow' and 'broad' as key guidance terms
    assert "narrow" in content, "Start-narrow guidance missing from query-strategy content"
    assert "broad" in content, "Broaden guidance missing from query-strategy content"


# ---------------------------------------------------------------------------
# UI resource — register_ui_resource
# ---------------------------------------------------------------------------


def test_register_ui_resource_returns_non_empty_html() -> None:
    """register_ui_resource(app) registers ui://arkeology-studio/index.html returning HTML."""
    # Arrange
    app = fastmcp.FastMCP(name="test-arkeology-ui", version="0.0.0")

    # Act
    register_ui_resource(app)

    # Assert — the resource is registered
    resources = asyncio.run(app._list_resources())  # type: ignore[attr-defined]
    registered_uris = {str(r.uri) for r in resources}
    assert "ui://arkeology-studio/index.html" in registered_uris, (
        f"Expected 'ui://arkeology-studio/index.html' not found in: {registered_uris}"
    )

    # Assert — the handler returns a non-empty string
    result = asyncio.run(app.read_resource("ui://arkeology-studio/index.html"))
    # FastMCP read_resource returns a ResourceResult with a 'contents' list.
    # Each item has a 'content' attribute (not 'text').
    contents = result.contents if hasattr(result, "contents") else []
    assert len(contents) > 0, (
        "Expected at least one content item from ui://arkeology-studio/index.html"
    )
    text = contents[0].content if hasattr(contents[0], "content") else ""
    assert isinstance(text, str) and len(text) > 0, f"Expected non-empty HTML string, got: {text!r}"


# ---------------------------------------------------------------------------
# CSP origins — Google Fonts must never be declared
# ---------------------------------------------------------------------------


def test_browser_csp_origins_are_exactly_unpkg_and_jsdelivr() -> None:
    """The arkeology studio CSP declares only the two CDN origins — no web-font origins.

    Loading web fonts from Google's CDN leaks the user's IP to a third party and is
    disallowed on GDPR grounds. The accepted set is
    exactly ``unpkg.com`` (ext-apps SDK) + ``cdn.jsdelivr.net`` (marked.js / mermaid.js).
    """
    assert _BROWSER_CDN_ORIGINS == [
        "https://unpkg.com",
        "https://cdn.jsdelivr.net",
    ]


def test_browser_csp_origins_exclude_google_fonts() -> None:
    """No Google Fonts origin appears in the CSP origin list (GDPR)."""
    forbidden = {"https://fonts.googleapis.com", "https://fonts.gstatic.com"}
    assert forbidden.isdisjoint(_BROWSER_CDN_ORIGINS), (
        f"Google Fonts origins must not be declared in the CSP: {_BROWSER_CDN_ORIGINS}"
    )


# ---------------------------------------------------------------------------
# Sync invariant — content functions derive live from ARTIFACT_TYPES
# ---------------------------------------------------------------------------


def test_artifact_schema_content_reflects_monkeypatched_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """artifact_schema_content() includes a new type after ARTIFACT_TYPES is patched."""
    # Arrange — add a fake type to ARTIFACT_TYPES
    fake_type = "fake_type_xyz"
    patched_types = ARTIFACT_TYPES | frozenset({fake_type})
    monkeypatch.setattr(artifact_module, "ARTIFACT_TYPES", patched_types)

    # Act — call the content function after patching
    # The function must read ARTIFACT_TYPES at call-time, not at import-time
    content = artifact_schema_content()

    # Assert
    assert fake_type in content, (
        "artifact_schema_content() does not reflect live ARTIFACT_TYPES after monkey-patch"
    )


def test_types_schema_content_reflects_monkeypatched_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """types_schema_content() includes a new type after ARTIFACT_TYPES is patched."""
    # Arrange — add a fake type to ARTIFACT_TYPES
    fake_type = "fake_type_xyz"
    patched_types = ARTIFACT_TYPES | frozenset({fake_type})
    monkeypatch.setattr(artifact_module, "ARTIFACT_TYPES", patched_types)

    # Act — call the content function after patching
    content = types_schema_content()

    # Assert
    assert fake_type in content, (
        "types_schema_content() does not reflect live ARTIFACT_TYPES after monkey-patch"
    )
