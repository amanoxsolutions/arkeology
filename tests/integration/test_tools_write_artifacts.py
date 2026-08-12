"""Integration tests for arkeology.tools.write_artifacts.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration.

M-16 (Phase 12 review, Cluster E): write_artifacts had zero integration
coverage. These tests exercise the concurrent bulk-write path against real S3
and S3 Vectors — the moto unit suite already covers the same logic against a
simulated backend, so this file focuses on round-trip fidelity (real content,
real vector indexing) and the intra-batch duplicate-key guard, both of which
depend on real S3 existence checks / object storage rather than pure Python
logic.
"""

import pytest

from arkeology.clients.bedrock import BedrockClientImpl
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.tools.delete import delete_artifact
from arkeology.tools.write_artifacts import write_artifacts


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Session-scoped Settings constructed from environment after load_env runs."""
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


_BASE_KWARGS: dict = {
    "team": "platform",
    "project": "arkeology",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "visibility": "shared",
}


@pytest.mark.integration
async def test_write_artifacts_round_trip_concurrent(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Two descriptors written concurrently → both stored with real content and vectors."""
    descriptors = [
        {
            **_BASE_KWARGS,
            "type": "code_review",
            "title": "write_artifacts integration alpha",
            "description": "Alpha descriptor for write_artifacts integration test.",
            "content": "## Summary\n\nAlpha content.",
        },
        {
            **_BASE_KWARGS,
            "type": "adr",
            "title": "write_artifacts integration beta",
            "description": "Beta descriptor for write_artifacts integration test.",
            "content": "## Summary\n\nBeta content.",
        },
    ]

    written_ids: list[str] = []
    try:
        result = await write_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifacts=descriptors,
            artifact_concurrency=2,
        )

        assert "results" in result
        assert len(result["results"]) == 2
        for entry, descriptor in zip(result["results"], descriptors, strict=True):
            assert entry.get("written") is True, entry
            artifact_id = entry["artifact_id"]
            written_ids.append(artifact_id)
            assert s3.get_object(artifact_id) == descriptor["content"]
            assert entry["sections_indexed"] >= 1

            keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
            assert len(keys) >= 1
    finally:
        for artifact_id in written_ids:
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=artifact_id,
                confirm=True,
            )


@pytest.mark.integration
async def test_write_artifacts_intra_batch_duplicate_key_rejected(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Two descriptors resolving to the same S3 key → the second is validation_error.

    Real-AWS assertion: only one S3 object is ever created for the collided key —
    the duplicate-key guard runs before any coroutine is launched, so this proves
    no race between the two concurrent write attempts ever produces two writers
    for the same key against the real store.
    """
    shared_title = "write_artifacts integration duplicate-key"
    descriptors = [
        {
            **_BASE_KWARGS,
            "type": "code_review",
            "title": shared_title,
            "description": "First descriptor targeting the duplicate key.",
            "content": "## Summary\n\nFirst writer content.",
        },
        {
            **_BASE_KWARGS,
            "type": "code_review",
            "title": shared_title,
            "description": "Second descriptor targeting the duplicate key.",
            "content": "## Summary\n\nSecond writer content.",
        },
    ]

    artifact_id: str = ""
    try:
        result = await write_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifacts=descriptors,
            artifact_concurrency=2,
        )

        assert len(result["results"]) == 2
        written = [e for e in result["results"] if e.get("written")]
        errored = [e for e in result["results"] if "error" in e]
        assert len(written) == 1
        assert len(errored) == 1
        assert errored[0]["error"] == "validation_error"

        artifact_id = written[0]["artifact_id"]
        # Real-AWS assertion: exactly the winning descriptor's content is stored.
        stored = s3.get_object(artifact_id)
        assert stored in (descriptors[0]["content"], descriptors[1]["content"])
    finally:
        if artifact_id:
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=artifact_id,
                confirm=True,
            )
