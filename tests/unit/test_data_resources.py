"""Unit tests for arkeology data resources (arkeology://artifact/{id*} and arkeology://artifacts).

Tests verify registration, content delivery, cross-scope gate, and lastModified annotation
using moto-backed clients and FakeBedrockClient.
"""

import asyncio

import fastmcp
import pytest

from arkeology.artifact import generate_artifact_id
from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.references import ManifestEntry, build_path_to_id_map
from arkeology.resources import register_data_resources
from arkeology.tools.write import write_artifact
from tests.unit.conftest import _make_settings

# ---------------------------------------------------------------------------
# Shared write kwargs helpers
# ---------------------------------------------------------------------------

_OWN_SCOPE_WRITE_KWARGS: dict = {
    "type": "implementation_note",
    "team": "platform",
    "project": "arkeology",
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
    return FakeBedrockClient()


@pytest.fixture
def bedrock_1024() -> FakeBedrockClient:
    """FakeBedrockClient with 1024-dim embeddings (matches vectors_client)."""
    return FakeBedrockClient()


# ---------------------------------------------------------------------------
# Test 1: arkeology://artifact/{id} URI template present in templates list
# ---------------------------------------------------------------------------


def test_register_data_resources_artifact_template_uri_present(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    bedrock_8: FakeBedrockClient,
) -> None:
    """After register_data_resources, arkeology://artifact/{id} appears in the template list."""
    # Arrange
    app = fastmcp.FastMCP(name="test-arkeology", version="0.0.0")

    # Act
    register_data_resources(app, settings, s3_client, vectors_client_8, bedrock_8)

    # Assert — the template uses the {id*} RFC 6570 wildcard-path parameter (not plain
    # {id}) so that a full S3 key artifact_id (which contains '/') is matched in full
    # rather than truncated at the first path segment.
    templates = asyncio.run(app._list_resource_templates())  # type: ignore[attr-defined]
    template_uris = {str(t.uri_template) for t in templates}
    assert "arkeology://artifact/{id*}" in template_uris, (
        f"Expected 'arkeology://artifact/{{id*}}' in templates, got: {template_uris}"
    )


# ---------------------------------------------------------------------------
# Test 2: arkeology://artifacts static URI present in resources list
# ---------------------------------------------------------------------------


def test_register_data_resources_artifacts_static_uri_present(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    bedrock_8: FakeBedrockClient,
) -> None:
    """After register_data_resources, arkeology://artifacts appears in the resource list."""
    # Arrange
    app = fastmcp.FastMCP(name="test-arkeology", version="0.0.0")

    # Act
    register_data_resources(app, settings, s3_client, vectors_client_8, bedrock_8)

    # Assert
    resources = asyncio.run(app._list_resources())  # type: ignore[attr-defined]
    resource_uris = {str(r.uri) for r in resources}
    assert "arkeology://artifacts" in resource_uris, (
        f"Expected 'arkeology://artifacts' in resources, got: {resource_uris}"
    )


# ---------------------------------------------------------------------------
# Test 3: arkeology://artifact/{id} returns markdown content for own-scope artifact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_resource_returns_markdown_content(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    bedrock_1024: FakeBedrockClient,
) -> None:
    """Reading arkeology://artifact/{id} for a known own-scope artifact returns markdown content."""
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

    from arkeology.resources import _artifact_resource_content

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
    """Reading arkeology://artifact/{id} for a foreign-scope tier 2 artifact returns an error."""
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

    from arkeology.resources import _artifact_resource_content

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
    """Reading arkeology://artifact/{id} for a non-existent ID returns a not-found error."""
    from arkeology.resources import _artifact_resource_content

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

    from arkeology.resources import _artifact_last_modified

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
            "project": "arkeology",
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

    from arkeology.resources import _artifact_last_modified

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
# Test 8: arkeology://artifacts returns markdown listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifacts_resource_returns_markdown_listing(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    bedrock_1024: FakeBedrockClient,
) -> None:
    """Reading arkeology://artifacts with active own-scope artifacts returns a markdown listing."""
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

    from arkeology.resources import _artifacts_listing_content

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
# Test 9: arkeology://artifacts with no active artifacts returns non-error markdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifacts_resource_empty_scope_returns_markdown(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    bedrock_8: FakeBedrockClient,
) -> None:
    """Reading arkeology://artifacts with no active artifacts returns non-error markdown."""
    from arkeology.resources import _artifacts_listing_content

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


# ---------------------------------------------------------------------------
# Test 10 — embedded newline in a cell value must not corrupt the markdown table
# _render_artifacts_markdown escapes '|' but not '\n', so a
# description/title containing a literal newline splits what should be one table
# row into multiple lines, corrupting every subsequent row's column alignment.
# ---------------------------------------------------------------------------


def test_render_artifacts_markdown_escapes_embedded_newline_in_cell() -> None:
    """A description containing an embedded newline must not break the table's row
    structure. A raw (unescaped) '\\n' splits one logical row into two physical
    lines — the tail fragment ("line two |") is neither the title line, blank, nor
    a '|'-prefixed table line, so it corrupts every subsequent row's column
    alignment when rendered. Every physical line in the output must be the title,
    blank, or a '|'-prefixed table row."""
    from arkeology.resources import _render_artifacts_markdown

    artifacts = [
        {
            "artifact_id": "artifacts/a1",
            "title": "Fine",
            "type": "adr",
            "description": "line one\nline two",
        },
        {
            "artifact_id": "artifacts/a2",
            "title": "Also fine",
            "type": "adr",
            "description": "unrelated",
        },
    ]

    content = _render_artifacts_markdown(artifacts)

    for line in content.split("\n"):
        assert line == "" or line.startswith("#") or line.startswith("|"), (
            f"malformed line — likely an unescaped embedded newline: {line!r}"
        )
    # One table row per artifact, none swallowed or split apart.
    row_lines = [line for line in content.split("\n") if line.startswith("| artifacts/")]
    assert len(row_lines) == len(artifacts)


# ---------------------------------------------------------------------------
# The full S3 key is the operative artifact_id
# ---------------------------------------------------------------------------
#
# The bug: build_path_to_id_map emitted the BARE generate_artifact_id output, but
# every consuming surface (write.py's vector metadata, read_artifact's scope gate,
# the referenced_by reverse lookup) operates on the FULL S3 key
# f"{write_prefix}/{bare_id}{extension}". A migration-produced reference or a
# arkeology://artifact/{id} URI built from the bare id is dead on every one of those
# surfaces. These tests prove: (1) build_path_to_id_map's output matches EXACTLY
# what write_artifact itself stores as artifact_id, and (2) a full key (which
# contains '/' from write_prefix) resolves through the ACTUAL registered FastMCP
# resource template — not just the inner content helper — which is what exposed the
# {id} vs {id*} URI template gap in the first place (a plain {id} segment parameter
# only matches a single path segment and silently rejects every real artifact_id).


@pytest.mark.asyncio
async def test_build_path_to_id_map_matches_live_write_artifact_full_key(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    bedrock_1024: FakeBedrockClient,
) -> None:
    """Red-first (TDD 1a): build_path_to_id_map's full-key output for a manifest
    entry equals EXACTLY the artifact_id write_artifact returns for the same
    type/tier/title/date — the map must never diverge from the live write-path key
    composition in ``write_artifact``."""
    # Arrange — write an artifact via the real write path
    write_kwargs = {
        "type": "adr",
        "team": "platform",
        "project": "arkeology",
        "tier": 3,
        "date": "2026-07-01",
        "status": "active",
        "title": "Use S3 Vectors For References",
        "description": "Decision to use S3 Vectors for the references map.",
        "content": "## Context\n\nSome context.",
        "visibility": "shared",
    }
    result = await write_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock_1024,
        **write_kwargs,  # type: ignore[arg-type]
    )
    assert "artifact_id" in result, f"write_artifact failed: {result}"

    # Act — build the map from an equivalent manifest entry (same type/tier/title/date)
    entry: ManifestEntry = {
        "path": "docs/adr/001-use-s3-vectors.md",
        "type": "adr",
        "tier": 3,
        "title": "Use S3 Vectors For References",
        "date": "2026-07-01",
    }
    path_to_id_map = build_path_to_id_map([entry], write_prefix=settings.write_prefix)

    # Assert — the map's full key equals EXACTLY the live artifact_id write_artifact stored
    expected_bare_id = generate_artifact_id(
        type="adr", tier=3, date="2026-07-01", title=write_kwargs["title"]
    )
    assert result["artifact_id"] == f"{settings.write_prefix}/{expected_bare_id}.md"
    assert path_to_id_map[entry["path"]] == result["artifact_id"]


@pytest.mark.asyncio
async def test_arkeology_artifact_template_resolves_full_key_own_scope(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    bedrock_1024: FakeBedrockClient,
) -> None:
    """TDD 1c: arkeology://artifact/{full-key} resolves end-to-end through the ACTUAL
    registered FastMCP resource template (not just the inner content function) for an
    own-scope artifact. The full key contains '/' from write_prefix — proving the
    {id*} wildcard-path template parameter (not plain {id}) is what is registered."""
    # Arrange — write an artifact and register the real data resources on a fresh app
    result = await write_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock_1024,
        **_OWN_SCOPE_WRITE_KWARGS,  # type: ignore[arg-type]
    )
    assert "artifact_id" in result, f"write_artifact failed: {result}"
    artifact_id = result["artifact_id"]
    assert "/" in artifact_id, "Test assumes a full key containing write_prefix + '/'"

    app = fastmcp.FastMCP(name="test-arkeology-fullkey", version="0.0.0")
    register_data_resources(app, settings, s3_client, vectors_client, bedrock_1024)

    # Act — read through the actual registered URI template, not the inner helper
    read_result = await app.read_resource(f"arkeology://artifact/{artifact_id}")

    # Assert
    contents = read_result.contents
    assert len(contents) > 0
    text = contents[0].content
    assert "Test content here" in text


@pytest.mark.asyncio
async def test_arkeology_artifact_template_gates_full_key_foreign_scope_tier2(
    settings_with_read_prefix: Settings,
    aws_mock: None,
    vectors_client_8: VectorsClientImpl,
    bedrock_8: FakeBedrockClient,
) -> None:
    """TDD 1c: a foreign-scope tier-2 full key is still correctly GATED (access
    denied) when resolved through the ACTUAL registered {id*} template — the wildcard
    fix that lets full keys match must not also bypass the cross-scope gate."""
    import boto3

    settings = settings_with_read_prefix

    boto3.client("s3", region_name=settings.aws_region).create_bucket(
        Bucket=settings.artifact_bucket,
    )
    s3_client = S3ClientImpl(
        region=settings.aws_region,
        profile=None,
        bucket=settings.artifact_bucket,
    )
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

    app = fastmcp.FastMCP(name="test-arkeology-fullkey-gate", version="0.0.0")
    register_data_resources(app, settings, s3_client, vectors_client_8, bedrock_8)

    # Act — read through the actual registered URI template
    read_result = await app.read_resource(f"arkeology://artifact/{foreign_artifact_id}")

    # Assert — access denied, not the foreign content
    contents = read_result.contents
    assert len(contents) > 0
    text = contents[0].content
    assert "error" in text.lower() or "denied" in text.lower()
    assert "Foreign content" not in text
