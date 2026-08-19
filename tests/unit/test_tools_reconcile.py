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

from arkeology.annotations import CAS_MAX_ATTEMPTS, apply_link_annotations
from arkeology.artifact import VECTOR_FILTERABLE_METADATA_MAX_BYTES
from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import CredentialError
from arkeology.tools import reconcile as reconcile_module
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
# T48 — reconcile rebuilds commit_refs / references from durable annotations
# ---------------------------------------------------------------------------


async def test_reindex_restores_link_fields_from_annotations(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """RED proof (ADR-011 / T48, Story 2): an object whose S3 user-defined metadata has
    NO commit_refs/references keys at all (the post-T47 reality) but whose durable
    annotations carry both fields — reconcile must source the rebuilt vector metadata
    from the annotations, not from S3 metadata. Fails before the fix because the
    current implementation only ever reads commit_refs from S3 metadata (which is
    absent here) and never reads references at all.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-from-annotations"
    s3_reconcile.put_object(artifact_id, _CONTENT_TWO_SECTIONS, {**_BASE_S3_META})
    apply_link_annotations(
        s3_reconcile,
        artifact_id,
        commit_refs=["abc123", "def456"],
        references=["implementation-note-2026-01-01-other"],
    )
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
    assert vmeta.get("references") == ["implementation-note-2026-01-01-other"]


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
    assert "commit_refs" not in vmeta
    assert "references" not in vmeta


async def test_reindex_annotations_unavailable_degrades(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """When reading annotations fails for reasons other than absence (feature
    unavailable in this region/bucket type, AccessDenied, or any other exception),
    reconcile logs the failure and treats both link fields as empty for that
    artifact — the run must still complete (ADR-011 decision 5), not abort."""
    artifact_id = "artifacts/implementation-note-2026-01-01-annotations-unavailable"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    mocker.patch.object(
        s3_reconcile,
        "get_object_annotation",
        side_effect=RuntimeError("simulated annotation feature unavailable"),
    )
    bedrock = FakeBedrockClient(dimension=DIMENSION)

    result = await reconcile_index(
        settings=reconcile_settings,
        s3=s3_reconcile,
        vectors=vectors_reconcile,
        bedrock=bedrock,
    )

    assert "error" not in result
    reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
    assert artifact_id in reconciled_ids
    keys = vectors_reconcile.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    items = vectors_reconcile.get_vectors(keys)
    assert items, "reconcile should still have indexed vectors for the artifact"
    vmeta = items[0]["metadata"]
    assert "commit_refs" not in vmeta
    assert "references" not in vmeta


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

    bedrock = FakeBedrockClient(dimension=DIMENSION)

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
# Union-of-both-stores authority model
# ---------------------------------------------------------------------------


async def test_reindex_from_failure_log_preserves_vector_only_link_fields(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """RED: an artifact whose commit_refs/references live ONLY in vector metadata
    (e.g. a T52 annotation-unavailable deployment, where the annotation write degraded
    but the vector write still carried the fields) must survive a reconcile re-index
    with those fields intact. Re-index is forced here via a failure-log entry so
    ``_reindex_artifact`` runs even though a vector is already indexed. Before the fix,
    reconcile read annotations only (empty, since none were ever written), and
    overwrote vector metadata from that — erasing the only durable copy of the fields.
    """
    artifact_id = "artifacts/implementation-note-2026-01-01-vector-only-links"
    s3_reconcile.put_object(artifact_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    # No apply_link_annotations call — simulates an annotation-unavailable deployment.
    vectors_reconcile.put_vector(
        artifact_id,
        [0.1] * DIMENSION,
        {
            "artifact_id": artifact_id,
            "scope": reconcile_settings.write_prefix,
            "type": "implementation_note",
            "commit_refs": ["abc123"],
            "references": ["implementation-note-2026-01-01-other"],
        },
    )
    _write_failure_log(
        reconcile_settings.failure_log_path,
        [{**_BASE_LOG_ENTRY, "artifact_id": artifact_id}],
    )
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
    assert items, "reconcile should have re-indexed vectors for the artifact"
    vmeta = items[0]["metadata"]
    assert vmeta.get("commit_refs") == ["abc123"]
    assert vmeta.get("references") == ["implementation-note-2026-01-01-other"]


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
    bedrock = FakeBedrockClient(dimension=DIMENSION)

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
    """S3 has only _arkeology_health_probe key → orphans_found == 0."""
    s3_reconcile.put_object("artifacts/_arkeology_health_probe", "probe", {})
    bedrock = FakeBedrockClient(dimension=DIMENSION)

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
    bedrock = FakeBedrockClient(dimension=DIMENSION)

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
    bedrock = FakeBedrockClient(dimension=DIMENSION)

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
    bedrock = FakeBedrockClient(dimension=DIMENSION)

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
    bedrock = FakeBedrockClient(dimension=DIMENSION)

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
            "project": "arkeology",
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
            "project": "arkeology",
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
        bedrock=FakeBedrockClient(dimension=DIMENSION),
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
    bedrock = FakeBedrockClient(dimension=DIMENSION)
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
    bedrock = FakeBedrockClient(dimension=DIMENSION)
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
    bedrock = FakeBedrockClient(dimension=DIMENSION)
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
    whose durable references annotation is oversize is rejected identically to the
    failure-log-replay path — both share _reindex_artifact — reported in `failed`,
    zero put_vector calls, a normal orphan in the same run still reconciles."""
    oversize_id = "artifacts/implementation-note-2026-01-01-orphan-oversize"
    normal_id = "artifacts/implementation-note-2026-01-01-orphan-normal"
    s3_reconcile.put_object(oversize_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    s3_reconcile.put_object(normal_id, _CONTENT_NO_SECTIONS, {**_BASE_S3_META})
    apply_link_annotations(s3_reconcile, oversize_id, commit_refs=[], references=[_HUGE_COMMIT_REF])
    bedrock = FakeBedrockClient(dimension=DIMENSION)
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

    bedrock = FakeBedrockClient(dimension=DIMENSION)
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
    bedrock = FakeBedrockClient(dimension=DIMENSION)
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
    bedrock = FakeBedrockClient(dimension=DIMENSION)

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
    assert not reconcile_settings.failure_log_path.exists()


async def test_response_omits_stuck_failures_when_none(
    reconcile_settings: Settings,
    s3_reconcile: S3ClientImpl,
    vectors_reconcile: VectorsClientImpl,
) -> None:
    """A run with no entries crossing the retry threshold omits 'stuck_failures'
    entirely from the response, matching the optional-field convention used by
    skipped_existing/generation_failed-style fields elsewhere."""
    bedrock = FakeBedrockClient(dimension=DIMENSION)

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
    bedrock = FakeBedrockClient(dimension=DIMENSION)
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
    bedrock = FakeBedrockClient(dimension=DIMENSION)
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
    bedrock = FakeBedrockClient(dimension=DIMENSION)

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
