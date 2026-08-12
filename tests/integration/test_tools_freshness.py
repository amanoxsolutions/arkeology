"""Integration tests for arkeology.tools.freshness.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration. Teardown uses delete_artifact
with confirm=True in try/finally — idempotent on already-deleted artifacts.
"""

import pytest

from arkeology.clients.bedrock import BedrockClientImpl
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.tools.delete import delete_artifact

# Implementation import — will fail until src/arkeology/tools/freshness.py is created
from arkeology.tools.freshness import check_synthesis_freshness
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
# Base write kwargs for source and synthesis artifacts
# ---------------------------------------------------------------------------

_SOURCE_KWARGS: dict = {
    "type": "implementation_note",
    "team": "platform",
    "project": "arkeology",
    "tier": 2,
    "status": "active",
    "description": "Integration test source artifact for freshness.",
    "content": "## Summary\n\nSource content.",
    "visibility": "shared",
}

_SYNTHESIS_KWARGS: dict = {
    "type": "synthesis",
    "team": "platform",
    "project": "arkeology",
    "tier": 3,
    "status": "active",
    "description": "Integration test synthesis artifact for freshness.",
    "content": "## Summary\n\nSynthesis content.",
    "visibility": "shared",
}


# ---------------------------------------------------------------------------
# Test 1: Source newer than synthesis → source in stale_sources
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_freshness_stale_source_detected(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write source (date 2026-01-01), write synthesis referencing it (date 2025-06-01)
    → source in stale_sources."""
    source_id = ""
    synthesis_id = ""
    try:
        source_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{
                **_SOURCE_KWARGS,
                "date": "2026-01-01",
                "title": "Integration Freshness Source Stale",
            },
        )
        source_id = source_r["artifact_id"]

        synth_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{
                **_SYNTHESIS_KWARGS,
                "date": "2025-06-01",
                "title": "Integration Freshness Synthesis Stale",
                "source_artifacts": [source_id],
            },
        )
        synthesis_id = synth_r["artifact_id"]

        result = await check_synthesis_freshness(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock
        )

        assert "error" not in result
        stale_entry = next((e for e in result["stale"] if e["artifact_id"] == synthesis_id), None)
        assert stale_entry is not None, f"Synthesis {synthesis_id} not found in stale list"
        assert source_id in stale_entry["stale_sources"]
    finally:
        for aid in (synthesis_id, source_id):
            if aid:
                await delete_artifact(
                    settings=settings,
                    s3=s3,
                    vectors=vectors,
                    bedrock=bedrock,
                    artifact_id=aid,
                    confirm=True,
                )


# ---------------------------------------------------------------------------
# Test 2: Archived source → source in archived_sources
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_freshness_archived_source_detected(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write inactive source, write synthesis referencing it → source in archived_sources."""
    source_id = ""
    synthesis_id = ""
    try:
        source_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{
                **_SOURCE_KWARGS,
                "date": "2026-01-01",
                "status": "inactive",
                "title": "Integration Freshness Source Archived",
            },
        )
        source_id = source_r["artifact_id"]

        synth_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{
                **_SYNTHESIS_KWARGS,
                "date": "2026-06-01",
                "title": "Integration Freshness Synthesis Archived",
                "source_artifacts": [source_id],
            },
        )
        synthesis_id = synth_r["artifact_id"]

        result = await check_synthesis_freshness(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock
        )

        assert "error" not in result
        archived_entry = next(
            (e for e in result["archived_sources"] if e["artifact_id"] == synthesis_id), None
        )
        assert archived_entry is not None, (
            f"Synthesis {synthesis_id} not found in archived_sources list"
        )
        assert source_id in archived_entry["archived_sources"]
    finally:
        for aid in (synthesis_id, source_id):
            if aid:
                await delete_artifact(
                    settings=settings,
                    s3=s3,
                    vectors=vectors,
                    bedrock=bedrock,
                    artifact_id=aid,
                    confirm=True,
                )


# ---------------------------------------------------------------------------
# Test 3: Non-existent source → source in missing_sources
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_freshness_missing_source_detected(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write synthesis referencing a non-existent artifact ID → source in missing_sources."""
    synthesis_id = ""
    nonexistent_source_id = (
        f"{settings.write_prefix}/"
        "implementation-note-2099-12-31-definitely-does-not-exist-freshness-xyz999"
    )
    try:
        synth_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{
                **_SYNTHESIS_KWARGS,
                "date": "2026-06-01",
                "title": "Integration Freshness Synthesis Missing Source",
                "source_artifacts": [nonexistent_source_id],
            },
        )
        synthesis_id = synth_r["artifact_id"]

        result = await check_synthesis_freshness(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock
        )

        assert "error" not in result
        missing_entry = next(
            (e for e in result["missing_sources"] if e["artifact_id"] == synthesis_id), None
        )
        assert missing_entry is not None, (
            f"Synthesis {synthesis_id} not found in missing_sources list"
        )
        assert nonexistent_source_id in missing_entry["missing_sources"]
    finally:
        if synthesis_id:
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=synthesis_id,
                confirm=True,
            )


# ---------------------------------------------------------------------------
# Test 4: All-fresh synthesis → all_fresh True for that synthesis
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_freshness_all_fresh(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Source and synthesis both written; synthesis date newer than source
    → synthesis not in stale."""
    source_id = ""
    synthesis_id = ""
    try:
        source_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{
                **_SOURCE_KWARGS,
                "date": "2026-01-01",
                "title": "Integration Freshness Source Fresh",
            },
        )
        source_id = source_r["artifact_id"]

        synth_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{
                **_SYNTHESIS_KWARGS,
                "date": "2026-06-01",
                "title": "Integration Freshness Synthesis Fresh",
                "source_artifacts": [source_id],
            },
        )
        synthesis_id = synth_r["artifact_id"]

        result = await check_synthesis_freshness(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock
        )

        assert "error" not in result
        # This synthesis must NOT appear in stale
        stale_ids = [e["artifact_id"] for e in result["stale"]]
        assert synthesis_id not in stale_ids
    finally:
        for aid in (synthesis_id, source_id):
            if aid:
                await delete_artifact(
                    settings=settings,
                    s3=s3,
                    vectors=vectors,
                    bedrock=bedrock,
                    artifact_id=aid,
                    confirm=True,
                )


# ---------------------------------------------------------------------------
# Test 5: Malformed synthesis without confirm → in malformed; artifact still in index
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_freshness_malformed_no_confirm_still_present(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write synthesis with empty source_artifacts, call without confirm → in malformed;
    artifact still retrievable."""
    synthesis_id = ""
    try:
        synth_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{
                **_SYNTHESIS_KWARGS,
                "date": "2026-06-01",
                "title": "Integration Freshness Malformed No Confirm",
                # source_artifacts omitted → defaults to [] → stored without field in vectors
            },
        )
        synthesis_id = synth_r["artifact_id"]

        result = await check_synthesis_freshness(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock
        )

        assert "error" not in result
        malformed_ids = result["malformed"]
        assert synthesis_id in malformed_ids
        # Artifact must still be in the vector index
        vec_keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": synthesis_id}})
        assert len(vec_keys) > 0, "Artifact should still be in vectors index"
    finally:
        if synthesis_id:
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=synthesis_id,
                confirm=True,
            )


# ---------------------------------------------------------------------------
# Test 6: Malformed synthesis with confirm=True → in deleted_malformed; no longer retrievable
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_freshness_malformed_confirm_true_deleted(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write synthesis with empty source_artifacts, call with confirm=True → in deleted_malformed;
    no longer retrievable."""
    synthesis_id = ""
    try:
        synth_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{
                **_SYNTHESIS_KWARGS,
                "date": "2026-06-01",
                "title": "Integration Freshness Malformed Confirm Delete",
            },
        )
        synthesis_id = synth_r["artifact_id"]

        result = await check_synthesis_freshness(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, confirm=True
        )

        assert "error" not in result
        deleted_ids = result["deleted_malformed"]
        assert synthesis_id in deleted_ids
        # Artifact must no longer exist in vectors
        vec_keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": synthesis_id}})
        assert len(vec_keys) == 0, "Artifact should have been removed from vectors index"
        synthesis_id = ""  # Already deleted by the tool — skip teardown delete
    finally:
        if synthesis_id:
            # Only reached if tool did NOT delete it (test failure scenario)
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=synthesis_id,
                confirm=True,
            )
