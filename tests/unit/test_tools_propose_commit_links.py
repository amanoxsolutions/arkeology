"""Unit tests for cairn_mcp.tools.propose_commit_links.

Tests propose_commit_links() using moto-backed VectorsClientImpl.
No S3 or Bedrock calls — all data is seeded directly into the vector index.
"""

import math
from typing import Any

import pytest
from pytest_mock import MockerFixture

from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools.propose_commit_links import propose_commit_links
from tests.unit.conftest import _make_settings as _make_settings_base

# ---------------------------------------------------------------------------
# Deterministic ULID constants (generated once; LOW < MID < HIGH lexicographically)
# ---------------------------------------------------------------------------
# ULID_LOW  → 2026-01-01T00:00:00+00:00
# ULID_MID  → 2026-03-01T00:00:00+00:00
# ULID_HIGH → 2026-06-01T00:00:00+00:00
ULID_LOW = "01KDVDNA00FN74309G4MXHQ1KK"
ULID_MID = "01KJKB3Q00FN74309G4MXHQ1KM"
ULID_HIGH = "01KT07NV00FN74309G4MXHQ1KN"

COMMIT_SHA = "deadbeef1234"


# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, **overrides)


# ---------------------------------------------------------------------------
# Vector seed helpers
# ---------------------------------------------------------------------------


def _unit_vec(seed: float, dim: int = 2) -> list[float]:
    raw = [seed, seed + 0.1]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


_BASE_META: dict[str, Any] = {
    "scope": "artifacts",
    "type": "code_review",
    "team": "platform",
    "project": "cairn",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "title": "Some review",
    "visibility": "shared",
    "feature_tags": [],
    "author_role": "developer",
    "description": "A review.",
}


def _seed_standard(vectors: VectorsClientImpl) -> None:
    """Seed four artifacts as described in the spec.

    A: own-scope, ULID_LOW, no commit_refs  → candidate
    B: own-scope, ULID_HIGH, no commit_refs → candidate
    C: own-scope, ULID_HIGH, commit_refs=["abc123"] → linked, excluded
    D: foreign-scope, no commit_refs → foreign, excluded
    """
    # artifact-A: own scope, old ULID, no commit_refs
    # 'commit_refs' key absent — production write_artifact omits it when empty
    vectors.put_vector(
        "artifacts/artifact-a#summary",
        _unit_vec(1.0),
        {
            **_BASE_META,
            "artifact_id": "artifacts/artifact-a",
            "last_edited_ulid": ULID_LOW,
            "title": "Artifact A",
        },
    )
    # artifact-B: own scope, new ULID, no commit_refs
    # 'commit_refs' key absent — production write_artifact omits it when empty
    vectors.put_vector(
        "artifacts/artifact-b#summary",
        _unit_vec(0.9),
        {
            **_BASE_META,
            "artifact_id": "artifacts/artifact-b",
            "last_edited_ulid": ULID_HIGH,
            "title": "Artifact B",
        },
    )
    # artifact-C: own scope, new ULID, already linked
    vectors.put_vector(
        "artifacts/artifact-c#summary",
        _unit_vec(0.8),
        {
            **_BASE_META,
            "artifact_id": "artifacts/artifact-c",
            "last_edited_ulid": ULID_HIGH,
            "commit_refs": ["abc123"],
            "title": "Artifact C",
        },
    )
    # artifact-D: foreign scope, no commit_refs
    # 'commit_refs' key absent — production write_artifact omits it when empty
    vectors.put_vector(
        "other-team/artifact-d#summary",
        _unit_vec(0.7),
        {
            **_BASE_META,
            "artifact_id": "other-team/artifact-d",
            "scope": "other-team",
            "title": "Artifact D",
        },
    )


# ---------------------------------------------------------------------------
# Story 1 — since_ulid filters by time range
# ---------------------------------------------------------------------------


async def test_since_ulid_returns_only_b(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """since_ulid=ULID_MID → only artifact-B returned (A too old, C linked, D foreign)."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2)

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
        since_ulid=ULID_MID,
    )

    assert "proposed" in result
    ids = [e["artifact_id"] for e in result["proposed"]]
    assert "artifacts/artifact-b" in ids
    assert "artifacts/artifact-a" not in ids
    assert "artifacts/artifact-c" not in ids
    assert "other-team/artifact-d" not in ids


async def test_since_ulid_empty_range_returns_empty_proposed(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """since_ulid beyond all ULIDs → proposed is [] (not an error)."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2)

    # Use a ULID higher than ULID_HIGH so nothing qualifies
    future_ulid = "01ZZ0000000000000000000000"

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
        since_ulid=future_ulid,
    )

    assert result["proposed"] == []


# ---------------------------------------------------------------------------
# Story 2 — no since_ulid → all unlinked own-scope artifacts
# ---------------------------------------------------------------------------


async def test_no_since_ulid_returns_a_and_b(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """No since_ulid → A and B in proposed (C linked, D foreign)."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2)

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    assert "proposed" in result
    ids = [e["artifact_id"] for e in result["proposed"]]
    assert "artifacts/artifact-a" in ids
    assert "artifacts/artifact-b" in ids
    assert "artifacts/artifact-c" not in ids
    assert "other-team/artifact-d" not in ids


async def test_all_linked_returns_empty_proposed(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """All own-scope artifacts have commit_refs → proposed is []."""
    settings = _make_settings(monkeypatch)
    # Only seed artifact-C (linked)
    vectors_client_2.put_vector(
        "artifacts/artifact-c#summary",
        _unit_vec(0.8),
        {
            **_BASE_META,
            "artifact_id": "artifacts/artifact-c",
            "last_edited_ulid": ULID_HIGH,
            "commit_refs": ["abc123"],
            "title": "Artifact C",
        },
    )

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    assert result["proposed"] == []


# ---------------------------------------------------------------------------
# Story 3 — Response shape and human-readable timestamp
# ---------------------------------------------------------------------------


async def test_response_shape_has_commit_sha(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Response always includes 'commit_sha' matching the supplied value."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2)

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    assert result["commit_sha"] == COMMIT_SHA


async def test_entry_has_required_fields(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Each proposed entry has artifact_id, title, type, last_edited_ulid, last_edited_at."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2)

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    assert len(result["proposed"]) > 0
    required = ["artifact_id", "title", "type", "last_edited_ulid", "last_edited_at"]
    for entry in result["proposed"]:
        for field in required:
            assert field in entry, f"Missing field '{field}' in entry: {entry}"


async def test_entry_last_edited_at_is_iso8601(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Entry with known last_edited_ulid → last_edited_at is a non-empty ISO-8601 string."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2)

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    # artifact-A has ULID_LOW — check its last_edited_at
    entries = {e["artifact_id"]: e for e in result["proposed"]}
    assert "artifacts/artifact-a" in entries
    entry_a = entries["artifacts/artifact-a"]
    assert entry_a["last_edited_ulid"] == ULID_LOW
    assert entry_a["last_edited_at"] is not None
    assert isinstance(entry_a["last_edited_at"], str)
    assert "2026-01-01" in entry_a["last_edited_at"]  # matches ULID_LOW timestamp


# ---------------------------------------------------------------------------
# Artifact with no last_edited_ulid → null fields but still a candidate
# ---------------------------------------------------------------------------


async def test_missing_last_edited_ulid_yields_null_fields_and_is_candidate(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Artifact without last_edited_ulid → null fields; still proposed."""
    settings = _make_settings(monkeypatch)
    # Seed a legacy artifact without last_edited_ulid or commit_refs
    vectors_client_2.put_vector(
        "artifacts/legacy#summary",
        _unit_vec(0.5),
        {
            **_BASE_META,
            "artifact_id": "artifacts/legacy",
            "title": "Legacy artifact",
            # no last_edited_ulid, no commit_refs
        },
    )

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    ids = [e["artifact_id"] for e in result["proposed"]]
    assert "artifacts/legacy" in ids

    legacy = next(e for e in result["proposed"] if e["artifact_id"] == "artifacts/legacy")
    assert legacy["last_edited_ulid"] is None
    assert legacy["last_edited_at"] is None


async def test_legacy_artifact_excluded_when_since_ulid_provided(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Legacy artifact (no last_edited_ulid) is excluded when since_ulid is given.

    The $gte filter returns False for a None field value, so legacy artifacts
    can never satisfy last_edited_ulid >= since_ulid and must be absent from results.
    """
    settings = _make_settings(monkeypatch)
    # Legacy artifact: own-scope, no last_edited_ulid, no commit_refs
    vectors_client_2.put_vector(
        "artifacts/legacy#summary",
        _unit_vec(0.5),
        {
            **_BASE_META,
            "artifact_id": "artifacts/legacy",
            "title": "Legacy artifact",
            # no last_edited_ulid — pre-T36 artifact
        },
    )
    # Modern artifact: own-scope, ULID_HIGH, no commit_refs
    vectors_client_2.put_vector(
        "artifacts/modern#summary",
        _unit_vec(0.6),
        {
            **_BASE_META,
            "artifact_id": "artifacts/modern",
            "last_edited_ulid": ULID_HIGH,
            "title": "Modern artifact",
        },
    )

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
        since_ulid=ULID_MID,
    )

    ids = [e["artifact_id"] for e in result["proposed"]]
    assert "artifacts/legacy" not in ids, "Legacy artifact must be excluded by $gte filter"
    assert "artifacts/modern" in ids, "Modern artifact (ULID_HIGH >= ULID_MID) must be included"


# ---------------------------------------------------------------------------
# Story 4 — Foreign-scope excluded
# ---------------------------------------------------------------------------


async def test_foreign_scope_excluded(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Foreign-scope artifact with no commit_refs is NOT in proposed."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2)

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    ids = [e["artifact_id"] for e in result["proposed"]]
    assert "other-team/artifact-d" not in ids


# ---------------------------------------------------------------------------
# Deduplication — multiple section vectors collapse to one entry
# ---------------------------------------------------------------------------


async def test_multiple_section_vectors_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Two section vectors for same artifact → exactly one entry in proposed."""
    settings = _make_settings(monkeypatch)
    # 'commit_refs' key absent — production write_artifact omits it when empty
    meta = {
        **_BASE_META,
        "artifact_id": "artifacts/multi-section",
        "last_edited_ulid": ULID_HIGH,
        "title": "Multi-section artifact",
    }
    vectors_client_2.put_vector("artifacts/multi-section#summary", _unit_vec(1.1), meta)
    vectors_client_2.put_vector("artifacts/multi-section#details", _unit_vec(1.2), meta)

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    ids = [e["artifact_id"] for e in result["proposed"]]
    assert ids.count("artifacts/multi-section") == 1


# ---------------------------------------------------------------------------
# Story 5 — Credential failures return structured error
# ---------------------------------------------------------------------------


async def test_list_vectors_credential_error_returns_structured(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    mocker.patch.object(
        vectors_client_2,
        "list_vectors_by_metadata",
        side_effect=CredentialError(
            message="Credential failure (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    assert "error" in result


async def test_get_vectors_credential_error_returns_structured(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """get_vectors raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2)
    mocker.patch.object(
        vectors_client_2,
        "get_vectors",
        side_effect=CredentialError(
            message="Credential failure on get_vectors (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await propose_commit_links(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    assert "error" in result
