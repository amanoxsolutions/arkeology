"""Unit tests for cairn_mcp.tools.synthesise.

Tests synthesise_artifacts() using all three fakes: FakeS3, FakeVectors, FakeBedrock.
"""

import math
from typing import Any

import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.fakes.fake_s3 import FakeS3Client
from cairn_mcp.clients.fakes.fake_vectors import FakeVectorsClient
from cairn_mcp.config import Settings
from cairn_mcp.tools.synthesise import synthesise_artifacts

# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-bucket")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")
    monkeypatch.setenv("WRITE_PREFIX", "artifacts")
    monkeypatch.setenv("READ_PREFIXES", "other-team")
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    return Settings()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _unit_vec(seed: float, dim: int = 8) -> list[float]:
    raw = [seed + i * 0.1 for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


_BASE_S3_META: dict[str, str] = {
    "type": "code_review",
    "team": "platform",
    "project": "cairn",
    "tier": "2",
    "date": "2026-05-30",
    "status": "active",
    "title": "Fix auth bug",
    "visibility": "shared",
    "feature_tags": "auth",
    "author_role": "developer",
    "description": "Review of the auth module.",
}

_BASE_VECTOR_META: dict[str, Any] = {
    "scope": "artifacts",
    "type": "code_review",
    "team": "platform",
    "project": "cairn",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "title": "Fix auth bug",
    "visibility": "shared",
    "feature_tags": ["auth"],
    "author_role": "developer",
    "description": "Review of the auth module.",
}

_CONTENT = "## Summary\n\nAll looks good."


def _seed_all(s3: FakeS3Client, vectors: FakeVectorsClient) -> None:
    """Seed S3 + vectors with representative artifacts for synthesise tests."""
    # own-scope tier 2 active
    s3.put_object("artifacts/t2-review", _CONTENT + " (T2)", {**_BASE_S3_META})
    vectors.put_vector(
        "artifacts/t2-review#summary",
        _unit_vec(1.0),
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-review"},
    )

    # own-scope tier 3 shared
    s3.put_object(
        "artifacts/t3-shared-adr",
        _CONTENT + " (T3S)",
        {**_BASE_S3_META, "tier": "3", "type": "adr", "feature_tags": "adr"},
    )
    vectors.put_vector(
        "artifacts/t3-shared-adr#summary",
        _unit_vec(0.9),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/t3-shared-adr",
            "tier": 3,
            "type": "adr",
            "visibility": "shared",
        },
    )

    # foreign-scope tier 2 — should be EXCLUDED
    s3.put_object(
        "other-team/t2-foreign",
        _CONTENT + " (foreign T2)",
        {**_BASE_S3_META, "team": "network"},
    )
    vectors.put_vector(
        "other-team/t2-foreign#summary",
        _unit_vec(0.8),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t2-foreign",
            "scope": "other-team",
            "team": "network",
            "tier": 2,
        },
    )

    # foreign-scope tier 3 shared — should be INCLUDED
    s3.put_object(
        "other-team/t3-shared-foreign",
        _CONTENT + " (foreign T3S)",
        {**_BASE_S3_META, "tier": "3", "visibility": "shared", "team": "network"},
    )
    vectors.put_vector(
        "other-team/t3-shared-foreign#summary",
        _unit_vec(0.7),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-shared-foreign",
            "scope": "other-team",
            "team": "network",
            "tier": 3,
            "visibility": "shared",
        },
    )

    # foreign-scope tier 3 confidential — should be EXCLUDED
    s3.put_object(
        "other-team/t3-confidential-foreign",
        _CONTENT + " (foreign T3C)",
        {**_BASE_S3_META, "tier": "3", "visibility": "confidential", "team": "network"},
    )
    vectors.put_vector(
        "other-team/t3-confidential-foreign#summary",
        _unit_vec(0.6),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-confidential-foreign",
            "scope": "other-team",
            "team": "network",
            "tier": 3,
            "visibility": "confidential",
        },
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_synthesise_returns_results_with_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Query with no filters → results contain full content."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=10
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert "content" in artifact
        assert artifact["content"] is not None


async def test_synthesise_result_has_all_required_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each result dict contains all required fields including content."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=10
    )

    required = [
        "artifact_id", "content", "type", "team", "project", "tier", "date",
        "status", "title", "visibility", "feature_tags", "author_role", "description",
    ]
    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        for field in required:
            assert field in artifact, f"Missing field '{field}' in result: {artifact}"


async def test_synthesise_feature_tags_is_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """feature_tags in results is a list, not a comma-separated string."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=10
    )

    for artifact in result["artifacts"]:
        assert isinstance(artifact["feature_tags"], list)


async def test_synthesise_content_matches_s3_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """content in results matches what was written to fake S3."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=10
    )

    for artifact in result["artifacts"]:
        expected_content = s3.get_object(artifact["artifact_id"])
        assert artifact["content"] == expected_content


# ---------------------------------------------------------------------------
# top_k
# ---------------------------------------------------------------------------


async def test_synthesise_top_k_limits_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """top_k=2 → at most 2 results."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=2
    )

    assert len(result["artifacts"]) <= 2


async def test_synthesise_top_k_default_is_10(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """top_k absent → at most 10 results."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review"
    )

    assert len(result["artifacts"]) <= 10


async def test_synthesise_top_k_above_ceiling_clamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """top_k=150 → clamped to 100; no error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=150
    )

    assert len(result["artifacts"]) <= 100
    assert isinstance(result["artifacts"], list)


# ---------------------------------------------------------------------------
# Cross-scope gate
# ---------------------------------------------------------------------------


async def test_synthesise_foreign_tier2_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope tier 2 artifact excluded from results."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=20
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t2-foreign" not in ids


async def test_synthesise_foreign_tier3_shared_included(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope tier 3 shared artifact included with full content."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=20
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-shared-foreign" in ids
    foreign = next(
        a for a in result["artifacts"] if a["artifact_id"] == "other-team/t3-shared-foreign"
    )
    assert "content" in foreign


async def test_synthesise_foreign_tier3_confidential_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope tier 3 confidential artifact excluded from results."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=20
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-confidential-foreign" not in ids


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


async def test_synthesise_s3_read_failure_skips_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 get_object raises KeyError for one artifact → that artifact skipped; others returned."""
    settings = _make_settings(monkeypatch)

    class FailFirstRead(FakeS3Client):
        def __init__(self) -> None:
            super().__init__()
            self._call_count = 0

        def get_object(self, key: str) -> str:
            self._call_count += 1
            if self._call_count == 1:
                raise KeyError(key)
            return super().get_object(key)

    s3 = FailFirstRead()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    # Must not raise; should return remaining results
    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=10
    )

    assert isinstance(result["artifacts"], list)


async def test_synthesise_empty_search_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search returns no results → empty list, no error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    # Do not seed any vectors

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="anything", top_k=5
    )

    assert result["artifacts"] == []


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_synthesise_embed_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embed call raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    bedrock.set_credential_failure(True)
    _seed_all(s3, vectors)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=5
    )

    assert "error" in result or result.get("error_type") is not None


async def test_synthesise_query_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """query_vectors raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)
    vectors.set_credential_failure(True)

    result = await synthesise_artifacts(
        settings=settings, s3=s3, vectors=vectors, bedrock=bedrock, query="review", top_k=5
    )

    assert "error" in result or result.get("error_type") is not None


async def test_synthesise_get_object_credential_error_is_hard_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_object raises CredentialError (not KeyError) → structured error (hard failure)."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_all(s3, vectors)

    class CredFailGetObject(FakeS3Client):
        def get_object(self, key: str) -> str:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(message="Simulated.", service="s3", original=Exception("sim"))

    s3_fail = CredFailGetObject()
    # Copy seeded objects into the failing client
    s3_fail._objects = s3._objects.copy()

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_fail,
        vectors=vectors,
        bedrock=bedrock,
        query="review",
        top_k=5,
    )

    assert "error" in result or result.get("error_type") is not None
