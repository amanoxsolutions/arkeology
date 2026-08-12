"""Integration tests for arkeology.tools.studio (arkeology_studio).

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration.

These tests are arkeology_studio's only real-AWS coverage. Its only AWS-touching
branch is the non-supporting-host fallback, which delegates to list_artifacts
against the real vector index —
the supporting-host branch and the exception branch are pure Python (already
covered by the moto/mock unit suite in tests/unit/test_tools_studio.py) and
are not repeated here. ``ctx`` (the FastMCP request Context) is mocked because
it is a protocol/transport concern unrelated to AWS — only
``ctx.client_supports_extension`` is read by the tool, matching the existing
unit-test convention.
"""

from unittest.mock import MagicMock

import pytest
from fastmcp.tools.base import ToolResult

from arkeology.clients.bedrock import BedrockClientImpl
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.tools.delete import delete_artifact
from arkeology.tools.studio import arkeology_studio
from arkeology.tools.write import write_artifact


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
async def test_arkeology_studio_non_supporting_host_lists_real_artifact(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Non-supporting-host fallback lists a real, freshly written own-scope artifact."""
    artifact_id: str = ""
    try:
        write_result = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            type="code_review",
            team="platform",
            project="arkeology",
            tier=2,
            date="2026-05-30",
            status="active",
            title="arkeology_studio integration listing",
            description="Artifact for arkeology_studio integration test.",
            content="## Summary\n\nStudio listing content.",
            visibility="shared",
        )
        artifact_id = write_result["artifact_id"]

        ctx = MagicMock()
        ctx.client_supports_extension.return_value = False

        result = await arkeology_studio(settings=settings, vectors=vectors, ctx=ctx)

        assert isinstance(result, ToolResult)
        assert not result.is_error
        assert result.structured_content is not None
        assert result.structured_content["write_prefix"] == settings.write_prefix
        listed_ids = [a["artifact_id"] for a in result.structured_content["artifacts"]]
        assert artifact_id in listed_ids
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
