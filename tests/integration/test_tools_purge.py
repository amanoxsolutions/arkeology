"""Integration tests for arkeology.tools.purge.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration.
"""

import pytest

from arkeology.clients.bedrock import BedrockClientImpl
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.tools.archive import archive_artifact
from arkeology.tools.delete import delete_artifact
from arkeology.tools.list import list_artifacts
from arkeology.tools.purge import purge_archived
from arkeology.tools.write import write_artifact


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


_BASE_KWARGS: dict = {
    "type": "code_review",
    "team": "platform",
    "project": "arkeology",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "title": "Integration purge test artifact",
    "description": "Written by integration purge test.",
    "content": "## Summary\n\nAll good.\n\n## Details\n\nNo issues found.",
    "visibility": "shared",
}


@pytest.mark.integration
async def test_purge_two_archived_artifacts_both_absent(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write and archive two artifacts; purge → both absent from list; purged_count=2."""
    id1: str = ""
    id2: str = ""
    try:
        r1 = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{**_BASE_KWARGS, "title": "Integration purge test artifact one"},
        )
        id1 = r1["artifact_id"]
        r2 = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{**_BASE_KWARGS, "title": "Integration purge test artifact two"},
        )
        id2 = r2["artifact_id"]

        await archive_artifact(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, artifact_id=id1
        )
        await archive_artifact(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, artifact_id=id2
        )

        result = await purge_archived(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, confirm=True
        )

        # Run-scoped isolation (see tests/integration/_isolation.py) guarantees this
        # scope contains no other archived artifacts, so the count is exact.
        assert result["purged_count"] == 2
        assert id1 in result["purged_ids"]
        assert id2 in result["purged_ids"]

        inactive_list = await list_artifacts(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, status="inactive"
        )
        inactive_ids = [a["artifact_id"] for a in inactive_list["artifacts"]]
        assert id1 not in inactive_ids
        assert id2 not in inactive_ids
        id1 = ""
        id2 = ""
    finally:
        for aid in [id1, id2]:
            if aid:
                await delete_artifact(
                    settings=settings,
                    s3=s3,
                    vectors=vectors,
                    bedrock=bedrock,
                    artifact_id=aid,
                    confirm=True,
                )


@pytest.mark.integration
async def test_purge_active_artifact_untouched(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write an active artifact; purge → active artifact untouched.

    purged_count counts only inactive artifacts.
    """
    written_id: str = ""
    try:
        r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{**_BASE_KWARGS, "title": "Integration purge active keep test"},
        )
        written_id = r["artifact_id"]

        result = await purge_archived(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, confirm=True
        )

        assert written_id not in result.get("purged_ids", [])

        active_list = await list_artifacts(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock
        )
        active_ids = [a["artifact_id"] for a in active_list["artifacts"]]
        assert written_id in active_ids
    finally:
        if written_id:
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=written_id,
                confirm=True,
            )


@pytest.mark.integration
async def test_purge_synthesis_cascade_deleted(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write a synthesis with all sources archived; purge → synthesis cascade-deleted."""
    source_id: str = ""
    synthesis_id: str = ""
    try:
        source_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{**_BASE_KWARGS, "title": "Integration purge cascade source"},
        )
        source_id = source_r["artifact_id"]

        synth_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{
                **_BASE_KWARGS,
                "type": "synthesis",
                "tier": 3,
                "title": "Integration purge cascade synthesis",
                "source_artifacts": [source_id],
                "visibility": "shared",
            },
        )
        synthesis_id = synth_r["artifact_id"]

        await archive_artifact(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, artifact_id=source_id
        )

        result = await purge_archived(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, confirm=True
        )

        assert source_id in result["purged_ids"]
        assert synthesis_id in result["cascade_deleted"]
        source_id = ""
        synthesis_id = ""
    finally:
        if source_id:
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=source_id,
                confirm=True,
            )
        if synthesis_id:
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=synthesis_id,
                confirm=True,
            )


@pytest.mark.integration
async def test_purge_no_inactive_returns_zero(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Purge with no inactive artifacts in own scope → purged_count=0, no error."""
    # Ensure nothing inactive by running a purge first, then immediately run again
    await purge_archived(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, confirm=True)

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, confirm=True
    )

    assert result["purged_count"] == 0
    assert result["purged_ids"] == []
    assert "error" not in result
