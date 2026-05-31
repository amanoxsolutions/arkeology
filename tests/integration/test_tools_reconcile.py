"""Integration tests for cairn_mcp.tools.reconcile.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration. Teardown uses delete_artifact
with confirm=True in try/finally — idempotent on already-deleted artifacts.
"""

from pathlib import Path

import pytest

from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.failure_log import append_failure_entry
from cairn_mcp.tools.delete import delete_artifact

# Implementation import — will fail until src/cairn_mcp/tools/reconcile.py is created
from cairn_mcp.tools.reconcile import reconcile_index
from cairn_mcp.tools.write import write_artifact

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
        FAILURE_LOG_PATH=str(tmp_path / ".cairn_failures.jsonl"),
    )


# ---------------------------------------------------------------------------
# Base write kwargs
# ---------------------------------------------------------------------------

_BASE_KWARGS: dict = {
    "type": "implementation_note",
    "team": "platform",
    "project": "cairn",
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
