"""Unit tests for cairn_mcp.references — pure migration reference resolution helpers.

Maps to AC-58 (T51) and review finding C1: bounded path normalization, forward-safe
path->full-key map construction (the full S3 key is the operative artifact_id — see
C1), and reference resolution with http(s):// / unresolved passthrough. No AWS,
no I/O — every helper here is pure.
"""

import pytest

from cairn_mcp.artifact import generate_artifact_id
from cairn_mcp.errors import CairnError
from cairn_mcp.references import (
    ManifestEntry,
    build_path_to_id_map,
    join_reference_path,
    normalize_reference_path,
    resolve_reference,
)

# Write prefix used across tests — matches the documented WRITE_PREFIX convention
# (see setting-up-cairn skill) but any value proves the composition is parameterised.
_WRITE_PREFIX = "myteam/myproject"

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
# build_path_to_id_map — full-manifest, forward-safe (D4), full-key output (C1)
# ---------------------------------------------------------------------------


def test_build_path_to_id_map_matches_deterministic_generate_artifact_id() -> None:
    """The map's value for a path is the FULL S3 key — write_prefix + '/' + the bare
    id from generate_artifact_id + extension — not the bare id alone (C1). This is
    the exact composition write.py uses for the operative artifact_id."""
    entries = [_entry("docs/adr/001-use-s3.md", "adr", 3, "Use S3", "2026-01-01")]

    result = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    bare_id = generate_artifact_id(type="adr", tier=3, date="2026-01-01", title="Use S3")
    assert result == {"docs/adr/001-use-s3.md": f"{_WRITE_PREFIX}/{bare_id}.md"}


def test_build_path_to_id_map_full_key_matches_write_path_s3_key_form() -> None:
    """Red-first (C1): the map's full key for an entry must equal EXACTLY the
    f'{write_prefix}/{bare_id}{extension}' form write.py composes as its s3_key
    (write.py:342) and stores as the vector artifact_id (write.py:367) — the map must
    never emit the bare generate_artifact_id output on its own."""
    entries = [_entry("docs/spec/search.md", "spec", 3, "Search Spec", "2026-02-01")]

    result = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    bare_id = generate_artifact_id(type="spec", tier=3, date="2026-02-01", title="Search Spec")
    expected_full_key = f"{_WRITE_PREFIX}/{bare_id}.md"
    assert result["docs/spec/search.md"] == expected_full_key
    # The bare id alone (the pre-fix, dead-on-every-surface value) must NOT be what
    # is returned — this is exactly what C1 flagged as broken.
    assert result["docs/spec/search.md"] != bare_id


def test_build_path_to_id_map_derives_extension_from_path() -> None:
    """The file extension in the full key is derived from the manifest entry's own
    path (posixpath.splitext), not hardcoded to '.md'."""
    entries = [_entry("docs/notes/readme.txt", "session_summary", 2, "Readme", "2026-01-05")]

    result = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    bare_id = generate_artifact_id(
        type="session_summary", tier=2, date="2026-01-05", title="Readme"
    )
    assert result["docs/notes/readme.txt"] == f"{_WRITE_PREFIX}/{bare_id}.txt"


def test_build_path_to_id_map_defaults_extension_to_md_when_path_has_none() -> None:
    """A manifest path with no extension defaults to '.md' — mirroring write_artifact's
    own file_extension default."""
    entries = [_entry("docs/notes/README", "session_summary", 2, "Readme", "2026-01-05")]

    result = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    bare_id = generate_artifact_id(
        type="session_summary", tier=2, date="2026-01-05", title="Readme"
    )
    assert result["docs/notes/README"] == f"{_WRITE_PREFIX}/{bare_id}.md"


def test_build_path_to_id_map_forward_reference_present_regardless_of_order() -> None:
    """An entry scheduled later in the manifest is still present in the map (D4) —
    forward references resolve independently of write/entry order."""
    entries = [
        _entry("docs/a.md", "spec", 3, "A spec", "2026-01-01"),
        _entry("docs/decisions/b.md", "adr", 3, "B decision", "2026-01-02"),
    ]

    result = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    expected_b_bare_id = generate_artifact_id(
        type="adr", tier=3, date="2026-01-02", title="B decision"
    )
    assert result["docs/decisions/b.md"] == f"{_WRITE_PREFIX}/{expected_b_bare_id}.md"


def test_build_path_to_id_map_empty_manifest_returns_empty_map() -> None:
    """An empty manifest produces an empty map, not an error."""
    result = build_path_to_id_map([], write_prefix=_WRITE_PREFIX)

    assert result == {}


def test_build_path_to_id_map_normalizes_dot_slash_prefixed_manifest_path() -> None:
    """M13: a manifest entry whose own path is spelled with a leading './' must be
    keyed on its NORMALIZED form — the same form resolve_reference always normalizes
    its lookup candidate to — or the raw, unnormalized key never matches any lookup
    and the migration rewrite silently becomes a no-op."""
    entries = [_entry("./docs/adr/001-use-s3.md", "adr", 3, "Use S3", "2026-01-01")]

    result = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    assert "docs/adr/001-use-s3.md" in result
    assert "./docs/adr/001-use-s3.md" not in result


def test_build_path_to_id_map_normalizes_backslash_manifest_path() -> None:
    """A manifest entry spelled with backslash separators is keyed on its
    forward-slash-normalized form."""
    entries = [_entry("docs\\adr\\001-use-s3.md", "adr", 3, "Use S3", "2026-01-01")]

    result = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    assert "docs/adr/001-use-s3.md" in result
    assert "docs\\adr\\001-use-s3.md" not in result


def test_build_path_to_id_map_duplicate_normalized_path_signals_collision() -> None:
    """Phase-12 #23: two manifest entries whose paths normalize to the same key must
    not silently last-write-win with zero signal — the caller has no way to know one
    manifest entry's mapping was discarded. A genuine collision must raise a typed,
    catchable error rather than silently returning a map with the second entry's
    mapping only."""
    entries = [
        _entry("docs/adr/001-use-s3.md", "adr", 3, "First title", "2026-01-01"),
        # Normalizes to the identical key as above (leading './' stripped) but is a
        # distinct manifest entry describing a different artifact.
        _entry("./docs/adr/001-use-s3.md", "spec", 3, "Second title", "2026-01-02"),
    ]

    with pytest.raises(CairnError):
        build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)


# ---------------------------------------------------------------------------
# resolve_reference
# ---------------------------------------------------------------------------


def test_resolve_reference_resolves_matching_path() -> None:
    """A path present in the map (after bounded normalization) resolves to its id."""
    entries = [_entry("docs/adr/001-use-s3.md", "adr", 3, "Use S3", "2026-01-01")]
    path_to_id_map = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    result = resolve_reference("./docs/adr/001-use-s3.md", path_to_id_map)

    assert result == path_to_id_map["docs/adr/001-use-s3.md"]


def test_resolve_reference_forward_reference_resolves_regardless_of_order() -> None:
    """Story 1 (AC-58): a same-batch forward reference to an entry scheduled later in
    the manifest still resolves, because the map was built from the full manifest."""
    entries = [
        _entry("docs/a.md", "spec", 3, "A spec", "2026-01-01"),
        _entry("docs/decisions/b.md", "adr", 3, "B decision", "2026-01-02"),
    ]
    path_to_id_map = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    result = resolve_reference("docs/decisions/b.md", path_to_id_map)

    assert result == path_to_id_map["docs/decisions/b.md"]


@pytest.mark.parametrize("url", ["http://example.com/x", "https://example.com/x"])
def test_resolve_reference_returns_none_for_urls(url: str) -> None:
    """Story 2 (AC-58): http(s):// entries are never treated as path candidates, even
    when a same-named path happens to exist in the map."""
    path_to_id_map = {"docs/a.md": "spec-2026-01-01-a-spec-abcd1234"}

    result = resolve_reference(url, path_to_id_map)

    assert result is None


def test_resolve_reference_resolves_when_manifest_path_had_leading_dot_slash() -> None:
    """M13 end-to-end: a manifest whose path used a leading './' still resolves
    through resolve_reference (which always normalizes its own lookup candidate) once
    build_path_to_id_map normalizes its keys the same way — before the fix, the raw
    unnormalized map key never matched."""
    entries = [_entry("./docs/adr/001-use-s3.md", "adr", 3, "Use S3", "2026-01-01")]
    path_to_id_map = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    result = resolve_reference("docs/adr/001-use-s3.md", path_to_id_map)

    assert result is not None
    assert result == path_to_id_map["docs/adr/001-use-s3.md"]


def test_resolve_reference_returns_none_for_unresolved_path() -> None:
    """A path absent from the map returns None (unresolved fall-through, cluster E) —
    the caller is responsible for leaving the text untouched and reporting it."""
    path_to_id_map = {"docs/a.md": "spec-2026-01-01-a-spec-abcd1234"}

    result = resolve_reference("docs/missing.md", path_to_id_map)

    assert result is None


def test_resolve_reference_returns_none_when_match_requires_beyond_ceiling_normalization() -> None:
    """Story 3 (AC-58): a path that would only match after normalization beyond the
    bounded ceiling (e.g. '../' relative navigation) returns None rather than being
    repaired — no further transformation is attempted, when no referencing_file_path
    is supplied (the join step is opt-in via that parameter)."""
    path_to_id_map = {"docs/decisions/b.md": "adr-b-decision-abcd1234"}

    result = resolve_reference("../decisions/b.md", path_to_id_map)

    assert result is None


# ---------------------------------------------------------------------------
# join_reference_path — relative ('./', '../') path joining (C6 fix)
# ---------------------------------------------------------------------------


def test_join_reference_path_joins_dotdot_relative_against_referencing_directory() -> None:
    """A '../' relative reference joins against the referencing file's own directory,
    not the repo root."""
    result = join_reference_path("notes/A.md", "../decisions/B.md")

    assert result == "decisions/B.md"


def test_join_reference_path_joins_dot_relative_against_referencing_directory() -> None:
    """A './' relative reference joins against the referencing file's own directory."""
    result = join_reference_path("dir/A.md", "./sibling.md")

    assert result == "dir/sibling.md"


def test_join_reference_path_leaves_url_unchanged() -> None:
    """An http(s):// URL is never treated as a path candidate and passes through
    unchanged, regardless of the referencing file's location."""
    result = join_reference_path("notes/A.md", "https://example.com/x")

    assert result == "https://example.com/x"


def test_join_reference_path_leaves_repo_relative_non_dotted_path_unchanged() -> None:
    """A path that is already repo-relative (does not start with './' or '../') is not
    joined against the referencing file's directory — it is returned unchanged."""
    result = join_reference_path("notes/A.md", "docs/adr/001-use-s3.md")

    assert result == "docs/adr/001-use-s3.md"


def test_join_reference_path_escaping_repo_root_does_not_raise() -> None:
    """A '../' that escapes above the repo root normalizes to a path that still carries
    a leading '../' — which simply will not be present in any map — rather than
    raising."""
    result = join_reference_path("notes/A.md", "../../outside/C.md")

    assert result == "../outside/C.md"


# ---------------------------------------------------------------------------
# resolve_reference — relative-path join wiring (C6 fix, T51 Story 1)
# ---------------------------------------------------------------------------


def test_resolve_reference_joins_dotdot_relative_against_referencing_file() -> None:
    """T51 Story 1 (AC-58): '../decisions/B.md' referenced from 'notes/A.md' joins to
    'decisions/B.md' before the map lookup and resolves to B's id — a same-batch
    forward reference using a well-formed relative path (C6 fix: relative references
    now resolve instead of falling through as unresolvable)."""
    entries = [_entry("decisions/B.md", "adr", 3, "B decision", "2026-01-02")]
    path_to_id_map = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    result = resolve_reference(
        "../decisions/B.md", path_to_id_map, referencing_file_path="notes/A.md"
    )

    assert result == path_to_id_map["decisions/B.md"]


def test_resolve_reference_joins_dot_relative_against_referencing_file() -> None:
    """'./sibling.md' referenced from 'dir/A.md' joins to 'dir/sibling.md' before the
    map lookup and resolves to the sibling's id."""
    entries = [_entry("dir/sibling.md", "spec", 3, "Sibling", "2026-01-01")]
    path_to_id_map = build_path_to_id_map(entries, write_prefix=_WRITE_PREFIX)

    result = resolve_reference("./sibling.md", path_to_id_map, referencing_file_path="dir/A.md")

    assert result == path_to_id_map["dir/sibling.md"]


def test_resolve_reference_escaping_root_relative_path_stays_unresolved() -> None:
    """A '../' path that escapes above the repo root joins to a path absent from any
    map and resolves to None — no exception is raised."""
    path_to_id_map = {"decisions/b.md": "adr-b-decision-abcd1234"}

    result = resolve_reference(
        "../../outside.md", path_to_id_map, referencing_file_path="notes/A.md"
    )

    assert result is None


@pytest.mark.parametrize("url", ["http://example.com/x", "https://example.com/x"])
def test_resolve_reference_url_passthrough_unaffected_by_referencing_file_path(
    url: str,
) -> None:
    """http(s):// entries still resolve to None even when a referencing_file_path is
    supplied — URLs are never treated as path candidates, joined or not."""
    path_to_id_map = {"docs/a.md": "spec-2026-01-01-a-spec-abcd1234"}

    result = resolve_reference(url, path_to_id_map, referencing_file_path="notes/A.md")

    assert result is None
