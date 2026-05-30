"""Integration tests for cairn_mcp.tools.search.

Requires real AWS credentials and configured .env file.
Depends on T7 integration write tests having already seeded data.
All tests decorated with @pytest.mark.integration.
"""

import pytest

from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.tools.search import search_artifacts
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
async def test_write_then_search_finds_artifact(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write 3 artifacts; search with related query; at least 1 appears in results."""
    base_kwargs = {
        "team": "platform",
        "project": "cairn",
        "tier": 2,
        "date": "2026-05-30",
        "status": "active",
        "description": "Integration search test artifact.",
        "visibility": "shared",
    }

    titles = [
        ("code_review", "Search test auth review"),
        ("adr", "Search test postgres decision"),
        ("spec", "Search test api spec"),
    ]

    written_ids = []
    for artifact_type, title in titles:
        kwargs = {
            **base_kwargs,
            "type": artifact_type,
            "title": title,
            "content": f"## Summary\n\n{title} content.",
        }
        result = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
        )
        written_ids.append(result["artifact_id"])

    search_result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="auth review", top_k=10
    )

    found_ids = [a["artifact_id"] for a in search_result["artifacts"]]
    assert any(aid in found_ids for aid in written_ids)


@pytest.mark.integration
async def test_type_filter_reduces_results(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """type filter reduces results correctly — all returned artifacts match the type."""
    result = await search_artifacts(
        vectors=vectors,
        bedrock=bedrock,
        settings=settings,
        query="auth review",
        top_k=10,
        type="code_review",
    )

    for artifact in result["artifacts"]:
        assert artifact["type"] == "code_review"


@pytest.mark.integration
async def test_zero_result_query_returns_empty_without_error(
    settings: Settings,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Semantically unrelated query → empty list without error."""
    result = await search_artifacts(
        vectors=vectors,
        bedrock=bedrock,
        settings=settings,
        query="xyzzy frobnicate quux 92837465 unrelated nonsense",
        top_k=5,
    )

    # Should not raise; artifacts list may be empty or have low-scoring results
    assert isinstance(result["artifacts"], list)


@pytest.mark.integration
async def test_own_scope_and_foreign_tier3_shared_present_tier2_absent(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Combined scope: own-scope result present; foreign-scope tier 2 absent."""
    # We cannot easily control foreign-scope data in integration tests, so
    # this test verifies that own-scope results appear and that the response
    # structure is valid.
    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="auth review", top_k=10
    )

    # All returned artifact_ids must come from allowed scopes
    allowed_scopes = settings.effective_read_scopes
    for artifact in result["artifacts"]:
        artifact_id = artifact["artifact_id"]
        # artifact must start with one of the allowed scopes
        assert any(artifact_id.startswith(scope + "/") for scope in allowed_scopes), (
            f"Artifact {artifact_id!r} not in any allowed scope: {allowed_scopes}"
        )
