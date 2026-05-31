"""Unit tests for cairn_mcp.tools.reconcile.

Tests reconcile_index() using FakeS3Client + FakeVectorsClient + FakeBedrockClient.
All tests run without real AWS calls. This file is intentionally written before the
implementation (Red phase of TDD) — the import below will fail until
src/cairn_mcp/tools/reconcile.py is created.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.fakes.fake_s3 import FakeS3Client
from cairn_mcp.clients.fakes.fake_vectors import FakeVectorsClient
from cairn_mcp.config import Settings

# Implementation import — will fail until src/cairn_mcp/tools/reconcile.py is created
from cairn_mcp.tools.reconcile import reconcile_index
from tests.unit.conftest import _make_settings as _make_settings_base

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIMENSION = 8

# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


def _make_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, tmp_path=tmp_path, **overrides)


# ---------------------------------------------------------------------------
# Failure log helpers
# ---------------------------------------------------------------------------

_BASE_LOG_ENTRY: dict[str, Any] = {
    "title": "Test Artifact",
    "type": "implementation_note",
    "tier": 2,
    "date": "2026-01-01",
    "failure_step": "put_vector",
    "reason": "Simulated vector write failure",
    "timestamp": "2026-01-01T00:00:00+00:00",
}


def _write_failure_log(path: Path, entries: list[dict[str, Any]]) -> None:
    """Write JSONL failure log entries to the given path."""
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# S3 artifact helpers
# ---------------------------------------------------------------------------

_BASE_S3_META: dict[str, str] = {
    "type": "implementation_note",
    "team": "platform",
    "project": "cairn",
    "tier": "2",
    "date": "2026-01-01",
    "status": "active",
    "title": "Test Artifact",
    "visibility": "shared",
    "feature_tags": "",
    "author_role": "",
    "description": "A test artifact for reconcile.",
    "source_artifacts": "",
}

_CONTENT_NO_SECTIONS = "No heading content here. Just plain text."
_CONTENT_TWO_SECTIONS = "## Overview\n\nSome overview text.\n\n## Details\n\nSome detail text."

# ---------------------------------------------------------------------------
# Failure log replay tests
# ---------------------------------------------------------------------------


async def test_no_failure_log_runs_without_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No failure log file → tool runs without error; failure_log_entries_before is 0."""
    settings = _make_settings(monkeypatch, tmp_path)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    assert result["failure_log_entries_before"] == 0


async def test_failure_log_resolvable_entry_reconciled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Failure log with one resolvable entry (S3 object exists) → re-indexed; in reconciled
    with source='failure_log'; log cleared."""
    settings = _make_settings(monkeypatch, tmp_path)
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"

    s3 = FakeS3Client()
    s3.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    _write_failure_log(
        settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    assert result["failure_log_entries_before"] == 1
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert artifact_id in reconciled_ids
    reconciled_entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert reconciled_entry["source"] == "failure_log"
    assert result["failure_log_entries_after"] == 0


async def test_failure_log_unresolvable_entry_kept_in_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Failure log with one unresolvable entry (S3 object absent) → entry kept;
    in failed with reason containing 'not found'."""
    settings = _make_settings(monkeypatch, tmp_path)
    missing_id = "artifacts/implementation-note-2026-01-01-nonexistent"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    _write_failure_log(
        settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": missing_id}],
    )

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    failed_ids = [e["artifact_id"] for e in result["failed"]]
    assert missing_id in failed_ids
    failed_entry = next(e for e in result["failed"] if e["artifact_id"] == missing_id)
    assert "not found" in failed_entry["reason"].lower()
    assert result["failure_log_entries_after"] >= 1


async def test_failure_log_duplicate_artifact_id_deduplication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Two failure log entries with same artifact_id → only one re-index attempt
    (put_vector not doubled)."""
    settings = _make_settings(monkeypatch, tmp_path)
    artifact_id = "artifacts/implementation-note-2026-01-01-dedup-target"

    s3 = FakeS3Client()
    s3.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})

    put_vector_calls: list[str] = []

    class TrackingVectors(FakeVectorsClient):
        def put_vector(self, key: str, vector: list[float], metadata: dict[str, Any]) -> None:
            put_vector_calls.append(key)
            super().put_vector(key, vector, metadata)

    vectors = TrackingVectors(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    # Two entries for the same artifact_id — should only trigger one re-index
    _write_failure_log(
        settings.failure_log_path,
        [
            {**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "failure_step": "bedrock_embed"},
            {**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "failure_step": "put_vector"},
        ],
    )

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    # No sections → doc-level fallback → exactly 1 put_vector call (not 2)
    assert len(put_vector_calls) == 1
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert reconciled_ids.count(artifact_id) == 1


async def test_failure_log_mixed_entries_one_reconciled_one_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Mixed entries: one resolvable, one not → one in reconciled, one in failed;
    log retains only unresolved."""
    settings = _make_settings(monkeypatch, tmp_path)
    existing_id = "artifacts/implementation-note-2026-01-01-existing"
    missing_id = "artifacts/implementation-note-2026-01-01-missing"

    s3 = FakeS3Client()
    s3.put_object(existing_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    _write_failure_log(
        settings.failure_log_path,
        [
            {**_BASE_LOG_ENTRY, "artifact_id": existing_id},
            {**_BASE_LOG_ENTRY, "artifact_id": missing_id},
        ],
    )

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    failed_ids = [e["artifact_id"] for e in result["failed"]]
    assert existing_id in reconciled_ids
    assert missing_id not in reconciled_ids
    assert missing_id in failed_ids
    assert existing_id not in failed_ids
    # Log retains only the unresolved entry
    assert result["failure_log_entries_after"] == 1


async def test_failure_log_foreign_scope_entry_skipped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Failure log entry whose artifact_id starts with a foreign scope prefix →
    skipped (not reconciled, not failed); log entry is retained."""
    settings = _make_settings(monkeypatch, tmp_path)
    foreign_id = "other-team/implementation-note-2026-01-01-foreign"

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    _write_failure_log(
        settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": foreign_id}],
    )

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    failed_ids = [e["artifact_id"] for e in result["failed"]]
    assert foreign_id not in reconciled_ids
    assert foreign_id not in failed_ids
    # Entry before == 1; entry is retained (not resolved) → after == 1
    assert result["failure_log_entries_before"] == 1
    assert result["failure_log_entries_after"] == 1


# ---------------------------------------------------------------------------
# Orphan scan tests
# ---------------------------------------------------------------------------


async def test_orphan_scan_no_s3_objects_zero_orphans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No S3 objects → orphans_found is 0."""
    settings = _make_settings(monkeypatch, tmp_path)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    assert result["orphans_found"] == 0


async def test_orphan_scan_s3_object_with_matching_vector_not_reindexed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """S3 object with matching vector entry → not re-indexed; orphans_found is 0."""
    settings = _make_settings(monkeypatch, tmp_path)
    artifact_id = "artifacts/implementation-note-2026-01-01-already-indexed"

    s3 = FakeS3Client()
    s3.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})

    put_vector_calls: list[str] = []

    class TrackingVectors(FakeVectorsClient):
        def put_vector(self, key: str, vector: list[float], metadata: dict[str, Any]) -> None:
            put_vector_calls.append(key)
            super().put_vector(key, vector, metadata)

    vectors = TrackingVectors(dimension=DIMENSION)
    # Seed existing vector entry so artifact is not an orphan
    vectors.put_vector(
        f"{artifact_id}#section",
        [1.0] + [0.0] * (DIMENSION - 1),
        {"artifact_id": artifact_id, "scope": "artifacts"},
    )
    # Reset tracking list — the seed call above is not under test
    put_vector_calls.clear()
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    assert result["orphans_found"] == 0
    assert len(put_vector_calls) == 0


async def test_orphan_scan_s3_object_no_vectors_reindexed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """S3 object with no vector entries → re-indexed; orphans_found is 1; source='orphan_scan'."""
    settings = _make_settings(monkeypatch, tmp_path)
    artifact_id = "artifacts/implementation-note-2026-01-01-orphan"

    s3 = FakeS3Client()
    s3.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    assert result["orphans_found"] == 1
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert artifact_id in reconciled_ids
    reconciled_entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert reconciled_entry["source"] == "orphan_scan"


async def test_orphan_scan_key_not_under_write_prefix_slash_not_touched(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """S3 object whose key starts with write_prefix but not write_prefix+'/' → not touched."""
    settings = _make_settings(monkeypatch, tmp_path)
    own_id = "artifacts/implementation-note-2026-01-01-own"
    # "artifacts-sibling" starts with "artifacts" but NOT "artifacts/"
    foreign_id = "artifacts-sibling/implementation-note-2026-01-01-foreign"

    s3 = FakeS3Client()
    s3.put_object(own_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    s3.put_object(foreign_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    # Only own-scope orphan counted
    assert result["orphans_found"] == 1
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert own_id in reconciled_ids
    assert foreign_id not in reconciled_ids


# ---------------------------------------------------------------------------
# Re-indexing mechanics
# ---------------------------------------------------------------------------


async def test_reindex_artifact_two_sections_puts_two_vectors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Artifact with two ## sections → put_vector called twice; sections_indexed is 2."""
    settings = _make_settings(monkeypatch, tmp_path)
    artifact_id = "artifacts/implementation-note-2026-01-01-two-sections"

    s3 = FakeS3Client()
    s3.put_object(artifact_id, _CONTENT_TWO_SECTIONS, {**_BASE_S3_META})

    put_vector_calls: list[str] = []

    class TrackingVectors(FakeVectorsClient):
        def put_vector(self, key: str, vector: list[float], metadata: dict[str, Any]) -> None:
            put_vector_calls.append(key)
            super().put_vector(key, vector, metadata)

    vectors = TrackingVectors(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    assert len(put_vector_calls) == 2
    reconciled_entry = next(
        (e for e in result["reconciled"] if e["artifact_id"] == artifact_id), None
    )
    assert reconciled_entry is not None
    assert reconciled_entry["sections_indexed"] == 2


async def test_reindex_artifact_no_sections_puts_one_vector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Artifact with no ## sections → put_vector called once (doc-level fallback);
    sections_indexed is 1."""
    settings = _make_settings(monkeypatch, tmp_path)
    artifact_id = "artifacts/implementation-note-2026-01-01-no-sections"

    s3 = FakeS3Client()
    s3.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})

    put_vector_calls: list[str] = []

    class TrackingVectors(FakeVectorsClient):
        def put_vector(self, key: str, vector: list[float], metadata: dict[str, Any]) -> None:
            put_vector_calls.append(key)
            super().put_vector(key, vector, metadata)

    vectors = TrackingVectors(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    assert len(put_vector_calls) == 1
    reconciled_entry = next(
        (e for e in result["reconciled"] if e["artifact_id"] == artifact_id), None
    )
    assert reconciled_entry is not None
    assert reconciled_entry["sections_indexed"] == 1


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------


async def test_response_always_has_all_six_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """All 6 fields always present in non-error response regardless of workload."""
    settings = _make_settings(monkeypatch, tmp_path)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    required_fields = (
        "reconciled",
        "failed",
        "failure_log_entries_before",
        "failure_log_entries_after",
        "orphans_found",
        "total_reconciled",
    )
    for field in required_fields:
        assert field in result, f"Missing required field '{field}' in response"


async def test_total_reconciled_equals_len_reconciled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """total_reconciled always equals len(reconciled)."""
    settings = _make_settings(monkeypatch, tmp_path)
    artifact_id = "artifacts/implementation-note-2026-01-01-for-total-check"

    s3 = FakeS3Client()
    s3.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result["total_reconciled"] == len(result["reconciled"])


# ---------------------------------------------------------------------------
# Scope gate
# ---------------------------------------------------------------------------


async def test_scope_gate_own_scope_scanned_foreign_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """S3 contains own-scope and foreign-scope objects → only own-scope scanned;
    foreign not in reconciled."""
    settings = _make_settings(monkeypatch, tmp_path)
    own_id = "artifacts/implementation-note-2026-01-01-own-scope"
    # Completely different prefix — not under "artifacts/"
    foreign_id = "other-team/implementation-note-2026-01-01-foreign"

    s3 = FakeS3Client()
    s3.put_object(own_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    s3.put_object(foreign_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert own_id in reconciled_ids
    assert foreign_id not in reconciled_ids


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_list_vectors_exception_returns_internal_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Unexpected exception from list_vectors_by_metadata → returns
    {'error': 'internal_error', 'message': ...}."""
    settings = _make_settings(monkeypatch, tmp_path)
    s3 = FakeS3Client()
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    class ExplodingVectors(FakeVectorsClient):
        def list_vectors_by_metadata(self, filter: dict[str, Any]) -> list[str]:
            raise RuntimeError("Simulated unexpected failure in list_vectors_by_metadata")

    vectors = ExplodingVectors(dimension=DIMENSION)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result.get("error") == "internal_error"
    assert "message" in result


# ---------------------------------------------------------------------------
# Spec 01 — CredentialError from list_objects → credential_error response
# ---------------------------------------------------------------------------


async def test_credential_error_on_list_objects_returns_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CredentialError from s3.list_objects → response is credential_error."""
    settings = _make_settings(monkeypatch, tmp_path)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    s3.set_credential_failure(True)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result.get("error") == "credential_error"


# ---------------------------------------------------------------------------
# Spec 03 — Health probe keys excluded from reconciliation
# ---------------------------------------------------------------------------


async def test_health_probe_key_excluded_from_orphans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """S3 has only _cairn_health_probe key → orphans_found == 0."""
    settings = _make_settings(monkeypatch, tmp_path)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    s3.put_object("artifacts/_cairn_health_probe", "probe", {})

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result.get("orphans_found", 0) == 0
    reconciled = result.get("reconciled", [])
    assert "_cairn_health_probe" not in str(reconciled)


async def test_health_probe_excluded_but_real_orphan_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """S3 has probe + real orphan → orphans_found == 1, only real artifact reconciled."""
    settings = _make_settings(monkeypatch, tmp_path)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    s3.put_object("artifacts/_cairn_health_probe", "probe", {})
    s3.put_object(
        "artifacts/code-review-2026-05-30-orphan",
        "## Summary\n\nOrphan content.",
        {
            "type": "code_review",
            "team": "platform",
            "project": "cairn",
            "tier": "2",
            "date": "2026-05-30",
            "status": "active",
            "title": "Orphan",
            "visibility": "shared",
            "description": "An orphan",
        },
    )

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result.get("orphans_found", 0) == 1
    reconciled = result.get("reconciled", [])
    assert "_cairn_health_probe" not in str(reconciled)


async def test_nested_probe_key_also_excluded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Probe key at nested path (endswith match) → excluded."""
    settings = _make_settings(monkeypatch, tmp_path)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    s3.put_object("artifacts/subdir/_cairn_health_probe", "probe", {})

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result.get("orphans_found", 0) == 0


# ---------------------------------------------------------------------------
# Spec 13 — CredentialError tests for reconcile call sites
# ---------------------------------------------------------------------------


async def test_credential_error_on_bedrock_embed_returns_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CredentialError from bedrock.embed during reconcile → credential_error response."""
    settings = _make_settings(monkeypatch, tmp_path)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    s3.put_object(
        "artifacts/code-review-2026-05-30-orphan",
        "## Summary\n\nOrphan.",
        {
            "type": "code_review",
            "team": "platform",
            "project": "cairn",
            "tier": "2",
            "date": "2026-05-30",
            "status": "active",
            "title": "Orphan",
            "visibility": "shared",
            "description": "An orphan",
        },
    )

    bedrock.set_credential_failure(True)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result.get("error") == "credential_error"


async def test_credential_error_on_vectors_put_returns_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CredentialError from vectors.put_vector during reconcile → credential_error response."""
    settings = _make_settings(monkeypatch, tmp_path)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    s3.put_object(
        "artifacts/code-review-2026-05-30-orphan",
        "## Summary\n\nOrphan.",
        {
            "type": "code_review",
            "team": "platform",
            "project": "cairn",
            "tier": "2",
            "date": "2026-05-30",
            "status": "active",
            "title": "Orphan",
            "visibility": "shared",
            "description": "An orphan",
        },
    )

    vectors.set_credential_failure(True)

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result.get("error") == "credential_error"


@pytest.mark.asyncio
async def test_startup_probe_key_excluded_from_orphan_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Orphan scan skips S3 keys containing '_cairn_mcp_startup_probe'."""
    settings = _make_settings(monkeypatch, tmp_path)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=DIMENSION)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    # Seed a real artifact so reconcile has something to verify against
    s3.put_object(
        "artifacts/code-review-2026-01-01-real",
        "## Summary\n\nReal artifact.",
        {
            "type": "code_review",
            "team": "platform",
            "project": "cairn",
            "tier": "2",
            "date": "2026-01-01",
            "status": "active",
            "title": "Real",
            "visibility": "shared",
            "description": "A real artifact",
        },
    )
    # Seed a startup probe key — must NOT be picked up as an orphan
    s3.put_object(
        "artifacts/_cairn_mcp_startup_probe",
        "startup-probe",
        {},
    )
    # Index the real artifact so it is not reported as an orphan
    vectors.put_vector(
        "artifacts/code-review-2026-01-01-real",
        [1.0] + [0.0] * (DIMENSION - 1),
        {"artifact_id": "artifacts/code-review-2026-01-01-real", "scope": "artifacts"},
    )

    result = await reconcile_index(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "error" not in result
    # The startup probe must not appear in reconciled or failed lists
    all_ids = [e["artifact_id"] for e in result.get("reconciled", []) + result.get("failed", [])]
    assert not any("_cairn_mcp_startup_probe" in aid for aid in all_ids)
    # orphans_found should be 0 — the real artifact is already indexed
    assert result["orphans_found"] == 0
