"""Unit tests for cairn_mcp.references — pure migration reference resolution helpers.

Maps to AC-58 (T51): bounded path normalization, forward-safe path->artifact_id map
construction, and reference resolution with http(s):// / unresolved passthrough. No AWS,
no I/O — every helper here is pure.
"""

import pytest

from cairn_mcp.artifact import generate_artifact_id
from cairn_mcp.references import (
    ManifestEntry,
    build_path_to_id_map,
    normalize_reference_path,
    resolve_reference,
)

# ---------------------------------------------------------------------------
# Shared fixture helper
# ---------------------------------------------------------------------------


def _entry(path: str, artifact_type: str, tier: int, title: str, date: str) -> ManifestEntry:
    return {"path": path, "type": artifact_type, "tier": tier, "title": title, "date": date}


# ---------------------------------------------------------------------------
# normalize_reference_path — bounded ceiling (D6)
# ---------------------------------------------------------------------------


def test_normalize_reference_path_converts_backslashes_to_forward_slashes() -> None:
    """Windows-style backslash separators are converted to forward slashes."""
    result = normalize_reference_path("docs\\adr\\001-use-s3.md")

    assert result == "docs/adr/001-use-s3.md"


def test_normalize_reference_path_strips_dot_slash_prefix() -> None:
    """A leading './' is stripped."""
    result = normalize_reference_path("./docs/adr/001-use-s3.md")

    assert result == "docs/adr/001-use-s3.md"


def test_normalize_reference_path_strips_single_leading_slash() -> None:
    """A single leading '/' is stripped."""
    result = normalize_reference_path("/docs/adr/001-use-s3.md")

    assert result == "docs/adr/001-use-s3.md"


def test_normalize_reference_path_no_prefix_is_unchanged() -> None:
    """A path with none of the recognised prefixes passes through unchanged."""
    result = normalize_reference_path("docs/adr/001-use-s3.md")

    assert result == "docs/adr/001-use-s3.md"


def test_normalize_reference_path_backslash_and_dot_prefix_combined() -> None:
    """Backslash conversion is applied before the leading './' strip."""
    result = normalize_reference_path(".\\docs\\adr\\001-use-s3.md")

    assert result == "docs/adr/001-use-s3.md"


def test_normalize_reference_path_does_not_repair_beyond_ceiling() -> None:
    """Relative '../' navigation is NOT resolved — beyond the bounded ceiling, so the
    path is returned unchanged rather than repaired (D6: no further transformation)."""
    result = normalize_reference_path("../decisions/b.md")

    assert result == "../decisions/b.md"


# ---------------------------------------------------------------------------
# build_path_to_id_map — full-manifest, forward-safe (D4)
# ---------------------------------------------------------------------------


def test_build_path_to_id_map_matches_deterministic_generate_artifact_id() -> None:
    """The map's id for a path matches generate_artifact_id computed directly with the
    same attributes — the map must not invent its own id scheme."""
    entries = [_entry("docs/adr/001-use-s3.md", "adr", 3, "Use S3", "2026-01-01")]

    result = build_path_to_id_map(entries)

    expected_id = generate_artifact_id(type="adr", tier=3, date="2026-01-01", title="Use S3")
    assert result == {"docs/adr/001-use-s3.md": expected_id}


def test_build_path_to_id_map_forward_reference_present_regardless_of_order() -> None:
    """An entry scheduled later in the manifest is still present in the map (D4) —
    forward references resolve independently of write/entry order."""
    entries = [
        _entry("docs/a.md", "spec", 3, "A spec", "2026-01-01"),
        _entry("docs/decisions/b.md", "adr", 3, "B decision", "2026-01-02"),
    ]

    result = build_path_to_id_map(entries)

    expected_b_id = generate_artifact_id(type="adr", tier=3, date="2026-01-02", title="B decision")
    assert result["docs/decisions/b.md"] == expected_b_id


def test_build_path_to_id_map_empty_manifest_returns_empty_map() -> None:
    """An empty manifest produces an empty map, not an error."""
    result = build_path_to_id_map([])

    assert result == {}


# ---------------------------------------------------------------------------
# resolve_reference
# ---------------------------------------------------------------------------


def test_resolve_reference_resolves_matching_path() -> None:
    """A path present in the map (after bounded normalization) resolves to its id."""
    entries = [_entry("docs/adr/001-use-s3.md", "adr", 3, "Use S3", "2026-01-01")]
    path_to_id_map = build_path_to_id_map(entries)

    result = resolve_reference("./docs/adr/001-use-s3.md", path_to_id_map)

    assert result == path_to_id_map["docs/adr/001-use-s3.md"]


def test_resolve_reference_forward_reference_resolves_regardless_of_order() -> None:
    """Story 1 (AC-58): a same-batch forward reference to an entry scheduled later in
    the manifest still resolves, because the map was built from the full manifest."""
    entries = [
        _entry("docs/a.md", "spec", 3, "A spec", "2026-01-01"),
        _entry("docs/decisions/b.md", "adr", 3, "B decision", "2026-01-02"),
    ]
    path_to_id_map = build_path_to_id_map(entries)

    result = resolve_reference("docs/decisions/b.md", path_to_id_map)

    assert result == path_to_id_map["docs/decisions/b.md"]


@pytest.mark.parametrize("url", ["http://example.com/x", "https://example.com/x"])
def test_resolve_reference_returns_none_for_urls(url: str) -> None:
    """Story 2 (AC-58): http(s):// entries are never treated as path candidates, even
    when a same-named path happens to exist in the map."""
    path_to_id_map = {"docs/a.md": "spec-2026-01-01-a-spec-abcd1234"}

    result = resolve_reference(url, path_to_id_map)

    assert result is None


def test_resolve_reference_returns_none_for_unresolved_path() -> None:
    """A path absent from the map returns None (unresolved fall-through, cluster E) —
    the caller is responsible for leaving the text untouched and reporting it."""
    path_to_id_map = {"docs/a.md": "spec-2026-01-01-a-spec-abcd1234"}

    result = resolve_reference("docs/missing.md", path_to_id_map)

    assert result is None


def test_resolve_reference_returns_none_when_match_requires_beyond_ceiling_normalization() -> None:
    """Story 3 (AC-58): a path that would only match after normalization beyond the
    bounded ceiling (e.g. '../' relative navigation) returns None rather than being
    repaired — no further transformation is attempted."""
    path_to_id_map = {"docs/decisions/b.md": "adr-b-decision-abcd1234"}

    result = resolve_reference("../decisions/b.md", path_to_id_map)

    assert result is None
