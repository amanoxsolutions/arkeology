"""Unit tests for cairn_mcp.tools.delete.

Tests delete_artifact() using FakeS3Client + FakeVectorsClient.
"""

from typing import Any

import pytest
from cairn_mcp.tools.delete import delete_artifact

from cairn_mcp.clients.fakes.fake_s3 import FakeS3Client
from cairn_mcp.clients.fakes.fake_vectors import FakeVectorsClient
from cairn_mcp.config import Settings

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
    """Seed S3 and vectors with representative objects for delete tests."""
    # own-scope tier 2 active
    s3.put_object("artifacts/t2-active", _CONTENT, {**_BASE_S3_META, "tier": "2"})
    vectors.put_vector(
        "artifacts/t2-active#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-active", "tier": 2},
    )
    vectors.put_vector(
        "artifacts/t2-active#details",
        [0.9, 0.1],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-active", "tier": 2},
    )

    # own-scope tier 3 active
    s3.put_object(
        "artifacts/t3-active",
        _CONTENT,
        {**_BASE_S3_META, "tier": "3", "type": "adr", "visibility": "shared"},
    )
    vectors.put_vector(
        "artifacts/t3-active#summary",
        [0.8, 0.2],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/t3-active",
            "tier": 3,
            "type": "adr",
            "visibility": "shared",
        },
    )

    # foreign-scope active
    s3.put_object(
        "other-team/foreign-active",
        _CONTENT,
        {**_BASE_S3_META, "team": "network"},
    )

    # synthesis referencing t2-active
    s3.put_object(
        "artifacts/synthesis-one",
        _CONTENT,
        {
            **_BASE_S3_META,
            "type": "synthesis",
            "source_artifacts": "artifacts/t2-active",
            "status": "active",
        },
    )
    vectors.put_vector(
        "artifacts/synthesis-one#summary",
        [0.7, 0.3],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/synthesis-one",
            "type": "synthesis",
            "source_artifacts": ["artifacts/t2-active"],
            "status": "active",
        },
    )

    # second synthesis referencing t2-active
    s3.put_object(
        "artifacts/synthesis-two",
        _CONTENT,
        {
            **_BASE_S3_META,
            "type": "synthesis",
            "source_artifacts": "artifacts/t2-active",
            "status": "active",
        },
    )
    vectors.put_vector(
        "artifacts/synthesis-two#summary",
        [0.6, 0.4],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/synthesis-two",
            "type": "synthesis",
            "source_artifacts": ["artifacts/t2-active"],
            "status": "active",
        },
    )


# ---------------------------------------------------------------------------
# Confirmation gate
# ---------------------------------------------------------------------------


async def test_confirm_false_returns_error_no_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """confirm=False → structured error; no AWS writes."""
    settings = _make_settings(monkeypatch)

    delete_calls: list[str] = []

    class TrackingS3(FakeS3Client):
        def delete_object(self, key: str) -> None:
            delete_calls.append(key)
            super().delete_object(key)

    s3 = TrackingS3()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=False,
    )

    assert "error" in result or result.get("error_type") is not None
    assert len(delete_calls) == 0


async def test_confirm_missing_returns_error_no_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """confirm not provided → structured error; no AWS writes."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)
    initial_count = len(s3._objects)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
    )

    assert "error" in result or result.get("error_type") is not None
    assert len(s3._objects) == initial_count


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_delete_own_scope_artifact_returns_deleted_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """confirm=True, own-scope artifact → response has deleted=True."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert result["artifact_id"] == "artifacts/t2-active"
    assert result["deleted"] is True


async def test_delete_removes_from_s3_and_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After delete, artifact absent from fake S3 and fake vectors."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "artifacts/t2-active" not in s3._objects
    assert "artifacts/t2-active#summary" not in vectors._vectors
    assert "artifacts/t2-active#details" not in vectors._vectors


async def test_delete_tier2_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 2 artifact is deletable (immutability is content-only)."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert result.get("deleted") is True


async def test_delete_no_synthesis_references_no_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artifact not referenced by any synthesis → warnings absent or empty."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t3-active",
        confirm=True,
    )

    warnings = result.get("warnings", [])
    assert warnings == [] or warnings is None


# ---------------------------------------------------------------------------
# Synthesis warning
# ---------------------------------------------------------------------------


async def test_delete_with_one_synthesis_reference_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artifact referenced by one synthesis → warnings contains that synthesis id."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert result.get("deleted") is True
    warnings = result.get("warnings", [])
    assert "artifacts/synthesis-one" in warnings


async def test_delete_with_two_synthesis_references_warns_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artifact referenced by two syntheses → both identifiers in warnings."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    warnings = result.get("warnings", [])
    assert "artifacts/synthesis-one" in warnings
    assert "artifacts/synthesis-two" in warnings


# ---------------------------------------------------------------------------
# Cross-scope gate
# ---------------------------------------------------------------------------


async def test_delete_foreign_scope_access_denied_no_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope artifact → access-denied error; no AWS writes."""
    settings = _make_settings(monkeypatch)

    delete_calls: list[str] = []

    class TrackingS3(FakeS3Client):
        def delete_object(self, key: str) -> None:
            delete_calls.append(key)
            super().delete_object(key)

    s3 = TrackingS3()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)
    delete_calls.clear()

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="other-team/foreign-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "access" in result_str or "denied" in result_str or "forbidden" in result_str
    assert len(delete_calls) == 0


async def test_delete_unknown_scope_access_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """artifact_id matching no known scope → access-denied error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="unknown-scope/thing",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


async def test_delete_nonexistent_own_scope_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Own-scope artifact_id not in S3 → not-found error; no vector deletes."""
    settings = _make_settings(monkeypatch)

    delete_vectors_calls: list[Any] = []

    class TrackingVectors(FakeVectorsClient):
        def delete_vectors(self, keys: list[str]) -> None:
            delete_vectors_calls.append(keys)
            super().delete_vectors(keys)

    s3 = FakeS3Client()
    vectors = TrackingVectors(dimension=2)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/nonexistent",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    assert len(delete_vectors_calls) == 0


# ---------------------------------------------------------------------------
# Ordering and partial failure
# ---------------------------------------------------------------------------


async def test_delete_vectors_failure_leaves_s3_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_vectors raises non-credential exception → structured error; S3 object intact."""
    settings = _make_settings(monkeypatch)

    class FailingDeleteVectors(FakeVectorsClient):
        def delete_vectors(self, keys: list[str]) -> None:
            raise RuntimeError("Simulated vector delete failure")

    s3 = FakeS3Client()
    vectors = FailingDeleteVectors(dimension=2)
    _seed_all(s3, vectors)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    # S3 object must remain
    assert "artifacts/t2-active" in s3._objects


async def test_delete_s3_failure_after_vectors_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 delete fails after vectors deleted → partial-failure error; S3 object still present."""
    settings = _make_settings(monkeypatch)

    class FailingDeleteObject(FakeS3Client):
        def delete_object(self, key: str) -> None:
            raise RuntimeError("Simulated S3 delete failure")

    s3 = FailingDeleteObject()
    s3.put_object("artifacts/t2-active", _CONTENT, {**_BASE_S3_META, "tier": "2"})
    vectors = FakeVectorsClient(dimension=2)
    vectors.put_vector(
        "artifacts/t2-active#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-active"},
    )

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "partial" in result_str or "artifacts/t2-active" in str(result)
    # Vectors are deleted (orphan state)
    assert "artifacts/t2-active#summary" not in vectors._vectors
    # S3 still present (recoverable)
    assert "artifacts/t2-active" in s3._objects


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_delete_head_object_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """head_object raises CredentialError → structured error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    s3.put_object("artifacts/t2-active", _CONTENT, {**_BASE_S3_META})
    s3.set_credential_failure(True)
    vectors = FakeVectorsClient(dimension=2)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None


async def test_delete_list_vectors_credential_error_s3_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error; no S3 deletes."""
    settings = _make_settings(monkeypatch)

    class CredFailListVectors(FakeVectorsClient):
        def list_vectors_by_metadata(self, filter: dict[str, Any]) -> list[str]:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(message="Simulated.", service="s3vectors", original=Exception("sim"))

    s3 = FakeS3Client()
    s3.put_object("artifacts/t2-active", _CONTENT, {**_BASE_S3_META})
    vectors = CredFailListVectors(dimension=2)

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    assert "artifacts/t2-active" in s3._objects


async def test_delete_vectors_credential_error_s3_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_vectors raises CredentialError → structured error; S3 object intact."""
    settings = _make_settings(monkeypatch)

    class CredFailDeleteVectors(FakeVectorsClient):
        def delete_vectors(self, keys: list[str]) -> None:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(message="Simulated.", service="s3vectors", original=Exception("sim"))

    s3 = FakeS3Client()
    s3.put_object("artifacts/t2-active", _CONTENT, {**_BASE_S3_META})
    vectors = CredFailDeleteVectors(dimension=2)
    vectors.put_vector(
        "artifacts/t2-active#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-active"},
    )

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    assert "artifacts/t2-active" in s3._objects


async def test_delete_s3_delete_credential_error_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_object raises CredentialError after vectors deleted → partial-failure error."""
    settings = _make_settings(monkeypatch)

    class CredFailDeleteObject(FakeS3Client):
        def delete_object(self, key: str) -> None:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(message="Simulated.", service="s3", original=Exception("sim"))

    s3 = CredFailDeleteObject()
    s3.put_object("artifacts/t2-active", _CONTENT, {**_BASE_S3_META})
    vectors = FakeVectorsClient(dimension=2)
    vectors.put_vector(
        "artifacts/t2-active#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-active"},
    )

    result = await delete_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result)
    assert "artifacts/t2-active" in result_str
