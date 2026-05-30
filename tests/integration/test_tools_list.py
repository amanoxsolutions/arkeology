"""Integration tests for cairn_mcp.tools.list.

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
    "title": "Integration list test artifact",
    "description": "Written by integration list test.",
    "content": "## Summary\n\nAll good.\n\n## Details\n\nNo issues found.",
    "visibility": "shared",
}


@pytest.mark.integration
async def test_list_no_filters_returns_written_artifacts(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write 2 artifacts; list with no filters → both appear in results."""
    written_ids: list[str] = []
    try:
        r1 = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings,
            **{**_BASE_KWARGS, "title": "Integration list test one"},
        )
        r2 = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings,
            **{**_BASE_KWARGS, "title": "Integration list test two"},
        )
        written_ids = [r1["artifact_id"], r2["artifact_id"]]

        result = await list_artifacts(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock
        )

        listed_ids = [a["artifact_id"] for a in result["artifacts"]]
        for aid in written_ids:
            assert aid in listed_ids
    finally:
        for aid in written_ids:
            await delete_artifact(
                settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
                artifact_id=aid, confirm=True,
            )


@pytest.mark.integration
async def test_list_archived_absent_from_default_filter(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write then archive an artifact; list default → absent; list inactive → present."""
    from cairn_mcp.tools.archive import archive_artifact

    written_id: str = ""
    try:
        r = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings,
            **{**_BASE_KWARGS, "title": "Integration list archive test"},
        )
        written_id = r["artifact_id"]

        await archive_artifact(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
            artifact_id=written_id,
        )

        # Default filter (active) — must be absent
        active_result = await list_artifacts(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock
        )
        active_ids = [a["artifact_id"] for a in active_result["artifacts"]]
        assert written_id not in active_ids

        # Inactive filter — must be present
        inactive_result = await list_artifacts(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, status="inactive"
        )
        inactive_ids = [a["artifact_id"] for a in inactive_result["artifacts"]]
        assert written_id in inactive_ids
    finally:
        if written_id:
            await delete_artifact(
                settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
                artifact_id=written_id, confirm=True,
            )


@pytest.mark.integration
async def test_list_type_filter_returns_correct_subset(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write artifacts with different types; list with type filter → correct subset."""
    written_ids: list[str] = []
    try:
        r1 = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings,
            **{**_BASE_KWARGS, "type": "code_review", "title": "Integration list type code review"},
        )
        r2 = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings,
            **{
                **_BASE_KWARGS,
                "type": "adr",
                "title": "Integration list type adr",
                "tier": 3,
                "visibility": "shared",
            },
        )
        written_ids = [r1["artifact_id"], r2["artifact_id"]]

        result = await list_artifacts(
            settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, type="code_review"
        )

        for artifact in result["artifacts"]:
            assert artifact["type"] == "code_review"
    finally:
        for aid in written_ids:
            await delete_artifact(
                settings=settings, s3=s3, vectors=vectors, bedrock=bedrock,
                artifact_id=aid, confirm=True,
            )


@pytest.mark.integration
async def test_list_nonexistent_filter_returns_empty_list(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Non-existent filter combination → empty list, no error."""
    result = await list_artifacts(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        type="session_summary",
        team="team-that-definitely-does-not-exist-xyz999",
    )

    assert isinstance(result["artifacts"], list)
    assert "error" not in result
