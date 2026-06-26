"""Unit tests for cairn_mcp.tools.reconcile.

Tests reconcile_index() using moto-backed S3ClientImpl + VectorsClientImpl + FakeBedrockClient.
All tests run without real AWS calls.
"""

import json
from pathlib import Path
from typing import Any

import boto3
import pytest
from pytest_mock import MockerFixture

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools.reconcile import reconcile_index
from tests.unit.conftest import _make_settings as _make_settings_base
from tests.unit.conftest import _make_vectors_client

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIMENSION = 8

# ---------------------------------------------------------------------------
# Local fixtures (need tmp_path for failure_log_path)
# ---------------------------------------------------------------------------


@pytest.fixture
def reconcile_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    """Settings with FAILURE_LOG_PATH pointing to a temp file and BEDROCK_EMBEDDING_DIMENSIONS=8."""
    return _make_settings_base(
        monkeypatch,
        tmp_path=tmp_path,
        BEDROCK_EMBEDDING_DIMENSIONS=str(DIMENSION),
    )


@pytest.fixture
def s3_reconcile(aws_mock: None, reconcile_settings: Settings) -> S3ClientImpl:
    """S3ClientImpl backed by moto for reconcile tests."""
    boto3.client("s3", region_name=reconcile_settings.aws_region).create_bucket(
        Bucket=reconcile_settings.artifact_bucket,
    )
    return S3ClientImpl(
        region=reconcile_settings.aws_region,
        profile=None,
        bucket=reconcile_settings.artifact_bucket,
    )


@pytest.fixture
def vectors_reconcile(aws_mock: None, reconcile_settings: Settings) -> VectorsClientImpl:
    """VectorsClientImpl backed by moto with dim=8 for reconcile tests."""
    return _make_vectors_client(reconcile_settings, dimension=DIMENSION)


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
    "tags": "",
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
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """No failure log file → tool runs without error; failure_log_entries_before is 0."""
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["failure_log_entries_before"] == 0


async def test_failure_log_resolvable_entry_reconciled(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Failure log with one resolvable entry (S3 object exists) → re-indexed; in reconciled
    with source='failure_log'; log cleared."""
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["failure_log_entries_before"] == 1
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert artifact_id in reconciled_ids
    reconciled_entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert reconciled_entry["source"] == "failure_log"
    assert result["failure_log_entries_after"] == 0


async def test_failure_log_unresolvable_entry_kept_in_failed(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Failure log with one unresolvable entry (S3 object absent) → entry kept;
    in failed with reason containing 'not found'."""
    missing_id = "artifacts/implementation-note-2026-01-01-nonexistent"
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": missing_id}],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    failed_ids = [e["artifact_id"] for e in result["failed"]]
    assert missing_id in failed_ids
    failed_entry = next(e for e in result["failed"] if e["artifact_id"] == missing_id)
    assert "not found" in failed_entry["reason"].lower()
    assert result["failure_log_entries_after"] >= 1


async def test_failure_log_duplicate_artifact_id_deduplication(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Two failure log entries with same artifact_id → only one re-index attempt
    (put_vector not doubled)."""
    artifact_id = "artifacts/implementation-note-2026-01-01-dedup-target"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    # Two entries for the same artifact_id — should only trigger one re-index
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "failure_step": "bedrock_embed"},
            {**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "failure_step": "put_vector"},
        ],
    )

    spy = mocker.spy(vectors_reconcile, "put_vector")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    # No sections → doc-level fallback → exactly 1 put_vector call (not 2)
    assert spy.call_count == 1
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert reconciled_ids.count(artifact_id) == 1


async def test_failure_log_mixed_entries_one_reconciled_one_failed(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Mixed entries: one resolvable, one not → one in reconciled, one in failed;
    log retains only unresolved."""
    existing_id = "artifacts/implementation-note-2026-01-01-existing"
    missing_id = "artifacts/implementation-note-2026-01-01-missing"
    s3_reconcile.put_object(existing_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {**_BASE_LOG_ENTRY, "artifact_id": existing_id},
            {**_BASE_LOG_ENTRY, "artifact_id": missing_id},
        ],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

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
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Failure log entry whose artifact_id starts with a foreign scope prefix →
    skipped (not reconciled, not failed); log entry is retained."""
    foreign_id = "other-team/implementation-note-2026-01-01-foreign"
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": foreign_id}],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

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
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """No S3 objects → orphans_found is 0."""
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["orphans_found"] == 0


async def test_orphan_scan_s3_object_with_matching_vector_not_reindexed(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """S3 object with matching vector entry → not re-indexed; orphans_found is 0."""
    artifact_id = "artifacts/implementation-note-2026-01-01-already-indexed"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})

    # Seed existing vector entry so artifact is not an orphan
    vectors_reconcile.put_vector(
        f"{artifact_id}#section",
        [1.0] + [0.0] * (DIMENSION - 1),
        {"artifact_id": artifact_id, "scope": "artifacts"},
    )

    bedrock = FakeBedrockClient(dimension=DIMENSION)
    # Install spy AFTER seed so pre-seed call is not counted
    spy = mocker.spy(vectors_reconcile, "put_vector")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["orphans_found"] == 0
    assert spy.call_count == 0


async def test_orphan_scan_s3_object_no_vectors_reindexed(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """S3 object with no vector entries → re-indexed; orphans_found is 1; source='orphan_scan'."""
    artifact_id = "artifacts/implementation-note-2026-01-01-orphan"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["orphans_found"] == 1
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert artifact_id in reconciled_ids
    reconciled_entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert reconciled_entry["source"] == "orphan_scan"


async def test_orphan_scan_key_not_under_write_prefix_slash_not_touched(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """S3 object whose key starts with write_prefix but not write_prefix+'/' → not touched."""
    own_id = "artifacts/implementation-note-2026-01-01-own"
    # "artifacts-sibling" starts with "artifacts" but NOT "artifacts/"
    foreign_id = "artifacts-sibling/implementation-note-2026-01-01-foreign"

    s3_reconcile.put_object(own_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    s3_reconcile.put_object(foreign_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

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
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Artifact with two ## sections → put_vector called twice; sections_indexed is 2."""
    artifact_id = "artifacts/implementation-note-2026-01-01-two-sections"
    s3_reconcile.put_object(artifact_id, _CONTENT_TWO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient(dimension=DIMENSION)
    spy = mocker.spy(vectors_reconcile, "put_vector")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert spy.call_count == 2
    reconciled_entry = next(
        (e for e in result["reconciled"] if e["artifact_id"] == artifact_id), None
    )
    assert reconciled_entry is not None
    assert reconciled_entry["sections_indexed"] == 2


async def test_reindex_artifact_no_sections_puts_one_vector(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Artifact with no ## sections → put_vector called once (doc-level fallback);
    sections_indexed is 1."""
    artifact_id = "artifacts/implementation-note-2026-01-01-no-sections"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient(dimension=DIMENSION)
    spy = mocker.spy(vectors_reconcile, "put_vector")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert spy.call_count == 1
    reconciled_entry = next(
        (e for e in result["reconciled"] if e["artifact_id"] == artifact_id), None
    )
    assert reconciled_entry is not None
    assert reconciled_entry["sections_indexed"] == 1


async def test_reindex_preserves_commit_refs_and_last_edited_ulid(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Reconcile must reconstruct vector metadata mirroring write_artifact (T21), including
    commit_refs (as list[str]) and last_edited_ulid — otherwise commit-ref filtering silently
    stops matching and last_edited_ulid is lost for the rebuilt artifact.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-with-refs"
    ulid = "01HZZZ0000000000000000000A"
    meta = {
        **_BASE_S3_META,
        "commit_refs": "abc123,def456",
        "last_edited_ulid": ulid,
    }
    s3_reconcile.put_object(artifact_id, _CONTENT_TWO_SECTIONS, meta)
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )
    assert "error" not in result

    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    items = vectors_reconcile.get_vectors(keys)
    assert items, "reconcile should have indexed vectors for the artifact"
    vmeta = items[0]["metadata"]
    assert vmeta.get("commit_refs") == ["abc123", "def456"]
    assert vmeta.get("last_edited_ulid") == ulid


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------


async def test_response_always_has_all_six_fields(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """All 6 fields always present in non-error response regardless of workload."""
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

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
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """total_reconciled always equals len(reconciled)."""
    artifact_id = "artifacts/implementation-note-2026-01-01-for-total-check"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result["total_reconciled"] == len(result["reconciled"])


# ---------------------------------------------------------------------------
# Scope gate
# ---------------------------------------------------------------------------


async def test_scope_gate_own_scope_scanned_foreign_ignored(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """S3 contains own-scope and foreign-scope objects → only own-scope scanned;
    foreign not in reconciled."""
    own_id = "artifacts/implementation-note-2026-01-01-own-scope"
    # Completely different prefix — not under "artifacts/"
    foreign_id = "other-team/implementation-note-2026-01-01-foreign"

    s3_reconcile.put_object(own_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    s3_reconcile.put_object(foreign_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert own_id in reconciled_ids
    assert foreign_id not in reconciled_ids


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_list_vectors_exception_returns_internal_error(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Unexpected exception from list_vectors_by_metadata → returns
    {'error': 'internal_error', 'message': ...}."""
    bedrock = FakeBedrockClient(dimension=DIMENSION)
    mocker.patch.object(
        vectors_reconcile,
        "list_vectors_by_metadata",
        side_effect=RuntimeError("Simulated unexpected failure in list_vectors_by_metadata"),
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("error") == "internal_error"
    assert "message" in result


# ---------------------------------------------------------------------------
# Spec 01 — CredentialError from list_objects → credential_error response
# ---------------------------------------------------------------------------


async def test_credential_error_on_list_objects_returns_credential_error(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """CredentialError from s3.list_objects → response is credential_error."""
    bedrock = FakeBedrockClient(dimension=DIMENSION)
    mocker.patch.object(
        s3_reconcile,
        "list_objects",
        side_effect=CredentialError(message="Simulated.", service="s3", original=Exception("sim")),
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("error") == "credential_error"


# ---------------------------------------------------------------------------
# Spec 03 — Health probe keys excluded from reconciliation
# ---------------------------------------------------------------------------


async def test_health_probe_key_excluded_from_orphans(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """S3 has only _cairn_health_probe key → orphans_found == 0."""
    s3_reconcile.put_object("artifacts/_cairn_health_probe", "probe", {})
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("orphans_found", 0) == 0
    reconciled = result.get("reconciled", [])
    assert "_cairn_health_probe" not in str(reconciled)


async def test_health_probe_excluded_but_real_orphan_found(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """S3 has probe + real orphan → orphans_found == 1, only real artifact reconciled."""
    s3_reconcile.put_object("artifacts/_cairn_health_probe", "probe", {})
    s3_reconcile.put_object(
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
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("orphans_found", 0) == 1
    reconciled = result.get("reconciled", [])
    assert "_cairn_health_probe" not in str(reconciled)


async def test_nested_probe_key_also_excluded(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Probe key at nested path (endswith match) → excluded."""
    s3_reconcile.put_object("artifacts/subdir/_cairn_health_probe", "probe", {})
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("orphans_found", 0) == 0


# ---------------------------------------------------------------------------
# Spec 13 — CredentialError tests for reconcile call sites
# ---------------------------------------------------------------------------


async def test_credential_error_on_bedrock_embed_returns_credential_error(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """CredentialError from bedrock.embed during reconcile → credential_error response."""
    s3_reconcile.put_object(
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
    bedrock = FakeBedrockClient(dimension=DIMENSION)
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=CredentialError(
            message="Simulated.", service="bedrock", original=Exception("sim")
        ),
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("error") == "credential_error"


async def test_credential_error_on_vectors_put_returns_credential_error(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """CredentialError from vectors.put_vector during reconcile → credential_error response."""
    s3_reconcile.put_object(
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
    bedrock = FakeBedrockClient(dimension=DIMENSION)
    mocker.patch.object(
        vectors_reconcile,
        "put_vector",
        side_effect=CredentialError(
            message="Simulated.", service="s3vectors", original=Exception("sim")
        ),
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("error") == "credential_error"


async def test_startup_probe_key_excluded_from_orphan_scan(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Orphan scan skips S3 keys containing '_cairn_mcp_startup_probe'."""
    # Seed a real artifact
    s3_reconcile.put_object(
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
    s3_reconcile.put_object(
        "artifacts/_cairn_mcp_startup_probe",
        "startup-probe",
        {},
    )
    # Index the real artifact so it is not reported as an orphan
    vectors_reconcile.put_vector(
        "artifacts/code-review-2026-01-01-real",
        [1.0] + [0.0] * (DIMENSION - 1),
        {"artifact_id": "artifacts/code-review-2026-01-01-real", "scope": "artifacts"},
    )
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    # The startup probe must not appear in reconciled or failed lists
    all_ids = [e["artifact_id"] for e in result.get("reconciled", []) + result.get("failed", [])]
    assert not any("_cairn_mcp_startup_probe" in aid for aid in all_ids)
    # orphans_found should be 0 — the real artifact is already indexed
    assert result["orphans_found"] == 0


# ---------------------------------------------------------------------------
# Phase 3: Dangling vector pruning tests
# ---------------------------------------------------------------------------


async def test_phase3_dangling_vector_pruned(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Vector index has one entry for own-scope/artifact-a but no S3 object;
    reconcile_index prunes the dangling vector and reports it."""
    artifact_id = "artifacts/implementation-note-2026-01-01-artifact-a"
    vec_key = f"{artifact_id}#section-one"

    # Seed a vector entry with NO corresponding S3 object
    vectors_reconcile.put_vector(
        vec_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        {
            "artifact_id": artifact_id,
            "scope": "artifacts",
            "type": "implementation_note",
            "tier": 2,
            "title": "Artifact A",
        },
    )

    bedrock = FakeBedrockClient(dimension=DIMENSION)
    spy = mocker.spy(vectors_reconcile, "delete_vectors")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["dangling_artifacts_found"] == 1
    assert result["dangling_vectors_pruned"] == 1
    assert result["dangling_artifacts"] == [artifact_id]
    spy.assert_called_once_with([vec_key])


async def test_phase3_multi_section_artifact_all_keys_pruned(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Vector index has 3 entries for the same dangling artifact (one per section);
    all three keys are pruned in a single delete_vectors call."""
    artifact_id = "artifacts/implementation-note-2026-01-01-multi-section"
    vec_keys = [
        f"{artifact_id}#s1",
        f"{artifact_id}#s2",
        f"{artifact_id}#s3",
    ]
    base_meta = {
        "artifact_id": artifact_id,
        "scope": "artifacts",
        "type": "implementation_note",
        "tier": 2,
        "title": "Multi Section",
    }

    for key in vec_keys:
        vectors_reconcile.put_vector(
            key,
            [1.0] + [0.0] * (DIMENSION - 1),
            base_meta,
        )

    bedrock = FakeBedrockClient(dimension=DIMENSION)
    spy = mocker.spy(vectors_reconcile, "delete_vectors")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["dangling_vectors_pruned"] == 3
    # All three keys passed in a single call
    assert spy.call_count == 1
    called_keys = spy.call_args[0][0]
    assert sorted(called_keys) == sorted(vec_keys)


async def test_phase3_no_dangling_vectors(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """All vector entries have matching S3 objects; no dangling vectors detected."""
    artifact_id = "artifacts/implementation-note-2026-01-01-present"
    vec_key = f"{artifact_id}#section"

    # S3 object exists
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    # Vector entry exists for the same artifact
    vectors_reconcile.put_vector(
        vec_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        {"artifact_id": artifact_id, "scope": "artifacts"},
    )

    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["dangling_artifacts_found"] == 0
    assert result["dangling_vectors_pruned"] == 0
    assert result["dangling_artifacts"] == []


async def test_phase2_and_phase3_both_run(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """One Scenario 2 orphan (S3 object present, no vector entry) AND one Scenario 3 dangling
    (vector entry present, no S3 object); both detected in the same reconcile call."""
    orphan_id = "artifacts/implementation-note-2026-01-01-orphan"
    dangling_id = "artifacts/implementation-note-2026-01-01-dangling"
    dangling_vec_key = f"{dangling_id}#section"

    # Orphan: S3 object with no vector entry
    s3_reconcile.put_object(orphan_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})

    # Dangling: vector entry with no S3 object
    vectors_reconcile.put_vector(
        dangling_vec_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        {"artifact_id": dangling_id, "scope": "artifacts"},
    )

    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["orphans_found"] == 1
    assert result["dangling_artifacts_found"] == 1
    assert dangling_id in result["dangling_artifacts"]


async def test_phase3_foreign_scope_not_pruned(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Vector index has an entry with a foreign scope; the corresponding S3 object is absent.
    The foreign-scope entry must NOT appear in dangling_artifacts because the scope filter
    on list_vectors_by_metadata already excludes it."""
    foreign_artifact_id = "foreign-team/foreign-project/artifact-x"
    foreign_vec_key = f"{foreign_artifact_id}#section"

    # Put a foreign-scope vector with no S3 backing
    vectors_reconcile.put_vector(
        foreign_vec_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        {
            "artifact_id": foreign_artifact_id,
            "scope": "foreign-team/foreign-project",  # different from settings.write_prefix
        },
    )

    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["dangling_artifacts_found"] == 0
    assert foreign_artifact_id not in result["dangling_artifacts"]


async def test_phase3_credential_error_on_delete(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """CredentialError from vectors.delete_vectors during dangling prune →
    response is {'error': 'credential_error', ...}."""
    artifact_id = "artifacts/implementation-note-2026-01-01-cred-fail"
    vec_key = f"{artifact_id}#section"

    # Seed dangling vector (no S3 object)
    vectors_reconcile.put_vector(
        vec_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        {"artifact_id": artifact_id, "scope": "artifacts"},
    )

    bedrock = FakeBedrockClient(dimension=DIMENSION)
    mocker.patch.object(
        vectors_reconcile,
        "delete_vectors",
        side_effect=CredentialError(
            message="cred fail",
            service="s3vectors",
            original=Exception("sim"),
        ),
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("error") == "credential_error"
    assert "cred fail" in result.get("message", "")


async def test_phase3_unexpected_error_on_delete_continues(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """When delete_vectors raises RuntimeError for the first dangling artifact but
    succeeds for the second, the failing artifact appears in 'failed' and the
    successful one appears in 'dangling_artifacts'."""
    artifact_id_fail = "artifacts/implementation-note-2026-01-01-delete-fail"
    artifact_id_ok = "artifacts/implementation-note-2026-01-01-delete-ok"
    vec_key_fail = f"{artifact_id_fail}#section"
    vec_key_ok = f"{artifact_id_ok}#section"

    # Seed both as dangling (no S3 objects)
    base_meta_fail = {"artifact_id": artifact_id_fail, "scope": "artifacts"}
    base_meta_ok = {"artifact_id": artifact_id_ok, "scope": "artifacts"}
    vectors_reconcile.put_vector(vec_key_fail, [1.0] + [0.0] * (DIMENSION - 1), base_meta_fail)
    vectors_reconcile.put_vector(vec_key_ok, [1.0] + [0.0] * (DIMENSION - 1), base_meta_ok)

    bedrock = FakeBedrockClient(dimension=DIMENSION)

    # Patch delete_vectors to fail for the first artifact's keys, succeed for the second
    original_delete = vectors_reconcile.delete_vectors

    def _selective_delete(keys: list[str]) -> None:
        if vec_key_fail in keys:
            raise RuntimeError("simulated delete failure")
        original_delete(keys)

    mocker.patch.object(vectors_reconcile, "delete_vectors", side_effect=_selective_delete)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    failed_ids = [e["artifact_id"] for e in result["failed"]]
    assert artifact_id_fail in failed_ids
    assert artifact_id_ok in result["dangling_artifacts"]
    assert result["dangling_artifacts_found"] == 1


async def test_response_schema_includes_new_fields(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """A reconcile_index call with nothing to do returns all three new Phase 3 fields:
    dangling_artifacts_found, dangling_vectors_pruned, dangling_artifacts."""
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert "dangling_artifacts_found" in result, "Missing 'dangling_artifacts_found' in response"
    assert "dangling_vectors_pruned" in result, "Missing 'dangling_vectors_pruned' in response"
    assert "dangling_artifacts" in result, "Missing 'dangling_artifacts' in response"


# ---------------------------------------------------------------------------
# M15 — Phase-1 failure must not cause duplicate failed entry via Phase-2 orphan scan
# ---------------------------------------------------------------------------


async def test_m15_phase1_failure_not_duplicated_as_phase2_orphan(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """M15: When a failure log entry re-index attempt fails in Phase 1 (e.g. bedrock.embed
    raises), the artifact is added to failed exactly ONCE.  Before the fix, failed_ids was
    initialised inside the ``if log_path.exists():`` block and therefore not visible to the
    Phase-2 orphan scan, which would add the same artifact_id to failed a second time.

    Scenario:
    - Failure log has one entry for artifact_id.
    - The S3 object exists (so Phase-1 can attempt re-indexing).
    - bedrock.embed raises so Phase-1 fails and adds artifact_id to failed_ids.
    - Phase-2 orphan scan sees the S3 key is not in indexed_artifact_ids and — because
      failed_ids is inaccessible — also adds artifact_id to failed.
    Expected: artifact_id appears in failed exactly ONCE.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-m15-dup"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )

    bedrock = FakeBedrockClient(dimension=DIMENSION)
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=RuntimeError("simulated embed failure"),
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    failed_ids = [e["artifact_id"] for e in result["failed"]]
    count = failed_ids.count(artifact_id)
    assert count == 1, (
        f"M15: artifact_id should appear in failed exactly once, but found {count} times. "
        f"failed list: {result['failed']}"
    )
