"""Integration tests for cairn_mcp.tools.archive.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration.
"""

import pytest

from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.tools.archive import archive_artifact
from cairn_mcp.tools.delete import delete_artifact
from cairn_mcp.tools.list import list_artifacts
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
    "title": "Integration archive test artifact",
    "description": "Written by integration archive test.",
    "content": "## Summary\n\nAll good.\n\n## Details\n\nNo issues found.",
    "visibility": "shared",
}


@pytest.mark.integration
async def test_archive_then_absent_from_list_present_in_inactive(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write → archive → list default: absent; list inactive: present; read: content intact."""
    written_id: str = ""
    try:
        r = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{**_BASE_KWARGS, "title": "Integration archive round-trip"},
        )
        written_id = r["artifact_id"]

        archive_result = await archive_artifact(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_id=written_id,
        )
        assert archive_result["status"] == "inactive"

        # Active list — artifact must be absent
        active_list = await list_artifacts(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock
        )
        active_ids = [a["artifact_id"] for a in active_list["artifacts"]]
        assert written_id not in active_ids

        # Inactive list — artifact must appear
        inactive_list = await list_artifacts(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, status="inactive"
        )
        inactive_ids = [a["artifact_id"] for a in inactive_list["artifacts"]]
        assert written_id in inactive_ids

        # Direct read — content must still be accessible
        read_result = await read_artifact(s3=s3, settings=settings, artifact_id=written_id)
        assert read_result["content"] == _BASE_KWARGS["content"]
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
async def test_archive_foreign_scope_returns_access_denied(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Archive a foreign-scope artifact → access-denied error."""
    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        artifact_id="nonexistent-foreign-scope/some-artifact",
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "access" in result_str or "denied" in result_str or "forbidden" in result_str


@pytest.mark.integration
async def test_archive_nonexistent_artifact_returns_not_found(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Archive non-existent artifact → not-found error."""
    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        artifact_id=f"{settings.write_prefix}/nonexistent-artifact-archive-test-xyz999",
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "not" in result_str or "found" in result_str or "missing" in result_str
