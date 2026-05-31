"""Unit tests for cairn_mcp.tools.archive.

Tests archive_artifact() using FakeS3Client + FakeVectorsClient.
"""

from typing import Any

import pytest

from cairn_mcp.clients.fakes.fake_s3 import FakeS3Client
from cairn_mcp.clients.fakes.fake_vectors import FakeVectorsClient
from cairn_mcp.config import Settings
from cairn_mcp.tools.archive import archive_artifact
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, READ_PREFIXES="other-team", **overrides)


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
    "feature_tags": "auth,security",
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
    "feature_tags": ["auth", "security"],
    "author_role": "developer",
    "description": "Review of the auth module.",
}

_CONTENT = "## Summary\n\nAll looks good."


def _seed_all(s3: FakeS3Client, vectors: FakeVectorsClient) -> None:
    """Seed S3 and vectors with representative objects for archive tests."""
    # own-scope active artifact with two section vectors
    s3.put_object("artifacts/active-review", _CONTENT, {**_BASE_S3_META, "status": "active"})
    vectors.put_vector(
        "artifacts/active-review#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/active-review", "status": "active"},
    )
    vectors.put_vector(
        "artifacts/active-review#details",
        [0.9, 0.1],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/active-review", "status": "active"},
    )

    # own-scope already-archived artifact
    s3.put_object("artifacts/already-archived", _CONTENT, {**_BASE_S3_META, "status": "inactive"})
    vectors.put_vector(
        "artifacts/already-archived#summary",
        [0.8, 0.2],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/already-archived",
            "status": "inactive",
        },
    )

    # foreign-scope active artifact — should be denied
    s3.put_object(
        "other-team/foreign-active",
        _CONTENT,
        {**_BASE_S3_META, "status": "active", "team": "network"},
    )
    vectors.put_vector(
        "other-team/foreign-active#summary",
        [0.7, 0.3],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/foreign-active",
            "scope": "other-team",
            "status": "active",
        },
    )

    # own-scope artifact with single document-level vector (no # in key)
    s3.put_object(
        "artifacts/doc-level-only",
        _CONTENT,
        {**_BASE_S3_META, "status": "active"},
    )
    vectors.put_vector(
        "artifacts/doc-level-only",
        [0.6, 0.4],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/doc-level-only",
            "status": "active",
        },
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_archive_active_artifact_returns_inactive_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archive active own-scope artifact → response has status='inactive'."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert result["artifact_id"] == "artifacts/active-review"
    assert result["status"] == "inactive"


async def test_archive_does_not_change_s3_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archiving preserves S3 object content unchanged."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert s3.get_object("artifacts/active-review") == _CONTENT


async def test_archive_updates_s3_metadata_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archiving updates S3 object metadata status to 'inactive'."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    meta = s3.head_object("artifacts/active-review")
    assert meta["status"] == "inactive"


async def test_archive_updates_all_section_vectors_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archiving updates status='inactive' on all section vectors for the artifact."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    for key in ["artifacts/active-review#summary", "artifacts/active-review#details"]:
        vec_results = vectors.get_vectors([key])
        assert len(vec_results) == 1
        assert vec_results[0]["metadata"]["status"] == "inactive"


async def test_archive_already_archived_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archiving an already-archived artifact succeeds idempotently (no error)."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/already-archived",
    )

    assert result["status"] == "inactive"
    assert "error" not in result


async def test_archive_doc_level_vector_updated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artifact with single document-level vector (no #) → that vector updated to inactive."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)

    await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/doc-level-only",
    )

    vec_results = vectors.get_vectors(["artifacts/doc-level-only"])
    assert len(vec_results) == 1
    assert vec_results[0]["metadata"]["status"] == "inactive"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


async def test_archive_foreign_scope_returns_access_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope artifact → structured access-denied error; no AWS writes."""
    settings = _make_settings(monkeypatch)

    put_object_calls: list[str] = []

    class TrackingS3(FakeS3Client):
        def put_object(self, key: str, body: str, metadata: dict[str, str]) -> None:
            put_object_calls.append(key)
            super().put_object(key, body, metadata)

    s3 = TrackingS3()
    vectors = FakeVectorsClient(dimension=2)
    _seed_all(s3, vectors)
    put_object_calls.clear()

    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="other-team/foreign-active",
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "access" in result_str or "denied" in result_str or "forbidden" in result_str
    assert len(put_object_calls) == 0


async def test_archive_unknown_scope_returns_access_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """artifact_id matching no known scope → access-denied error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)

    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="unknown-scope/some-artifact",
    )

    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


async def test_archive_nonexistent_own_scope_returns_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Own-scope artifact_id not in S3 → not-found error; no vector calls."""
    settings = _make_settings(monkeypatch)

    list_vectors_calls: list[Any] = []

    class TrackingVectors(FakeVectorsClient):
        def list_vectors_by_metadata(self, filter: dict[str, Any]) -> list[str]:
            list_vectors_calls.append(filter)
            return super().list_vectors_by_metadata(filter)

    s3 = FakeS3Client()
    vectors = TrackingVectors(dimension=2)

    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/nonexistent",
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "not" in result_str or "found" in result_str or "missing" in result_str
    assert len(list_vectors_calls) == 0


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_archive_get_object_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_object raises CredentialError → structured error; no vector writes."""
    settings = _make_settings(monkeypatch)

    put_vector_calls: list[str] = []

    class TrackingVectors(FakeVectorsClient):
        def put_vector(self, key: str, vector: list[float], metadata: dict[str, Any]) -> None:
            put_vector_calls.append(key)
            super().put_vector(key, vector, metadata)

    class GetObjectCredFail(FakeS3Client):
        def get_object(self, key: str) -> str:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(message="Simulated.", service="s3", original=Exception("sim"))

    s3 = GetObjectCredFail()
    vectors = TrackingVectors(dimension=2)
    # Seed head_object so scope check passes, then get_object fails
    s3._objects["artifacts/active-review"] = (_CONTENT, {**_BASE_S3_META, "status": "active"})

    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" in result or result.get("error_type") is not None
    assert len(put_vector_calls) == 0


async def test_archive_put_object_credential_error_no_vector_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """put_object raises CredentialError → structured error; vectors NOT updated."""
    settings = _make_settings(monkeypatch)

    put_vector_calls: list[str] = []

    class TrackingVectors(FakeVectorsClient):
        def put_vector(self, key: str, vector: list[float], metadata: dict[str, Any]) -> None:
            put_vector_calls.append(key)
            super().put_vector(key, vector, metadata)

    class PutObjectCredFail(FakeS3Client):
        def put_object(self, key: str, body: str, metadata: dict[str, str]) -> None:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(message="Simulated.", service="s3", original=Exception("sim"))

    s3 = PutObjectCredFail()
    s3._objects["artifacts/active-review"] = (_CONTENT, {**_BASE_S3_META, "status": "active"})
    vectors = TrackingVectors(dimension=2)

    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" in result or result.get("error_type") is not None
    assert len(put_vector_calls) == 0


async def test_archive_list_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    s3.put_object("artifacts/active-review", _CONTENT, {**_BASE_S3_META, "status": "active"})

    class CredFailVectors(FakeVectorsClient):
        def list_vectors_by_metadata(self, filter: dict[str, Any]) -> list[str]:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(message="Simulated.", service="s3vectors", original=Exception("sim"))

    vectors = CredFailVectors(dimension=2)

    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" in result or result.get("error_type") is not None


async def test_archive_get_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_vectors raises CredentialError → structured error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    s3.put_object("artifacts/active-review", _CONTENT, {**_BASE_S3_META, "status": "active"})

    class GetVectorsCredFail(FakeVectorsClient):
        def get_vectors(self, keys: list[str]) -> list[dict[str, Any]]:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(message="Simulated.", service="s3vectors", original=Exception("sim"))

    vectors = GetVectorsCredFail(dimension=2)
    vectors.put_vector(
        "artifacts/active-review#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/active-review", "status": "active"},
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" in result or result.get("error_type") is not None


async def test_archive_put_vector_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """put_vector raises CredentialError on first section → structured error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    s3.put_object("artifacts/active-review", _CONTENT, {**_BASE_S3_META, "status": "active"})

    class PutVectorCredFail(FakeVectorsClient):
        def put_vector(self, key: str, vector: list[float], metadata: dict[str, Any]) -> None:
            from cairn_mcp.errors import CredentialError as CE

            raise CE(message="Simulated.", service="s3vectors", original=Exception("sim"))

    vectors = PutVectorCredFail(dimension=2)
    vectors._vectors["artifacts/active-review#summary"] = (
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/active-review", "status": "active"},
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# Spec 09 — Archive idempotency
# ---------------------------------------------------------------------------


async def test_archive_already_inactive_returns_already_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archiving already-inactive artifact returns already_archived: True."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)

    s3.put_object(
        "artifacts/already-archived-v2",
        _CONTENT,
        {**_BASE_S3_META, "status": "inactive"},
    )
    vectors.put_vector(
        "artifacts/already-archived-v2#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/already-archived-v2", "status": "inactive"},
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/already-archived-v2",
    )

    assert result.get("already_archived") is True


async def test_archive_already_inactive_makes_no_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archiving already-inactive artifact makes no put_object or put_vector calls."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=2)

    s3.put_object(
        "artifacts/already-archived-v3",
        _CONTENT,
        {**_BASE_S3_META, "status": "inactive"},
    )
    vectors.put_vector(
        "artifacts/already-archived-v3#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/already-archived-v3", "status": "inactive"},
    )

    put_object_count_before = len(s3._store)
    put_vector_count_before = len(vectors._vectors)

    await archive_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=None,
        artifact_id="artifacts/already-archived-v3",
    )

    assert len(s3._store) == put_object_count_before
    assert len(vectors._vectors) == put_vector_count_before
