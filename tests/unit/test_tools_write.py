"""Unit tests for cairn_mcp.tools.write.

Tests write_artifact() and its embedding helper functions using moto-backed clients.
"""

import asyncio
import json
import logging

import botocore.exceptions
import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools.write import (
    _build_document_embedding_text,
    _build_section_embedding_text,
    write_artifact,
)
from tests.unit.conftest import _make_settings

# Base write kwargs
_BASE_WRITE_KWARGS: dict = {
    "type": "code_review",
    "team": "platform",
    "project": "cairn",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "title": "Fix auth bug",
    "description": "Review of the auth module.",
    "content": (
        "## Summary\n\nAll looks good.\n\n"
        "## Details\n\nSee inline comments.\n\n"
        "## Action Items\n\nNone."
    ),
    "visibility": "shared",
}

_ONE_SECTION_KWARGS: dict = {
    **_BASE_WRITE_KWARGS,
    "content": "No headings here — just plain content.",
}


# ---------------------------------------------------------------------------
# _build_section_embedding_text
# ---------------------------------------------------------------------------


def test_section_embed_starts_with_title() -> None:
    """_build_section_embedding_text output starts with 'Title: {title}'."""
    text = _build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert text.startswith("Title: Fix auth bug")


def test_section_embed_contains_type() -> None:
    """_build_section_embedding_text output contains 'Type: {type}'."""
    text = _build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert "Type: code_review" in text


def test_section_embed_contains_tags_when_present() -> None:
    """_build_section_embedding_text output contains tags when tags non-empty."""
    text = _build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=["auth", "security"],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert "Tags:" in text
    assert "auth" in text
    assert "security" in text


def test_section_embed_omits_tags_when_empty() -> None:
    """_build_section_embedding_text omits the Tags line when tags is empty."""
    text = _build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert "Tags:" not in text


def test_section_embed_contains_heading_and_body() -> None:
    """_build_section_embedding_text contains the section heading and body."""
    text = _build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert "Summary" in text
    assert "All looks good." in text


# ---------------------------------------------------------------------------
# _build_document_embedding_text
# ---------------------------------------------------------------------------


def test_document_embed_starts_with_title() -> None:
    """_build_document_embedding_text output starts with 'Title: {title}'."""
    text = _build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        description="Review of the auth module.",
    )
    assert text.startswith("Title: Fix auth bug")


def test_document_embed_contains_type() -> None:
    """_build_document_embedding_text output contains 'Type: {type}'."""
    text = _build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        description="Review of the auth module.",
    )
    assert "Type: code_review" in text


def test_document_embed_contains_description() -> None:
    """_build_document_embedding_text output contains 'Description: {description}'."""
    text = _build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        description="Review of the auth module.",
    )
    assert "Description: Review of the auth module." in text


def test_document_embed_omits_tags_when_empty() -> None:
    """_build_document_embedding_text omits the Tags line when tags is empty."""
    text = _build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        description="A description.",
    )
    assert "Tags:" not in text


def test_document_embed_contains_tags_when_present() -> None:
    """_build_document_embedding_text contains tags when tags non-empty."""
    text = _build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=["payments"],
        description="A description.",
    )
    assert "Tags:" in text
    assert "payments" in text


# ---------------------------------------------------------------------------
# write_artifact — happy path
# ---------------------------------------------------------------------------


async def test_three_section_content_indexes_three_sections(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Three-section content → sections_indexed == 3 and 3 vectors in index."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert result["sections_indexed"] == 3
    artifact_id = result["artifact_id"]
    all_keys = vectors_client.list_vectors_by_metadata({})
    matching_keys = [k for k in all_keys if k == artifact_id or k.startswith(artifact_id + "#")]
    assert len(matching_keys) == 3


async def test_no_section_content_indexes_one_document_fallback(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """No-section content → sections_indexed == 1 (document-level fallback)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result["sections_indexed"] == 1


async def test_s3_contains_content_at_correct_key(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """After write_artifact, S3 contains the content at the returned artifact_id key."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    artifact_id = result["artifact_id"]
    stored_content = s3_client.get_object(artifact_id)
    assert stored_content == _BASE_WRITE_KWARGS["content"]


async def test_returned_artifact_id_is_full_s3_key(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Returned artifact_id is the full S3 key including write_prefix."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    artifact_id = result["artifact_id"]
    assert artifact_id.startswith(settings.write_prefix + "/")


async def test_section_vector_keys_contain_hash_separator(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Vector keys for sections have format {s3_key}#{section_slug}."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    artifact_id = result["artifact_id"]
    all_keys = vectors_client.list_vectors_by_metadata({})
    section_keys = [k for k in all_keys if k.startswith(artifact_id + "#")]
    assert len(section_keys) == 3
    for key in section_keys:
        assert "#" in key


async def test_document_fallback_vector_key_has_no_hash(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Document-level fallback vector key equals {s3_key} (no # suffix)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    artifact_id = result["artifact_id"]
    all_keys = vectors_client.list_vectors_by_metadata({})
    assert artifact_id in all_keys
    assert not any(k.startswith(artifact_id + "#") for k in all_keys)


async def test_vector_metadata_includes_artifact_id_and_scope(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Each vector's metadata includes artifact_id (full S3 key) and scope (write_prefix)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    artifact_id = result["artifact_id"]
    all_keys = vectors_client.list_vectors_by_metadata({})
    entries = vectors_client.get_vectors(all_keys)
    for entry in entries:
        assert entry["metadata"]["artifact_id"] == artifact_id
        assert entry["metadata"]["scope"] == settings.write_prefix


async def test_response_has_artifact_id_and_sections_indexed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Response dict has keys 'artifact_id' and 'sections_indexed'."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "artifact_id" in result
    assert "sections_indexed" in result


# ---------------------------------------------------------------------------
# Tier 2 idempotency
# ---------------------------------------------------------------------------


async def test_tier2_write_twice_same_date_one_s3_object(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Write same tier 2 artifact twice (same date) → exactly 1 S3 object."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )
    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert len(s3_client.list_objects("")) == 1


async def test_tier2_write_twice_same_date_vector_count_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Write same tier 2 artifact twice (same date) → vector count is unchanged (upsert)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result1 = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )
    count_after_first = len(vectors_client.list_vectors_by_metadata({}))
    result2 = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert result1["artifact_id"] == result2["artifact_id"]
    assert len(vectors_client.list_vectors_by_metadata({})) == count_after_first


async def test_tier2_different_dates_produce_distinct_keys(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Write same tier 2 artifact on two different dates → 2 distinct S3 keys."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    kwargs_day1 = {**_BASE_WRITE_KWARGS, "date": "2026-05-30"}
    kwargs_day2 = {**_BASE_WRITE_KWARGS, "date": "2026-05-31"}

    result1 = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_day1
    )
    result2 = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_day2
    )

    assert result1["artifact_id"] != result2["artifact_id"]
    assert len(s3_client.list_objects("")) == 2


# ---------------------------------------------------------------------------
# Tier 3 re-write (orphan cleanup)
# ---------------------------------------------------------------------------


async def test_tier3_rewrite_fewer_sections_cleans_orphans(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Tier 3: first write 3 sections, re-write 2 → orphan section C key is absent."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    three_section_content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B.\n\n## Gamma\n\nBody C."
    two_section_content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B."

    kwargs_3 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": three_section_content}
    kwargs_2 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": two_section_content}

    result1 = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_3
    )
    artifact_id = result1["artifact_id"]

    all_keys_before = vectors_client.list_vectors_by_metadata({})
    keys_before = [k for k in all_keys_before if k.startswith(artifact_id)]
    assert len(keys_before) == 3

    await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_2
    )

    all_keys_after = vectors_client.list_vectors_by_metadata({})
    keys_after = [k for k in all_keys_after if k.startswith(artifact_id)]
    assert len(keys_after) == 2
    gamma_keys = [k for k in keys_after if "gamma" in k]
    assert len(gamma_keys) == 0


async def test_tier3_rewrite_more_sections(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Tier 3: first write 1 section, re-write 3 → 3 vectors after re-write."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    three_section_content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B.\n\n## Gamma\n\nBody C."
    kwargs_1 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": "## Alpha\n\nBody A."}
    kwargs_3 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": three_section_content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_1
    )
    artifact_id = result["artifact_id"]

    await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_3
    )

    all_keys = vectors_client.list_vectors_by_metadata({})
    keys_after = [k for k in all_keys if k.startswith(artifact_id)]
    assert len(keys_after) == 3


async def test_tier3_rewrite_identical_sections_count_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Tier 3: re-write with identical sections → vector count unchanged."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B."
    kwargs = {**_BASE_WRITE_KWARGS, "tier": 3, "content": content}

    await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )
    count_after_first = len(vectors_client.list_vectors_by_metadata({}))

    await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )
    assert len(vectors_client.list_vectors_by_metadata({})) == count_after_first


# ---------------------------------------------------------------------------
# Tier 3 key stability
# ---------------------------------------------------------------------------


async def test_tier3_different_dates_same_artifact_id(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Tier 3: writes with different dates, same type+title → same artifact_id."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    kwargs_day1 = {**_BASE_WRITE_KWARGS, "tier": 3, "date": "2026-05-30"}
    kwargs_day2 = {**_BASE_WRITE_KWARGS, "tier": 3, "date": "2026-06-15"}

    result1 = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_day1
    )
    result2 = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_day2
    )

    assert result1["artifact_id"] == result2["artifact_id"]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


async def test_validation_description_too_long_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """description > 280 chars → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    kwargs = {**_BASE_WRITE_KWARGS, "description": "x" * 281}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3_client.list_objects("")) == 0


async def test_validation_invalid_type_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Invalid type → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    kwargs = {**_BASE_WRITE_KWARGS, "type": "invalid_type"}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3_client.list_objects("")) == 0


async def test_validation_invalid_tier_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Invalid tier → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    kwargs = {**_BASE_WRITE_KWARGS, "tier": 1}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3_client.list_objects("")) == 0


async def test_validation_invalid_visibility_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Invalid visibility → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    kwargs = {**_BASE_WRITE_KWARGS, "visibility": "public"}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3_client.list_objects("")) == 0


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_s3_credential_failure_returns_error_bedrock_not_called(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """S3 credential failure → error in response; bedrock.embed NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    spy = mocker.spy(bedrock, "embed")
    mocker.patch.object(
        s3_client,
        "head_object",
        side_effect=CredentialError(
            message="simulated",
            service="s3",
            original=Exception("simulated"),
        ),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "error" in result or result.get("success") is False
    assert spy.call_count == 0


async def test_bedrock_credential_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Bedrock credential failure → error in response (S3 may already have been written)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    bedrock.set_credential_failure(True)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "error" in result or result.get("success") is False


# ---------------------------------------------------------------------------
# T1: vector metadata stores tags as list
# ---------------------------------------------------------------------------


async def test_vector_metadata_tags_is_list(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """After successful write, tags in vector metadata is a list (not a string)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    kwargs = {**_BASE_WRITE_KWARGS, "tags": ["auth", "security"]}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    s3_key = result["artifact_id"]
    all_keys = vectors_client.list_vectors_by_metadata({})
    relevant_keys = [k for k in all_keys if k.startswith(s3_key)]
    vec_results = vectors_client.get_vectors(relevant_keys)
    assert len(vec_results) > 0
    for entry in vec_results:
        assert isinstance(entry["metadata"]["tags"], list), (
            f"Expected list, got {type(entry['metadata']['tags'])}"
        )


# ---------------------------------------------------------------------------
# T2: S3 metadata stores tags and source_artifacts as comma-joined strings
# ---------------------------------------------------------------------------


async def test_s3_metadata_tags_and_source_artifacts_are_strings(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """After successful write, S3 metadata stores tags and source_artifacts
    as comma-joined strings (not lists), per S3 metadata constraints."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    kwargs = {
        **_BASE_WRITE_KWARGS,
        "tags": ["auth", "security"],
        "source_artifacts": ["adr-one", "adr-two"],
    }
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    s3_key = result["artifact_id"]
    meta = s3_client.head_object(s3_key)
    assert isinstance(meta["tags"], str), f"Expected str in S3 metadata, got {type(meta['tags'])}"
    assert meta["tags"] == "auth,security"
    assert isinstance(meta["source_artifacts"], str), (
        f"Expected str in S3 metadata, got {type(meta['source_artifacts'])}"
    )
    assert meta["source_artifacts"] == "adr-one,adr-two"


# ---------------------------------------------------------------------------
# T15: Throttle retry and partial write failure log
# ---------------------------------------------------------------------------


def _throttle_error() -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "InvokeModel",
    )


def _non_throttle_error() -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError(
        {"Error": {"Code": "ValidationException", "Message": "Bad input"}},
        "InvokeModel",
    )


class _ThrottleThenSucceedBedrock(FakeBedrockClient):
    """Raises ThrottlingException on the first embed call, then succeeds."""

    def __init__(self, **kwargs: int) -> None:
        super().__init__(**kwargs)
        self._call_count = 0

    def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
        self._call_count += 1
        if self._call_count == 1:
            raise _throttle_error()
        return super().embed(text, model_id, dimensions)


class _ThrottleAlwaysBedrock(FakeBedrockClient):
    """Raises ThrottlingException on every embed call."""

    def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
        raise _throttle_error()


class _NonThrottleErrorBedrock(FakeBedrockClient):
    """Raises a non-throttle ClientError on every embed call."""

    def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
        raise _non_throttle_error()


async def _instant_sleep(_seconds: float) -> None:
    """Drop-in replacement for asyncio.sleep that returns immediately."""


async def test_throttle_on_doc_fallback_returns_partial_write_no_retry(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Throttle on doc-level embed → immediate partial_write; no write.py-level retry.

    write.py delegates retry to BedrockClientImpl; the document-level fallback path
    does not retry throttle errors itself.
    """
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = _ThrottleAlwaysBedrock()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result
    assert log_path.exists()


async def test_throttle_retry_both_fail_returns_partial_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Throttle on both embed calls → partial_write error; artifact_id in response."""
    log_path = tmp_path / "failures.jsonl"
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = _ThrottleAlwaysBedrock()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result


async def test_throttle_retry_both_fail_writes_failure_log_bedrock_embed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Throttle on both embed calls → failure log entry with failure_step='bedrock_embed'."""
    log_path = tmp_path / "failures.jsonl"
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = _ThrottleAlwaysBedrock()

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "bedrock_embed"


async def test_non_throttle_error_returns_partial_write_no_retry(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Non-throttle ClientError → no retry; partial_write error; failure log written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = _NonThrottleErrorBedrock()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "bedrock_embed"


async def test_put_vector_failure_returns_partial_write_with_log(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """S3 write succeeds, put_vectors_batch raises → partial_write error; failure log written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(
        vectors_client,
        "put_vectors_batch",
        side_effect=RuntimeError("simulated put_vectors_batch failure"),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "put_vector"


async def test_failure_log_entry_contains_all_required_fields(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Failure log entry contains all required fields with correct types."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(
        vectors_client,
        "put_vectors_batch",
        side_effect=RuntimeError("simulated put_vectors_batch failure"),
    )

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    entry = json.loads(log_path.read_text().splitlines()[0])
    required_fields = (
        "artifact_id",
        "title",
        "type",
        "tier",
        "date",
        "failure_step",
        "reason",
        "timestamp",
    )
    for field in required_fields:
        assert field in entry, f"Missing field: {field}"
    assert entry["title"] == _ONE_SECTION_KWARGS["title"]
    assert entry["type"] == _ONE_SECTION_KWARGS["type"]
    assert entry["tier"] == _ONE_SECTION_KWARGS["tier"]
    assert entry["date"] == _ONE_SECTION_KWARGS["date"]
    from datetime import datetime

    datetime.fromisoformat(entry["timestamp"])


async def test_failure_log_appends_across_multiple_failures(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Two separate partial write failures → failure log has two entries (append behaviour)."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(
        vectors_client,
        "put_vectors_batch",
        side_effect=RuntimeError("simulated put_vectors_batch failure"),
    )

    for _ in range(2):
        await write_artifact(
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock,
            settings=settings,
            **_ONE_SECTION_KWARGS,
        )

    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        entry = json.loads(line)
        assert entry["failure_step"] == "put_vector"


async def test_bedrock_credential_error_no_failure_log(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Bedrock CredentialError → credential_error response; no failure log entry written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient(dimension=1024)
    bedrock.set_credential_failure(True)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "credential_error"
    assert not log_path.exists()


async def test_put_vector_credential_error_no_failure_log(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """put_vectors_batch CredentialError → credential_error response; no failure log written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(
        vectors_client,
        "put_vectors_batch",
        side_effect=CredentialError(
            message="AWS credentials are invalid or expired (simulated).",
            service="s3vectors",
            original=Exception("simulated credential failure"),
        ),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "credential_error"
    assert not log_path.exists()


# ---------------------------------------------------------------------------
# Spec 18 — Orphan cleanup skipped for new artifacts
# ---------------------------------------------------------------------------


async def test_new_artifact_skips_orphan_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """New artifact (head_object 404) → list_vectors_by_metadata NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    spy = mocker.spy(vectors_client, "list_vectors_by_metadata")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert spy.call_count == 0


async def test_existing_artifact_runs_orphan_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Existing artifact (head_object returns meta) → list_vectors_by_metadata called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    spy = mocker.spy(vectors_client, "list_vectors_by_metadata")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert spy.call_count >= 1


# ---------------------------------------------------------------------------
# Orphan cleanup is best-effort — a cleanup failure must not invert a durable write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orphan_cleanup_list_failure_does_not_fail_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A non-credential failure listing existing vectors during orphan cleanup must NOT
    invert an already-successful write — by Step 8 the artifact is durably in S3 and its
    new section vectors are indexed, so the result must still report success.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    # Orphan cleanup (only reached on the re-write) hits a non-credential error.
    mocker.patch.object(
        vectors_client, "list_vectors_by_metadata", side_effect=RuntimeError("boom")
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "error" not in result, f"cleanup failure must not fail the write, got: {result}"
    assert result.get("artifact_id"), f"artifact_id missing: {result}"
    assert "sections_indexed" in result


@pytest.mark.asyncio
async def test_orphan_cleanup_delete_failure_does_not_fail_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A non-credential failure deleting orphan vectors must NOT fail the write; the new
    content is written and the new section vectors are indexed regardless.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    three = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B.\n\n## Gamma\n\nBody C."
    two = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B."
    kwargs_3 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": three}
    kwargs_2 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": two}

    first = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_3
    )
    artifact_id = first["artifact_id"]

    # Re-write with fewer sections → orphan exists → delete_vectors is called and fails.
    mocker.patch.object(vectors_client, "delete_vectors", side_effect=RuntimeError("boom"))

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_2
    )

    assert "error" not in result, f"cleanup failure must not fail the write, got: {result}"
    assert result.get("artifact_id") == artifact_id
    assert result.get("sections_indexed") == 2


@pytest.mark.asyncio
async def test_orphan_cleanup_credential_failure_does_not_fail_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A CredentialError during orphan cleanup must also not invert a durable write —
    cleanup is best-effort (the write already succeeded before Step 8).
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    mocker.patch.object(
        vectors_client,
        "list_vectors_by_metadata",
        side_effect=CredentialError(
            message="AWS credentials are invalid or expired (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "error" not in result, (
        f"cleanup credential failure must not fail the write, got: {result}"
    )
    assert result.get("artifact_id")


# ---------------------------------------------------------------------------
# Spec 19 — CredentialError from head_object returns credential_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_head_object_credential_error_returns_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """CredentialError raised by head_object → credential_error response; write not attempted."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(
        s3_client,
        "head_object",
        side_effect=CredentialError(
            message="AWS credentials are invalid or expired (simulated).",
            service="s3",
            original=Exception("simulated"),
        ),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert result.get("error") == "credential_error"
    assert len(s3_client.list_objects("")) == 0


# ---------------------------------------------------------------------------
# Helpers shared by T26 / T28 tests
# ---------------------------------------------------------------------------


def _make_sections_content(count: int, body_length: int = 120) -> str:
    """Build Markdown with ``count`` H2 sections, each body ``body_length`` chars long."""
    parts = [f"## Section {i}\n\n{'x' * body_length}" for i in range(1, count + 1)]
    return "\n\n".join(parts)


def _make_mixed_sections_content(
    long_count: int, short_count: int, long_len: int = 120, short_len: int = 10
) -> str:
    """Build Markdown with a mix of long and short sections (long sections first)."""
    parts = [f"## Long {i}\n\n{'x' * long_len}" for i in range(1, long_count + 1)]
    parts += [f"## Short {i}\n\n{'x' * short_len}" for i in range(1, short_count + 1)]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# T26 — Concurrent embedding and batched put_vectors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_sections_embeds_all_concurrently(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """8-section document → embed called 8 times; put_vectors_batch called exactly once."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    content = _make_sections_content(8)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert embed_spy.call_count == 8
    assert batch_spy.call_count == 1


@pytest.mark.asyncio
async def test_write_sections_batch_put_called_once(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """5-section document → put_vectors_batch called exactly once (not 5 times)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    content = _make_sections_content(5)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert batch_spy.call_count == 1


class _FailOnSecondEmbedBedrock(FakeBedrockClient):
    """Raises RuntimeError on the 2nd outer embed() call — thread-safe counter."""

    import threading

    def __init__(self, **kwargs: int) -> None:
        super().__init__(**kwargs)
        self._call_count = 0
        self._lock = __import__("threading").Lock()

    def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
        with self._lock:
            self._call_count += 1
            count = self._call_count
        if count == 2:
            raise RuntimeError("simulated embed failure on 2nd call")
        return super().embed(text, model_id, dimensions)


@pytest.mark.asyncio
async def test_write_any_embed_failure_aborts_atomically(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Any embed failure → put_vectors_batch never called; response contains partial_write."""
    settings = _make_settings(monkeypatch)
    bedrock = _FailOnSecondEmbedBedrock(dimension=1024)
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    # 8 sections: the 2nd embed call will raise, aborting the whole batch
    content = _make_sections_content(8)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "partial_write"
    assert batch_spy.call_count == 0


@pytest.mark.asyncio
async def test_write_embed_credential_error_aborts(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """CredentialError on any embed → response error == 'credential_error'; no vectors written."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    bedrock.set_credential_failure(True)
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    content = _make_sections_content(3)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "credential_error"
    assert batch_spy.call_count == 0


@pytest.mark.asyncio
async def test_write_sections_semaphore_default(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """10-section write completes without error under default SECTION_CONCURRENCY=5."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    content = _make_sections_content(10)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert result["sections_indexed"] == 10


# ---------------------------------------------------------------------------
# T27 — Throttle fix: no asyncio.sleep from write.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_throttle_exhausted_calls_embed_exactly_twice(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Throttle exhausted → embed called exactly once; error is partial_write.

    write.py delegates retry to BedrockClientImpl; the write tool itself calls
    embed exactly once per document-level fallback and propagates any exception.
    """
    settings = _make_settings(monkeypatch)
    # _ThrottleAlwaysBedrock raises botocore ThrottlingException on every call
    bedrock = _ThrottleAlwaysBedrock()
    embed_spy = mocker.spy(bedrock, "embed")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert embed_spy.call_count == 1
    assert result.get("error") == "partial_write"


@pytest.mark.asyncio
async def test_no_extra_sleep_from_write_on_throttle(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """write.py must not call asyncio.sleep with a positive argument on throttle.

    The sleep-with-jitter belongs in BedrockClientImpl, not in the write tool.
    Any asyncio.sleep(0) is acceptable (yield-to-event-loop pattern); only positive
    values indicate a retry delay injected by write.py.
    """
    settings = _make_settings(monkeypatch)
    bedrock = _ThrottleAlwaysBedrock()

    positive_sleep_calls: list[float] = []

    async def capture_sleep(delay: float) -> None:
        if delay > 0:
            positive_sleep_calls.append(delay)

    mocker.patch("asyncio.sleep", side_effect=capture_sleep)

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert positive_sleep_calls == [], (
        f"write.py called asyncio.sleep with positive delay(s): {positive_sleep_calls}. "
        "The retry sleep must live in BedrockClientImpl, not in write.py."
    )


# ---------------------------------------------------------------------------
# T28 — Configurable section caps and min-length filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_section_skipped(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Sections shorter than EMBED_MIN_SECTION_LENGTH are skipped; only longer ones are embedded."""
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="50")
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")

    # Section 1: 10 chars (skipped). Sections 2 & 3: 200 chars each (pass filter).
    content = (
        "## Short Section\n\n" + "x" * 10 + "\n\n"
        "## Long Section A\n\n" + "x" * 200 + "\n\n"
        "## Long Section B\n\n" + "x" * 200
    )
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert embed_spy.call_count == 2
    assert result["sections_indexed"] == 2


@pytest.mark.asyncio
async def test_all_sections_short_falls_back_to_document(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """When all sections are filtered by min-length, document-level embed is used as fallback."""
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="50")
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")

    # Both sections have bodies of only 10 chars — both below the 50-char threshold
    content = "## Tiny A\n\n" + "x" * 10 + "\n\n## Tiny B\n\n" + "x" * 10
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    # Document-level fallback: exactly one embed call, one vector indexed
    assert embed_spy.call_count == 1
    assert result["sections_indexed"] == 1


@pytest.mark.asyncio
async def test_min_length_zero_skips_no_sections(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """EMBED_MIN_SECTION_LENGTH=0 disables the filter — all sections are embedded."""
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="0")
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")

    # Mix of very short and longer sections; with min=0 all 4 pass
    content = (
        "## Tiny\n\nx\n\n"
        "## Small\n\n" + "x" * 5 + "\n\n"
        "## Medium\n\n" + "x" * 80 + "\n\n"
        "## Large\n\n" + "x" * 200
    )
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert embed_spy.call_count == 4
    assert result["sections_indexed"] == 4


@pytest.mark.asyncio
async def test_sections_capped_at_max(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """25-section document with EMBED_MAX_SECTIONS=20 → only 20 sections are embedded."""
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTIONS="20")
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")

    content = _make_sections_content(25)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert embed_spy.call_count == 20
    assert result["sections_indexed"] == 20


@pytest.mark.asyncio
async def test_sections_under_cap_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """10-section document with EMBED_MAX_SECTIONS=20 → all 10 sections are embedded (no cap)."""
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTIONS="20")
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")

    content = _make_sections_content(10)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert embed_spy.call_count == 10
    assert result["sections_indexed"] == 10


@pytest.mark.asyncio
async def test_length_filter_then_cap(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Filter applied first, then cap: 30 sections (5 short) → 25 pass filter, capped at 20."""
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="50", EMBED_MAX_SECTIONS="20")
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")

    # 25 long sections (120 chars) + 5 short sections (10 chars)
    content = _make_mixed_sections_content(long_count=25, short_count=5)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    # 25 long pass filter; capped at 20
    assert embed_spy.call_count == 20
    assert result["sections_indexed"] == 20


@pytest.mark.asyncio
async def test_all_filtered_then_capped_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """All sections filtered by a very large min-length → document-level fallback (1 embed)."""
    # Set min-length so large that all section bodies are below threshold
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="10000")
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")

    content = _make_sections_content(5, body_length=50)  # 50 chars each — far below 10000
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    # All filtered → document-level fallback: one embed, one vector
    assert embed_spy.call_count == 1
    assert result["sections_indexed"] == 1


# ---------------------------------------------------------------------------
# Z1 — P4 Section body truncation before embed (EMBED_MAX_SECTION_LENGTH)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_body_truncated_before_embed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Section body > embed_max_section_length → bedrock.embed receives truncated body.

    The embed text must not contain the full 200-char body; only the first 100 chars
    of the body should appear in the embedding input.
    """
    # Red: EMBED_MAX_SECTION_LENGTH is not a Settings field yet; write.py never truncates.
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="100")
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")

    body = "a" * 200
    content = f"## Truncation Test\n\n{body}"
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    embed_texts = [call.args[0] for call in embed_spy.call_args_list]
    assert len(embed_texts) >= 1
    # With EMBED_MAX_SECTION_LENGTH=100, no embed call should contain 101+ consecutive 'a's
    assert all("a" * 101 not in text for text in embed_texts), (
        "bedrock.embed received the full untruncated body — truncation not implemented"
    )


@pytest.mark.asyncio
async def test_section_full_body_stored_in_s3_despite_embed_truncation(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """S3 stores the full untruncated body even when EMBED_MAX_SECTION_LENGTH is set.

    The truncation is embedding-input-only; the stored content is always the original.
    """
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="100")
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")

    body = "a" * 200
    content = f"## Truncation Test\n\n{body}"
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    # S3 must store the full untruncated content
    stored = s3_client.get_object(result["artifact_id"])
    assert body in stored, "S3 must contain the full untruncated body"

    # Embed must have received the truncated body (not the full 200 chars)
    embed_texts = [call.args[0] for call in embed_spy.call_args_list]
    assert all("a" * 101 not in text for text in embed_texts), (
        "bedrock.embed received the full untruncated body — truncation not implemented"
    )


@pytest.mark.asyncio
async def test_sections_under_max_length_are_all_embedded(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Sections whose bodies are below EMBED_MAX_SECTION_LENGTH are embedded unchanged.

    This is the normal-path case: every section should appear in sections_indexed
    and bedrock.embed must receive the full (untruncated) body for each section.
    """
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="200")
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")

    body_a = "a" * 50  # well under the 200-char limit
    body_b = "b" * 75  # well under the 200-char limit
    content = f"## Section A\n\n{body_a}\n\n## Section B\n\n{body_b}"
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    # Both sections must be indexed — document-level fallback must NOT fire
    assert result["sections_indexed"] == 2, (
        f"Expected 2 sections indexed, got {result['sections_indexed']}. "
        "Sections under embed_max_section_length may have been silently dropped."
    )

    # Each embed call must carry the full (untruncated) body
    embed_texts = [call.args[0] for call in embed_spy.call_args_list]
    assert any(body_a in text for text in embed_texts), (
        "Full body_a not found in any bedrock.embed call — section was dropped or truncated"
    )
    assert any(body_b in text for text in embed_texts), (
        "Full body_b not found in any bedrock.embed call — section was dropped or truncated"
    )


@pytest.mark.asyncio
async def test_embed_max_section_length_zero_disables_truncation(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """EMBED_MAX_SECTION_LENGTH=0 → section bodies passed to embed unmodified.

    Zero is the special sentinel that disables the truncation guard entirely.
    """
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="0")
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")

    body = "b" * 500
    content = f"## Big Section\n\n{body}"
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    # Red: Settings doesn't have embed_max_section_length yet — attribute access fails
    assert getattr(settings, "embed_max_section_length", "NOT_SET") == 0, (
        "Settings.embed_max_section_length not yet implemented"
    )
    embed_texts = [call.args[0] for call in embed_spy.call_args_list]
    # With limit=0, the full 500-char body must appear in at least one embed call
    assert any("b" * 500 in text for text in embed_texts), (
        "Full body should be passed unchanged when embed_max_section_length=0"
    )


@pytest.mark.asyncio
async def test_section_truncation_logged_at_debug(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When a section body is truncated, the event is logged at DEBUG level."""
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="50")
    bedrock = FakeBedrockClient(dimension=1024)

    body = "c" * 200  # body exceeds the 50-char limit
    content = f"## Long Section\n\n{body}"
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    with caplog.at_level(logging.DEBUG, logger="cairn_mcp.tools.write"):
        await write_artifact(
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock,
            settings=settings,
            **kwargs,
        )

    # Red: write.py does not log truncation yet
    truncation_logs = [r for r in caplog.records if "truncat" in r.message.lower()]
    assert len(truncation_logs) >= 1, (
        "Expected at least one DEBUG log message mentioning 'truncat' — not yet implemented"
    )


# ---------------------------------------------------------------------------
# T36 — last_edited_ulid and commit_refs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_response_includes_last_edited_ulid(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """write_artifact response includes 'last_edited_ulid' as a non-empty string."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "last_edited_ulid" in result
    assert isinstance(result["last_edited_ulid"], str)
    assert len(result["last_edited_ulid"]) > 0


@pytest.mark.asyncio
async def test_write_successive_ulids_are_monotonic(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Two successive write_artifact calls produce monotonically ordered ULIDs."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result1 = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "title": "First artifact"},
    )
    result2 = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "title": "Second artifact"},
    )

    assert result1["last_edited_ulid"] <= result2["last_edited_ulid"]


@pytest.mark.asyncio
async def test_write_last_edited_ulid_in_s3_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """S3 put_object is called with 'last_edited_ulid' in the metadata dict."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    spy = mocker.spy(s3_client, "put_object")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    _, _, metadata = spy.call_args.args
    assert "last_edited_ulid" in metadata
    assert isinstance(metadata["last_edited_ulid"], str)
    assert len(metadata["last_edited_ulid"]) > 0


@pytest.mark.asyncio
async def test_write_last_edited_ulid_in_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """put_vectors_batch is called with 'last_edited_ulid' in each vector's metadata."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    spy = mocker.spy(vectors_client, "put_vectors_batch")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    items = spy.call_args.args[0]
    for item in items:
        assert "last_edited_ulid" in item["metadata"]
        assert isinstance(item["metadata"]["last_edited_ulid"], str)


@pytest.mark.asyncio
async def test_write_commit_refs_stored_in_s3_and_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """commit_refs=['abc1234'] stored as comma-joined string in S3 and list[str] in vectors."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    s3_spy = mocker.spy(s3_client, "put_object")
    vec_spy = mocker.spy(vectors_client, "put_vectors_batch")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "commit_refs": ["abc1234"]},
    )

    _, _, s3_meta = s3_spy.call_args.args
    assert s3_meta["commit_refs"] == "abc1234"

    vec_items = vec_spy.call_args.args[0]
    for item in vec_items:
        assert item["metadata"]["commit_refs"] == ["abc1234"]


@pytest.mark.asyncio
async def test_write_empty_commit_refs_stored_as_empty_string_in_s3(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """commit_refs=[] stored as '' in S3 metadata and omitted from vector metadata."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    s3_spy = mocker.spy(s3_client, "put_object")
    vec_spy = mocker.spy(vectors_client, "put_vectors_batch")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    _, _, s3_meta = s3_spy.call_args.args
    assert s3_meta["commit_refs"] == ""

    vec_items = vec_spy.call_args.args[0]
    for item in vec_items:
        assert "commit_refs" not in item["metadata"]


# ---------------------------------------------------------------------------
# file_extension parameter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_extension_txt_produces_key_ending_in_txt(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """file_extension='.txt' → returned artifact_id ends with '.txt'."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        file_extension=".txt",
        **_BASE_WRITE_KWARGS,
    )

    assert "error" not in result
    assert result["artifact_id"].endswith(".txt")


@pytest.mark.asyncio
async def test_file_extension_without_dot_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """file_extension without leading dot → validation_error; no AWS calls made."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        file_extension="nodot",
        **_BASE_WRITE_KWARGS,
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3_client.list_objects("")) == 0


@pytest.mark.asyncio
async def test_default_file_extension_is_md(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Default file_extension → returned artifact_id ends with '.md'."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "error" not in result
    assert result["artifact_id"].endswith(".md")


# ---------------------------------------------------------------------------
# M11 — dedicated embed executor
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# M12 — partial_write message includes failure log path (T15 AC)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_write_embed_message_includes_failure_log_path(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """partial_write on embed failure → message includes the failure log path (T15 AC).

    A caller receiving partial_write must be able to locate the failure log entry
    without searching — the path is embedded in the error message.
    """
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = _FailOnSecondEmbedBedrock(dimension=1024)

    content = _make_sections_content(3)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "partial_write"
    assert str(log_path) in result["message"]


@pytest.mark.asyncio
async def test_partial_write_put_vector_message_includes_failure_log_path(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """partial_write on put_vectors_batch failure → message includes the failure log path."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(
        vectors_client,
        "put_vectors_batch",
        side_effect=RuntimeError("simulated put failure"),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "partial_write"
    assert str(log_path) in result["message"]


def test_embed_executor_has_adequate_max_workers() -> None:
    """_EMBED_EXECUTOR must be sized for the maximum compound concurrency.

    Peak demand = artifact_concurrency_max (15) × SECTION_CONCURRENCY default (5).
    The dedicated pool must not be smaller than that product so that SECTION_CONCURRENCY
    semaphore slots across all concurrent artifact writes can all run simultaneously.
    """
    import cairn_mcp.tools.write as write_module
    from cairn_mcp.tools.write_artifacts import _ARTIFACT_CONCURRENCY_MAX

    expected_min = _ARTIFACT_CONCURRENCY_MAX * 5  # 5 = SECTION_CONCURRENCY default
    assert write_module._EMBED_EXECUTOR._max_workers >= expected_min


@pytest.mark.asyncio
async def test_embed_uses_dedicated_executor(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Section embed calls must go through _EMBED_EXECUTOR, not the default asyncio executor.

    Verifies that run_in_executor(_EMBED_EXECUTOR, ...) is used rather than to_thread(),
    so compound concurrency (artifact_concurrency × section_concurrency) is bounded by the
    dedicated pool and not by asyncio's default executor.
    """
    import cairn_mcp.tools.write as write_module

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    submit_spy = mocker.spy(write_module._EMBED_EXECUTOR, "submit")

    content = _make_sections_content(3)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    # 3 sections → 3 run_in_executor calls → 3 submit() calls on _EMBED_EXECUTOR
    assert submit_spy.call_count == 3


@pytest.mark.asyncio
async def test_doc_fallback_embed_uses_dedicated_executor(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Document-fallback embed (no sections) must also use _EMBED_EXECUTOR."""
    import cairn_mcp.tools.write as write_module

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    submit_spy = mocker.spy(write_module._EMBED_EXECUTOR, "submit")

    # No H2 headings → falls through to document-level embedding
    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert "error" not in result
    # 1 document-level embed → exactly 1 submit call
    assert submit_spy.call_count == 1
