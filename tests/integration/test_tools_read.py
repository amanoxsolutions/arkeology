"""Integration tests for cairn_mcp.tools.read.

Requires real AWS credentials and configured .env file.
Depends on T7 integration write tests having seeded data.
All tests decorated with @pytest.mark.integration.
"""

import pytest

from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.tools.delete import delete_artifact
from cairn_mcp.tools.read import read_artifact
from cairn_mcp.tools.write import write_artifact


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


@pytest.mark.integration
async def test_write_then_read_content_matches(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write artifact via write_artifact then read it back; content matches exactly."""
    content = "## Summary\n\nIntegration read test content.\n\n## Details\n\nAll clear."
    kwargs = {
        "type": "code_review",
        "team": "platform",
        "project": "cairn",
        "tier": 2,
        "date": "2026-05-30",
        "status": "active",
        "title": "Integration read test artifact",
        "description": "Written by integration read test.",
        "content": content,
        "visibility": "shared",
        "feature_tags": ["auth", "read-test"],
    }

    artifact_id: str = ""
    try:
        write_result = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
        )
        artifact_id = write_result["artifact_id"]

        read_result = await read_artifact(s3=s3, settings=settings, artifact_id=artifact_id)

        assert read_result["content"] == content
    finally:
        if artifact_id:
            await delete_artifact(
                settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
                artifact_id=artifact_id, confirm=True,
            )


@pytest.mark.integration
async def test_read_metadata_fields_complete_and_typed(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """All metadata fields present in response; feature_tags is list; tier is int."""
    content = "## Summary\n\nMetadata test."
    kwargs = {
        "type": "adr",
        "team": "platform",
        "project": "cairn",
        "tier": 3,
        "date": "2026-05-30",
        "status": "active",
        "title": "Integration metadata test",
        "description": "Metadata field type check.",
        "content": content,
        "visibility": "shared",
        "feature_tags": ["meta", "test"],
    }

    artifact_id: str = ""
    try:
        write_result = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
        )
        artifact_id = write_result["artifact_id"]

        read_result = await read_artifact(s3=s3, settings=settings, artifact_id=artifact_id)

        for field in [
            "type", "team", "project", "tier", "date", "status", "title",
            "visibility", "feature_tags", "description", "content",
        ]:
            assert field in read_result, f"Missing field: {field}"

        assert isinstance(read_result["feature_tags"], list)
        assert "meta" in read_result["feature_tags"]
        assert isinstance(read_result["tier"], int)
        assert read_result["tier"] == 3
    finally:
        if artifact_id:
            await delete_artifact(
                settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
                artifact_id=artifact_id, confirm=True,
            )


@pytest.mark.integration
async def test_nonexistent_artifact_id_returns_not_found(
    settings: Settings,
    s3: S3ClientImpl,
) -> None:
    """Non-existent artifact_id → not-found error (no exception propagation)."""
    result = await read_artifact(
        s3=s3,
        settings=settings,
        artifact_id=f"{settings.write_prefix}/nonexistent-artifact-id-999",
    )

    assert isinstance(result, dict)
    assert "error" in result or result.get("error_type") is not None
