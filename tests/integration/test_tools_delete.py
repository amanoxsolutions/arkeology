"""Integration tests for cairn_mcp.tools.delete.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration.
"""

import pytest
from cairn_mcp.tools.delete import delete_artifact
from cairn_mcp.tools.list import list_artifacts

from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.tools.read import read_artifact
from cairn_mcp.tools.write import write_artifact


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
    "project": "cairn",
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
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings,
        **{**_BASE_KWARGS, "title": "Integration delete confirm test"},
    )
    artifact_id = r["artifact_id"]

    result = await delete_artifact(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
        artifact_id=artifact_id, confirm=True,
    )

    assert result["deleted"] is True

    # Not retrievable by ID
    read_result = await read_artifact(s3=s3, settings=settings, artifact_id=artifact_id)
    assert "error" in read_result or read_result.get("error_type") is not None

    # Not in list
    list_result = await list_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock
    )
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
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings,
            **{**_BASE_KWARGS, "title": "Integration delete no confirm test"},
        )
        written_id = r["artifact_id"]

        result = await delete_artifact(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
            artifact_id=written_id,
        )

        assert "error" in result or result.get("error_type") is not None

        # Artifact still readable
        read_result = await read_artifact(s3=s3, settings=settings, artifact_id=written_id)
        assert "content" in read_result
    finally:
        if written_id:
            await delete_artifact(
                settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
                artifact_id=written_id, confirm=True,
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

    assert "error" in result or result.get("error_type") is not None
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

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "not" in result_str or "found" in result_str or "missing" in result_str


@pytest.mark.integration
async def test_delete_synthesis_source_includes_warnings(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write a synthesis with source_artifacts; delete source → response includes warnings."""
    source_id: str = ""
    synthesis_id: str = ""
    try:
        source_r = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings,
            **{**_BASE_KWARGS, "title": "Integration delete source artifact"},
        )
        source_id = source_r["artifact_id"]

        synth_r = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings,
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
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
            artifact_id=source_id, confirm=True,
        )

        assert result.get("deleted") is True
        warnings = result.get("warnings", [])
        assert synthesis_id in warnings
        source_id = ""  # already deleted
    finally:
        if source_id:
            await delete_artifact(
                settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
                artifact_id=source_id, confirm=True,
            )
        if synthesis_id:
            await delete_artifact(
                settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
                artifact_id=synthesis_id, confirm=True,
            )
