"""Integration tests for cairn_mcp.tools.migrate_artifacts.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration.

M-16 (Phase 12 review, Cluster E): migrate_artifacts had zero integration
coverage. These tests exercise the live write path (delegation to
write_artifacts against real S3/S3 Vectors) and the A-1 skip-existing guard
(real S3 head_object check), which is exactly the kind of real-store behaviour
moto cannot be trusted to stand in for on its own.

Deferred coverage (explicitly, not silently skipped): the Nova Lite
description-generation path (missing "description" → BEDROCK_TEXT_MODEL call)
is NOT exercised here because this environment's .env does not configure
BEDROCK_TEXT_MODEL (Settings().bedrock_text_model is None). Exercising a real
Nova Lite generation call — success or failure — requires that model to be
configured and entitled in the target account; that is a deployment-specific
prerequisite outside this test suite's control. The one assertion this file
CAN make about that path with the current environment — the guard returns a
structured configuration_error rather than silently writing an
empty-description artifact — is included below.
"""

import pytest

from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.tools.delete import delete_artifact
from cairn_mcp.tools.migrate_artifacts import migrate_artifacts


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
    "team": "platform",
    "project": "cairn",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "visibility": "shared",
}


@pytest.mark.integration
async def test_migrate_artifacts_live_write_round_trip(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """dry_run=False with explicit descriptions → real S3 content + real vectors.

    Descriptions are supplied explicitly so the Nova Lite generation branch is
    never entered — this test exercises migrate_artifacts' own logic (the A-1
    skip-existing pre-check and delegation to write_artifacts) against the real
    store, independent of the deferred Nova Lite coverage noted in this file's
    module docstring.
    """
    descriptor = {
        **_BASE_KWARGS,
        "type": "code_review",
        "title": "migrate_artifacts integration round trip",
        "description": "Explicit description — Nova Lite generation not exercised.",
        "content": "## Summary\n\nMigrated content.",
    }

    artifact_id: str = ""
    try:
        result = await migrate_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            descriptors=[descriptor],
            dry_run=False,
        )

        assert "results" in result
        assert len(result["results"]) == 1
        entry = result["results"][0]
        assert entry.get("written") is True, entry
        artifact_id = entry["artifact_id"]

        assert s3.get_object(artifact_id) == descriptor["content"]
        keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        assert len(keys) >= 1
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
async def test_migrate_artifacts_rerun_skips_existing(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """A-1: re-running migrate_artifacts over the same descriptor skips, never overwrites.

    Real-AWS assertion: the second run's head_object check against the real S3
    bucket finds the key from the first run and skips it — the S3 content from
    the first run is left byte-identical (not overwritten by the second run's
    distinct content).
    """
    title = "migrate_artifacts integration idempotent rerun"
    first_content = "## Summary\n\nFirst run content."
    second_content = "## Summary\n\nSecond run content — must never be written."

    descriptor_first = {
        **_BASE_KWARGS,
        "type": "code_review",
        "title": title,
        "description": "First run descriptor.",
        "content": first_content,
    }
    descriptor_second = {
        **_BASE_KWARGS,
        "type": "code_review",
        "title": title,
        "description": "Second run descriptor — must be skipped.",
        "content": second_content,
    }

    artifact_id: str = ""
    try:
        first_result = await migrate_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            descriptors=[descriptor_first],
            dry_run=False,
        )
        assert first_result["results"][0]["written"] is True
        artifact_id = first_result["results"][0]["artifact_id"]

        second_result = await migrate_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            descriptors=[descriptor_second],
            dry_run=False,
        )

        assert second_result["results"][0]["skipped"] is True
        assert "skipped_existing" in second_result
        assert second_result["skipped_existing"][0]["artifact_id"] == artifact_id

        # Real-AWS assertion: the real S3 object was never overwritten.
        assert s3.get_object(artifact_id) == first_content
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
async def test_migrate_artifacts_missing_description_without_text_model_is_configuration_error(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Guard against silently writing an empty description when generation cannot run.

    This environment's .env does not configure BEDROCK_TEXT_MODEL (see module
    docstring), so a descriptor missing "description" must be rejected up front
    with a structured configuration_error — never written with an empty
    description. This exercises the real (unmocked) Settings object; it does
    not require a live Nova Lite call, since the guard runs before any Bedrock
    text-model invocation is attempted.
    """
    assert settings.bedrock_text_model is None, (
        "This test assumes BEDROCK_TEXT_MODEL is unset in the integration "
        "environment; if it has since been configured, the deferred Nova Lite "
        "generation coverage noted in this file's docstring should be added "
        "instead of relying on this configuration_error guard test."
    )

    descriptor = {
        **_BASE_KWARGS,
        "type": "code_review",
        "title": "migrate_artifacts integration missing description",
        "content": "## Summary\n\nContent with no description supplied.",
    }

    result = await migrate_artifacts(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        descriptors=[descriptor],
        dry_run=False,
    )

    assert result.get("error") == "configuration_error"
