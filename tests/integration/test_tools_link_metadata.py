"""Integration tests for arkeology.tools.link_metadata.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration.

M-16 (Phase 12 review, Cluster E): link_metadata had zero integration
coverage, and it is the tool most dependent on real AWS behaviour in this
cluster — it dual-writes to a real S3 object annotation (ADR-011,
PutObjectAnnotation) and reuses each vector's existing float32 embedding
unchanged. Neither of those behaviours is meaningfully exercised by moto:
S3 object annotations are entirely self-mocked in tests/unit/conftest.py
(see tests/integration/clients/test_s3_annotations.py for the dedicated
annotation-API integration coverage), and moto's query_vectors extension
is the circular simulation boundary M-16 calls out directly.
"""

import pytest

from arkeology.clients.bedrock import BedrockClientImpl
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.tools.delete import delete_artifact
from arkeology.tools.link_metadata import link_metadata
from arkeology.tools.read import read_artifact
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


_BASE_KWARGS: dict = {
    "type": "code_review",
    "team": "platform",
    "project": "arkeology",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "visibility": "shared",
}


@pytest.mark.integration
async def test_link_metadata_round_trip_durable_annotation_and_vector_metadata(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """commit_refs/references backfilled → durable in BOTH the real S3 annotation
    and vector metadata, and reappear via read_artifact without a Bedrock re-embed.
    """
    artifact_id: str = ""
    try:
        write_result = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            title="link_metadata integration round trip",
            description="Artifact for link_metadata integration round-trip test.",
            content="## Summary\n\nContent to be linked.",
            **_BASE_KWARGS,
        )
        artifact_id = write_result["artifact_id"]

        # Capture the embedding stored before link_metadata runs, to prove it is
        # reused unchanged (no Bedrock re-embed) rather than merely unchanged
        # because the assertion happens to tolerate drift.
        before_vectors = vectors.get_vectors(
            vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        )
        assert before_vectors, "expected at least one vector for the freshly written artifact"
        before_embedding_by_key = {v["key"]: v["data"]["float32"] for v in before_vectors}

        link_result = await link_metadata(
            settings=settings,
            s3=s3,
            vectors=vectors,
            artifact_ids=[artifact_id],
            commit_refs=["abc1234"],
            references=[f"{settings.write_prefix}/adr-2026-05-30-some-decision-deadbeef"],
        )

        assert link_result["linked"] == 1
        assert link_result["skipped"] == 0
        assert "next_since_ulid" in link_result

        # ── Durable S3 annotation (ADR-011) — real PutObjectAnnotation/GetObjectAnnotation ──
        assert s3.get_object_annotation(artifact_id, "commit_refs") == "abc1234"
        assert (
            s3.get_object_annotation(artifact_id, "references")
            == f"{settings.write_prefix}/adr-2026-05-30-some-decision-deadbeef"
        )

        # ── Vector metadata dual-write, embeddings reused unchanged ──
        after_vectors = vectors.get_vectors(
            vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        )
        assert after_vectors
        for v in after_vectors:
            assert v["metadata"]["commit_refs"] == ["abc1234"]
            assert v["metadata"]["references"] == [
                f"{settings.write_prefix}/adr-2026-05-30-some-decision-deadbeef"
            ]
            assert v["data"]["float32"] == before_embedding_by_key[v["key"]], (
                "link_metadata must reuse the existing embedding unchanged, "
                "never issue a Bedrock re-embed"
            )

        # ── read_artifact surfaces the durable copy end-to-end ──
        read_result = await read_artifact(
            settings=settings, s3=s3, vectors=vectors, artifact_id=artifact_id
        )
        assert read_result["commit_refs"] == ["abc1234"]
        assert read_result["references"] == [
            f"{settings.write_prefix}/adr-2026-05-30-some-decision-deadbeef"
        ]
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
async def test_link_metadata_merges_and_deduplicates_across_two_calls(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """A second link_metadata call merges into the existing durable state, dedup'd.

    Real-AWS assertion: the second call's read-forward (annotations.read_current_link_fields)
    correctly unions the prior real S3 annotation with the newly supplied value.
    """
    artifact_id: str = ""
    try:
        write_result = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            title="link_metadata integration merge dedup",
            description="Artifact for link_metadata merge/dedup integration test.",
            content="## Summary\n\nContent to be linked twice.",
            **_BASE_KWARGS,
        )
        artifact_id = write_result["artifact_id"]

        first = await link_metadata(
            settings=settings,
            s3=s3,
            vectors=vectors,
            artifact_ids=[artifact_id],
            commit_refs=["sha-one"],
        )
        assert first["linked"] == 1

        second = await link_metadata(
            settings=settings,
            s3=s3,
            vectors=vectors,
            artifact_ids=[artifact_id],
            commit_refs=["sha-one", "sha-two"],
        )
        assert second["linked"] == 1

        assert s3.get_object_annotation(artifact_id, "commit_refs") == "sha-one,sha-two"
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
async def test_link_metadata_foreign_scope_artifact_is_skipped(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """A foreign-scope artifact_id is never linked — the scope gate rejects it."""
    foreign_scope = settings.read_prefixes_list[0] if settings.read_prefixes_list else None
    assert foreign_scope, (
        "isolate_run_scope must always populate READ_PREFIXES with the run's "
        "ephemeral foreign scope"
    )
    foreign_artifact_id = f"{foreign_scope}/code-review-2026-05-30-not-ours-deadbeef"

    result = await link_metadata(
        settings=settings,
        s3=s3,
        vectors=vectors,
        artifact_ids=[foreign_artifact_id],
        commit_refs=["should-not-apply"],
    )

    assert result["linked"] == 0
    assert result["skipped"] == 1
