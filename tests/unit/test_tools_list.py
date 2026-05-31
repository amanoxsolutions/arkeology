"""Unit tests for cairn_mcp.tools.list.

Tests list_artifacts() using FakeVectorsClient only — no S3 or Bedrock calls.
"""

import math
from typing import Any

import pytest

from cairn_mcp.clients.fakes.fake_vectors import FakeVectorsClient
from cairn_mcp.config import Settings
from cairn_mcp.tools.list import list_artifacts

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
# Fake vector helpers
# ---------------------------------------------------------------------------


def _unit_vec(seed: float, dim: int = 8) -> list[float]:
    raw = [seed + i * 0.1 for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


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


def _seed_vectors(vectors: FakeVectorsClient) -> None:
    """Seed a rich set of vectors for list tests."""
    # own-scope active tier 2 (two section vectors — dedup test)
    for section in ["#summary", "#details"]:
        vectors.put_vector(
            f"artifacts/t2-active-review{section}",
            _unit_vec(1.0),
            {
                **_BASE_VECTOR_META,
                "artifact_id": "artifacts/t2-active-review",
                "tier": 2,
                "status": "active",
                "type": "code_review",
                "feature_tags": ["auth"],
            },
        )

    # own-scope active tier 3 shared (two section vectors)
    for section in ["#summary", "#details"]:
        vectors.put_vector(
            f"artifacts/t3-shared-adr{section}",
            _unit_vec(0.9),
            {
                **_BASE_VECTOR_META,
                "artifact_id": "artifacts/t3-shared-adr",
                "tier": 3,
                "visibility": "shared",
                "type": "adr",
                "feature_tags": ["payments"],
                "status": "active",
            },
        )

    # own-scope inactive tier 2 (two section vectors)
    for section in ["#summary", "#details"]:
        vectors.put_vector(
            f"artifacts/t2-inactive-review{section}",
            _unit_vec(0.8),
            {
                **_BASE_VECTOR_META,
                "artifact_id": "artifacts/t2-inactive-review",
                "tier": 2,
                "status": "inactive",
                "type": "code_review",
                "feature_tags": [],
            },
        )

    # own-scope active tier 2 code_review tagged "auth"
    vectors.put_vector(
        "artifacts/t2-auth-review#summary",
        _unit_vec(0.7),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/t2-auth-review",
            "tier": 2,
            "status": "active",
            "type": "code_review",
            "feature_tags": ["auth"],
            "team": "platform",
            "project": "infra",
        },
    )

    # foreign-scope active tier 3 shared — ALLOWED
    vectors.put_vector(
        "other-team/t3-foreign-shared-adr#summary",
        _unit_vec(0.6),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-foreign-shared-adr",
            "scope": "other-team",
            "team": "network",
            "tier": 3,
            "visibility": "shared",
            "status": "active",
            "type": "adr",
            "feature_tags": [],
        },
    )
    # second section vector for the foreign t3 shared — dedup test
    vectors.put_vector(
        "other-team/t3-foreign-shared-adr#details",
        _unit_vec(0.61),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-foreign-shared-adr",
            "scope": "other-team",
            "team": "network",
            "tier": 3,
            "visibility": "shared",
            "status": "active",
            "type": "adr",
            "feature_tags": [],
        },
    )

    # foreign-scope active tier 2 — DENIED
    vectors.put_vector(
        "other-team/t2-foreign-review#summary",
        _unit_vec(0.5),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t2-foreign-review",
            "scope": "other-team",
            "team": "network",
            "tier": 2,
            "visibility": "shared",
            "status": "active",
            "type": "code_review",
            "feature_tags": [],
        },
    )

    # foreign-scope active tier 3 hidden — DENIED
    vectors.put_vector(
        "other-team/t3-foreign-hidden-adr#summary",
        _unit_vec(0.4),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-foreign-hidden-adr",
            "scope": "other-team",
            "team": "network",
            "tier": 3,
            "visibility": "hidden",
            "status": "active",
            "type": "adr",
            "feature_tags": [],
        },
    )


# ---------------------------------------------------------------------------
# Default behaviour
# ---------------------------------------------------------------------------


async def test_no_filters_returns_own_scope_and_foreign_tier3_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No filters → own-scope active artifacts and foreign-scope tier 3 shared returned."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(settings=settings, vectors=vectors, s3=None, bedrock=None)

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-active-review" in ids
    assert "artifacts/t3-shared-adr" in ids
    assert "other-team/t3-foreign-shared-adr" in ids


async def test_default_status_active_excludes_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No status filter → status defaults to 'active'; inactive artifacts absent."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(settings=settings, vectors=vectors, s3=None, bedrock=None)

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-inactive-review" not in ids


async def test_status_inactive_override_returns_only_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """status='inactive' → only inactive artifacts returned."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(
        settings=settings, vectors=vectors, s3=None, bedrock=None, status="inactive"
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-inactive-review" in ids
    for artifact_id in ids:
        assert "inactive" in artifact_id or True  # check via status field
    for artifact in result["artifacts"]:
        assert artifact["status"] == "inactive"


# ---------------------------------------------------------------------------
# Filter combinations
# ---------------------------------------------------------------------------


async def test_filter_type_code_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """type='code_review' → only code reviews in results."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(
        settings=settings, vectors=vectors, s3=None, bedrock=None, type="code_review"
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert artifact["type"] == "code_review"


async def test_filter_feature_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """feature_tags=['auth'] → only artifacts with 'auth' tag."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(
        settings=settings, vectors=vectors, s3=None, bedrock=None, feature_tags=["auth"]
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert "auth" in artifact["feature_tags"]


async def test_filter_type_and_feature_tags_intersection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """type='code_review' + feature_tags=['auth'] → intersection of both constraints."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(
        settings=settings,
        vectors=vectors,
        s3=None,
        bedrock=None,
        type="code_review",
        feature_tags=["auth"],
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert artifact["type"] == "code_review"
        assert "auth" in artifact["feature_tags"]


async def test_filter_team(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """team='platform' → only platform team artifacts."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(
        settings=settings, vectors=vectors, s3=None, bedrock=None, team="platform"
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert artifact["team"] == "platform"


async def test_filter_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """project='infra' → only infra project artifacts."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(
        settings=settings, vectors=vectors, s3=None, bedrock=None, project="infra"
    )

    for artifact in result["artifacts"]:
        assert artifact["project"] == "infra"


async def test_filter_tier3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tier=3 → only tier 3 artifacts."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(
        settings=settings, vectors=vectors, s3=None, bedrock=None, tier=3
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert artifact["tier"] == 3


async def test_no_matching_artifacts_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filters that match no artifacts → empty list, no error."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(
        settings=settings, vectors=vectors, s3=None, bedrock=None, type="session_summary"
    )

    assert result["artifacts"] == []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


async def test_deduplication_two_sections_one_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two section vectors for same artifact_id → exactly one record in results."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(settings=settings, vectors=vectors, s3=None, bedrock=None)

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert ids.count("artifacts/t2-active-review") == 1
    assert ids.count("other-team/t3-foreign-shared-adr") == 1


async def test_result_has_required_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each result contains all required metadata fields; no 'content' field."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(settings=settings, vectors=vectors, s3=None, bedrock=None)

    assert len(result["artifacts"]) > 0
    required = [
        "artifact_id", "type", "team", "project", "tier", "date", "status",
        "title", "visibility", "feature_tags", "author_role", "description",
    ]
    for artifact in result["artifacts"]:
        for field in required:
            assert field in artifact, f"Missing field '{field}' in result: {artifact}"
        assert "content" not in artifact, "Unexpected 'content' field in list result"


async def test_feature_tags_in_response_is_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """feature_tags in response is a list, not a comma-separated string."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(settings=settings, vectors=vectors, s3=None, bedrock=None)

    for artifact in result["artifacts"]:
        assert isinstance(artifact["feature_tags"], list), (
            f"Expected list, got {type(artifact['feature_tags'])}"
        )


# ---------------------------------------------------------------------------
# Cross-scope gate
# ---------------------------------------------------------------------------


async def test_foreign_tier3_shared_included(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope tier 3 shared artifact appears in results."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(settings=settings, vectors=vectors, s3=None, bedrock=None)

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-foreign-shared-adr" in ids


async def test_foreign_tier2_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope tier 2 artifact is excluded from results."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(settings=settings, vectors=vectors, s3=None, bedrock=None)

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t2-foreign-review" not in ids


async def test_foreign_tier3_hidden_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope tier 3 hidden artifact is excluded from results."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(settings=settings, vectors=vectors, s3=None, bedrock=None)

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-foreign-hidden-adr" not in ids


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_list_vectors_by_metadata_credential_error_returns_structured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    vectors.set_credential_failure(True)

    result = await list_artifacts(settings=settings, vectors=vectors, s3=None, bedrock=None)

    assert "error" in result or result.get("error_type") is not None


async def test_get_vectors_credential_error_returns_structured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_vectors raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)

    class CredFailOnGetVectors(FakeVectorsClient):
        def get_vectors(self, keys: list[str]) -> list[dict[str, Any]]:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(
                message="Credential failure on get_vectors (simulated).",
                service="s3vectors",
                original=Exception("simulated"),
            )

    vectors = CredFailOnGetVectors(dimension=8)
    _seed_vectors(vectors)

    result = await list_artifacts(settings=settings, vectors=vectors, s3=None, bedrock=None)

    assert "error" in result or result.get("error_type") is not None
