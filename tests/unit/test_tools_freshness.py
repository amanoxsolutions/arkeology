"""Unit tests for cairn_mcp.tools.freshness.

Tests check_synthesis_freshness() using FakeS3Client + FakeVectorsClient.
All tests run without real AWS calls. This file is intentionally written before the
implementation (Red phase of TDD) — the import below will fail until
src/cairn_mcp/tools/freshness.py is created.
"""

from typing import Any

import pytest

from cairn_mcp.clients.fakes.fake_s3 import FakeS3Client
from cairn_mcp.clients.fakes.fake_vectors import FakeVectorsClient
from cairn_mcp.config import Settings

# Implementation import — will fail until src/cairn_mcp/tools/freshness.py is created
from cairn_mcp.tools.freshness import check_synthesis_freshness

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIMENSION = 8
DUMMY_VEC = [1.0] + [0.0] * (DIMENSION - 1)

# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-bucket")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")
    monkeypatch.setenv("WRITE_PREFIX", "artifacts")
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    return Settings()


# ---------------------------------------------------------------------------
# Metadata factory helpers
# ---------------------------------------------------------------------------


def _synthesis_meta(
    artifact_id: str,
    date: str,
    source_artifacts: list[str],
    scope: str = "artifacts",
    status: str = "active",
) -> dict[str, Any]:
    """Build vector metadata for a synthesis artifact."""
    meta: dict[str, Any] = {
        "artifact_id": artifact_id,
        "scope": scope,
        "type": "synthesis",
        "status": status,
        "date": date,
        "title": "Test Synthesis",
        "team": "platform",
        "project": "cairn",
        "tier": 3,
        "visibility": "shared",
        "description": "A test synthesis artifact.",
    }
    # Mirror write.py: omit source_artifacts when empty (S3 Vectors rejects empty arrays)
    if source_artifacts:
        meta["source_artifacts"] = source_artifacts
    return meta


def _source_meta(
    artifact_id: str,
    date: str,
    status: str = "active",
    scope: str = "artifacts",
) -> dict[str, Any]:
    """Build vector metadata for a source artifact."""
    return {
        "artifact_id": artifact_id,
        "scope": scope,
        "type": "implementation_note",
        "status": status,
        "date": date,
        "title": "Test Source",
        "team": "platform",
        "project": "cairn",
        "tier": 2,
        "visibility": "shared",
        "description": "A test source artifact.",
    }


_MALFORMED_S3_META: dict[str, str] = {
    "type": "synthesis",
    "team": "platform",
    "project": "cairn",
    "tier": "3",
    "date": "2026-01-01",
    "status": "active",
    "title": "Malformed Synthesis",
    "visibility": "shared",
    "feature_tags": "",
    "author_role": "",
    "description": "A synthesis with no source artifacts.",
    "source_artifacts": "",
}


# ---------------------------------------------------------------------------
# Helper: check whether a filter expression queries for a specific artifact_id
# ---------------------------------------------------------------------------


def _filter_matches_artifact_id(filter_expr: dict[str, Any], artifact_id: str) -> bool:
    """Return True iff filter_expr is a direct $eq lookup for the given artifact_id."""
    if "artifact_id" in filter_expr:
        eq_val = filter_expr["artifact_id"].get("$eq")
        return eq_val == artifact_id
    if "$and" in filter_expr:
        return any(
            _filter_matches_artifact_id(clause, artifact_id)
            for clause in filter_expr["$and"]
        )
    return False


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


async def test_empty_state_no_synthesis_all_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No synthesis artifacts in index → total_checked=0, all_fresh=True, all lists empty."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    assert result["total_checked"] == 0
    assert result["all_fresh"] is True
    assert result["stale"] == []
    assert result["archived_sources"] == []
    assert result["missing_sources"] == []


# ---------------------------------------------------------------------------
# All-fresh state
# ---------------------------------------------------------------------------


async def test_all_fresh_two_sources_both_older_and_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One synthesis, two sources both older than synthesis date, both active → all_fresh=True."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-all-fresh"
    src1_id = "artifacts/implementation-note-2026-01-01-source-a"
    src2_id = "artifacts/implementation-note-2026-02-01-source-b"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-06-01", [src1_id, src2_id]),
    )
    vectors.put_vector(src1_id, DUMMY_VEC, _source_meta(src1_id, "2026-01-01"))
    vectors.put_vector(src2_id, DUMMY_VEC, _source_meta(src2_id, "2026-02-01"))

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    assert result["all_fresh"] is True
    assert result["stale"] == []
    assert result["archived_sources"] == []


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------


async def test_stale_source_newer_than_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis date 2026-01-01, source date 2026-06-01 → synthesis in stale;
    source listed in stale_sources."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-stale-by-date"
    src_id = "artifacts/implementation-note-2026-01-01-newer-source"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-01-01", [src_id]),
    )
    vectors.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-06-01"))

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    stale_ids = [e["artifact_id"] for e in result["stale"]]
    assert synth_id in stale_ids
    stale_entry = next(e for e in result["stale"] if e["artifact_id"] == synth_id)
    assert src_id in stale_entry["stale_sources"]


async def test_stale_two_sources_only_newer_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two sources — one newer, one older than synthesis → only newer source in stale_sources."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-partial-stale"
    newer_src = "artifacts/implementation-note-2026-01-01-newer"
    older_src = "artifacts/implementation-note-2026-01-01-older"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-03-01", [newer_src, older_src]),
    )
    vectors.put_vector(newer_src, DUMMY_VEC, _source_meta(newer_src, "2026-06-01"))
    vectors.put_vector(older_src, DUMMY_VEC, _source_meta(older_src, "2026-01-01"))

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    stale_entry = next((e for e in result["stale"] if e["artifact_id"] == synth_id), None)
    assert stale_entry is not None
    assert newer_src in stale_entry["stale_sources"]
    assert older_src not in stale_entry["stale_sources"]


async def test_stale_same_day_not_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis date equals source date → NOT reported as stale (strict > comparison required)."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-same-day"
    src_id = "artifacts/implementation-note-2026-03-15-same-day-src"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-03-15", [src_id]),
    )
    vectors.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-03-15"))

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    stale_ids = [e["artifact_id"] for e in result["stale"]]
    assert synth_id not in stale_ids


# ---------------------------------------------------------------------------
# Archived source detection
# ---------------------------------------------------------------------------


async def test_archived_source_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis referencing source with status='inactive' → synthesis appears
    in archived_sources."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-with-archived-source"
    src_id = "artifacts/adr-archived-decision"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-06-01", [src_id]),
    )
    vectors.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-01-01", status="inactive"))

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    archived_ids = [e["artifact_id"] for e in result["archived_sources"]]
    assert synth_id in archived_ids
    archived_entry = next(e for e in result["archived_sources"] if e["artifact_id"] == synth_id)
    assert src_id in archived_entry["archived_sources"]


async def test_source_both_newer_and_archived_appears_in_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source both newer AND archived → synthesis appears in both stale and archived_sources."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-both-issues"
    src_id = "artifacts/adr-newer-and-archived"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-01-01", [src_id]),
    )
    # Source is both newer (date > synthesis date) and inactive
    vectors.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-06-01", status="inactive"))

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    stale_ids = [e["artifact_id"] for e in result["stale"]]
    archived_ids = [e["artifact_id"] for e in result["archived_sources"]]
    assert synth_id in stale_ids
    assert synth_id in archived_ids


# ---------------------------------------------------------------------------
# Missing source detection
# ---------------------------------------------------------------------------


async def test_missing_source_no_vector_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis referencing source ID with no vector entries → source in missing_sources."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-with-missing-source"
    missing_src_id = "artifacts/nonexistent-source-xyz"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-06-01", [missing_src_id]),
    )
    # Intentionally no vector for missing_src_id

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    missing_entry = next(
        (e for e in result["missing_sources"] if e["artifact_id"] == synth_id), None
    )
    assert missing_entry is not None
    assert missing_src_id in missing_entry["missing_sources"]


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


async def test_two_section_vectors_same_synthesis_counted_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two section vectors for the same synthesis artifact_id → counted as one synthesis
    (total_checked=1)."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-dedup-sections"
    src_id = "artifacts/implementation-note-2026-01-01-source"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    # Two section vectors sharing the same artifact_id
    synth_meta = _synthesis_meta(synth_id, "2026-06-01", [src_id])
    vectors.put_vector(f"{synth_id}#overview", DUMMY_VEC, synth_meta)
    vectors.put_vector(f"{synth_id}#details", DUMMY_VEC, synth_meta)
    vectors.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-01-01"))

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    assert result["total_checked"] == 1


async def test_same_source_referenced_by_two_syntheses_looked_up_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same source referenced by two syntheses → list_vectors_by_metadata called once
    for that source."""
    settings = _make_settings(monkeypatch)
    synth1_id = "artifacts/synthesis-alpha"
    synth2_id = "artifacts/synthesis-beta"
    shared_src_id = "artifacts/implementation-note-2026-01-01-shared-source"

    s3 = FakeS3Client()

    all_filter_calls: list[dict[str, Any]] = []

    class TrackingVectors(FakeVectorsClient):
        def list_vectors_by_metadata(self, filter: dict[str, Any]) -> list[str]:
            all_filter_calls.append(filter)
            return super().list_vectors_by_metadata(filter)

    vectors = TrackingVectors(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth1_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth1_id, "2026-06-01", [shared_src_id]),
    )
    vectors.put_vector(
        f"{synth2_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth2_id, "2026-06-01", [shared_src_id]),
    )
    vectors.put_vector(shared_src_id, DUMMY_VEC, _source_meta(shared_src_id, "2026-01-01"))

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    assert result["total_checked"] == 2
    # Exactly one lookup for the shared source artifact_id
    source_specific_calls = [
        f for f in all_filter_calls if _filter_matches_artifact_id(f, shared_src_id)
    ]
    assert len(source_specific_calls) == 1


# ---------------------------------------------------------------------------
# Scope gate
# ---------------------------------------------------------------------------


async def test_scope_gate_only_own_scope_synthesis_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fake has own-scope and foreign-scope synthesis vectors → total_checked is 1."""
    settings = _make_settings(monkeypatch)
    own_synth_id = "artifacts/synthesis-own-scope"
    foreign_synth_id = "other-team/synthesis-foreign-scope"
    src_id = "artifacts/implementation-note-2026-01-01-source"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{own_synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(own_synth_id, "2026-06-01", [src_id], scope="artifacts"),
    )
    # Foreign-scope synthesis — scope does not match write_prefix
    vectors.put_vector(
        f"{foreign_synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(foreign_synth_id, "2026-06-01", [src_id], scope="other-team"),
    )
    vectors.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-01-01"))

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    assert result["total_checked"] == 1


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------


async def test_response_always_has_all_seven_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All 7 fields always present in every non-error response."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    required_fields = (
        "stale",
        "archived_sources",
        "missing_sources",
        "malformed",
        "deleted_malformed",
        "total_checked",
        "all_fresh",
    )
    for field in required_fields:
        assert field in result, f"Missing required field '{field}' in response"


async def test_all_fresh_true_iff_all_issue_lists_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """all_fresh is True iff stale, archived_sources, missing_sources, and malformed are
    all empty."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    all_empty = (
        result["stale"] == []
        and result["archived_sources"] == []
        and result["missing_sources"] == []
        and result["malformed"] == []
    )
    assert result["all_fresh"] is all_empty


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_list_vectors_exception_returns_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected exception from list_vectors_by_metadata → returns
    {'error': 'internal_error', 'message': ...}."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()

    class ExplodingVectors(FakeVectorsClient):
        def list_vectors_by_metadata(self, filter: dict[str, Any]) -> list[str]:
            raise RuntimeError("Simulated unexpected failure in list_vectors_by_metadata")

    vectors = ExplodingVectors(dimension=DIMENSION)

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert result.get("error") == "internal_error"
    assert "message" in result


# ---------------------------------------------------------------------------
# Malformed synthesis — report only (confirm=False / default)
# ---------------------------------------------------------------------------


async def test_malformed_synthesis_no_confirm_reported_not_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis with empty source_artifacts, confirm=False → in malformed; NOT deleted;
    artifact still exists."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-no-confirm"

    s3 = FakeS3Client()
    s3.put_object(synth_id, "Malformed synthesis content.", {**_MALFORMED_S3_META})
    vectors = FakeVectorsClient(dimension=DIMENSION)
    # No source_artifacts field → malformed (mirrors empty-list omission in write.py)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-01-01", []),
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3, vectors=vectors, confirm=False
    )

    assert "error" not in result
    assert synth_id in result["malformed"]
    assert synth_id not in result["deleted_malformed"]
    # Artifact still exists in S3 and vectors
    assert synth_id in s3._objects
    vec_keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": synth_id}})
    assert len(vec_keys) > 0


async def test_malformed_synthesis_makes_all_fresh_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis with empty source_artifacts → all_fresh is False even with no stale or
    archived issues."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-fresh-check"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-01-01", []),
    )

    result = await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors)

    assert "error" not in result
    assert result["all_fresh"] is False


# ---------------------------------------------------------------------------
# Malformed synthesis — deletion (confirm=True)
# ---------------------------------------------------------------------------


async def test_malformed_synthesis_confirm_true_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis with empty source_artifacts, confirm=True → in deleted_malformed;
    removed from S3 and vectors."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-to-delete"

    s3 = FakeS3Client()
    s3.put_object(synth_id, "Malformed content.", {**_MALFORMED_S3_META})
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-01-01", []),
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3, vectors=vectors, confirm=True
    )

    assert "error" not in result
    assert synth_id in result["deleted_malformed"]
    assert synth_id not in result["malformed"]
    # Removed from S3 and vectors
    assert synth_id not in s3._objects
    vec_keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": synth_id}})
    assert len(vec_keys) == 0


async def test_malformed_and_stale_both_reported_in_same_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two syntheses: one malformed, one valid with stale source → both issues in response;
    malformed deleted; stale not deleted."""
    settings = _make_settings(monkeypatch)
    malformed_id = "artifacts/synthesis-malformed-combined"
    stale_synth_id = "artifacts/synthesis-stale-combined"
    stale_src_id = "artifacts/implementation-note-2026-01-01-newer-combined"

    s3 = FakeS3Client()
    s3.put_object(malformed_id, "Malformed content.", {**_MALFORMED_S3_META})
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{malformed_id}#section",
        DUMMY_VEC,
        _synthesis_meta(malformed_id, "2026-01-01", []),
    )
    vectors.put_vector(
        f"{stale_synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(stale_synth_id, "2026-01-01", [stale_src_id]),
    )
    vectors.put_vector(stale_src_id, DUMMY_VEC, _source_meta(stale_src_id, "2026-06-01"))

    result = await check_synthesis_freshness(
        settings=settings, s3=s3, vectors=vectors, confirm=True
    )

    assert "error" not in result
    stale_ids = [e["artifact_id"] for e in result["stale"]]
    assert malformed_id in result["deleted_malformed"]
    assert stale_synth_id in stale_ids
    # Stale synthesis was NOT deleted
    vec_keys_stale = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": stale_synth_id}})
    assert len(vec_keys_stale) > 0


async def test_malformed_deletion_vectors_before_s3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed synthesis deletion: delete_vectors is called before delete_object
    (vectors-first ordering)."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-order-check"

    call_order: list[str] = []

    class TrackingS3(FakeS3Client):
        def delete_object(self, key: str) -> None:
            call_order.append(f"delete_object:{key}")
            super().delete_object(key)

    class TrackingVectors(FakeVectorsClient):
        def delete_vectors(self, keys: list[str]) -> None:
            call_order.append("delete_vectors")
            super().delete_vectors(keys)

    s3 = TrackingS3()
    s3.put_object(synth_id, "Order check content.", {**_MALFORMED_S3_META})
    vectors = TrackingVectors(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-01-01", []),
    )

    await check_synthesis_freshness(settings=settings, s3=s3, vectors=vectors, confirm=True)

    assert "delete_vectors" in call_order
    assert f"delete_object:{synth_id}" in call_order
    dv_idx = call_order.index("delete_vectors")
    do_idx = call_order.index(f"delete_object:{synth_id}")
    assert dv_idx < do_idx, (
        f"delete_vectors (index {dv_idx}) must be called before "
        f"delete_object (index {do_idx}); full order: {call_order}"
    )


async def test_confirm_true_all_malformed_all_fresh_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One malformed synthesis (empty source_artifacts), confirm=True →
    all_fresh is True (malformed deleted), deleted_malformed is non-empty,
    malformed list is empty."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-confirm-fresh"

    s3 = FakeS3Client()
    s3.put_object(synth_id, "Malformed synthesis content.", {**_MALFORMED_S3_META})
    vectors = FakeVectorsClient(dimension=DIMENSION)
    vectors.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-01-01", []),
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3, vectors=vectors, confirm=True
    )

    assert "error" not in result
    assert result["all_fresh"] is True
    assert synth_id in result["deleted_malformed"]
    assert result["malformed"] == []
