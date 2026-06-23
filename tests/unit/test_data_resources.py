"""Unit tests for cairn_mcp data resources (cairn://artifact/{id} and cairn://artifacts).

Tests verify registration, content delivery, cross-scope gate, and lastModified annotation
using moto-backed clients and FakeBedrockClient.
"""

import asyncio

import fastmcp
import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.resources import register_data_resources
from cairn_mcp.tools.write import write_artifact
from tests.unit.conftest import _make_settings

# ---------------------------------------------------------------------------
# Shared write kwargs helpers
# ---------------------------------------------------------------------------

_OWN_SCOPE_WRITE_KWARGS: dict = {
    "type": "implementation_note",
    "team": "platform",
    "project": "cairn",
    "tier": 2,
    "date": "2026-06-23",
    "status": "active",
    "title": "Test Artifact",
    "description": "A test artifact for data resources.",
    "content": "## Summary\n\nTest content here.",
    "visibility": "shared",
}

_FOREIGN_TIER2_WRITE_KWARGS: dict = {
    **_OWN_SCOPE_WRITE_KWARGS,
    "type": "code_review",
    "title": "Foreign Tier2 Artifact",
    "description": "Foreign scope tier 2 artifact (should be blocked).",
    "tier": 2,
    "visibility": "shared",
}


# ---------------------------------------------------------------------------
# Fixture: isolated FastMCP app with data resources registered
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_with_read_prefix(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with a read prefix configured for foreign-scope tests."""
    return _make_settings(monkeypatch, READ_PREFIXES="foreign-scope")


@pytest.fixture
def bedrock_8() -> FakeBedrockClient:
    """FakeBedrockClient with 8-dim embeddings (matches vectors_client_8)."""
    return FakeBedrockClient(dimension=8)


@pytest.fixture
def bedrock_1024() -> FakeBedrockClient:
    """FakeBedrockClient with 1024-dim embeddings (matches vectors_client)."""
    return FakeBedrockClient(dimension=1024)


# ---------------------------------------------------------------------------
# Test 1: cairn://artifact/{id} URI template present in templates list
# ---------------------------------------------------------------------------


def test_register_data_resources_artifact_template_uri_present(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    bedrock_8: FakeBedrockClient,
) -> None:
    """After register_data_resources, cairn://artifact/{id} appears in the template list."""
    # Arrange
    app = fastmcp.FastMCP(name="test-cairn", version="0.0.0")

    # Act
    register_data_resources(app, settings, s3_client, vectors_client_8, bedrock_8)

    # Assert
    templates = asyncio.run(app._list_resource_templates())  # type: ignore[attr-defined]
    template_uris = {str(t.uri_template) for t in templates}
    assert "cairn://artifact/{id}" in template_uris, (
        f"Expected 'cairn://artifact/{{id}}' in templates, got: {template_uris}"
    )


# ---------------------------------------------------------------------------
# Test 2: cairn://artifacts static URI present in resources list
# ---------------------------------------------------------------------------


def test_register_data_resources_artifacts_static_uri_present(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    bedrock_8: FakeBedrockClient,
) -> None:
    """After register_data_resources, cairn://artifacts appears in the resource list."""
    # Arrange
    app = fastmcp.FastMCP(name="test-cairn", version="0.0.0")

    # Act
    register_data_resources(app, settings, s3_client, vectors_client_8, bedrock_8)

    # Assert
    resources = asyncio.run(app._list_resources())  # type: ignore[attr-defined]
    resource_uris = {str(r.uri) for r in resources}
    assert "cairn://artifacts" in resource_uris, (
        f"Expected 'cairn://artifacts' in resources, got: {resource_uris}"
    )


# ---------------------------------------------------------------------------
# Test 3: cairn://artifact/{id} returns markdown content for own-scope artifact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_resource_returns_markdown_content(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    bedrock_1024: FakeBedrockClient,
) -> None:
    """Reading cairn://artifact/{id} for a known own-scope artifact returns markdown content."""
    # Arrange — write an own-scope artifact
    result = await write_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock_1024,
        **_OWN_SCOPE_WRITE_KWARGS,  # type: ignore[arg-type]
    )
    assert "artifact_id" in result, f"write_artifact failed: {result}"
    artifact_id = result["artifact_id"]

    from cairn_mcp.resources import _artifact_resource_content

    # Act
    content, mime_type = await _artifact_resource_content(
        artifact_id=artifact_id,
        settings=settings,
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock_1024,
    )

    # Assert
    assert mime_type == "text/markdown"
    assert "Test content here" in content


# ---------------------------------------------------------------------------
# Test 4: Foreign-scope tier-2 artifact returns error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_resource_foreign_scope_tier2_returns_error(
    settings_with_read_prefix: Settings,
    aws_mock: None,
    bedrock_8: FakeBedrockClient,
) -> None:
    """Reading cairn://artifact/{id} for a foreign-scope tier 2 artifact returns an error."""
    import boto3

    settings = settings_with_read_prefix

    # Set up a foreign-scope S3 bucket and write a tier 2 artifact into it directly
    boto3.client("s3", region_name=settings.aws_region).create_bucket(
        Bucket=settings.artifact_bucket,
    )
    s3_client = S3ClientImpl(
        region=settings.aws_region,
        profile=None,
        bucket=settings.artifact_bucket,
    )

    # Write directly to S3 simulating a foreign-scope tier 2 artifact
    foreign_artifact_id = "foreign-scope/code-review-2026-06-23-foreign-tier2-artifact"
    s3_client.put_object(
        key=foreign_artifact_id,
        body="## Foreign content",
        metadata={
            "type": "code_review",
            "team": "other",
            "project": "other-proj",
            "tier": "2",
            "date": "2026-06-23",
            "status": "active",
            "title": "Foreign Tier2 Artifact",
            "visibility": "shared",
            "description": "Foreign tier 2.",
            "tags": "",
            "source_artifacts": "",
        },
    )

    from cairn_mcp.resources import _artifact_resource_content

    # Act — no vectors client needed for this error path
    content, mime_type = await _artifact_resource_content(
        artifact_id=foreign_artifact_id,
        settings=settings,
        s3=s3_client,
        vectors=None,
        bedrock=bedrock_8,
    )

    # Assert — should return an error response, not the content
    assert mime_type == "text/markdown"
    assert "error" in content.lower() or "access" in content.lower() or "denied" in content.lower()


# ---------------------------------------------------------------------------
# Test 5: Non-existent artifact ID returns not-found error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_resource_not_found_returns_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    bedrock_8: FakeBedrockClient,
) -> None:
    """Reading cairn://artifact/{id} for a non-existent ID returns a not-found error."""
    from cairn_mcp.resources import _artifact_resource_content

    artifact_id = f"{settings.write_prefix}/implementation-note-2026-06-23-nonexistent"

    # Act
    content, mime_type = await _artifact_resource_content(
        artifact_id=artifact_id,
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock_8,
    )

    # Assert
    assert mime_type == "text/markdown"
    assert "not_found" in content or "not found" in content.lower()


# ---------------------------------------------------------------------------
# Test 6: lastModified annotation present when artifact has last_edited_ulid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_resource_last_modified_annotation_present(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    bedrock_1024: FakeBedrockClient,
) -> None:
    """When the artifact has a last_edited_ulid, lastModified annotation is included."""
    # Arrange — write an artifact (write_artifact always sets last_edited_ulid)
    result = await write_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock_1024,
        **_OWN_SCOPE_WRITE_KWARGS,  # type: ignore[arg-type]
    )
    assert "artifact_id" in result
    artifact_id = result["artifact_id"]
    assert result.get("last_edited_ulid"), "Expected write_artifact to set last_edited_ulid"

    from cairn_mcp.resources import _artifact_last_modified

    # Act
    last_modified = await _artifact_last_modified(
        artifact_id=artifact_id,
        settings=settings,
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock_1024,
    )

    # Assert — should be an ISO 8601 datetime string
    assert last_modified is not None
    assert "T" in last_modified  # ISO 8601 format contains 'T'
    assert "2026" in last_modified  # Should be in 2026


# ---------------------------------------------------------------------------
# Test 7: lastModified annotation absent when artifact has no last_edited_ulid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_resource_last_modified_annotation_absent(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    bedrock_8: FakeBedrockClient,
) -> None:
    """When the artifact has no last_edited_ulid, lastModified annotation is omitted."""
    # Arrange — write an artifact without last_edited_ulid by writing directly to S3
    artifact_id = f"{settings.write_prefix}/implementation-note-2026-06-23-no-ulid-artifact"
    s3_client.put_object(
        key=artifact_id,
        body="## No ULID content",
        metadata={
            "type": "implementation_note",
            "team": "platform",
            "project": "cairn",
            "tier": "2",
            "date": "2026-06-23",
            "status": "active",
            "title": "No ULID Artifact",
            "visibility": "shared",
            "description": "Artifact with no ULID.",
            "tags": "",
            "source_artifacts": "",
            # Intentionally omit last_edited_ulid
        },
    )

    from cairn_mcp.resources import _artifact_last_modified

    # Act
    last_modified = await _artifact_last_modified(
        artifact_id=artifact_id,
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock_8,
    )

    # Assert — should be None when no ULID present
    assert last_modified is None


# ---------------------------------------------------------------------------
# Test 8: cairn://artifacts returns markdown listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifacts_resource_returns_markdown_listing(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    bedrock_1024: FakeBedrockClient,
) -> None:
    """Reading cairn://artifacts with active own-scope artifacts returns a markdown listing."""
    # Arrange — write two artifacts
    for title in ("First Artifact", "Second Artifact"):
        result = await write_artifact(
            settings=settings,
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock_1024,
            **{**_OWN_SCOPE_WRITE_KWARGS, "title": title},  # type: ignore[arg-type]
        )
        assert "artifact_id" in result, f"write_artifact failed: {result}"

    from cairn_mcp.resources import _artifacts_listing_content

    # Act
    content = await _artifacts_listing_content(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock_1024,
    )

    # Assert — markdown listing should contain artifact identifiers, titles, types, descriptions
    assert "First Artifact" in content
    assert "Second Artifact" in content
    assert "implementation_note" in content
    # Should contain the artifact IDs
    assert settings.write_prefix in content


# ---------------------------------------------------------------------------
# Test 9: cairn://artifacts with no active artifacts returns non-error markdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifacts_resource_empty_scope_returns_markdown(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    bedrock_8: FakeBedrockClient,
) -> None:
    """Reading cairn://artifacts with no active artifacts returns non-error markdown."""
    from cairn_mcp.resources import _artifacts_listing_content

    # Act — no artifacts written
    content = await _artifacts_listing_content(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock_8,
    )

    # Assert — should be a valid markdown string, not an error
    assert isinstance(content, str)
    assert len(content) > 0
    assert "error" not in content.lower()
