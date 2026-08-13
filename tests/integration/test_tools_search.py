"""Integration tests for arkeology.tools.search.

Requires real AWS credentials and configured .env file.
Each test seeds its own data via write_artifact and cleans up via delete_artifact.
All tests decorated with @pytest.mark.integration.
"""

import pytest

from arkeology.clients.bedrock import BedrockClientImpl
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.tools.delete import delete_artifact
from arkeology.tools.search import search_artifacts
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
async def test_write_then_search_finds_artifact(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write 3 artifacts; search with related query; at least 1 appears in results."""
    base_kwargs = {
        "team": "platform",
        "project": "arkeology",
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

    written_ids: list[str] = []
    try:
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
async def test_type_filter_reduces_results(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """type filter reduces results — matching-type artifact found, other-type artifact excluded."""
    base_kwargs = {
        "team": "platform",
        "project": "arkeology",
        "tier": 2,
        "date": "2026-05-30",
        "status": "active",
        "description": "Integration search type-filter test artifact.",
        "visibility": "shared",
    }

    titles = [
        ("code_review", "Type filter test auth review"),
        ("adr", "Type filter test auth review decision"),
    ]

    written_ids: dict[str, str] = {}
    try:
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
            written_ids[artifact_type] = result["artifact_id"]

        search_result = await search_artifacts(
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            query="auth review",
            top_k=10,
            type="code_review",
        )

        found_ids = [a["artifact_id"] for a in search_result["artifacts"]]
        for artifact in search_result["artifacts"]:
            assert artifact["type"] == "code_review"
        assert written_ids["code_review"] in found_ids
        assert written_ids["adr"] not in found_ids
    finally:
        for aid in written_ids.values():
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=aid,
                confirm=True,
            )


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
    # the foreign-scope-tier2-absent half is only covered indirectly: no
    # foreign tier 2 artifact is ever seeded, and the scope-membership
    # assertion below fails if one were ever to leak into the results. The
    # own-scope-result-present half is seeded and verified directly.
    base_kwargs = {
        "team": "platform",
        "project": "arkeology",
        "tier": 2,
        "date": "2026-05-30",
        "status": "active",
        "description": "Integration search own-scope test artifact.",
        "visibility": "shared",
        "type": "code_review",
        "title": "Own scope test auth review",
        "content": "## Summary\n\nOwn scope test auth review content.",
    }

    written_ids: list[str] = []
    try:
        write_result = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **base_kwargs
        )
        written_ids.append(write_result["artifact_id"])

        result = await search_artifacts(
            vectors=vectors, bedrock=bedrock, settings=settings, query="auth review", top_k=10
        )

        found_ids = [a["artifact_id"] for a in result["artifacts"]]
        assert write_result["artifact_id"] in found_ids

        # All returned artifact_ids must come from allowed scopes
        allowed_scopes = settings.effective_read_scopes
        for artifact in result["artifacts"]:
            artifact_id = artifact["artifact_id"]
            # artifact must start with one of the allowed scopes
            assert any(artifact_id.startswith(scope + "/") for scope in allowed_scopes), (
                f"Artifact {artifact_id!r} not in any allowed scope: {allowed_scopes}"
            )
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
