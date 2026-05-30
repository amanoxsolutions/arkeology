"""Unit tests for cairn_mcp.tools.purge.

Tests purge_archived() using FakeS3Client + FakeVectorsClient.
"""

from typing import Any

import pytest
from cairn_mcp.tools.purge import purge_archived

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
    "status": "inactive",
    "title": "Stale review",
    "visibility": "shared",
    "feature_tags": "",
    "author_role": "developer",
    "description": "A stale artifact.",
}

_BASE_VECTOR_META: dict[str, Any] = {
    "scope": "artifacts",
    "type": "code_review",
    "team": "platform",
    "project": "cairn",
    "tier": 2,
    "date": "2026-05-30",
    "status": "inactive",
    "title": "Stale review",
    "visibility": "shared",
    "feature_tags": [],
    "author_role": "developer",
    "description": "A stale artifact.",
}

_CONTENT = "## Old content."


def _seed_all(s3: FakeS3Client, vectors: FakeVectorsClient) -> None:
    """Seed S3 and vectors for purge tests."""
    # own-scope inactive tier 2
    s3.put_object("artifacts/inactive-t2", _CONTENT, {**_BASE_S3_META, "tier": "2"})
    vectors.put_vector(
        "artifacts/inactive-t2#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/inactive-t2"},
    )

    # own-scope inactive tier 3
    s3.put_object(
        "artifacts/inactive-t3",
        _CONTENT,
        {**_BASE_S3_META, "tier": "3", "type": "adr"},
    )
    vectors.put_vector(
        "artifacts/inactive-t3#summary",
        [0.9, 0.1],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/inactive-t3",
            "tier": 3,
            "type": "adr",
        },
    )

    # own-scope active artifact — should NOT be purged
    s3.put_object(
        "artifacts/active-keep",
        _CONTENT,
        {**_BASE_S3_META, "status": "active", "title": "Keep me"},
    )
    vectors.put_vector(
        "artifacts/active-keep#summary",
        [0.8, 0.2],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/active-keep", "status": "active"},
    )

    # synthesis whose ALL sources are in the inactive set → cascade
    s3.put_object(
        "artifacts/synthesis-cascade",
        _CONTENT,
        {
            **_BASE_S3_META,
            "type": "synthesis",
            "status": "active",
            "source_artifacts": "artifacts/inactive-t2,artifacts/inactive-t3",
        },
    )
    vectors.put_vector(
        "artifacts/synthesis-cascade#summary",
        [0.7, 0.3],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/synthesis-cascade",
            "type": "synthesis",
            "status": "active",
            "source_artifacts": ["artifacts/inactive-t2", "artifacts/inactive-t3"],
        },
    )

    # synthesis with one source OUTSIDE the inactive set → NOT cascade
    s3.put_object(
        "artifacts/synthesis-safe",
        _CONTENT,
        {
            **_BASE_S3_META,
            "type": "synthesis",
            "status": "active",
            "source_artifacts": "artifacts/inactive-t2,artifacts/active-keep",
        },
    )
    vectors.put_vector(
        "artifacts/synthesis-safe#summary",
        [0.6, 0.4],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/synthesis-safe",
            "type": "synthesis",
            "status": "active",
            "source_artifacts": ["artifacts/inactive-t2", "artifacts/active-keep"],
        },
    )

    # foreign-scope inactive — should NOT be purged
    s3.put_object(
        "other-team/foreign-inactive",
        _CONTENT,
        {**_BASE_S3_META, "team": "network"},
    )
    vectors.put_vector(
        "other-team/foreign-inactive#summary",
        [0.5, 0.5],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/foreign-inactive",
            "scope": "other-team",
        },
    )


# ---------------------------------------------------------------------------
# Confirmation gate
# ---------------------------------------------------------------------------


async def test_purge_confirm_false_returns_error_no_writes(
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

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=False
    )

    assert "error" in result or result.get("error_type") is not None
    assert len(delete_calls) == 0


async def test_purge_confirm_absent_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """confirm not provided → structured error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)
    initial_count = len(s3._objects)

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None
    )

    assert "error" in result or result.get("error_type") is not None
    assert len(s3._objects) == initial_count


# ---------------------------------------------------------------------------
# Empty purge set
# ---------------------------------------------------------------------------


async def test_purge_no_inactive_artifacts_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No inactive artifacts in own scope → purged_count=0, empty lists, no error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    # Only seed active artifact
    s3.put_object("artifacts/active-only", _CONTENT, {**_BASE_S3_META, "status": "active"})
    vectors.put_vector(
        "artifacts/active-only#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/active-only", "status": "active"},
    )

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=True
    )

    assert result["purged_count"] == 0
    assert result["purged_ids"] == []
    assert result["cascade_deleted"] == []


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_purge_removes_all_inactive_own_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple inactive artifacts → all absent from S3 and vectors after purge."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=True
    )

    assert "artifacts/inactive-t2" not in s3._objects
    assert "artifacts/inactive-t3" not in s3._objects
    assert "artifacts/inactive-t2#summary" not in vectors._vectors
    assert "artifacts/inactive-t3#summary" not in vectors._vectors
    assert result["purged_count"] == 2
    assert "artifacts/inactive-t2" in result["purged_ids"]
    assert "artifacts/inactive-t3" in result["purged_ids"]


async def test_purge_leaves_active_artifacts_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active artifacts in own scope are untouched after purge."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=True
    )

    assert "artifacts/active-keep" in s3._objects


async def test_purge_leaves_foreign_scope_inactive_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope inactive artifact is NOT purged."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=True
    )

    assert "other-team/foreign-inactive" in s3._objects


# ---------------------------------------------------------------------------
# Cascade
# ---------------------------------------------------------------------------


async def test_purge_cascade_deletes_synthesis_all_sources_in_purge_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis with all sources in purge set → cascade-deleted; in cascade_deleted list."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=True
    )

    assert "artifacts/synthesis-cascade" in result["cascade_deleted"]
    assert "artifacts/synthesis-cascade" not in s3._objects
    assert "artifacts/synthesis-cascade#summary" not in vectors._vectors


async def test_purge_does_not_cascade_delete_synthesis_with_surviving_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis with one source outside purge set → NOT cascade-deleted; still present."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=True
    )

    assert "artifacts/synthesis-safe" not in result["cascade_deleted"]
    assert "artifacts/synthesis-safe" in s3._objects


async def test_purge_no_synthesis_cascade_deleted_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No synthesis artifacts → cascade_deleted is empty list; no error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    # Only inactive non-synthesis
    s3.put_object("artifacts/inactive-only", _CONTENT, {**_BASE_S3_META})
    vectors.put_vector(
        "artifacts/inactive-only#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/inactive-only"},
    )

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=True
    )

    assert result["cascade_deleted"] == []


# ---------------------------------------------------------------------------
# Partial failure
# ---------------------------------------------------------------------------


async def test_purge_s3_delete_failure_partial_failure_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_object failure on one artifact → structured partial-failure error."""
    settings = _make_settings(monkeypatch)

    call_count = {"n": 0}

    class PartialFailS3(FakeS3Client):
        def delete_object(self, key: str) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Simulated S3 delete failure")
            super().delete_object(key)

    s3 = PartialFailS3()
    s3.put_object("artifacts/inactive-t2", _CONTENT, {**_BASE_S3_META})
    vectors = FakeVectorsClient(dimension=2)
    vectors.put_vector(
        "artifacts/inactive-t2#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/inactive-t2"},
    )

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=True
    )

    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_purge_list_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error; no deletes."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    vectors.set_credential_failure(True)

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=True
    )

    assert "error" in result or result.get("error_type") is not None


async def test_purge_delete_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_vectors raises CredentialError → structured error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    s3.put_object("artifacts/inactive-t2", _CONTENT, {**_BASE_S3_META})

    class CredFailDeleteVectors(FakeVectorsClient):
        def delete_vectors(self, keys: list[str]) -> None:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(message="Simulated.", service="s3vectors", original=Exception("sim"))

    vectors = CredFailDeleteVectors(dimension=2)
    vectors.put_vector(
        "artifacts/inactive-t2#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/inactive-t2"},
    )

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=True
    )

    assert "error" in result or result.get("error_type") is not None


async def test_purge_delete_object_credential_error_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_object raises CredentialError → structured partial-failure error with artifact_id."""
    settings = _make_settings(monkeypatch)

    class CredFailDeleteObject(FakeS3Client):
        def delete_object(self, key: str) -> None:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(message="Simulated.", service="s3", original=Exception("sim"))

    s3 = CredFailDeleteObject()
    s3.put_object("artifacts/inactive-t2", _CONTENT, {**_BASE_S3_META})
    vectors = FakeVectorsClient(dimension=2)
    vectors.put_vector(
        "artifacts/inactive-t2#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/inactive-t2"},
    )

    result = await purge_archived(
        settings=settings, s3=s3, vectors=vectors, bedrock=None, confirm=True
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result)
    assert "artifacts/inactive-t2" in result_str
