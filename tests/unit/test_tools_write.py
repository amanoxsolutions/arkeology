"""Unit tests for cairn_mcp.tools.write.

Tests write_artifact() and its embedding helper functions using in-memory fakes.
"""

import asyncio
import json

import botocore.exceptions
import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.fakes.fake_s3 import FakeS3Client
from cairn_mcp.clients.fakes.fake_vectors import FakeVectorsClient
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools.write import (
    _build_document_embedding_text,
    _build_section_embedding_text,
    write_artifact,
)

# ---------------------------------------------------------------------------
# Settings fixture helpers
# ---------------------------------------------------------------------------


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    """Build a Settings object with required env vars set, plus any overrides."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-bucket")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")
    monkeypatch.setenv("WRITE_PREFIX", "artifacts")
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    return Settings()


def _make_fakes(dimension: int = 1024) -> tuple[FakeS3Client, FakeVectorsClient, FakeBedrockClient]:
    return (
        FakeS3Client(),
        FakeVectorsClient(dimension=dimension),
        FakeBedrockClient(dimension=dimension),
    )


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
        feature_tags=[],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert text.startswith("Title: Fix auth bug")


def test_section_embed_contains_type() -> None:
    """_build_section_embedding_text output contains 'Type: {type}'."""
    text = _build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        feature_tags=[],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert "Type: code_review" in text


def test_section_embed_contains_tags_when_present() -> None:
    """_build_section_embedding_text output contains tags when feature_tags non-empty."""
    text = _build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        feature_tags=["auth", "security"],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert "Tags:" in text
    assert "auth" in text
    assert "security" in text


def test_section_embed_omits_tags_when_empty() -> None:
    """_build_section_embedding_text omits the Tags line when feature_tags is empty."""
    text = _build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        feature_tags=[],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert "Tags:" not in text


def test_section_embed_contains_heading_and_body() -> None:
    """_build_section_embedding_text contains the section heading and body."""
    text = _build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        feature_tags=[],
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
        feature_tags=[],
        description="Review of the auth module.",
    )
    assert text.startswith("Title: Fix auth bug")


def test_document_embed_contains_type() -> None:
    """_build_document_embedding_text output contains 'Type: {type}'."""
    text = _build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        feature_tags=[],
        description="Review of the auth module.",
    )
    assert "Type: code_review" in text


def test_document_embed_contains_description() -> None:
    """_build_document_embedding_text output contains 'Description: {description}'."""
    text = _build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        feature_tags=[],
        description="Review of the auth module.",
    )
    assert "Description: Review of the auth module." in text


def test_document_embed_omits_tags_when_empty() -> None:
    """_build_document_embedding_text omits the Tags line when feature_tags is empty."""
    text = _build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        feature_tags=[],
        description="A description.",
    )
    assert "Tags:" not in text


def test_document_embed_contains_tags_when_present() -> None:
    """_build_document_embedding_text contains tags when feature_tags non-empty."""
    text = _build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        feature_tags=["payments"],
        description="A description.",
    )
    assert "Tags:" in text
    assert "payments" in text


# ---------------------------------------------------------------------------
# write_artifact — happy path
# ---------------------------------------------------------------------------


async def test_three_section_content_indexes_three_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three-section content → sections_indexed == 3 and 3 vectors in fake index."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )

    assert result["sections_indexed"] == 3
    artifact_id = result["artifact_id"]
    matching_keys = [
        k for k in vectors._vectors if artifact_id.split("/")[-1] in k or artifact_id in k
    ]
    assert len(matching_keys) == 3


async def test_no_section_content_indexes_one_document_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-section content → sections_indexed == 1 (document-level fallback)."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_ONE_SECTION_KWARGS
    )

    assert result["sections_indexed"] == 1


async def test_s3_contains_content_at_correct_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After write_artifact, S3 contains the content at the returned artifact_id key."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )

    artifact_id = result["artifact_id"]
    stored_content = s3.get_object(artifact_id)
    assert stored_content == _BASE_WRITE_KWARGS["content"]


async def test_returned_artifact_id_is_full_s3_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returned artifact_id is the full S3 key including write_prefix."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )

    artifact_id = result["artifact_id"]
    assert artifact_id.startswith(settings.write_prefix + "/")


async def test_section_vector_keys_contain_hash_separator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vector keys for sections have format {s3_key}#{section_slug}."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )

    artifact_id = result["artifact_id"]
    section_keys = [k for k in vectors._vectors if k.startswith(artifact_id + "#")]
    assert len(section_keys) == 3
    for key in section_keys:
        assert "#" in key


async def test_document_fallback_vector_key_has_no_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Document-level fallback vector key equals {s3_key} (no # suffix)."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_ONE_SECTION_KWARGS
    )

    artifact_id = result["artifact_id"]
    # The fallback key is exactly artifact_id (no # separator)
    assert artifact_id in vectors._vectors
    assert not any(k.startswith(artifact_id + "#") for k in vectors._vectors)


async def test_vector_metadata_includes_artifact_id_and_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each vector's metadata includes artifact_id (full S3 key) and scope (write_prefix)."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )

    artifact_id = result["artifact_id"]
    for _key, (_vec, meta) in vectors._vectors.items():
        assert meta["artifact_id"] == artifact_id
        assert meta["scope"] == settings.write_prefix


async def test_response_has_artifact_id_and_sections_indexed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Response dict has keys 'artifact_id' and 'sections_indexed'."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )

    assert "artifact_id" in result
    assert "sections_indexed" in result


# ---------------------------------------------------------------------------
# Tier 2 idempotency
# ---------------------------------------------------------------------------


async def test_tier2_write_twice_same_date_one_s3_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write same tier 2 artifact twice (same date) → exactly 1 S3 object."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )
    await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )

    assert len(s3._objects) == 1


async def test_tier2_write_twice_same_date_vector_count_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write same tier 2 artifact twice (same date) → vector count is unchanged (upsert)."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    result1 = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )
    count_after_first = len(vectors._vectors)
    result2 = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )

    assert result1["artifact_id"] == result2["artifact_id"]
    assert len(vectors._vectors) == count_after_first


async def test_tier2_different_dates_produce_distinct_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write same tier 2 artifact on two different dates → 2 distinct S3 keys."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    kwargs_day1 = {**_BASE_WRITE_KWARGS, "date": "2026-05-30"}
    kwargs_day2 = {**_BASE_WRITE_KWARGS, "date": "2026-05-31"}

    result1 = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs_day1
    )
    result2 = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs_day2
    )

    assert result1["artifact_id"] != result2["artifact_id"]
    assert len(s3._objects) == 2


# ---------------------------------------------------------------------------
# Tier 3 re-write (orphan cleanup)
# ---------------------------------------------------------------------------


async def test_tier3_rewrite_fewer_sections_cleans_orphans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 3: first write 3 sections, re-write 2 → orphan section C key is absent."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    three_section_content = (
        "## Alpha\n\nBody A.\n\n## Beta\n\nBody B.\n\n## Gamma\n\nBody C."
    )
    two_section_content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B."

    kwargs_3 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": three_section_content}
    kwargs_2 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": two_section_content}

    result1 = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs_3
    )
    artifact_id = result1["artifact_id"]

    # Confirm 3 vectors before re-write
    keys_before = [k for k in vectors._vectors if k.startswith(artifact_id)]
    assert len(keys_before) == 3

    await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs_2
    )

    keys_after = [k for k in vectors._vectors if k.startswith(artifact_id)]
    assert len(keys_after) == 2
    # Gamma key should be gone
    gamma_keys = [k for k in keys_after if "gamma" in k]
    assert len(gamma_keys) == 0


async def test_tier3_rewrite_more_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 3: first write 1 section, re-write 3 → 3 vectors after re-write."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    three_section_content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B.\n\n## Gamma\n\nBody C."
    kwargs_1 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": "## Alpha\n\nBody A."}
    kwargs_3 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": three_section_content}

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs_1
    )
    artifact_id = result["artifact_id"]

    await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs_3
    )

    keys_after = [k for k in vectors._vectors if k.startswith(artifact_id)]
    assert len(keys_after) == 3


async def test_tier3_rewrite_identical_sections_count_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 3: re-write with identical sections → vector count unchanged."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B."
    kwargs = {**_BASE_WRITE_KWARGS, "tier": 3, "content": content}

    await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
    )
    count_after_first = len(vectors._vectors)

    await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
    )
    assert len(vectors._vectors) == count_after_first


# ---------------------------------------------------------------------------
# Tier 3 key stability
# ---------------------------------------------------------------------------


async def test_tier3_different_dates_same_artifact_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 3: writes with different dates, same type+title → same artifact_id."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    kwargs_day1 = {**_BASE_WRITE_KWARGS, "tier": 3, "date": "2026-05-30"}
    kwargs_day2 = {**_BASE_WRITE_KWARGS, "tier": 3, "date": "2026-06-15"}

    result1 = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs_day1
    )
    result2 = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs_day2
    )

    assert result1["artifact_id"] == result2["artifact_id"]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


async def test_validation_description_too_long_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """description > 280 chars → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    kwargs = {**_BASE_WRITE_KWARGS, "description": "x" * 281}
    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3._objects) == 0


async def test_validation_invalid_type_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid type → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    kwargs = {**_BASE_WRITE_KWARGS, "type": "invalid_type"}
    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3._objects) == 0


async def test_validation_invalid_tier_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid tier → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    kwargs = {**_BASE_WRITE_KWARGS, "tier": 1}
    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3._objects) == 0


async def test_validation_invalid_visibility_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid visibility → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    kwargs = {**_BASE_WRITE_KWARGS, "visibility": "public"}
    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3._objects) == 0


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_s3_credential_failure_returns_error_bedrock_not_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 credential failure → error in response; bedrock.embed NOT called."""
    settings = _make_settings(monkeypatch)

    call_log: list[str] = []

    class TrackingBedrockClient(FakeBedrockClient):
        def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
            call_log.append("embed")
            return super().embed(text, model_id, dimensions)

    s3, vectors = FakeS3Client(), FakeVectorsClient()
    bedrock = TrackingBedrockClient()
    s3.set_credential_failure(True)

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )

    assert "error" in result or result.get("success") is False
    assert len(call_log) == 0


async def test_bedrock_credential_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bedrock credential failure → error in response (S3 may already have been written)."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()
    bedrock.set_credential_failure(True)

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_BASE_WRITE_KWARGS
    )

    assert "error" in result or result.get("success") is False


# ---------------------------------------------------------------------------
# T1: vector metadata stores feature_tags as list
# ---------------------------------------------------------------------------


async def test_vector_metadata_feature_tags_is_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After successful write, feature_tags in vector metadata is a list (not a string)."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    kwargs = {**_BASE_WRITE_KWARGS, "feature_tags": ["auth", "security"]}
    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
    )

    s3_key = result["artifact_id"]
    vec_results = vectors.get_vectors([k for k in vectors._vectors if k.startswith(s3_key)])
    assert len(vec_results) > 0
    for entry in vec_results:
        assert isinstance(entry["metadata"]["feature_tags"], list), (
            f"Expected list, got {type(entry['metadata']['feature_tags'])}"
        )


# ---------------------------------------------------------------------------
# T2: S3 metadata stores feature_tags and source_artifacts as comma-joined strings
# ---------------------------------------------------------------------------


async def test_s3_metadata_feature_tags_and_source_artifacts_are_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After successful write, S3 metadata stores feature_tags and source_artifacts
    as comma-joined strings (not lists), per S3 metadata constraints."""
    settings = _make_settings(monkeypatch)
    s3, vectors, bedrock = _make_fakes()

    kwargs = {
        **_BASE_WRITE_KWARGS,
        "feature_tags": ["auth", "security"],
        "source_artifacts": ["adr-one", "adr-two"],
    }
    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **kwargs
    )

    s3_key = result["artifact_id"]
    meta = s3.head_object(s3_key)
    assert isinstance(meta["feature_tags"], str), (
        f"Expected str in S3 metadata, got {type(meta['feature_tags'])}"
    )
    assert meta["feature_tags"] == "auth,security"
    assert isinstance(meta["source_artifacts"], str), (
        f"Expected str in S3 metadata, got {type(meta['source_artifacts'])}"
    )
    assert meta["source_artifacts"] == "adr-one,adr-two"


# ---------------------------------------------------------------------------
# T15: Throttle retry and partial write failure log
# ---------------------------------------------------------------------------

# ── Helpers ─────────────────────────────────────────────────────────────────


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


class _PutVectorFailVectors(FakeVectorsClient):
    """Raises RuntimeError from every put_vector call."""

    def put_vector(self, key: str, vector: list[float], metadata: dict) -> None:
        raise RuntimeError("simulated put_vector failure")


class _PutVectorCredentialFailVectors(FakeVectorsClient):
    """Raises CredentialError from every put_vector call."""

    def put_vector(self, key: str, vector: list[float], metadata: dict) -> None:
        raise CredentialError(
            message="AWS credentials are invalid or expired (simulated).",
            service="s3vectors",
            original=Exception("simulated credential failure"),
        )


async def _instant_sleep(_seconds: float) -> None:
    """Drop-in replacement for asyncio.sleep that returns immediately."""


# ── Tests ────────────────────────────────────────────────────────────────────


async def test_throttle_retry_success_returns_success_no_failure_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Throttle on first embed, succeed on retry → success response; no failure log entry."""
    log_path = tmp_path / "failures.jsonl"
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    s3, vectors = FakeS3Client(), FakeVectorsClient()
    bedrock = _ThrottleThenSucceedBedrock()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_ONE_SECTION_KWARGS
    )

    assert "error" not in result
    assert "artifact_id" in result
    assert not log_path.exists()


async def test_throttle_retry_both_fail_returns_partial_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Throttle on both embed calls → partial_write error; artifact_id in response."""
    log_path = tmp_path / "failures.jsonl"
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    s3, vectors = FakeS3Client(), FakeVectorsClient()
    bedrock = _ThrottleAlwaysBedrock()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_ONE_SECTION_KWARGS
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result


async def test_throttle_retry_both_fail_writes_failure_log_bedrock_embed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Throttle on both embed calls → failure log entry with failure_step='bedrock_embed'."""
    log_path = tmp_path / "failures.jsonl"
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    s3, vectors = FakeS3Client(), FakeVectorsClient()
    bedrock = _ThrottleAlwaysBedrock()

    await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_ONE_SECTION_KWARGS
    )

    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "bedrock_embed"


async def test_non_throttle_error_returns_partial_write_no_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Non-throttle ClientError → no retry; partial_write error; failure log written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    s3, vectors = FakeS3Client(), FakeVectorsClient()
    bedrock = _NonThrottleErrorBedrock()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_ONE_SECTION_KWARGS
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "bedrock_embed"


async def test_put_vector_failure_returns_partial_write_with_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """S3 write succeeds, put_vector raises → partial_write error; failure log written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    s3 = FakeS3Client()
    vectors = _PutVectorFailVectors()
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_ONE_SECTION_KWARGS
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "put_vector"


async def test_failure_log_entry_contains_all_required_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Failure log entry contains all required fields with correct types."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    s3 = FakeS3Client()
    vectors = _PutVectorFailVectors()
    bedrock = FakeBedrockClient()

    await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_ONE_SECTION_KWARGS
    )

    entry = json.loads(log_path.read_text().splitlines()[0])
    required_fields = (
        "artifact_id", "title", "type", "tier", "date", "failure_step", "reason", "timestamp"
    )
    for field in required_fields:
        assert field in entry, f"Missing field: {field}"
    assert entry["title"] == _ONE_SECTION_KWARGS["title"]
    assert entry["type"] == _ONE_SECTION_KWARGS["type"]
    assert entry["tier"] == _ONE_SECTION_KWARGS["tier"]
    assert entry["date"] == _ONE_SECTION_KWARGS["date"]
    # timestamp must be a valid ISO-8601 string
    from datetime import datetime
    datetime.fromisoformat(entry["timestamp"])


async def test_failure_log_appends_across_multiple_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Two separate partial write failures → failure log has two entries (append behaviour)."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))

    for _ in range(2):
        s3 = FakeS3Client()
        vectors = _PutVectorFailVectors()
        bedrock = FakeBedrockClient()
        await write_artifact(
            s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_ONE_SECTION_KWARGS
        )

    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        entry = json.loads(line)
        assert entry["failure_step"] == "put_vector"


async def test_bedrock_credential_error_no_failure_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Bedrock CredentialError → credential_error response; no failure log entry written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    s3, vectors = FakeS3Client(), FakeVectorsClient()
    bedrock = FakeBedrockClient()
    bedrock.set_credential_failure(True)

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_ONE_SECTION_KWARGS
    )

    assert result.get("error") == "credential_error"
    assert not log_path.exists()


async def test_put_vector_credential_error_no_failure_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """put_vector CredentialError → credential_error response; no failure log entry written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    s3 = FakeS3Client()
    vectors = _PutVectorCredentialFailVectors()
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3, vectors=vectors, bedrock=bedrock, settings=settings, **_ONE_SECTION_KWARGS
    )

    assert result.get("error") == "credential_error"
    assert not log_path.exists()
