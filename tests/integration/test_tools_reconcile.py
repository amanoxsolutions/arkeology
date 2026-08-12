"""Integration tests for arkeology.tools.reconcile.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration. Teardown uses delete_artifact
with confirm=True in try/finally — idempotent on already-deleted artifacts.
"""

from pathlib import Path

import pytest

from arkeology.clients.bedrock import BedrockClientImpl
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.failure_log import append_failure_entry
from arkeology.tools.delete import delete_artifact
from arkeology.tools.link_metadata import link_metadata

# Implementation import — will fail until src/arkeology/tools/reconcile.py is created
from arkeology.tools.reconcile import reconcile_index
from arkeology.tools.search import search_artifacts
from arkeology.tools.write import write_artifact

# ---------------------------------------------------------------------------
# Session-scoped AWS fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def s3(settings: Settings) -> S3ClientImpl:
    return S3ClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.artifact_bucket,
    )


@pytest.fixture(scope="session")
def vectors(settings: Settings) -> VectorsClientImpl:
    return VectorsClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.vectors_bucket,
        index=settings.vectors_index,
    )


@pytest.fixture(scope="session")
def bedrock(settings: Settings) -> BedrockClientImpl:
    return BedrockClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
    )


# ---------------------------------------------------------------------------
# Per-test Settings with a fresh temporary failure log path
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_with_tmp_log(settings: Settings, tmp_path: Path) -> Settings:
    """Function-scoped Settings overriding FAILURE_LOG_PATH to a temp file."""
    return Settings(
        AWS_REGION=settings.aws_region,
        ARTIFACT_BUCKET=settings.artifact_bucket,
        VECTORS_BUCKET=settings.vectors_bucket,
        VECTORS_INDEX=settings.vectors_index,
        WRITE_PREFIX=settings.write_prefix,
        FAILURE_LOG_PATH=str(tmp_path / ".arkeology_failures.jsonl"),
    )


# ---------------------------------------------------------------------------
# Base write kwargs
# ---------------------------------------------------------------------------

_BASE_KWARGS: dict = {
    "type": "implementation_note",
    "team": "platform",
    "project": "arkeology",
    "tier": 2,
    "date": "2026-05-31",
    "status": "active",
    "description": "Written by integration reconcile test.",
    "content": "## Summary\n\nAll good.\n\n## Details\n\nNo issues found.",
    "visibility": "shared",
}


# ---------------------------------------------------------------------------
# Test 1: Orphan scan re-indexes artifact whose vectors were manually deleted
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_reconcile_orphan_scan_reindexes_artifact(
    settings_with_tmp_log: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write artifact → delete vectors manually → reconcile → artifact in reconciled
    with source='orphan_scan'."""
    artifact_id = ""
    try:
        r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings_with_tmp_log,
            **{**_BASE_KWARGS, "title": "Integration Reconcile Orphan Scan Test"},
        )
        artifact_id = r["artifact_id"]

        # Manually delete all vectors for this artifact to simulate a partial-delete orphan
        vec_keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        assert len(vec_keys) > 0, "Expected vectors to exist after write"
        vectors.delete_vectors(vec_keys)

        result = await reconcile_index(
            settings=settings_with_tmp_log,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
        )

        assert "error" not in result
        reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
        assert artifact_id in reconciled_ids
        reconciled_entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
        assert reconciled_entry["source"] == "orphan_scan"
        # Artifact should now be searchable again
        re_indexed_keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        assert len(re_indexed_keys) > 0
    finally:
        if artifact_id:
            await delete_artifact(
                settings=settings_with_tmp_log,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=artifact_id,
                confirm=True,
            )


# ---------------------------------------------------------------------------
# Test 2: Failure log entry for known artifact → reconciled with source='failure_log'
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_reconcile_failure_log_entry_reconciled(
    settings_with_tmp_log: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write artifact → append failure log entry → reconcile → artifact in reconciled
    with source='failure_log'; log cleared."""
    artifact_id = ""
    try:
        r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings_with_tmp_log,
            **{**_BASE_KWARGS, "title": "Integration Reconcile Failure Log Test"},
        )
        artifact_id = r["artifact_id"]

        # Manually write a failure log entry for this artifact
        append_failure_entry(
            settings_with_tmp_log.failure_log_path,
            {
                "artifact_id": artifact_id,
                "title": "Integration Reconcile Failure Log Test",
                "type": "implementation_note",
                "tier": 2,
                "date": "2026-05-31",
                "failure_step": "put_vector",
                "reason": "Simulated failure for integration test",
                "timestamp": "2026-05-31T00:00:00+00:00",
            },
        )

        result = await reconcile_index(
            settings=settings_with_tmp_log,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
        )

        assert "error" not in result
        assert result["failure_log_entries_before"] >= 1
        reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
        assert artifact_id in reconciled_ids
        reconciled_entry = next(e for e in result["reconciled"] if e["artifact_id"] == artifact_id)
        assert reconciled_entry["source"] == "failure_log"
        assert result["failure_log_entries_after"] == 0
    finally:
        if artifact_id:
            await delete_artifact(
                settings=settings_with_tmp_log,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=artifact_id,
                confirm=True,
            )


# ---------------------------------------------------------------------------
# Test 3: Failure log entry for non-existent artifact → in failed; log entry retained
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_reconcile_failure_log_nonexistent_artifact_in_failed(
    settings_with_tmp_log: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Failure log entry for non-existent artifact_id → entry in failed;
    failure log entry retained."""
    # Use a deterministically unique key that won't exist in the real environment
    nonexistent_id = (
        f"{settings_with_tmp_log.write_prefix}/"
        "implementation-note-2099-12-31-does-not-exist-reconcile-test-xyz999"
    )

    append_failure_entry(
        settings_with_tmp_log.failure_log_path,
        {
            "artifact_id": nonexistent_id,
            "title": "Nonexistent Artifact",
            "type": "implementation_note",
            "tier": 2,
            "date": "2099-12-31",
            "failure_step": "put_vector",
            "reason": "Simulated failure for nonexistent artifact in integration test",
            "timestamp": "2099-12-31T00:00:00+00:00",
        },
    )

    result = await reconcile_index(
        settings=settings_with_tmp_log,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
    )

    assert "error" not in result
    failed_ids = [e["artifact_id"] for e in result["failed"]]
    assert nonexistent_id in failed_ids
    # Entry was not resolved → should remain in log
    assert result["failure_log_entries_after"] >= 1


# ---------------------------------------------------------------------------
# Test 4: Clean state — no failure log, all vectors present → total_reconciled=0
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_reconcile_clean_state_written_artifact_not_reindexed(
    settings_with_tmp_log: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """No failure log, artifact with vectors present → written artifact not in reconciled;
    no error."""
    artifact_id = ""
    try:
        r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings_with_tmp_log,
            **{**_BASE_KWARGS, "title": "Integration Reconcile Clean State Test"},
        )
        artifact_id = r["artifact_id"]

        result = await reconcile_index(
            settings=settings_with_tmp_log,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
        )

        assert "error" not in result
        assert result["failure_log_entries_before"] == 0
        # The artifact has vectors → must not appear as an orphan
        reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
        assert artifact_id not in reconciled_ids
    finally:
        if artifact_id:
            await delete_artifact(
                settings=settings_with_tmp_log,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=artifact_id,
                confirm=True,
            )


# ---------------------------------------------------------------------------
# Test 4b: link_metadata backfill survives a vector-drop-and-reconcile round trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_reconcile_restores_link_fields_backfilled_via_link_metadata(
    settings_with_tmp_log: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write → link_metadata backfill (commit_refs + references) → drop all
    vectors → reconcile_index must restore both fields from the durable S3 annotation
    onto the rebuilt vector metadata — against real AWS."""
    artifact_id = ""
    try:
        r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings_with_tmp_log,
            **{**_BASE_KWARGS, "title": "Integration Reconcile Link Metadata Restore Test"},
        )
        artifact_id = r["artifact_id"]

        backfill = await link_metadata(
            settings=settings_with_tmp_log,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_ids=[artifact_id],
            commit_refs=["abc1234"],
            references=["implementation-note-2026-01-01-other"],
        )
        assert backfill["linked"] == 1

        # Drop all vectors, simulating the state reconcile's orphan scan must repair.
        vec_keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        assert len(vec_keys) > 0, "Expected vectors to exist after write"
        vectors.delete_vectors(vec_keys)

        result = await reconcile_index(
            settings=settings_with_tmp_log,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
        )

        assert "error" not in result
        reconciled_ids = [e["artifact_id"] for e in result["reconciled"]]
        assert artifact_id in reconciled_ids

        re_indexed_keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        assert len(re_indexed_keys) > 0
        entries = vectors.get_vectors(re_indexed_keys)
        for entry in entries:
            assert entry["metadata"]["commit_refs"] == ["abc1234"]
            assert entry["metadata"]["references"] == ["implementation-note-2026-01-01-other"]
    finally:
        if artifact_id:
            await delete_artifact(
                settings=settings_with_tmp_log,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=artifact_id,
                confirm=True,
            )


# ---------------------------------------------------------------------------
# Test 5: Phase 3 — Dangling vector pruning
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_phase3_dangling_vector_pruned_integration(
    settings_with_tmp_log: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write an artifact → delete its S3 object directly (bypassing the MCP tool) →
    call reconcile_index → dangling_artifacts_found is 1 and the artifact is absent
    from search results."""
    artifact_id = ""
    try:
        r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings_with_tmp_log,
            **{**_BASE_KWARGS, "title": "Integration Reconcile Phase 3 Dangling Vector Test"},
        )
        artifact_id = r["artifact_id"]

        # Directly delete the S3 object to simulate an external deletion,
        # leaving vector entries intact — this creates a dangling vector
        s3.delete_object(artifact_id)

        result = await reconcile_index(
            settings=settings_with_tmp_log,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
        )

        assert "error" not in result
        assert result["dangling_artifacts_found"] == 1
        assert artifact_id in result["dangling_artifacts"]

        # After reconcile, the artifact must not appear in search results
        search_result = await search_artifacts(
            settings=settings_with_tmp_log,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            query="Integration Reconcile Phase 3 Dangling Vector Test",
            top_k=10,
        )
        found_ids = [hit["artifact_id"] for hit in search_result.get("results", [])]
        assert artifact_id not in found_ids, (
            f"Artifact {artifact_id!r} should not appear in search results after dangling prune"
        )
    finally:
        if artifact_id:
            s3.delete_object(artifact_id)  # idempotent — silently ignores missing keys
            # Clean up any remaining vectors (S3 object was already deleted above)
            remaining_vec_keys = vectors.list_vectors_by_metadata(
                {"artifact_id": {"$eq": artifact_id}}
            )
            if remaining_vec_keys:
                vectors.delete_vectors(remaining_vec_keys)
