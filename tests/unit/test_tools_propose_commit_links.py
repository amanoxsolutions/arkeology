"""Unit tests for arkeology.tools.propose_commit_links.

Tests propose_commit_links() using moto-backed VectorsClientImpl and S3ClientImpl —
candidates are seeded into the vector index and their commit_refs into the durable S3
object annotations, their sole source of truth. No Bedrock calls.
"""

import math
from typing import Any

import pytest
from pytest_mock import MockerFixture

from arkeology.annotations import apply_link_annotations
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import CredentialError
from arkeology.tools.propose_commit_links import propose_commit_links
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
    "project": "arkeology",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "title": "Some review",
    "visibility": "shared",
    "tags": [],
    "author_role": "developer",
    "description": "A review.",
}


def _seed_standard(vectors: VectorsClientImpl, s3: S3ClientImpl) -> None:
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
    # artifact-C: own scope, new ULID, already linked. The annotation is the sole source
    # of truth for commit_refs; the vector copy below is the derived filter index.
    s3.put_object("artifacts/artifact-c", "Content.", {"title": "Artifact C"})
    apply_link_annotations(s3, "artifacts/artifact-c", commit_refs=["abc123"], references=[])
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
    s3_client: S3ClientImpl,
) -> None:
    """since_ulid=ULID_MID → only artifact-B returned (A too old, C linked, D foreign)."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2, s3_client)

    result = await propose_commit_links(
        settings=settings,
        s3=s3_client,
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
    s3_client: S3ClientImpl,
) -> None:
    """since_ulid beyond all ULIDs → proposed is [] (not an error)."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2, s3_client)

    # Use a ULID higher than ULID_HIGH so nothing qualifies
    future_ulid = "01ZZ0000000000000000000000"

    result = await propose_commit_links(
        settings=settings,
        s3=s3_client,
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
    s3_client: S3ClientImpl,
) -> None:
    """No since_ulid → A and B in proposed (C linked, D foreign)."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2, s3_client)

    result = await propose_commit_links(
        settings=settings,
        s3=s3_client,
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
    s3_client: S3ClientImpl,
) -> None:
    """All own-scope artifacts have commit_refs → proposed is []."""
    settings = _make_settings(monkeypatch)
    # Only seed artifact-C (linked)
    s3_client.put_object("artifacts/artifact-c", "Content.", {"title": "Artifact C"})
    apply_link_annotations(s3_client, "artifacts/artifact-c", commit_refs=["abc123"], references=[])
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
        s3=s3_client,
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
    s3_client: S3ClientImpl,
) -> None:
    """Response always includes 'commit_sha' matching the supplied value."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2, s3_client)

    result = await propose_commit_links(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    assert result["commit_sha"] == COMMIT_SHA


async def test_entry_has_required_fields(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Each proposed entry has artifact_id, title, type, last_edited_ulid, last_edited_at."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2, s3_client)

    result = await propose_commit_links(
        settings=settings,
        s3=s3_client,
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
    s3_client: S3ClientImpl,
) -> None:
    """Entry with known last_edited_ulid → last_edited_at is a non-empty ISO-8601 string."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2, s3_client)

    result = await propose_commit_links(
        settings=settings,
        s3=s3_client,
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
    s3_client: S3ClientImpl,
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
        s3=s3_client,
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
    s3_client: S3ClientImpl,
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
        s3=s3_client,
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
    s3_client: S3ClientImpl,
) -> None:
    """Foreign-scope artifact with no commit_refs is NOT in proposed."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2, s3_client)

    result = await propose_commit_links(
        settings=settings,
        s3=s3_client,
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
    s3_client: S3ClientImpl,
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
        s3=s3_client,
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
    s3_client: S3ClientImpl,
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
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    assert result.get("error") == "credential_error"


async def test_get_vectors_credential_error_returns_structured(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """get_vectors raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2, s3_client)
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
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    assert result.get("error") == "credential_error"


# ---------------------------------------------------------------------------
# T58 — eligibility is sourced from read_link_annotations, the sole source of truth,
# never from a single vector's meta
# ---------------------------------------------------------------------------


async def test_commit_refs_on_non_first_section_vector_excluded_from_proposed(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """A multi-section artifact whose vector-metadata commit_refs live on a section
    vector other than the one the initial dedup (seen_ids) happens to keep as
    representative is still correctly excluded from proposed — eligibility comes from
    annotations.read_link_annotations, the complete durable copy, never from the single
    representative vector's own meta."""
    settings = _make_settings(monkeypatch)
    artifact_id = "artifacts/multi-section-linked-elsewhere"
    s3_client.put_object(artifact_id, "Content.", {"title": "Multi-section"})
    apply_link_annotations(s3_client, artifact_id, commit_refs=["sha1"], references=[])
    meta_no_refs = {
        **_BASE_META,
        "artifact_id": artifact_id,
        "last_edited_ulid": ULID_HIGH,
        "title": "Multi-section linked on non-first vector",
    }
    meta_with_refs = {**meta_no_refs, "commit_refs": ["sha1"]}
    # Insertion order is the order get_vectors/list_vectors_by_metadata return them in
    # moto — the first-inserted vector (no commit_refs) is the one a naive
    # first-occurrence-wins dedup would have kept as representative.
    vectors_client_2.put_vector(f"{artifact_id}#aaa-summary", _unit_vec(3.1), meta_no_refs)
    vectors_client_2.put_vector(f"{artifact_id}#zzz-details", _unit_vec(3.2), meta_with_refs)

    result = await propose_commit_links(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    ids = [e["artifact_id"] for e in result["proposed"]]
    assert artifact_id not in ids


async def test_commit_refs_over_cap_still_excluded_from_proposed(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """An artifact whose full commit_refs (annotation-sourced) exceeds the 20-entry
    vector-metadata cap (Story 2) is still correctly excluded from proposed —
    eligibility is decided via the annotation-backed, uncapped union
    (read_link_annotations), never from the vector's already-capped copy alone.
    Asserts the annotation is actually consulted (not merely that the capped vector
    copy happens to already be non-empty)."""
    settings = _make_settings(monkeypatch)
    artifact_id = "artifacts/over-cap-linked"
    full_commit_refs = [f"sha{i:04d}" for i in range(25)]
    # Annotations are set on an existing S3 object — real S3 semantics.
    s3_client.put_object(artifact_id, "content", {})
    s3_client.put_object_annotation(artifact_id, "commit_refs", ",".join(full_commit_refs))
    meta = {
        **_BASE_META,
        "artifact_id": artifact_id,
        "last_edited_ulid": ULID_HIGH,
        "title": "Over-cap linked artifact",
        "commit_refs": full_commit_refs[-20:],  # simulates T58's vector-metadata cap
    }
    vectors_client_2.put_vector(f"{artifact_id}#summary", _unit_vec(4.1), meta)
    annotation_spy = mocker.spy(s3_client, "get_object_annotation")

    result = await propose_commit_links(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    ids = [e["artifact_id"] for e in result["proposed"]]
    assert artifact_id not in ids
    annotation_spy.assert_any_call(artifact_id, "commit_refs")


async def test_commit_refs_resolution_credential_error_returns_structured(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """A CredentialError raised while resolving a candidate's commit_refs (the
    per-candidate read_link_annotations call, not the initial
    list_vectors_by_metadata/get_vectors fetch) returns the same structured
    credential-error response as the other two CredentialError paths.

    Patches read_link_annotations itself (the collaborator propose_commit_links.py
    calls) rather than an underlying client method, so this test targets exactly the
    exception-handling contract this task adds, independent of annotations.py's own
    internal (and separately-tested) error handling.
    """
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2, s3_client)
    mocker.patch(
        "arkeology.tools.propose_commit_links.read_link_annotations",
        side_effect=CredentialError(
            message="Credential failure resolving commit_refs (simulated).",
            service="s3",
            original=Exception("simulated"),
        ),
    )

    result = await propose_commit_links(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    assert result.get("error") == "credential_error"


async def test_commit_refs_resolution_non_credential_error_aborts_the_call(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """A non-CredentialError raised while resolving one candidate's commit_refs aborts
    the call rather than degrading that candidate to commit_refs=[]. Annotations are the
    sole source of truth, so a degraded candidate would be indistinguishable from a
    genuinely unlinked one — artifact C, which really is linked, would be proposed for
    linking again on the strength of a transient error."""
    settings = _make_settings(monkeypatch)
    _seed_standard(vectors_client_2, s3_client)

    def _fake_read_link_annotations(
        s3_arg: S3ClientImpl, artifact_id: str
    ) -> tuple[list[str], list[str]]:
        if artifact_id == "artifacts/artifact-c":
            raise RuntimeError("transient (simulated)")
        return ([], [])

    mocker.patch(
        "arkeology.tools.propose_commit_links.read_link_annotations",
        side_effect=_fake_read_link_annotations,
    )

    result = await propose_commit_links(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        commit_sha=COMMIT_SHA,
    )

    assert result.get("error") == "internal_error"
    assert "proposed" not in result
