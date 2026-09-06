"""Integration tests for arkeology.tools.delete.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration.
"""

import pytest

from arkeology.clients.bedrock import BedrockClientImpl
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.tools.delete import delete_artifact
from arkeology.tools.list import list_artifacts
from arkeology.tools.read import read_artifact
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
    "title": "Integration delete test artifact",
    "description": "Written by integration delete test.",
    "content": "## Summary\n\nAll good.\n\n## Details\n\nNo issues found.",
    "visibility": "shared",
}


@pytest.mark.integration
async def test_delete_confirm_true_artifact_not_retrievable(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write → delete confirm=True → not retrievable by ID; absent from list."""
    r = await write_artifact(
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_KWARGS, "title": "Integration delete confirm test"},
    )
    artifact_id = r["artifact_id"]

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        artifact_id=artifact_id,
        confirm=True,
    )

    assert result["deleted"] is True

    # Not retrievable by ID
    read_result = await read_artifact(s3=s3, settings=settings, artifact_id=artifact_id)
    assert read_result.get("error") == "not_found"

    # Not in list
    list_result = await list_artifacts(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)
    assert artifact_id not in [a["artifact_id"] for a in list_result["artifacts"]]


@pytest.mark.integration
async def test_delete_without_confirm_error_artifact_still_retrievable(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Delete without confirm=True → error; artifact still retrievable."""
    written_id: str = ""
    try:
        r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{**_BASE_KWARGS, "title": "Integration delete no confirm test"},
        )
        written_id = r["artifact_id"]

        result = await delete_artifact(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_id=written_id,
        )

        assert result.get("error") == "confirmation_required"

        # Artifact still readable
        read_result = await read_artifact(s3=s3, settings=settings, artifact_id=written_id)
        assert "content" in read_result
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
async def test_delete_foreign_scope_access_denied(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Delete foreign-scope artifact → access-denied error."""
    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        artifact_id="nonexistent-foreign-scope/some-artifact",
        confirm=True,
    )

    assert result.get("error") == "access_denied"
    result_str = str(result).lower()
    assert "access" in result_str or "denied" in result_str or "forbidden" in result_str


@pytest.mark.integration
async def test_delete_nonexistent_artifact_not_found(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Delete non-existent artifact → not-found error."""
    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        artifact_id=f"{settings.write_prefix}/nonexistent-delete-test-xyz999",
        confirm=True,
    )

    assert result.get("error") == "not_found"
    result_str = str(result).lower()
    assert "not" in result_str or "found" in result_str or "missing" in result_str


@pytest.mark.integration
async def test_delete_synthesis_source_includes_referrers(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write a synthesis with source_artifacts; delete source → response includes referrers."""
    source_id: str = ""
    synthesis_id: str = ""
    try:
        source_r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{**_BASE_KWARGS, "title": "Integration delete source artifact"},
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
                "title": "Integration delete synthesis artifact",
                "source_artifacts": [source_id],
                "visibility": "shared",
            },
        )
        synthesis_id = synth_r["artifact_id"]

        result = await delete_artifact(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_id=source_id,
            confirm=True,
        )

        assert result.get("deleted") is True
        referrers = result.get("referrers", [])
        assert synthesis_id in referrers
        source_id = ""  # already deleted
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
