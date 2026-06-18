"""Integration tests for cairn_mcp.tools.synthesise.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration.
"""

import pytest

from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.tools.delete import delete_artifact
from cairn_mcp.tools.synthesise import synthesise_artifacts
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
    "title": "Integration synthesise test artifact",
    "description": "Written by integration synthesise test.",
    "content": (
        "## Summary\n\nSynthesise integration test content.\n\n"
        "## Details\n\nAll clear for synthesis."
    ),
    "visibility": "shared",
}


@pytest.mark.integration
async def test_synthesise_top_k_limits_results_with_content(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write 3 artifacts; synthesise with top_k=2 → 2 results with full content."""
    written_ids: list[str] = []
    try:
        for i in range(3):
            r = await write_artifact(
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                settings=settings,
                **{**_BASE_KWARGS, "title": f"Integration synthesise test artifact {i + 1}"},
            )
            written_ids.append(r["artifact_id"])

        result = await synthesise_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            query="synthesise integration test",
            top_k=2,
        )

        assert len(result["artifacts"]) <= 2
        for artifact in result["artifacts"]:
            assert "content" in artifact
            assert artifact["content"] is not None
            assert len(artifact["content"]) > 0
    finally:
        for aid in written_ids:
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=aid,
                confirm=True,
            )


@pytest.mark.integration
async def test_synthesise_all_required_fields_present(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Each result contains all required fields."""
    written_ids: list[str] = []
    try:
        r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{**_BASE_KWARGS, "title": "Integration synthesise fields test"},
        )
        written_ids.append(r["artifact_id"])

        result = await synthesise_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            query="synthesise fields test",
            top_k=5,
        )

        required = [
            "artifact_id",
            "content",
            "type",
            "team",
            "project",
            "tier",
            "date",
            "status",
            "title",
            "visibility",
            "tags",
            "description",
        ]
        for artifact in result["artifacts"]:
            for field in required:
                assert field in artifact, f"Missing field '{field}' in result: {artifact}"
    finally:
        for aid in written_ids:
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=aid,
                confirm=True,
            )


@pytest.mark.integration
async def test_synthesise_nonmatching_query_returns_empty(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """synthesise_artifacts with non-matching query → empty list, no error."""
    result = await synthesise_artifacts(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        query="xyzzy-nonexistent-query-that-matches-nothing-in-the-index-at-all",
        top_k=5,
    )

    assert isinstance(result.get("artifacts", []), list)
    assert "error" not in result
