"""Integration tests for cairn_mcp.tools.write.

Requires real AWS credentials and configured .env file.
All tests are decorated with @pytest.mark.integration.
"""

import pytest

from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.tools.delete import delete_artifact
from cairn_mcp.tools.link_metadata import link_metadata
from cairn_mcp.tools.write import write_artifact


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Session-scoped Settings constructed from environment after load_env runs."""
    return Settings()


@pytest.fixture(scope="session")
def s3(settings: Settings) -> S3ClientImpl:
    """Session-scoped real S3 client."""
    return S3ClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.artifact_bucket,
    )


@pytest.fixture(scope="session")
def vectors(settings: Settings) -> VectorsClientImpl:
    """Session-scoped real S3 Vectors client."""
    return VectorsClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.vectors_bucket,
        index=settings.vectors_index,
    )


@pytest.fixture(scope="session")
def bedrock(settings: Settings) -> BedrockClientImpl:
    """Session-scoped real Bedrock client."""
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
    "title": "Integration test write artifact",
    "description": "Written by integration test suite.",
    "content": "## Summary\n\nAll good.\n\n## Details\n\nNo issues found.",
    "visibility": "shared",
}


@pytest.mark.integration
async def test_full_round_trip_s3_content_and_vector_metadata(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write artifact → S3 GetObject returns exact content; vector has correct artifact_id."""
    artifact_id: str = ""
    try:
        result = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_KWARGS
        )

        artifact_id = result["artifact_id"]
        stored_content = s3.get_object(artifact_id)
        assert stored_content == _BASE_KWARGS["content"]

        # At least one vector key should be indexed
        vector_results = vectors.get_vectors([artifact_id + "#summary"])
        # Try the fallback key if no sections were indexed
        if not vector_results:
            vector_results = vectors.get_vectors([artifact_id])
        assert len(vector_results) > 0
        assert vector_results[0]["metadata"]["artifact_id"] == artifact_id
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


@pytest.mark.integration
async def test_overwrite_preserves_link_metadata_backfilled_annotation(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """SA-3(a): write → link_metadata backfill → content-only overwrite must preserve
    the backfilled commit_refs, in both the durable S3 annotation and vector metadata,
    via write_artifact's Step 4a read-forward — against real AWS."""
    kwargs = {**_BASE_KWARGS, "tier": 3, "title": "Integration link-metadata overwrite test"}
    artifact_id: str = ""
    try:
        result = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
        )
        artifact_id = result["artifact_id"]

        backfill = await link_metadata(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_ids=[artifact_id],
            commit_refs=["abc1234"],
        )
        assert backfill["linked"] == 1

        overwrite_result = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            overwrite=True,
            **{**kwargs, "content": "## Summary\n\nUpdated content, no commit_refs supplied."},
        )
        assert "error" not in overwrite_result

        assert s3.get_object_annotation(artifact_id, "commit_refs") == "abc1234"
        keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        entries = vectors.get_vectors(keys)
        assert entries, "expected at least one vector for the overwritten artifact"
        for entry in entries:
            assert entry["metadata"]["commit_refs"] == ["abc1234"]
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


@pytest.mark.integration
async def test_tier3_rewrite_fewer_sections_cleans_orphans(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Tier 3 re-write with 2 sections after 3 → list_vectors_by_metadata returns 2 keys."""
    _body_a = "Body for Alpha — long enough to pass the default min section length filter."
    _body_b = "Body for Beta — long enough to pass the default min section length filter."
    _body_c = "Body for Gamma — long enough to pass the default min section length filter."
    three_section_content = (
        f"## Alpha\n\n{_body_a}\n\n## Beta\n\n{_body_b}\n\n## Gamma\n\n{_body_c}"
    )
    two_section_content = f"## Alpha\n\n{_body_a}\n\n## Beta\n\n{_body_b}"

    kwargs_3 = {**_BASE_KWARGS, "tier": 3, "title": "Integration rewrite test three"}
    kwargs_2 = {**_BASE_KWARGS, "tier": 3, "title": "Integration rewrite test three"}

    artifact_id: str = ""
    try:
        result = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            **{**kwargs_3, "content": three_section_content},
        )
        artifact_id = result["artifact_id"]

        await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            overwrite=True,
            **{**kwargs_2, "content": two_section_content},
        )

        keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        assert len(keys) == 2
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


@pytest.mark.integration
async def test_upsert_tier2_twice_one_s3_object_same_vector_count(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Write same tier 2 artifact twice → 1 S3 object; vector count unchanged."""
    kwargs = {
        **_BASE_KWARGS,
        "title": "Integration upsert test",
        "date": "2026-05-30",
        "tier": 2,
    }

    artifact_id: str = ""
    try:
        result1 = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
        )
        artifact_id = result1["artifact_id"]

        keys_after_first = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        count_after_first = len(keys_after_first)

        result2 = await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, overwrite=True, **kwargs
        )
        assert result1["artifact_id"] == result2["artifact_id"]

        # S3 should have exactly 1 object at this key
        assert s3.get_object(artifact_id) == kwargs["content"]

        keys_after_second = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        assert len(keys_after_second) == count_after_first
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
