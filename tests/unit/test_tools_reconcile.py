"""Unit tests for arkeology.tools.reconcile.

Tests reconcile_index() using moto-backed S3ClientImpl + VectorsClientImpl + FakeBedrockClient.
All tests run without real AWS calls.
"""

import json
import threading
from pathlib import Path
from typing import Any

import boto3
import pytest
from pytest_mock import MockerFixture

from arkeology.annotations import (
    CAS_MAX_ATTEMPTS,
    apply_link_annotations,
    decode_link_list,
    read_link_annotations,
)
from arkeology.artifact import VECTOR_FILTERABLE_METADATA_MAX_BYTES
from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.filter import matches_filter
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import CredentialError
from arkeology.failure_log import append_failure_entry
from arkeology.tools import reconcile as reconcile_module
from arkeology.tools._scope import build_scope_filter, is_cross_scope_readable
from arkeology.tools.reconcile import reconcile_index
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
    "project": "arkeology",
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
    bedrock = FakeBedrockClient()

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
    bedrock = FakeBedrockClient()

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


async def test_failure_log_removed_when_every_entry_resolved(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Draining the log to nothing removes the file rather than leaving an empty one."""
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert result["failure_log_entries_after"] == 0
    # Drained, not unlinked. read_text raises if the file is gone, so this still pins
    # that the log is emptied — an appender blocked on its lock while the rewrite ran
    # would write into an unlinked inode and lose the entry it holds.
    assert reconcile_settings.failure_log_path.read_text(encoding="utf-8").strip() == ""


async def test_failure_log_entry_appended_during_replay_survives_the_rewrite(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """An entry appended between the log read and the end-of-run rewrite is kept.

    Several server processes can share one failure log and FastMCP serves tool calls
    concurrently, so a partial write can be recorded while a replay is still running.
    The rewrite must remove only the keys it resolved, never everything it did not
    read, or the artifact the entry names is never reconciled — the exact loss the
    log exists to prevent.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    late_id = "artifacts/implementation-note-2026-01-02-late-artifact"

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )

    real_head_object = s3_reconcile.head_object
    appended = threading.Event()

    def _append_once_then_head(key: str) -> dict[str, Any]:
        """Stand in for a concurrent writer recording a partial write mid-replay."""
        if not appended.is_set():
            appended.set()
            append_failure_entry(
                reconcile_settings.failure_log_path,
                {**_BASE_LOG_ENTRY, "artifact_id": late_id},
            )
        return real_head_object(key)

    mocker.patch.object(s3_reconcile, "head_object", side_effect=_append_once_then_head)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    assert appended.is_set()
    assert artifact_id in [e["artifact_id"] for e in result["reconciled"]]
    assert result["failure_log_entries_after"] == 1
    assert reconcile_settings.failure_log_path.exists()
    remaining = [
        json.loads(line)
        for line in reconcile_settings.failure_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [e["artifact_id"] for e in remaining] == [late_id]


async def test_failure_log_entry_for_deleted_artifact_resolved_and_pruned(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """A failure-log entry whose S3 object no longer exists has nothing left to
    reconcile: the artifact is gone. It is resolved rather than failed — reported once in
    reconciled with source='failure_log_obsolete', absent from failed and from
    stuck_failures, and pruned from the log so the log actually drains."""
    missing_id = "artifacts/implementation-note-2026-01-01-nonexistent"
    bedrock = FakeBedrockClient()

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
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert reconciled_ids.count(missing_id) == 1
    obsolete_entry = next(e for e in result["reconciled"] if e["artifact_id"] == missing_id)
    assert obsolete_entry["source"] == "failure_log_obsolete"
    assert obsolete_entry["title"] == _BASE_LOG_ENTRY["title"]
    # Nothing was indexed, so no section count is reported.
    assert "sections_indexed" not in obsolete_entry

    assert missing_id not in [e["artifact_id"] for e in result["failed"]]
    assert missing_id not in [e["artifact_id"] for e in result.get("stuck_failures", [])]
    assert result["failure_log_entries_after"] < result["failure_log_entries_before"]
    assert result["failure_log_entries_after"] == 0


async def test_failure_log_entry_for_deleted_artifact_not_replayed_on_second_run(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """The entry pruned for a deleted artifact is gone for good: a second run over the
    same state reports it in neither reconciled nor failed, which is the whole point of
    resolving it rather than failing it."""
    missing_id = "artifacts/implementation-note-2026-01-01-gone-for-good"
    bedrock = FakeBedrockClient()

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": missing_id}],
    )

    first = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )
    assert "error" not in first

    second = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in second
    assert missing_id not in [e["artifact_id"] for e in second["reconciled"]]
    assert missing_id not in [e["artifact_id"] for e in second["failed"]]
    assert missing_id not in [e["artifact_id"] for e in second.get("stuck_failures", [])]
    assert second["failure_log_entries_before"] == 0


async def test_failure_log_credential_error_on_head_object_aborts_run(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A CredentialError from the replay's head_object still aborts the whole run with the
    structured credential-error response — only a genuine 404 resolves the entry, and the
    failure log is left untouched so the entry survives to be retried."""
    artifact_id = "artifacts/implementation-note-2026-01-01-cred-head"
    bedrock = FakeBedrockClient()

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )
    mocker.patch.object(
        s3_reconcile,
        "head_object",
        side_effect=CredentialError(message="Simulated.", service="s3", original=Exception("sim")),
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("error") == "credential_error"
    assert "reconciled" not in result
    log_lines = reconcile_settings.failure_log_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["artifact_id"] for line in log_lines] == [artifact_id]


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
    bedrock = FakeBedrockClient()

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


async def test_failure_log_mixed_entries_each_resolved_by_its_own_source(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Mixed entries: one whose S3 object exists, one whose object is gone. Both are
    resolved and pruned, but by different mechanisms — the first is re-indexed
    (source='failure_log'), the second is dropped as obsolete
    (source='failure_log_obsolete'). Neither lands in failed, and the log drains fully."""
    existing_id = "artifacts/implementation-note-2026-01-01-existing"
    missing_id = "artifacts/implementation-note-2026-01-01-missing"
    s3_reconcile.put_object(existing_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient()

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
    sources = {e["artifact_id"]: e["source"] for e in result["reconciled"]}
    assert sources[existing_id] == "failure_log"
    assert sources[missing_id] == "failure_log_obsolete"
    assert result["failed"] == []
    assert result["failure_log_entries_after"] == 0


async def test_failure_log_foreign_scope_entry_skipped(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Failure log entry whose artifact_id starts with a foreign scope prefix →
    skipped (not reconciled, not failed); log entry is retained."""
    foreign_id = "other-team/implementation-note-2026-01-01-foreign"
    bedrock = FakeBedrockClient()

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
    bedrock = FakeBedrockClient()

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

    bedrock = FakeBedrockClient()
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
    bedrock = FakeBedrockClient()

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
    bedrock = FakeBedrockClient()

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
# Orphan scan — non-artifact discrimination
# ---------------------------------------------------------------------------


async def test_orphan_scan_object_without_artifact_metadata_skipped(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A stray object carrying no artifact metadata → not indexed, reported as skipped."""
    stray_key = "artifacts/.DS_Store"
    s3_reconcile.put_object(stray_key, "not an artifact", {})
    bedrock = FakeBedrockClient()
    spy = mocker.spy(vectors_reconcile, "put_vector")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert spy.call_count == 0
    assert result["reconciled"] == []
    assert result["skipped_non_artifacts"] == [stray_key]


async def test_orphans_found_counts_artifacts_only_not_stray_objects(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """orphans_found counts artifact orphans needing re-index, not every key examined.

    A stray object is skipped, not reconciled, so counting it would hold the number at a
    non-zero floor on every future run for as long as the stray exists — an operator
    watching orphans_found trend to zero would never see it get there. Probe keys are
    already excluded before the count for the same reason; the two categories of
    "not an artifact" must agree.
    """
    stray_key = "artifacts/.DS_Store"
    artifact_id = "artifacts/implementation-note-2026-01-01-counted"
    s3_reconcile.put_object(stray_key, "not an artifact", {})
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["skipped_non_artifacts"] == [stray_key]
    assert result["orphans_found"] == 1, (
        "only the real artifact is an orphan; the stray was examined but is not one"
    )


async def test_orphan_scan_object_with_unknown_type_metadata_skipped(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Object whose `type` metadata is not a valid artifact type → skipped, not indexed."""
    key = "artifacts/implementation-note-2026-01-01-bogus-type"
    s3_reconcile.put_object(key, _CONTENT_NO_SECTIONS, {**_BASE_S3_META, "type": "not_a_type"})
    bedrock = FakeBedrockClient()
    spy = mocker.spy(vectors_reconcile, "put_vector")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert spy.call_count == 0
    assert result["reconciled"] == []
    assert result["skipped_non_artifacts"] == [key]


async def test_orphan_scan_valid_artifact_still_reindexed_alongside_stray_object(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """The metadata discriminator does not reject a real artifact sharing the prefix."""
    stray_key = "artifacts/.DS_Store"
    artifact_id = "artifacts/implementation-note-2026-01-01-real"
    s3_reconcile.put_object(stray_key, "not an artifact", {})
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert [e["artifact_id"] for e in result["reconciled"]] == [artifact_id]
    assert result["reconciled"][0]["source"] == "orphan_scan"
    assert result["reconciled"][0]["sections_indexed"] == 1
    assert result["skipped_non_artifacts"] == [stray_key]


async def test_probe_key_not_reported_as_skipped_non_artifact(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """A probe key is expected, not stray → excluded from the scan, absent from the report."""
    stray_key = "artifacts/.DS_Store"
    s3_reconcile.put_object("artifacts/_arkeology_health_probe", "probe", {})
    s3_reconcile.put_object(stray_key, "not an artifact", {})
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["skipped_non_artifacts"] == [stray_key]


async def test_skipped_non_artifacts_absent_when_nothing_skipped(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Nothing skipped → the field is absent, not an empty list."""
    artifact_id = "artifacts/implementation-note-2026-01-01-clean"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert "skipped_non_artifacts" not in result


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
    bedrock = FakeBedrockClient()
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
    bedrock = FakeBedrockClient()
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
    commit_refs (as list[str], sourced from the durable annotation per ADR-011/T48 — S3
    user-defined metadata no longer carries this field post-T47) and last_edited_ulid —
    otherwise commit-ref filtering silently stops matching and last_edited_ulid is lost
    for the rebuilt artifact.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-with-refs"
    ulid = "01HZZZ0000000000000000000A"
    meta = {
        **_BASE_S3_META,
        "last_edited_ulid": ulid,
    }
    s3_reconcile.put_object(artifact_id, _CONTENT_TWO_SECTIONS, meta)
    apply_link_annotations(
        s3_reconcile, artifact_id, commit_refs=["abc123", "def456"], references=[]
    )
    bedrock = FakeBedrockClient()

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


async def test_reindex_splits_comma_bearing_stored_tags(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Artifacts stored before tags/source_artifacts rejected commas can carry a comma
    inside a single element, which the S3 read path splits into two elements while the
    vector read path returns one — the two stores disagree. Reconcile rebuilds vector
    metadata from the S3 side through the same comma-splitting coercion, so after a
    reconcile both stores agree on the split form. This pins that self-heal path; the
    seed bypasses Artifact validation deliberately, since a write can no longer produce
    this shape.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-legacy-comma-tags"
    meta = {**_BASE_S3_META, "tags": "a,b", "source_artifacts": "adr-one,adr-two"}
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, meta)
    bedrock = FakeBedrockClient()

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
    assert vmeta.get("tags") == ["a", "b"]
    assert vmeta.get("source_artifacts") == ["adr-one", "adr-two"]


# ---------------------------------------------------------------------------
# T48 — reconcile rebuilds commit_refs / references from durable annotations
# ---------------------------------------------------------------------------


async def test_reindex_restores_link_fields_from_annotations(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """RED proof (ADR-011 / T48, Story 2): an object whose S3 user-defined metadata has
    NO commit_refs/references keys at all (the post-T47 reality) but whose durable
    annotations carry both fields — reconcile must source the rebuilt commit_refs from
    the annotations, not from S3 metadata; references is read from the annotation too
    (its sole source of truth) but, as of T58, is never re-written into vector metadata —
    it remains readable only via the annotation.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-from-annotations"
    s3_reconcile.put_object(artifact_id, _CONTENT_TWO_SECTIONS, {**_BASE_S3_META})
    apply_link_annotations(
        s3_reconcile,
        artifact_id,
        commit_refs=["abc123", "def456"],
        references=["implementation-note-2026-01-01-other"],
    )
    bedrock = FakeBedrockClient()

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
    # T58: references is never re-written into vector metadata, even though it was
    # read from the annotation above.
    assert "references" not in vmeta


async def test_reindex_clean_state_omits_empty_link_fields(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """An object with no link annotations at all reconciles to rebuilt vector metadata
    that simply omits commit_refs and references — no error, no empty-list keys (S3
    Vectors rejects empty arrays)."""
    artifact_id = "artifacts/implementation-note-2026-01-01-clean-state"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient()

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
    assert "commit_refs" not in vmeta
    assert "references" not in vmeta


async def test_reindex_annotation_read_failure_fails_the_artifact(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A failed annotation read must fail that artifact, never be treated as "no link
    fields". Reconcile rebuilds vector metadata from what it read, so degrading to empty
    here would write the emptiness back over the artifact's real link fields. The run
    still completes — the failure is reported per artifact, not as an aborted run."""
    artifact_id = "artifacts/implementation-note-2026-01-01-annotations-unavailable"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    mocker.patch.object(
        s3_reconcile,
        "get_object_annotation",
        side_effect=RuntimeError("simulated annotation feature unavailable"),
    )
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert artifact_id not in [e["artifact_id"] for e in result["reconciled"]]
    assert artifact_id in [e["artifact_id"] for e in result["failed"]]
    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    assert keys == [], "no vectors may be written from an unreadable link-field state"


async def test_failure_log_replay_and_orphan_scan_both_restore(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Both _reindex_artifact call sites — Phase 1 failure-log replay and Phase 2
    orphan scan — pass s3 through and restore link fields identically from
    annotations."""
    replay_id = "artifacts/implementation-note-2026-01-01-replay-restores"
    orphan_id = "artifacts/implementation-note-2026-01-01-orphan-restores"

    s3_reconcile.put_object(replay_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    apply_link_annotations(s3_reconcile, replay_id, commit_refs=["aaa1111"], references=[])
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": replay_id}],
    )

    s3_reconcile.put_object(orphan_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    apply_link_annotations(s3_reconcile, orphan_id, commit_refs=["bbb2222"], references=[])

    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result

    replay_keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": replay_id}})
    replay_items = vectors_reconcile.get_vectors(replay_keys)
    assert replay_items, "failure-log replay should have indexed vectors"
    assert replay_items[0]["metadata"].get("commit_refs") == ["aaa1111"]

    orphan_keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": orphan_id}})
    orphan_items = vectors_reconcile.get_vectors(orphan_keys)
    assert orphan_items, "orphan scan should have indexed vectors"
    assert orphan_items[0]["metadata"].get("commit_refs") == ["bbb2222"]

    reconciled_by_source = {e["artifact_id"]: e["source"] for e in result["reconciled"]}
    assert reconciled_by_source[replay_id] == "failure_log"
    assert reconciled_by_source[orphan_id] == "orphan_scan"


# ---------------------------------------------------------------------------
# Annotation authority model
# ---------------------------------------------------------------------------


async def test_reindex_from_failure_log_rebuilds_commit_refs_from_the_annotation(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Reconcile rebuilds the derived vector-metadata copy of commit_refs from the
    annotation, the sole source of truth — not from whatever the pre-existing vector
    happened to carry. A value present only on the old vector is not preserved: that
    copy is a derived filter index. Re-index is forced via a failure-log entry so
    ``_reindex_artifact`` runs even though a vector is already indexed. references is
    never written into vector metadata at all.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-vector-only-links"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    apply_link_annotations(
        s3_reconcile,
        artifact_id,
        commit_refs=["abc123"],
        references=["implementation-note-2026-01-01-other"],
    )
    vectors_reconcile.put_vector(
        artifact_id,
        [0.1] * DIMENSION,
        {
            "artifact_id": artifact_id,
            "scope": reconcile_settings.write_prefix,
            "type": "implementation_note",
            "commit_refs": ["stale-vector-only-sha"],
            "references": ["implementation-note-2026-01-01-other"],
        },
    )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    items = vectors_reconcile.get_vectors(keys)
    assert items, "reconcile should have re-indexed vectors for the artifact"
    vmeta = items[0]["metadata"]
    assert vmeta.get("commit_refs") == ["abc123"]
    # The annotation copy itself is untouched by the rebuild.
    assert s3_reconcile.get_object_annotation(artifact_id, "commit_refs") == "abc123"
    # references is never re-written into vector metadata.
    assert "references" not in vmeta


async def test_reindex_credential_error_from_annotation_read_propagates(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """RED: a CredentialError raised while reading link annotations during reconcile
    must propagate as a structured credential_error and abort the run — not be silently
    swallowed by a bare ``except Exception``, which would otherwise re-index every
    remaining artifact without its commit_refs/references and report success."""
    artifact_id = "artifacts/implementation-note-2026-01-01-cred-error"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )
    mocker.patch.object(
        s3_reconcile,
        "get_object_annotation",
        side_effect=CredentialError("expired", "s3", Exception("boom")),
    )
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("error") == "credential_error"
    # The artifact must not have been silently re-indexed without its link fields.
    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    assert keys == []


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------


async def test_response_always_has_all_six_fields(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """All 6 fields always present in non-error response regardless of workload."""
    bedrock = FakeBedrockClient()

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
    bedrock = FakeBedrockClient()

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
    bedrock = FakeBedrockClient()

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
    bedrock = FakeBedrockClient()
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
    bedrock = FakeBedrockClient()
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
    """S3 has only _arkeology_health_probe key → orphans_found == 0."""
    s3_reconcile.put_object("artifacts/_arkeology_health_probe", "probe", {})
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("orphans_found", 0) == 0
    reconciled = result.get("reconciled", [])
    assert "_arkeology_health_probe" not in str(reconciled)


async def test_health_probe_excluded_but_real_orphan_found(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """S3 has probe + real orphan → orphans_found == 1, only real artifact reconciled."""
    s3_reconcile.put_object("artifacts/_arkeology_health_probe", "probe", {})
    s3_reconcile.put_object(
        "artifacts/code-review-2026-05-30-orphan",
        "## Summary\n\nOrphan content.",
        {
            "type": "code_review",
            "team": "platform",
            "project": "arkeology",
            "tier": "2",
            "date": "2026-05-30",
            "status": "active",
            "title": "Orphan",
            "visibility": "shared",
            "description": "An orphan",
        },
    )
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("orphans_found", 0) == 1
    reconciled = result.get("reconciled", [])
    assert "_arkeology_health_probe" not in str(reconciled)


async def test_nested_probe_key_also_excluded(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Probe key at nested path (endswith match) → excluded."""
    s3_reconcile.put_object("artifacts/subdir/_arkeology_health_probe", "probe", {})
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("orphans_found", 0) == 0


async def test_annotation_probe_key_excluded_from_orphans(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Setup skill's `_arkeology_annotation_probe` leftover is never treated as an orphan."""
    s3_reconcile.put_object("artifacts/_arkeology_annotation_probe", "probe", {})
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("orphans_found", 0) == 0
    assert "_arkeology_annotation_probe" not in str(result)


async def test_annotation_probe_excluded_but_real_orphan_found(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """The `_arkeology_` exclusion filters probes only — a real orphan is still re-indexed."""
    s3_reconcile.put_object("artifacts/_arkeology_annotation_probe", "probe", {})
    s3_reconcile.put_object(
        "artifacts/code-review-2026-05-30-orphan",
        "## Summary\n\nOrphan content.",
        {
            "type": "code_review",
            "team": "platform",
            "project": "arkeology",
            "tier": "2",
            "date": "2026-05-30",
            "status": "active",
            "title": "Orphan",
            "visibility": "shared",
            "description": "An orphan",
        },
    )
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert result.get("orphans_found", 0) == 1
    reconciled_ids = [e["artifact_id"] for e in result.get("reconciled", [])]
    assert reconciled_ids == ["artifacts/code-review-2026-05-30-orphan"]
    assert "_arkeology_annotation_probe" not in str(result)


async def test_future_probe_key_excluded_without_code_change(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Any key whose final segment starts with `_arkeology_` is excluded — no per-name patch."""
    s3_reconcile.put_object("artifacts/nested/_arkeology_some_future_probe", "probe", {})
    bedrock = FakeBedrockClient()

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
            "project": "arkeology",
            "tier": "2",
            "date": "2026-05-30",
            "status": "active",
            "title": "Orphan",
            "visibility": "shared",
            "description": "An orphan",
        },
    )
    bedrock = FakeBedrockClient()
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
            "project": "arkeology",
            "tier": "2",
            "date": "2026-05-30",
            "status": "active",
            "title": "Orphan",
            "visibility": "shared",
            "description": "An orphan",
        },
    )
    bedrock = FakeBedrockClient()
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
    """Orphan scan skips S3 keys containing '_arkeology_startup_probe'."""
    # Seed a real artifact
    s3_reconcile.put_object(
        "artifacts/code-review-2026-01-01-real",
        "## Summary\n\nReal artifact.",
        {
            "type": "code_review",
            "team": "platform",
            "project": "arkeology",
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
        "artifacts/_arkeology_startup_probe",
        "startup-probe",
        {},
    )
    # Index the real artifact so it is not reported as an orphan
    vectors_reconcile.put_vector(
        "artifacts/code-review-2026-01-01-real",
        [1.0] + [0.0] * (DIMENSION - 1),
        {"artifact_id": "artifacts/code-review-2026-01-01-real", "scope": "artifacts"},
    )
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    # The startup probe must not appear in reconciled or failed lists
    all_ids = [e["artifact_id"] for e in result.get("reconciled", []) + result.get("failed", [])]
    assert not any("_arkeology_startup_probe" in aid for aid in all_ids)
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

    bedrock = FakeBedrockClient()
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

    bedrock = FakeBedrockClient()
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

    bedrock = FakeBedrockClient()

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

    bedrock = FakeBedrockClient()

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


async def test_phase3_race_written_after_vector_listing_not_pruned(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """RED proof: an artifact whose S3 object exists at prune time, but was excluded
    from the S3 listing snapshot Phase 2/3 took (simulating a write that completed
    between the S3 listing and the vector listing), must NOT have its vectors pruned.
    A re-``head_object`` check immediately before deletion must confirm the object is
    actually absent before treating the vector entry as dangling. Before the fix, the
    listing snapshot alone decided dangling-ness, so this concurrently-written
    artifact's fresh vectors would be deleted."""
    artifact_id = "artifacts/implementation-note-2026-01-01-race-written"
    vec_key = f"{artifact_id}#section"

    # The artifact is actually present in S3 (simulating: it was written between the
    # S3 listing and the vector listing) and its vector is indexed.
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    vectors_reconcile.put_vector(
        vec_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        {"artifact_id": artifact_id, "scope": "artifacts"},
    )

    # Simulate the race: the S3 listing snapshot taken by Phase 2/3 did NOT include
    # this key, as if it had not yet been written when list_objects ran — even though
    # the object exists in S3 by the time Phase 3 prunes.
    real_list_objects = s3_reconcile.list_objects

    def _stale_listing(prefix: str) -> list[str]:
        return [k for k in real_list_objects(prefix) if k != artifact_id]

    mocker.patch.object(s3_reconcile, "list_objects", side_effect=_stale_listing)
    spy_delete = mocker.spy(vectors_reconcile, "delete_vectors")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    assert artifact_id not in result["dangling_artifacts"]
    assert spy_delete.call_count == 0
    # The vector must still be present — not pruned.
    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    assert vec_key in keys


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

    bedrock = FakeBedrockClient()

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

    bedrock = FakeBedrockClient()
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

    bedrock = FakeBedrockClient()

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
    bedrock = FakeBedrockClient()

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


async def test_phase1_failure_not_duplicated_as_phase2_orphan(
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

    bedrock = FakeBedrockClient()
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


# ---------------------------------------------------------------------------
# T55 (Story 4) — reconcile rebuild preserves non-ASCII titles losslessly
# ---------------------------------------------------------------------------


async def test_reindex_preserves_non_ascii_title(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """An artifact seeded with a non-Latin title (transport-encoded on S3 by put_object,
    exactly as write_artifact would produce) is rebuilt by reconcile_index with the
    original title in vector metadata — not the percent-encoded transport form and not a
    stripped/empty string.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-non-ascii-title"
    non_ascii_title = "日本語のタイトル"
    s3_reconcile.put_object(
        artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META, "title": non_ascii_title}
    )
    bedrock = FakeBedrockClient()

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
    assert items[0]["metadata"]["title"] == non_ascii_title

    reconciled_entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert reconciled_entry["title"] == non_ascii_title


# ---------------------------------------------------------------------------
# reconcile_index's blocking client calls are offloaded off the event loop
# ---------------------------------------------------------------------------


async def test_reconcile_orphan_scan_calls_run_off_event_loop(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """During the orphan scan, s3.list_objects/get_object/head_object and
    bedrock.embed (invoked inside _reindex_artifact) all execute on a worker thread,
    never on the calling event-loop thread — proves the calls are routed through
    asyncio.to_thread."""
    artifact_id = "artifacts/implementation-note-2026-01-01-off-loop-orphan"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient()
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []

    original_list_objects = s3_reconcile.list_objects
    original_get_object = s3_reconcile.get_object
    original_head_object = s3_reconcile.head_object
    original_embed = bedrock.embed

    def spy_list_objects(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_list_objects(*args, **kwargs)

    def spy_get_object(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_get_object(*args, **kwargs)

    def spy_head_object(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_head_object(*args, **kwargs)

    def spy_embed(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_embed(*args, **kwargs)

    mocker.patch.object(s3_reconcile, "list_objects", side_effect=spy_list_objects)
    mocker.patch.object(s3_reconcile, "get_object", side_effect=spy_get_object)
    mocker.patch.object(s3_reconcile, "head_object", side_effect=spy_head_object)
    mocker.patch.object(bedrock, "embed", side_effect=spy_embed)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["orphans_found"] == 1
    assert seen_threads, "s3/bedrock calls were never made"
    assert all(t is not main_thread for t in seen_threads), (
        "s3/bedrock calls ran on the event-loop thread — they must be offloaded"
    )


async def test_reconcile_dangling_prune_calls_run_off_event_loop(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """During dangling-vector pruning, vectors.list_vectors_by_metadata,
    s3.head_object (re-confirmation), and vectors.delete_vectors all execute on a
    worker thread, never on the calling event-loop thread."""
    dangling_id = "artifacts/implementation-note-2026-01-01-off-loop-dangling"
    vectors_reconcile.put_vector(
        f"{dangling_id}#section",
        [0.1] * DIMENSION,
        {"artifact_id": dangling_id, "scope": "artifacts"},
    )
    bedrock = FakeBedrockClient()
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []

    original_list_by_meta = vectors_reconcile.list_vectors_by_metadata
    original_head_object = s3_reconcile.head_object
    original_delete_vectors = vectors_reconcile.delete_vectors

    def spy_list_by_meta(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_list_by_meta(*args, **kwargs)

    def spy_head_object(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_head_object(*args, **kwargs)

    def spy_delete_vectors(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_delete_vectors(*args, **kwargs)

    mocker.patch.object(vectors_reconcile, "list_vectors_by_metadata", side_effect=spy_list_by_meta)
    mocker.patch.object(s3_reconcile, "head_object", side_effect=spy_head_object)
    mocker.patch.object(vectors_reconcile, "delete_vectors", side_effect=spy_delete_vectors)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert result["dangling_artifacts_found"] == 1
    assert seen_threads, "vector/s3 calls were never made"
    assert all(t is not main_thread for t in seen_threads), (
        "Dangling-prune calls ran on the event-loop thread — they must be offloaded"
    )


# ---------------------------------------------------------------------------
# T57 — check_metadata_budgets guard coverage in reconcile.py's _reindex_artifact
# (docs/specs/p12-t57-guard-coverage.md, Story 2). An artifact whose rebuilt
# vector_metadata (including commit_refs/references restored from
# read_current_link_fields) would breach a metadata size budget must be rejected
# BEFORE any put_vector call, and reported in `failed` rather than crashing or
# silently succeeding.
# ---------------------------------------------------------------------------

_HUGE_COMMIT_REF = "a" * (VECTOR_FILTERABLE_METADATA_MAX_BYTES + 200)


async def test_failure_log_entry_oversize_link_fields_rejected_reported_in_failed(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A failure-log-replayed artifact whose durable commit_refs annotation is oversize
    breaches the vector filterable-metadata budget once rebuilt into vector_metadata —
    _reindex_artifact raises MetadataTooLargeError, reconcile_index reports it in
    `failed` (not a crash), makes zero put_vector calls for that artifact, and a
    normal artifact in the same run still reconciles successfully."""
    oversize_id = "artifacts/implementation-note-2026-01-01-oversize"
    normal_id = "artifacts/implementation-note-2026-01-01-normal"
    s3_reconcile.put_object(oversize_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    s3_reconcile.put_object(normal_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    apply_link_annotations(s3_reconcile, oversize_id, commit_refs=[_HUGE_COMMIT_REF], references=[])
    bedrock = FakeBedrockClient()
    put_vector_spy = mocker.spy(vectors_reconcile, "put_vector")

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {**_BASE_LOG_ENTRY, "artifact_id": oversize_id},
            {**_BASE_LOG_ENTRY, "artifact_id": normal_id},
        ],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    failed_ids = [e["artifact_id"] for e in result["failed"]]
    assert oversize_id in failed_ids
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert normal_id in reconciled_ids
    assert oversize_id not in reconciled_ids
    assert all(call.args[0] != oversize_id for call in put_vector_spy.call_args_list)


async def test_orphan_scan_oversize_link_fields_rejected_reported_in_failed(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """An orphan-scan-discovered artifact (indexed nowhere, so picked up by Phase 2)
    whose durable commit_refs annotation is oversize is rejected identically to the
    failure-log-replay path — both share _reindex_artifact — reported in `failed`,
    zero put_vector calls, a normal orphan in the same run still reconciles.

    Uses commit_refs (not references) as the oversize field: as of T58, references is
    never written into vector metadata under any code path, so an oversize references
    annotation alone can no longer breach the vector-metadata budget — only commit_refs
    (still vector-metadata-filterable, now capped at 20 entries but not at byte size per
    entry) can.
    """
    oversize_id = "artifacts/implementation-note-2026-01-01-orphan-oversize"
    normal_id = "artifacts/implementation-note-2026-01-01-orphan-normal"
    s3_reconcile.put_object(oversize_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    s3_reconcile.put_object(normal_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    apply_link_annotations(s3_reconcile, oversize_id, commit_refs=[_HUGE_COMMIT_REF], references=[])
    bedrock = FakeBedrockClient()
    put_vector_spy = mocker.spy(vectors_reconcile, "put_vector")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    failed_ids = [e["artifact_id"] for e in result["failed"]]
    assert oversize_id in failed_ids
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert normal_id in reconciled_ids
    assert oversize_id not in reconciled_ids
    assert all(call.args[0] != oversize_id for call in put_vector_spy.call_args_list)


# ---------------------------------------------------------------------------
# T58 — commit_refs vector-metadata cap (20) + references vector-metadata removal
# ---------------------------------------------------------------------------


async def test_reindex_commit_refs_over_cap_truncated_references_omitted(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """An artifact whose durable commit_refs annotation carries more than 20 (short,
    well-under-budget) entries, plus a non-empty references annotation: after
    reconcile, the rebuilt vector metadata carries only the last 20 commit_refs and no
    references key — the annotation itself remains the complete, uncapped source."""
    artifact_id = "artifacts/implementation-note-2026-01-01-over-cap"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    full_commit_refs = [f"sha{i:04d}" for i in range(25)]
    apply_link_annotations(
        s3_reconcile,
        artifact_id,
        commit_refs=full_commit_refs,
        references=["implementation-note-2026-01-01-other"],
    )
    bedrock = FakeBedrockClient()

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
    assert vmeta.get("commit_refs") == full_commit_refs[-20:]
    assert len(vmeta["commit_refs"]) == 20
    assert "references" not in vmeta
    # The annotation itself remains the complete, uncapped list.
    assert s3_reconcile.get_object_annotation(artifact_id, "commit_refs") == ",".join(
        full_commit_refs
    )


# T62 — Bounded failure-log retry: reconcile_attempts / stuck_failures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prior_attempts", [None, 0, 1, 2])
async def test_failure_log_entry_below_threshold_fails_increments_and_stays_in_failed(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
    prior_attempts: int | None,
) -> None:
    """An entry whose prior reconcile_attempts is below CAS_MAX_ATTEMPTS (unset/0/1/2)
    that fails this run: reconcile_attempts increments by one, and — because 2->3 is
    exactly the run on which the threshold is crossed — the entry lands in
    stuck_failures instead of failed once the increment reaches CAS_MAX_ATTEMPTS. Below
    that, it stays in failed exactly as today. Either way the rewritten failure log on
    disk carries the updated counter."""
    artifact_id = "artifacts/implementation-note-2026-01-01-below-threshold"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    entry: dict[str, Any] = {**_BASE_LOG_ENTRY, "artifact_id": artifact_id}
    if prior_attempts is not None:
        entry["reconcile_attempts"] = prior_attempts
    _write_failure_log(reconcile_settings.failure_log_path, [entry])

    bedrock = FakeBedrockClient()
    mocker.patch.object(bedrock, "embed", side_effect=RuntimeError("simulated embed failure"))

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    expected_attempts = (prior_attempts or 0) + 1
    failed_ids = [e["artifact_id"] for e in result["failed"]]
    stuck_ids = [e["artifact_id"] for e in result.get("stuck_failures", [])]

    if expected_attempts >= CAS_MAX_ATTEMPTS:
        assert artifact_id in stuck_ids
        assert artifact_id not in failed_ids
    else:
        assert artifact_id in failed_ids
        assert artifact_id not in stuck_ids

    log_lines = reconcile_settings.failure_log_path.read_text(encoding="utf-8").splitlines()
    persisted = [json.loads(line) for line in log_lines]
    persisted_entry = next(e for e in persisted if e["artifact_id"] == artifact_id)
    assert persisted_entry["reconcile_attempts"] == expected_attempts


async def test_failure_log_entry_at_threshold_skipped_and_reported_stuck(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """An entry whose reconcile_attempts is already >= CAS_MAX_ATTEMPTS before this run
    is never attempted — no _reindex_artifact call, hence no bedrock.embed / put_vector
    call for it — and is reported in stuck_failures, not failed. Its counter does not
    grow further since no attempt was made."""
    artifact_id = "artifacts/implementation-note-2026-01-01-already-stuck"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "reconcile_attempts": CAS_MAX_ATTEMPTS}],
    )
    bedrock = FakeBedrockClient()
    spy = mocker.spy(reconcile_module, "_reindex_artifact")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert spy.call_count == 0
    stuck_ids = [e["artifact_id"] for e in result.get("stuck_failures", [])]
    failed_ids = [e["artifact_id"] for e in result["failed"]]
    assert artifact_id in stuck_ids
    assert artifact_id not in failed_ids

    log_lines = reconcile_settings.failure_log_path.read_text(encoding="utf-8").splitlines()
    persisted = [json.loads(line) for line in log_lines]
    persisted_entry = next(e for e in persisted if e["artifact_id"] == artifact_id)
    assert persisted_entry["reconcile_attempts"] == CAS_MAX_ATTEMPTS


async def test_failure_log_entry_succeeds_pruned_regardless_of_prior_attempts(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """An entry that succeeds this run is pruned from the log regardless of its prior
    reconcile_attempts value — the counter is irrelevant once resolved."""
    artifact_id = "artifacts/implementation-note-2026-01-01-succeeds-with-history"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "reconcile_attempts": 2}],
    )
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert artifact_id in reconciled_ids
    assert result["failure_log_entries_after"] == 0
    # Drained, not unlinked. read_text raises if the file is gone, so this still pins
    # that the log is emptied — an appender blocked on its lock while the rewrite ran
    # would write into an unlinked inode and lose the entry it holds.
    assert reconcile_settings.failure_log_path.read_text(encoding="utf-8").strip() == ""


async def test_response_omits_stuck_failures_when_none(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """A run with no entries crossing the retry threshold omits 'stuck_failures'
    entirely from the response, matching the optional-field convention used by
    skipped_existing/generation_failed-style fields elsewhere."""
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert "stuck_failures" not in result


async def test_orphan_scan_failure_never_produces_stuck_failures(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A Phase 2 (orphan-scan) failure has no persisted failure-log entry and no
    reconcile_attempts counter — it always lands in 'failed', never 'stuck_failures',
    no matter how many times reconcile_index re-runs, since Phase 2's failed list is
    ephemeral per call and there is no replay loop to bound."""
    artifact_id = "artifacts/implementation-note-2026-01-01-orphan-always-fails"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    bedrock = FakeBedrockClient()
    mocker.patch.object(bedrock, "embed", side_effect=RuntimeError("simulated embed failure"))

    for _ in range(4):
        result = await reconcile_index(
            settings=reconcile_settings,
            s3=s3_reconcile,
            vectors=vectors_reconcile,
            bedrock=bedrock,
        )
        assert "error" not in result
        failed_ids = [e["artifact_id"] for e in result["failed"]]
        assert artifact_id in failed_ids
        assert "stuck_failures" not in result


async def test_three_consecutive_runs_cross_threshold_into_stuck_failures(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The same unresolved failure-log entry, replayed across four consecutive
    reconcile_index calls: it appears in 'failed' on runs 1-2, crosses into
    'stuck_failures' on run 3 (the run on which the increment reaches
    CAS_MAX_ATTEMPTS), and _reindex_artifact is never called again on run 4+."""
    artifact_id = "artifacts/implementation-note-2026-01-01-persistent-failure"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )
    bedrock = FakeBedrockClient()
    mocker.patch.object(bedrock, "embed", side_effect=RuntimeError("simulated embed failure"))

    for run in (1, 2):
        result = await reconcile_index(
            settings=reconcile_settings,
            s3=s3_reconcile,
            vectors=vectors_reconcile,
            bedrock=bedrock,
        )
        assert "error" not in result
        failed_ids = [e["artifact_id"] for e in result["failed"]]
        assert artifact_id in failed_ids, f"run {run}"
        assert "stuck_failures" not in result, f"run {run}"

    result_run_3 = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )
    assert "error" not in result_run_3
    stuck_ids = [e["artifact_id"] for e in result_run_3.get("stuck_failures", [])]
    assert artifact_id in stuck_ids
    assert artifact_id not in [e["artifact_id"] for e in result_run_3["failed"]]

    spy = mocker.spy(reconcile_module, "_reindex_artifact")
    result_run_4 = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )
    assert "error" not in result_run_4
    assert spy.call_count == 0
    stuck_ids_4 = [e["artifact_id"] for e in result_run_4.get("stuck_failures", [])]
    assert artifact_id in stuck_ids_4


# ---------------------------------------------------------------------------
# T62 — _fetch_and_reindex shared helper (Phase 1 / Phase 2 dedup)
# ---------------------------------------------------------------------------


async def test_fetch_and_reindex_shared_helper_used_by_both_phases(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Phase 1 (failure-log replay) and Phase 2 (orphan scan) both route their
    fetch-and-reindex sequence through the shared _fetch_and_reindex helper, each with
    the correct 'source' label, and s3.head_object is called exactly once per artifact
    across the pre-fetch and the helper combined (no duplicate re-fetch inside it)."""
    replay_id = "artifacts/implementation-note-2026-01-01-helper-replay"
    orphan_id = "artifacts/implementation-note-2026-01-01-helper-orphan"
    s3_reconcile.put_object(replay_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    s3_reconcile.put_object(orphan_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": replay_id}],
    )
    bedrock = FakeBedrockClient()

    fetch_spy = mocker.spy(reconcile_module, "_fetch_and_reindex")
    head_object_spy = mocker.spy(s3_reconcile, "head_object")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    assert fetch_spy.call_count == 2
    sources_by_artifact = {call.args[0]: call.args[2] for call in fetch_spy.call_args_list}
    assert sources_by_artifact[replay_id] == "failure_log"
    assert sources_by_artifact[orphan_id] == "orphan_scan"

    head_calls = [c.args[0] for c in head_object_spy.call_args_list]
    assert head_calls.count(replay_id) == 1
    assert head_calls.count(orphan_id) == 1


# ---------------------------------------------------------------------------
# T67 — orphan-cleanup failure-log kind: direct repair + (artifact_id, kind) dedup
# ---------------------------------------------------------------------------


async def test_orphan_cleanup_entry_repaired_by_direct_delete_no_reindex(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A failure-log entry carrying orphan_keys is repaired by a direct
    delete_vectors(orphan_keys) call — one head_object to learn the object's current
    last_edited_ulid for the live-key re-check, no get_object, no bedrock.embed for
    that entry — and is pruned from the log and reported in reconciled with the
    orphan_keys_deleted/source shape (no sections_indexed)."""
    artifact_id = "artifacts/implementation-note-2026-01-01-orphan-repair-target"
    stale_key = f"{artifact_id}#stale-section"
    vectors_reconcile.put_vector(
        stale_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        {
            "artifact_id": artifact_id,
            "scope": "artifacts",
            "type": "implementation_note",
            "tier": 2,
            "title": "Test Artifact",
        },
    )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "orphan_keys": [stale_key]}],
    )
    bedrock = FakeBedrockClient()
    delete_spy = mocker.spy(vectors_reconcile, "delete_vectors")
    head_spy = mocker.spy(s3_reconcile, "head_object")
    get_spy = mocker.spy(s3_reconcile, "get_object")
    embed_spy = mocker.spy(bedrock, "embed")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    delete_spy.assert_called_once_with([stale_key])
    assert head_spy.call_count == 1
    assert get_spy.call_count == 0
    assert embed_spy.call_count == 0

    reconciled_entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert reconciled_entry == {
        "artifact_id": artifact_id,
        "title": "Test Artifact",
        "orphan_keys_deleted": 1,
        "source": "orphan_vector_cleanup",
    }
    assert "sections_indexed" not in reconciled_entry
    assert result["failure_log_entries_after"] == 0
    # Drained, not unlinked. read_text raises if the file is gone, so this still pins
    # that the log is emptied — an appender blocked on its lock while the rewrite ran
    # would write into an unlinked inode and lose the entry it holds.
    assert reconcile_settings.failure_log_path.read_text(encoding="utf-8").strip() == ""


async def test_orphan_cleanup_and_reindex_entries_same_artifact_resolved_independently(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Story 5: a reindex-kind entry and an orphan-cleanup-kind entry for the SAME
    artifact_id are both attempted this run (dedup/resolution keyed by
    (artifact_id, kind)). The reindex succeeds; the orphan-cleanup delete fails — only
    the still-failing orphan-cleanup entry survives the log rewrite, the resolved
    reindex entry is pruned independently."""
    artifact_id = "artifacts/implementation-note-2026-01-01-coexist"
    stale_key = f"{artifact_id}#stale-section"
    # The recorded orphan key is absent from the index: the reindex half's post-write
    # prune then has nothing to delete, so the failing delete_vectors below is reached
    # only by the orphan-cleanup half (an absent recorded key is deleted as recorded).
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {**_BASE_LOG_ENTRY, "artifact_id": artifact_id},
            {**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "orphan_keys": [stale_key]},
        ],
    )
    bedrock = FakeBedrockClient()
    mocker.patch.object(vectors_reconcile, "delete_vectors", side_effect=RuntimeError("boom"))

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert artifact_id in reconciled_ids
    failed_entry = next(
        (e for e in result["failed"] if e["artifact_id"] == artifact_id and "orphan_keys" in e),
        None,
    )
    assert failed_entry is not None
    assert failed_entry["orphan_keys"] == [stale_key]

    log_lines = reconcile_settings.failure_log_path.read_text(encoding="utf-8").splitlines()
    persisted = [json.loads(line) for line in log_lines]
    assert len(persisted) == 1
    assert persisted[0].get("orphan_keys") == [stale_key]
    assert persisted[0]["reconcile_attempts"] == 1


async def test_orphan_cleanup_entry_at_threshold_skipped_and_reported_stuck(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Story 4: an orphan-cleanup entry crossing CAS_MAX_ATTEMPTS on this run's failed
    delete_vectors call is reported in stuck_failures (carrying orphan_keys) instead of
    failed; a subsequent run never attempts delete_vectors for it again."""
    artifact_id = "artifacts/implementation-note-2026-01-01-orphan-stuck"
    stale_key = f"{artifact_id}#stale-section"
    # An S3 object backs this artifact_id (matching the realistic T67 scenario — the
    # orphan-cleanup entry originates from Step 8 of a successful overwrite) so Phase 3's
    # dangling-vector prune never independently targets the same still-indexed stale_key
    # and double-reports this artifact_id in `failed`.
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    vectors_reconcile.put_vector(
        stale_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        {
            "artifact_id": artifact_id,
            "scope": "artifacts",
            "type": "implementation_note",
            "tier": 2,
            "title": "Test Artifact",
        },
    )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {
                **_BASE_LOG_ENTRY,
                "artifact_id": artifact_id,
                "orphan_keys": [stale_key],
                "reconcile_attempts": CAS_MAX_ATTEMPTS - 1,
            }
        ],
    )
    bedrock = FakeBedrockClient()
    mocker.patch.object(vectors_reconcile, "delete_vectors", side_effect=RuntimeError("boom"))

    result_run_1 = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result_run_1
    stuck = next(
        e for e in result_run_1.get("stuck_failures", []) if e["artifact_id"] == artifact_id
    )
    assert stuck["reconcile_attempts"] == CAS_MAX_ATTEMPTS
    assert stuck["orphan_keys"] == [stale_key]
    assert artifact_id not in [e["artifact_id"] for e in result_run_1["failed"]]

    delete_spy = mocker.patch.object(
        vectors_reconcile, "delete_vectors", side_effect=RuntimeError("boom")
    )
    result_run_2 = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result_run_2
    assert delete_spy.call_count == 0
    stuck_2 = next(
        e for e in result_run_2.get("stuck_failures", []) if e["artifact_id"] == artifact_id
    )
    assert stuck_2["reconcile_attempts"] == CAS_MAX_ATTEMPTS
    assert stuck_2["orphan_keys"] == [stale_key]


async def test_orphan_cleanup_partially_absent_keys_still_resolves(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Story 3 idempotency: orphan_keys containing one still-indexed key and one
    already-absent key does not raise and the entry still resolves exactly as a
    fully-successful delete."""
    artifact_id = "artifacts/implementation-note-2026-01-01-orphan-partial"
    present_key = f"{artifact_id}#present"
    absent_key = f"{artifact_id}#absent"
    vectors_reconcile.put_vector(
        present_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        {
            "artifact_id": artifact_id,
            "scope": "artifacts",
            "type": "implementation_note",
            "tier": 2,
            "title": "Test Artifact",
        },
    )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "orphan_keys": [present_key, absent_key]}],
    )
    bedrock = FakeBedrockClient()

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    reconciled_entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert reconciled_entry["orphan_keys_deleted"] == 2
    assert reconciled_entry["source"] == "orphan_vector_cleanup"
    assert result["failure_log_entries_after"] == 0
    # Drained, not unlinked. read_text raises if the file is gone, so this still pins
    # that the log is emptied — an appender blocked on its lock while the rewrite ran
    # would write into an unlinked inode and lose the entry it holds.
    assert reconcile_settings.failure_log_path.read_text(encoding="utf-8").strip() == ""


# ---------------------------------------------------------------------------
# Failure-log link-field restore
# ---------------------------------------------------------------------------


async def test_failure_log_entry_restores_link_fields_beyond_the_vector_cap(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """An entry carrying link fields has them re-applied as the durable annotation copy.

    The commit_refs list here is deliberately longer than the vector-metadata cap: the
    entries beyond that window exist nowhere else once the annotations were cleared, so
    this is the case the entry's copy is the only possible source for. References are
    never in vector metadata at all, so every value there is in the same position.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    commit_refs = [f"sha{index:04d}" for index in range(25)]

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {
                **_BASE_LOG_ENTRY,
                "artifact_id": artifact_id,
                "failure_step": "annotation_write",
                "commit_refs": commit_refs,
                "references": ["artifacts/some-adr"],
            }
        ],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    assert result["failure_log_entries_after"] == 0
    restored = decode_link_list(s3_reconcile.get_object_annotation(artifact_id, "commit_refs"))
    assert restored == commit_refs
    assert decode_link_list(s3_reconcile.get_object_annotation(artifact_id, "references")) == [
        "artifacts/some-adr"
    ]


async def test_failure_log_entry_without_link_fields_leaves_annotations_untouched(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """An entry written before link fields were recorded on it has neither field.

    Absence means "nothing to restore", never "clear the link fields": replaying such an
    entry must not raise and must leave the object's existing annotations intact.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    apply_link_annotations(
        s3_reconcile,
        artifact_id,
        commit_refs=["abc1234"],
        references=["artifacts/some-adr"],
    )

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    assert result["failure_log_entries_after"] == 0
    assert s3_reconcile.get_object_annotation(artifact_id, "commit_refs") == "abc1234"
    assert s3_reconcile.get_object_annotation(artifact_id, "references") == "artifacts/some-adr"


async def test_failure_log_entry_link_fields_union_with_the_current_value(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """The restore combines the entry's copy with the current value, never replaces it.

    A value re-added between the failure and the reconcile lives only in the current
    annotation copy; a replace would drop it, and a restore that skipped the entry's
    copy would drop what the failed write was holding. Both must survive.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    apply_link_annotations(
        s3_reconcile,
        artifact_id,
        commit_refs=["shab222"],
        references=["artifacts/adr-b"],
    )

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {
                **_BASE_LOG_ENTRY,
                "artifact_id": artifact_id,
                "commit_refs": ["shaa111"],
                "references": ["artifacts/adr-a"],
            }
        ],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    assert decode_link_list(s3_reconcile.get_object_annotation(artifact_id, "commit_refs")) == [
        "shaa111",
        "shab222",
    ]
    assert decode_link_list(s3_reconcile.get_object_annotation(artifact_id, "references")) == [
        "artifacts/adr-a",
        "artifacts/adr-b",
    ]


# ---------------------------------------------------------------------------
# T74.1 — the references supersession rule (AC-68)
#
# A failure-log entry may record the artifact's last_edited_ulid as it stood when
# the failure happened. references is restored only while that token still equals
# the artifact's current one; commit_refs unions unconditionally, being append-only.
# ---------------------------------------------------------------------------

_ULID_AT_FAILURE = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
_ULID_AFTER_LATER_WRITE = "01BRZ3NDEKTSV4RRFFQ69G5FAV"


def _seed_superseded_artifact(s3: S3ClientImpl) -> str:
    """Seed the AC-68 scenario: a later overwrite has already replaced the link fields.

    The artifact carries the ULID the *later* write generated, its annotations hold
    what that write established, and the failure-log entry (written by the earlier,
    failed write) still carries the pre-overwrite values under the older ULID.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3.put_object(
        artifact_id,
        _CONTENT_NO_SECTIONS,
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    apply_link_annotations(
        s3,
        artifact_id,
        commit_refs=["sha-added-later"],
        references=["artifacts/adr-the-later-write-kept"],
    )
    return artifact_id


_SUPERSEDED_ENTRY: dict[str, Any] = {
    **_BASE_LOG_ENTRY,
    "failure_step": "annotation_write",
    "last_edited_ulid": _ULID_AT_FAILURE,
    "commit_refs": ["sha-at-failure"],
    "references": ["artifacts/adr-the-later-write-removed"],
}


async def test_superseded_entry_does_not_restore_the_references_a_later_write_removed(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """AC-68, removal half: a `references` value a later successful overwrite removed
    stays removed across the replay.

    Every write replaces `references` outright, so an entry whose recorded
    `last_edited_ulid` no longer matches the artifact's describes a state a later write
    has already superseded. Restoring the entry's copy over it resurrects exactly the
    references that write deliberately dropped — the artifact must keep the list the
    later write set, and nothing else.
    """
    artifact_id = _seed_superseded_artifact(s3_reconcile)
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_SUPERSEDED_ENTRY, "artifact_id": artifact_id}],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    _commit_refs, references = read_link_annotations(s3_reconcile, artifact_id)
    assert references == ["artifacts/adr-the-later-write-kept"]


async def test_superseded_entry_still_restores_its_commit_refs_by_union(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """AC-68, accrual half: the same superseded entry's `commit_refs` is still restored.

    `commit_refs` is an append-only audit trail on which removal is not a supported
    operation, so supersession says nothing about it: the entry's copy and the value
    the later write added are both real history, and only the union keeps both. A fix
    that discarded the whole entry once the ULIDs diverge would lose the entry's copy —
    which, past the vector cap, exists nowhere else.
    """
    artifact_id = _seed_superseded_artifact(s3_reconcile)
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_SUPERSEDED_ENTRY, "artifact_id": artifact_id}],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    commit_refs, _references = read_link_annotations(s3_reconcile, artifact_id)
    assert commit_refs == ["sha-at-failure", "sha-added-later"]


async def test_unsuperseded_entry_restores_references_by_union(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """A matching `last_edited_ulid` means no write has landed since the failure, so the
    entry's `references` copy is still current and is restored by union.

    This is the case the entry exists for: `references` lives in no other store, so if
    the supersession test rejected a matching token too the only surviving copy would be
    thrown away on every replay.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(
        artifact_id,
        _CONTENT_NO_SECTIONS,
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AT_FAILURE},
    )
    apply_link_annotations(
        s3_reconcile,
        artifact_id,
        commit_refs=[],
        references=["artifacts/adr-still-current"],
    )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {
                **_BASE_LOG_ENTRY,
                "artifact_id": artifact_id,
                "failure_step": "annotation_write",
                "last_edited_ulid": _ULID_AT_FAILURE,
                "references": ["artifacts/adr-from-the-failed-write"],
            }
        ],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    _commit_refs, references = read_link_annotations(s3_reconcile, artifact_id)
    assert references == [
        "artifacts/adr-from-the-failed-write",
        "artifacts/adr-still-current",
    ]


async def test_entry_without_a_ulid_token_restores_references_by_union(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """An entry carrying no `last_edited_ulid` unions, even when the artifact has one.

    An absent token is missing evidence of supersession, not evidence of it. Treating
    it as a mismatch would discard every entry written before the token existed — the
    only surviving copy of values no later write had touched.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(
        artifact_id,
        _CONTENT_NO_SECTIONS,
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    apply_link_annotations(
        s3_reconcile,
        artifact_id,
        commit_refs=[],
        references=["artifacts/adr-current"],
    )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {
                **_BASE_LOG_ENTRY,
                "artifact_id": artifact_id,
                "failure_step": "annotation_write",
                "references": ["artifacts/adr-from-a-tokenless-entry"],
            }
        ],
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    _commit_refs, references = read_link_annotations(s3_reconcile, artifact_id)
    assert references == ["artifacts/adr-from-a-tokenless-entry", "artifacts/adr-current"]


async def test_supersession_is_detected_when_the_later_write_left_the_etag_unchanged(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """The supersession token has to be `last_edited_ulid`, never the object's ETag.

    An overwriting write that changes only `references` leaves the body byte-identical,
    so the ETag is unchanged — an ETag comparison would read "not superseded" and
    restore precisely the removal this rule exists to preserve. The ULID moves on that
    write regardless, which is why it is the token. The assertion on the two ETags is
    what makes this test distinguish the two implementations rather than merely repeat
    the removal case above.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(
        artifact_id,
        _CONTENT_NO_SECTIONS,
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AT_FAILURE},
    )
    etag_at_failure = s3_reconcile.head_object(artifact_id)["ETag"]
    apply_link_annotations(
        s3_reconcile,
        artifact_id,
        commit_refs=["sha-at-failure"],
        references=["artifacts/adr-the-later-write-removed"],
    )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {
                **_BASE_LOG_ENTRY,
                "artifact_id": artifact_id,
                "failure_step": "annotation_write",
                "last_edited_ulid": _ULID_AT_FAILURE,
                "commit_refs": ["sha-at-failure"],
                "references": ["artifacts/adr-the-later-write-removed"],
            }
        ],
    )

    # The later write: same body, new ULID, references cleared. The re-PUT wipes the
    # annotations, exactly as real S3 does, and the write supplies no references.
    s3_reconcile.put_object(
        artifact_id,
        _CONTENT_NO_SECTIONS,
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    etag_after_later_write = s3_reconcile.head_object(artifact_id)["ETag"]
    assert etag_after_later_write == etag_at_failure

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    commit_refs, references = read_link_annotations(s3_reconcile, artifact_id)
    assert references == []
    assert commit_refs == ["sha-at-failure"]


# ---------------------------------------------------------------------------
# T74.3 — prune and stamp by entry identity, not by (artifact_id, kind)
# ---------------------------------------------------------------------------


async def test_same_key_entry_appended_during_replay_survives_the_rewrite(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """An entry appended mid-run for an artifact this run *resolved* must still be kept.

    Pruning by ``(artifact_id, kind)`` drops it: the key is in the resolved set, so the
    end-of-run rewrite discards an entry the run never read, let alone processed. The
    artifact it names is then never repaired — it has vectors (the ones this run built
    from the *old* content), so the orphan scan never revisits it either. Only the
    entries the run actually read may be pruned.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "reason": "read at run start"}],
    )

    real_head_object = s3_reconcile.head_object
    appended = threading.Event()

    def _append_same_key_then_head(key: str) -> dict[str, Any]:
        """Stand in for a concurrent partial write of the SAME artifact, mid-replay."""
        if not appended.is_set():
            appended.set()
            append_failure_entry(
                reconcile_settings.failure_log_path,
                {
                    **_BASE_LOG_ENTRY,
                    "artifact_id": artifact_id,
                    "reason": "appended mid-run",
                },
            )
        return real_head_object(key)

    mocker.patch.object(s3_reconcile, "head_object", side_effect=_append_same_key_then_head)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    assert appended.is_set()
    assert result["failure_log_entries_after"] == 1
    assert reconcile_settings.failure_log_path.exists()
    remaining = [
        json.loads(line)
        for line in reconcile_settings.failure_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [e["reason"] for e in remaining] == ["appended mid-run"]


async def test_entry_appended_during_replay_is_not_stamped_with_attempts_it_never_earned(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A mid-run append must not inherit the attempt count of the entry the run failed.

    Stamping by ``(artifact_id, kind)`` writes ``reconcile_attempts`` onto an entry
    that has never been attempted once, so it reaches the bounded-retry ceiling — and
    ``stuck_failures``, which asks an operator to intervene — sooner than its own
    history justifies, and at the limit is retired without ever having been tried.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})

    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "reason": "read at run start"}],
    )

    real_head_object = s3_reconcile.head_object
    appended = threading.Event()

    def _append_same_key_then_head(key: str) -> dict[str, Any]:
        if not appended.is_set():
            appended.set()
            append_failure_entry(
                reconcile_settings.failure_log_path,
                {
                    **_BASE_LOG_ENTRY,
                    "artifact_id": artifact_id,
                    "reason": "appended mid-run",
                },
            )
        return real_head_object(key)

    mocker.patch.object(s3_reconcile, "head_object", side_effect=_append_same_key_then_head)
    # Make the replay of the entry read at run start fail, so the run stamps an
    # incremented reconcile_attempts for this artifact_id.
    mocker.patch.object(
        vectors_reconcile,
        "put_vectors_batch",
        side_effect=RuntimeError("Simulated vector write failure"),
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    assert appended.is_set()
    remaining = [
        json.loads(line)
        for line in reconcile_settings.failure_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {entry["reason"] for entry in remaining} == {"read at run start", "appended mid-run"}
    read_at_start = next(e for e in remaining if e["reason"] == "read at run start")
    appended_mid_run = next(e for e in remaining if e["reason"] == "appended mid-run")
    assert read_at_start["reconcile_attempts"] == 1
    assert "reconcile_attempts" not in appended_mid_run


# ---------------------------------------------------------------------------
# T74.5 — a failure log that vanishes between the existence check and the read
# ---------------------------------------------------------------------------


async def test_failure_log_vanishing_after_the_existence_check_does_not_fail_the_run(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A concurrent run draining the log between ``exists()`` and the read is not an error.

    Two reconcile runs share one log file, so the window is real. A log that is simply
    gone means "nothing to replay" — turning it into ``internal_error`` discards the
    orphan scan and the dangling-vector prune of an otherwise healthy run.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-test-artifact"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )

    mocker.patch.object(
        reconcile_module,
        "read_failure_entries",
        side_effect=FileNotFoundError(reconcile_settings.failure_log_path),
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    assert result["failure_log_entries_before"] == 0
    # The rest of the run still happened: the artifact has no vectors, so the orphan
    # scan must have found and re-indexed it.
    assert artifact_id in [e["artifact_id"] for e in result["reconciled"]]


# ---------------------------------------------------------------------------
# Contract: arkeology.tools.reconcile, reconcile_index Invariants — several entries per
# key; absent visibility; re-index replaces the vector set; orphan-cleanup replay
# re-checks at prune time.
# ---------------------------------------------------------------------------

_ENTRY_FIRST_FAILED_OVERWRITE: dict[str, Any] = {
    **_BASE_LOG_ENTRY,
    "failure_step": "annotation_write",
    "last_edited_ulid": _ULID_AT_FAILURE,
    "commit_refs": ["sha-a", "sha-b"],
    "references": ["artifacts/adr-first-overwrite"],
    "timestamp": "2026-01-01T00:00:01+00:00",
}
_ENTRY_SECOND_FAILED_OVERWRITE: dict[str, Any] = {
    **_BASE_LOG_ENTRY,
    "failure_step": "annotation_write",
    "last_edited_ulid": _ULID_AFTER_LATER_WRITE,
    "commit_refs": ["sha-c"],
    "references": ["artifacts/adr-second-overwrite"],
    "timestamp": "2026-01-01T00:00:02+00:00",
}


@pytest.mark.parametrize(
    "newest_last", [True, False], ids=["newest-read-last", "newest-read-first"]
)
async def test_entries_sharing_a_key_restore_union_commit_refs_and_newest_references(
    newest_last: bool,
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """commit_refs restores as a union, references only while the entry's recorded
    last_edited_ulid still equals the artifact's current one — the reconcile contract's
    reconcile_index Invariants.

    Two consecutive failed overwrites leave two entries for one key; each
    re-PUT cleared what the previous entry recorded, so the annotations hold nothing.
    The replay restores the union of every entry's commit_refs and the newest entry's
    references — newest by recorded last_edited_ulid, not by read order — and prunes
    both entries together."""
    artifact_id = "artifacts/implementation-note-2026-01-01-two-failed-overwrites"
    s3_reconcile.put_object(
        artifact_id,
        _CONTENT_NO_SECTIONS,
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    first = {**_ENTRY_FIRST_FAILED_OVERWRITE, "artifact_id": artifact_id}
    second = {**_ENTRY_SECOND_FAILED_OVERWRITE, "artifact_id": artifact_id}
    _write_failure_log(
        reconcile_settings.failure_log_path, [first, second] if newest_last else [second, first]
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    commit_refs, references = read_link_annotations(s3_reconcile, artifact_id)
    assert set(commit_refs) == {"sha-a", "sha-b", "sha-c"}
    assert references == ["artifacts/adr-second-overwrite"]
    assert result["failure_log_entries_before"] == 2
    assert result["failure_log_entries_after"] == 0
    assert [e["artifact_id"] for e in result["reconciled"]].count(artifact_id) == 1


async def test_reindex_absent_visibility_rebuilds_hidden_so_both_gate_forms_deny(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Reindexing an absent visibility yields "hidden", never "shared" — the reconcile
    contract's reconcile_index Invariants.

    An S3 object carrying no visibility rebuilds with visibility "hidden".
    The in-process gate reads the absent S3 value as "" and denies a foreign caller;
    the vector copy must not admit what that form refuses, so the server-side filter
    form must deny the rebuilt vector too."""
    artifact_id = "artifacts/implementation-note-2026-01-01-no-visibility"
    s3_meta = {k: v for k, v in _BASE_S3_META.items() if k != "visibility"}
    s3_meta["tier"] = "3"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, s3_meta)
    _write_failure_log(
        reconcile_settings.failure_log_path, [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}]
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    vector_meta = vectors_reconcile.get_vectors([artifact_id], include_data=False)[0]["metadata"]
    assert vector_meta["visibility"] == "hidden"
    # A foreign caller whose read_prefixes include this scope: both gate forms agree.
    foreign_scope, read_prefixes = "other-team", [reconcile_settings.write_prefix]
    assert not is_cross_scope_readable(
        s3_reconcile.head_object(artifact_id), artifact_id, foreign_scope, read_prefixes
    )
    assert not matches_filter(vector_meta, build_scope_filter(foreign_scope, read_prefixes))


def _section_vector_meta(artifact_id: str, ulid: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "scope": "artifacts",
        "type": "implementation_note",
        "tier": 2,
        "title": "Test Artifact",
        "last_edited_ulid": ulid,
    }


async def test_reindex_deletes_section_vectors_absent_from_the_rebuilt_set(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """A re-index replaces the artifact's vector set rather than adding to it — the
    reconcile contract's reconcile_index Invariants.

    A slug removed between versions must not survive a re-index as a searchable
    vector — the artifact's vector set equals the rebuilt set afterwards."""
    artifact_id = "artifacts/implementation-note-2026-01-01-stale-slug"
    s3_reconcile.put_object(
        artifact_id,
        "## Overview\n\nSome overview text.",
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    for slug in ("overview", "details"):
        vectors_reconcile.put_vector(
            f"{artifact_id}#{slug}",
            [1.0] + [0.0] * (DIMENSION - 1),
            _section_vector_meta(artifact_id, _ULID_AT_FAILURE),
        )
    _write_failure_log(
        reconcile_settings.failure_log_path, [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}]
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    assert set(keys) == {f"{artifact_id}#overview"}


async def test_reindex_lists_after_writing_and_spares_a_key_recreated_in_the_window(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A re-index replaces the artifact's vector set without racing a concurrent
    writer — the reconcile contract's reconcile_index Invariants.

    Ordering: the stale set is computed from a listing taken after the rebuilt
    vectors are written, and a listed key whose last_edited_ulid is newer than the one
    this re-index was built under belongs to a later write. A concurrent writer that
    re-creates a stale slug while the re-index is writing must find it still there."""
    artifact_id = "artifacts/implementation-note-2026-01-01-window-race"
    stale_key = f"{artifact_id}#details"
    newer_ulid = "01CRZ3NDEKTSV4RRFFQ69G5FAV"
    s3_reconcile.put_object(
        artifact_id,
        "## Overview\n\nSome overview text.",
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    gone_key = f"{artifact_id}#gone"  # stale and never re-created: deleted, after the write
    for key in (stale_key, gone_key):
        vectors_reconcile.put_vector(
            key,
            [1.0] + [0.0] * (DIMENSION - 1),
            _section_vector_meta(artifact_id, _ULID_AT_FAILURE),
        )
    _write_failure_log(
        reconcile_settings.failure_log_path, [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}]
    )

    original_put = vectors_reconcile.put_vector
    original_delete = vectors_reconcile.delete_vectors
    # call_order pins the order itself: a mutant that lists and deletes before writing
    # still passes the state assertions below, because this test's concurrent writer runs
    # from inside put_vector, after that mutant's delete.
    call_order: list[str] = []
    raced = False

    def _put_then_concurrent_writer_recreates_stale_key(*args: Any, **kwargs: Any) -> None:
        nonlocal raced
        call_order.append("put")
        original_put(*args, **kwargs)
        if not raced:
            raced = True
            original_put(
                stale_key,
                [0.0, 1.0] + [0.0] * (DIMENSION - 2),
                _section_vector_meta(artifact_id, newer_ulid),
            )

    def _record_delete(keys: list[str]) -> None:
        call_order.append("delete")
        original_delete(keys)

    mocker.patch.object(
        vectors_reconcile, "put_vector", side_effect=_put_then_concurrent_writer_recreates_stale_key
    )
    mocker.patch.object(vectors_reconcile, "delete_vectors", side_effect=_record_delete)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    assert call_order.count("delete") == 1
    assert "delete" not in call_order[: len(call_order) - call_order[::-1].index("put")], (
        "a delete_vectors call preceded the last put_vector call"
    )
    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    assert set(keys) == {f"{artifact_id}#overview", stale_key}
    recreated = vectors_reconcile.get_vectors([stale_key], include_data=False)[0]["metadata"]
    assert recreated["last_edited_ulid"] == newer_ulid


async def test_orphan_cleanup_replay_spares_a_recorded_key_that_is_live_again(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The dangling-vector prune re-checks at prune time, so it cannot race a
    concurrent write — the reconcile contract's reconcile_index Invariants.

    A recorded orphan key is deleted only when its vector's last_edited_ulid is
    strictly older than the object's current one. A key carrying the current token was
    re-created by a later write and is live; a key carrying a newer token was re-created
    by a write that landed after the token was read and is live too. Only the recorded key
    with the older token is deleted. orphan_keys_deleted counts the deletions."""
    artifact_id = "artifacts/implementation-note-2026-01-01-recreated-slug"
    live_key, stale_key = f"{artifact_id}#recreated", f"{artifact_id}#stale"
    newer_key = f"{artifact_id}#recreated-after-token-read"
    s3_reconcile.put_object(
        artifact_id,
        _CONTENT_NO_SECTIONS,
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    vectors_reconcile.put_vector(
        live_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        _section_vector_meta(artifact_id, _ULID_AFTER_LATER_WRITE),
    )
    vectors_reconcile.put_vector(
        newer_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        _section_vector_meta(artifact_id, "01CRZ3NDEKTSV4RRFFQ69G5FAV"),
    )
    vectors_reconcile.put_vector(
        stale_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        _section_vector_meta(artifact_id, _ULID_AT_FAILURE),
    )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {
                **_BASE_LOG_ENTRY,
                "artifact_id": artifact_id,
                "orphan_keys": [live_key, newer_key, stale_key],
            }
        ],
    )
    delete_spy = mocker.spy(vectors_reconcile, "delete_vectors")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    delete_spy.assert_called_once_with([stale_key])
    assert set(
        vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    ) == {live_key, newer_key}
    entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert entry["orphan_keys_deleted"] == 1
    assert result["failure_log_entries_after"] == 0


async def test_orphan_cleanup_replay_deletes_every_recorded_key_when_the_object_is_gone(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The dangling-vector prune re-checks at prune time — the reconcile contract's
    reconcile_index Invariants.

    Boundary: an artifact whose object no longer exists has no live vectors,
    so every recorded key is deleted whatever token its vector carries."""
    artifact_id = "artifacts/implementation-note-2026-01-01-object-gone"
    keys = [f"{artifact_id}#a", f"{artifact_id}#b"]
    for key in keys:
        vectors_reconcile.put_vector(
            key,
            [1.0] + [0.0] * (DIMENSION - 1),
            _section_vector_meta(artifact_id, _ULID_AT_FAILURE),
        )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "orphan_keys": keys}],
    )
    delete_spy = mocker.spy(vectors_reconcile, "delete_vectors")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    delete_spy.assert_called_once_with(keys)
    assert vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}}) == []
    entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert entry["orphan_keys_deleted"] == 2


# ---------------------------------------------------------------------------
# Review-fix stage (2026-09-06): mixed tokened/tokenless groups, tokenless-object
# re-index prune, group attempt budget and orphan_keys union, liveness + failed delete.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tokened_ulid", "expected_references"),
    [
        (
            _ULID_AFTER_LATER_WRITE,
            {"artifacts/adr-from-tokenless-entry", "artifacts/adr-from-tokened-entry"},
        ),
        (_ULID_AT_FAILURE, {"artifacts/adr-from-tokenless-entry"}),
    ],
    ids=["tokened-sibling-current", "tokened-sibling-superseded"],
)
async def test_mixed_group_restores_tokenless_references_by_union_regardless_of_sibling(
    tokened_ulid: str,
    expected_references: set[str],
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Grouping invariant, mixed case: a tokenless entry's references are restored by union
    whatever its tokened sibling's fate. The tokened half goes through the supersession
    test (restored when current, dropped when superseded); the tokenless half holds the
    only surviving copy of a value no later write touched and is never discarded on the
    strength of a sibling's token."""
    artifact_id = "artifacts/implementation-note-2026-01-01-mixed-group"
    s3_reconcile.put_object(
        artifact_id,
        _CONTENT_NO_SECTIONS,
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    tokenless = {
        **_BASE_LOG_ENTRY,
        "artifact_id": artifact_id,
        "failure_step": "annotation_write",
        "references": ["artifacts/adr-from-tokenless-entry"],
        "timestamp": "2026-01-01T00:00:01+00:00",
    }
    tokened = {
        **_BASE_LOG_ENTRY,
        "artifact_id": artifact_id,
        "failure_step": "annotation_write",
        "last_edited_ulid": tokened_ulid,
        "references": ["artifacts/adr-from-tokened-entry"],
        "timestamp": "2026-01-01T00:00:02+00:00",
    }
    _write_failure_log(reconcile_settings.failure_log_path, [tokenless, tokened])

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    _commit_refs, references = read_link_annotations(s3_reconcile, artifact_id)
    assert set(references) == expected_references
    assert result["failure_log_entries_after"] == 0


async def test_reindex_of_a_tokenless_object_still_deletes_stale_section_vectors(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Re-index clause, tokenless boundary: when the object carries no last_edited_ulid
    the newer-token exemption does not apply, so a stale slug whose vector carries a token
    is still deleted — the same decision the orphan-cleanup replay makes there."""
    artifact_id = "artifacts/implementation-note-2026-01-01-tokenless-stale-slug"
    s3_reconcile.put_object(artifact_id, "## Overview\n\nSome overview text.", {**_BASE_S3_META})
    for slug in ("overview", "details"):
        vectors_reconcile.put_vector(
            f"{artifact_id}#{slug}",
            [1.0] + [0.0] * (DIMENSION - 1),
            _section_vector_meta(artifact_id, _ULID_AT_FAILURE),
        )
    _write_failure_log(
        reconcile_settings.failure_log_path, [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}]
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    assert set(keys) == {f"{artifact_id}#overview"}


async def test_group_retry_budget_is_the_highest_member_counter(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Grouping invariant: the group's reconcile_attempts is the highest any member
    carries, so reaching stuck_failures does not depend on log read order. The member at
    CAS_MAX_ATTEMPTS - 1 is read second; a first-entry counter would report failed with
    attempts 1 instead of stuck."""
    artifact_id = "artifacts/implementation-note-2026-01-01-group-budget"
    stale_key = f"{artifact_id}#stale"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "orphan_keys": [stale_key]},
            {
                **_BASE_LOG_ENTRY,
                "artifact_id": artifact_id,
                "orphan_keys": [stale_key],
                "reconcile_attempts": CAS_MAX_ATTEMPTS - 1,
                "timestamp": "2026-01-01T00:00:02+00:00",
            },
        ],
    )
    mocker.patch.object(vectors_reconcile, "delete_vectors", side_effect=RuntimeError("boom"))

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    stuck = next(e for e in result.get("stuck_failures", []) if e["artifact_id"] == artifact_id)
    assert stuck["reconcile_attempts"] == CAS_MAX_ATTEMPTS
    assert artifact_id not in [e["artifact_id"] for e in result["failed"]]


async def test_orphan_cleanup_group_deletes_the_union_of_every_members_recorded_keys(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Grouping invariant: two failed cleanups that recorded different stale sets fold to
    the union, so the second entry's keys are deleted rather than leaked while its entry is
    pruned as resolved."""
    artifact_id = "artifacts/implementation-note-2026-01-01-orphan-union"
    first_key, second_key = f"{artifact_id}#first", f"{artifact_id}#second"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    for key in (first_key, second_key):
        vectors_reconcile.put_vector(
            key,
            [1.0] + [0.0] * (DIMENSION - 1),
            _section_vector_meta(artifact_id, _ULID_AT_FAILURE),
        )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [
            {**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "orphan_keys": [first_key]},
            {
                **_BASE_LOG_ENTRY,
                "artifact_id": artifact_id,
                "orphan_keys": [second_key],
                "timestamp": "2026-01-01T00:00:02+00:00",
            },
        ],
    )
    delete_spy = mocker.spy(vectors_reconcile, "delete_vectors")

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    delete_spy.assert_called_once_with([first_key, second_key])
    remaining = set(
        vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    )
    assert not remaining & {first_key, second_key}
    assert result["failure_log_entries_after"] == 0
    entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert entry["orphan_keys_deleted"] == 2


async def test_orphan_cleanup_liveness_recheck_then_failed_delete_is_reported_failed(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The liveness re-check ran (one live key spared, one stale key selected) and the
    delete of the stale key then failed: the entry is reported failed carrying its recorded
    keys, its counter advances, and both vectors remain — the live one because it was
    spared, the stale one because the delete failed."""
    artifact_id = "artifacts/implementation-note-2026-01-01-recheck-then-fail"
    live_key, stale_key = f"{artifact_id}#live", f"{artifact_id}#stale"
    s3_reconcile.put_object(
        artifact_id,
        _CONTENT_NO_SECTIONS,
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    vectors_reconcile.put_vector(
        live_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        _section_vector_meta(artifact_id, _ULID_AFTER_LATER_WRITE),
    )
    vectors_reconcile.put_vector(
        stale_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        _section_vector_meta(artifact_id, _ULID_AT_FAILURE),
    )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id, "orphan_keys": [live_key, stale_key]}],
    )
    delete_spy = mocker.patch.object(
        vectors_reconcile, "delete_vectors", side_effect=RuntimeError("boom")
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    delete_spy.assert_called_once_with([stale_key])
    failed_entry = next(e for e in result["failed"] if e["artifact_id"] == artifact_id)
    assert failed_entry["orphan_keys"] == [live_key, stale_key]
    persisted = [
        json.loads(line)
        for line in reconcile_settings.failure_log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(persisted) == 1
    assert persisted[0]["reconcile_attempts"] == 1
    assert set(
        vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    ) == {live_key, stale_key}


async def test_failed_post_write_prune_resolves_the_reindex_and_records_an_orphan_cleanup_entry(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Re-index clause: the rebuilt vectors are written before the prune, so a failed delete
    of the leftovers does not fail the re-index. It resolves as normal and the keys that
    could not be deleted are recorded in a new orphan-cleanup-kind entry (failure_step
    orphan_vector_cleanup, orphan_keys), as write_artifact does on the same failure."""
    artifact_id = "artifacts/implementation-note-2026-01-01-prune-fails"
    stale_key = f"{artifact_id}#details"
    s3_reconcile.put_object(
        artifact_id,
        "## Overview\n\nSome overview text.",
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    vectors_reconcile.put_vector(
        stale_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        _section_vector_meta(artifact_id, _ULID_AT_FAILURE),
    )
    _write_failure_log(
        reconcile_settings.failure_log_path, [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}]
    )
    mocker.patch.object(vectors_reconcile, "delete_vectors", side_effect=RuntimeError("boom"))

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    assert artifact_id not in [e["artifact_id"] for e in result["failed"]]
    assert "stuck_failures" not in result
    resolved = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert resolved["source"] == "failure_log"
    assert resolved["sections_indexed"] == 1
    persisted = [
        json.loads(line)
        for line in reconcile_settings.failure_log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(persisted) == 1
    assert persisted[0]["artifact_id"] == artifact_id
    assert persisted[0]["failure_step"] == "orphan_vector_cleanup"
    assert persisted[0]["orphan_keys"] == [stale_key]
    assert "commit_refs" not in persisted[0] and "references" not in persisted[0]
    # The artifact is correctly indexed; only the leftover survived.
    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    assert set(keys) == {f"{artifact_id}#overview", stale_key}


async def test_recorded_prune_failure_drains_on_the_next_run_without_re_embedding(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Re-index clause, no unbounded growth: the orphan-cleanup entry a failed prune records
    is replayed by the next run's cheap delete — no head-of-content fetch, no embedding —
    and pruned; a third run finds nothing to do and appends nothing."""
    artifact_id = "artifacts/implementation-note-2026-01-01-prune-drains"
    stale_key = f"{artifact_id}#details"
    s3_reconcile.put_object(
        artifact_id,
        "## Overview\n\nSome overview text.",
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    vectors_reconcile.put_vector(
        stale_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        _section_vector_meta(artifact_id, _ULID_AT_FAILURE),
    )
    _write_failure_log(
        reconcile_settings.failure_log_path, [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}]
    )
    bedrock = FakeBedrockClient()
    failing = mocker.patch.object(
        vectors_reconcile, "delete_vectors", side_effect=RuntimeError("boom")
    )
    run_1 = await reconcile_index(
        settings=reconcile_settings, s3=s3_reconcile, vectors=vectors_reconcile, bedrock=bedrock
    )
    assert "error" not in run_1
    assert run_1["failure_log_entries_after"] == 1
    mocker.stop(failing)

    embed_spy = mocker.spy(bedrock, "embed")
    run_2 = await reconcile_index(
        settings=reconcile_settings, s3=s3_reconcile, vectors=vectors_reconcile, bedrock=bedrock
    )
    assert "error" not in run_2
    assert embed_spy.call_count == 0
    cleanup = next(e for e in run_2["reconciled"] if e["artifact_id"] == artifact_id)
    assert cleanup["source"] == "orphan_vector_cleanup"
    assert cleanup["orphan_keys_deleted"] == 1
    assert run_2["failure_log_entries_after"] == 0
    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    assert set(keys) == {f"{artifact_id}#overview"}

    run_3 = await reconcile_index(
        settings=reconcile_settings, s3=s3_reconcile, vectors=vectors_reconcile, bedrock=bedrock
    )
    assert "error" not in run_3
    assert run_3["failure_log_entries_before"] == 0
    assert run_3["failure_log_entries_after"] == 0
    assert run_3["total_reconciled"] == 0


# ---------------------------------------------------------------------------
# Re-review stage (2026-09-07): equal-token sibling union, credential abort and
# unwritable-log handling in the post-write prune, newest-member reporting.
# ---------------------------------------------------------------------------

# Above the object's current token: a clock skew across hosts or a hand-edited log,
# never evidence of a later write.
_ULID_SKEWED_AHEAD = "01DRZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.mark.parametrize(
    ("first_token", "expected_references"),
    [
        (
            _ULID_AFTER_LATER_WRITE,
            {"artifacts/adr-from-first", "artifacts/adr-from-second"},
        ),
        (_ULID_SKEWED_AHEAD, {"artifacts/adr-from-second"}),
    ],
    ids=["equal-token-siblings-union", "skewed-token-sibling-does-not-mask-the-current-one"],
)
async def test_tokened_siblings_restore_every_copy_whose_token_is_the_objects_current_one(
    first_token: str,
    expected_references: set[str],
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Grouping invariant, tie clause: every tokened entry whose recorded token still equals
    the artifact's current one contributes its references, so equal-token siblings union —
    equal tokens mean no write intervened between them, so neither supersedes the other. A
    sibling recording a token the object does not carry is discarded whatever its ordering,
    including one above the current token, and never suppresses a sibling whose token is
    current. commit_refs unions across every member either way."""
    artifact_id = "artifacts/implementation-note-2026-01-01-equal-token-siblings"
    s3_reconcile.put_object(
        artifact_id,
        _CONTENT_NO_SECTIONS,
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    first = {
        **_BASE_LOG_ENTRY,
        "artifact_id": artifact_id,
        "failure_step": "annotation_write",
        "last_edited_ulid": first_token,
        "commit_refs": ["sha-a"],
        "references": ["artifacts/adr-from-first"],
        "timestamp": "2026-01-01T00:00:01+00:00",
    }
    second = {
        **_BASE_LOG_ENTRY,
        "artifact_id": artifact_id,
        "failure_step": "annotation_write",
        "last_edited_ulid": _ULID_AFTER_LATER_WRITE,
        "commit_refs": ["sha-b"],
        "references": ["artifacts/adr-from-second"],
        "timestamp": "2026-01-01T00:00:02+00:00",
    }
    _write_failure_log(reconcile_settings.failure_log_path, [first, second])

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    commit_refs, references = read_link_annotations(s3_reconcile, artifact_id)
    assert set(references) == expected_references
    assert set(commit_refs) == {"sha-a", "sha-b"}
    assert result["failure_log_entries_after"] == 0


async def test_credential_error_from_the_post_write_prune_abandons_the_whole_run(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Re-index clause: a CredentialError from the prune's delete is not a failed prune. It
    propagates and abandons the whole run, as it does from every other phase — recording it
    would report per-artifact success and append one spurious orphan-cleanup entry per
    artifact for the duration of a credential outage, of keys never proven stale."""
    artifact_id = "artifacts/implementation-note-2026-01-01-prune-credential"
    stale_key = f"{artifact_id}#details"
    s3_reconcile.put_object(
        artifact_id,
        "## Overview\n\nSome overview text.",
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    vectors_reconcile.put_vector(
        stale_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        _section_vector_meta(artifact_id, _ULID_AT_FAILURE),
    )
    _write_failure_log(
        reconcile_settings.failure_log_path, [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}]
    )
    mocker.patch.object(
        vectors_reconcile,
        "delete_vectors",
        side_effect=CredentialError("token expired", "s3vectors", Exception("sim")),
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert result.get("error") == "credential_error"
    persisted = [
        json.loads(line)
        for line in reconcile_settings.failure_log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [e["failure_step"] for e in persisted] == ["put_vector"]


async def test_a_failed_failure_log_append_does_not_invert_the_resolved_reindex(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Re-index clause: when the failure log itself cannot be written, the re-index still
    resolves — the artifact is indexed, so reporting it failed would be untrue and would
    re-embed it next run to fix something re-embedding cannot fix. The stale keys are leaked
    with both failures logged as the only remaining signal."""
    artifact_id = "artifacts/implementation-note-2026-01-01-unwritable-log"
    stale_key = f"{artifact_id}#details"
    s3_reconcile.put_object(
        artifact_id,
        "## Overview\n\nSome overview text.",
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    vectors_reconcile.put_vector(
        stale_key,
        [1.0] + [0.0] * (DIMENSION - 1),
        _section_vector_meta(artifact_id, _ULID_AT_FAILURE),
    )
    _write_failure_log(
        reconcile_settings.failure_log_path, [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}]
    )
    mocker.patch.object(vectors_reconcile, "delete_vectors", side_effect=RuntimeError("boom"))
    mocker.patch.object(
        reconcile_module, "append_failure_entry", side_effect=OSError("read-only file system")
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    resolved = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert resolved["source"] == "failure_log"
    assert artifact_id not in [e["artifact_id"] for e in result["failed"]]
    assert "stuck_failures" not in result
    # The resolved entry was pruned and no replacement could be written, so the leaked
    # stale vector's only record is the log line asserted below.
    assert result["failure_log_entries_after"] == 0
    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    assert set(keys) == {f"{artifact_id}#overview", stale_key}
    assert any(
        artifact_id in record.getMessage() and "boom" in record.getMessage()
        for record in caplog.records
    ), "neither the leaked keys nor the delete failure was reported anywhere"


@pytest.mark.parametrize(
    "newest_last", [True, False], ids=["newest-read-last", "newest-read-first"]
)
async def test_stuck_group_reports_the_newest_members_reason(
    newest_last: bool,
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Grouping invariant: the reason a group reports is its newest member's by recorded
    timestamp, not whichever line the appender happened to write first — reason is precisely
    the field that differs between members, and the group's budget is the newest member's
    too."""
    artifact_id = "artifacts/implementation-note-2026-01-01-stuck-group-reason"
    s3_reconcile.put_object(
        artifact_id,
        _CONTENT_NO_SECTIONS,
        {**_BASE_S3_META, "last_edited_ulid": _ULID_AFTER_LATER_WRITE},
    )
    older = {
        **_BASE_LOG_ENTRY,
        "artifact_id": artifact_id,
        "reason": "the first failure, long since superseded",
        "reconcile_attempts": CAS_MAX_ATTEMPTS,
        "timestamp": "2026-01-01T00:00:01+00:00",
    }
    newer = {
        **_BASE_LOG_ENTRY,
        "artifact_id": artifact_id,
        "reason": "the failure an operator is being asked to fix",
        "reconcile_attempts": CAS_MAX_ATTEMPTS,
        "timestamp": "2026-01-01T00:00:02+00:00",
    }
    _write_failure_log(
        reconcile_settings.failure_log_path, [older, newer] if newest_last else [newer, older]
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    stuck = next(e for e in result["stuck_failures"] if e["artifact_id"] == artifact_id)
    assert stuck["reason"] == "the failure an operator is being asked to fix"


@pytest.mark.parametrize(
    "newest_last", [True, False], ids=["newest-read-last", "newest-read-first"]
)
async def test_obsolete_group_reports_the_newest_members_title(
    newest_last: bool,
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """Grouping invariant, same clause for the title a resolution reports: the object is gone,
    so the title can only come from the group, and it is the newest member's — the one that
    describes the artifact as it last stood."""
    artifact_id = "artifacts/implementation-note-2026-01-01-obsolete-group-title"
    older = {
        **_BASE_LOG_ENTRY,
        "artifact_id": artifact_id,
        "title": "The Title Before It Was Renamed",
        "timestamp": "2026-01-01T00:00:01+00:00",
    }
    newer = {
        **_BASE_LOG_ENTRY,
        "artifact_id": artifact_id,
        "title": "The Title It Last Carried",
        "timestamp": "2026-01-01T00:00:02+00:00",
    }
    _write_failure_log(
        reconcile_settings.failure_log_path, [older, newer] if newest_last else [newer, older]
    )

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=FakeBedrockClient(),
    )

    assert "error" not in result
    resolved = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
    assert resolved["source"] == "failure_log_obsolete"
    assert resolved["title"] == "The Title It Last Carried"
