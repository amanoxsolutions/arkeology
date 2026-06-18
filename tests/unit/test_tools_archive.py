"""Unit tests for cairn_mcp.tools.archive.

Tests archive_artifact() using moto-backed S3ClientImpl + VectorsClientImpl.
"""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError
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
    "tags": "auth,security",
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
    "tags": ["auth", "security"],
    "author_role": "developer",
    "description": "Review of the auth module.",
}

_CONTENT = "## Summary\n\nAll looks good."


def _seed_all(s3: S3ClientImpl, vectors: VectorsClientImpl) -> None:
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
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/already-archived", "status": "inactive"},
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
    s3.put_object("artifacts/doc-level-only", _CONTENT, {**_BASE_S3_META, "status": "active"})
    vectors.put_vector(
        "artifacts/doc-level-only",
        [0.6, 0.4],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/doc-level-only", "status": "active"},
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_archive_active_artifact_returns_inactive_status(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Archive active own-scope artifact → response has status='inactive'."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert result["artifact_id"] == "artifacts/active-review"
    assert result["status"] == "inactive"


async def test_archive_does_not_change_s3_content(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Archiving preserves S3 object content unchanged."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert s3_client.get_object("artifacts/active-review") == _CONTENT


async def test_archive_updates_s3_metadata_status(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Archiving updates S3 object metadata status to 'inactive'."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    meta = s3_client.head_object("artifacts/active-review")
    assert meta["status"] == "inactive"


async def test_archive_updates_all_section_vectors_status(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Archiving updates status='inactive' on all section vectors for the artifact."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    for key in ["artifacts/active-review#summary", "artifacts/active-review#details"]:
        vec_results = vectors_client_2.get_vectors([key])
        assert len(vec_results) == 1
        assert vec_results[0]["metadata"]["status"] == "inactive"


async def test_archive_already_archived_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Archiving an already-archived artifact succeeds idempotently (no error)."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/already-archived",
    )

    assert result["status"] == "inactive"
    assert "error" not in result


async def test_archive_doc_level_vector_updated(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Artifact with single document-level vector (no #) → that vector updated to inactive."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/doc-level-only",
    )

    vec_results = vectors_client_2.get_vectors(["artifacts/doc-level-only"])
    assert len(vec_results) == 1
    assert vec_results[0]["metadata"]["status"] == "inactive"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


async def test_archive_foreign_scope_returns_access_denied(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Foreign-scope artifact → structured access-denied error; no AWS writes."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    spy_put = mocker.spy(s3_client, "put_object")
    initial_put_count = spy_put.call_count

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="other-team/foreign-active",
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "access" in result_str or "denied" in result_str or "forbidden" in result_str
    assert spy_put.call_count == initial_put_count


async def test_archive_unknown_scope_returns_access_denied(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """artifact_id matching no known scope → access-denied error."""
    settings = _make_settings(monkeypatch)

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="unknown-scope/some-artifact",
    )

    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


async def test_archive_nonexistent_own_scope_returns_not_found(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Own-scope artifact_id not in S3 → not-found error; no vector calls."""
    settings = _make_settings(monkeypatch)
    spy_list = mocker.spy(vectors_client_2, "list_vectors_by_metadata")

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/nonexistent",
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "not" in result_str or "found" in result_str or "missing" in result_str
    assert spy_list.call_count == 0


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_archive_get_object_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """get_object raises CredentialError → structured error; no vector writes."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/active-review", _CONTENT, {**_BASE_S3_META, "status": "active"})
    spy_put_vec = mocker.spy(vectors_client_2, "put_vector")
    mocker.patch.object(
        s3_client,
        "get_object",
        side_effect=CredentialError(message="Simulated.", service="s3", original=Exception("sim")),
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" in result or result.get("error_type") is not None
    assert spy_put_vec.call_count == 0


async def test_archive_put_object_credential_error_no_vector_writes(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """put_object raises CredentialError → structured error; vectors NOT updated."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/active-review", _CONTENT, {**_BASE_S3_META, "status": "active"})
    spy_put_vec = mocker.spy(vectors_client_2, "put_vector")
    mocker.patch.object(
        s3_client,
        "put_object",
        side_effect=CredentialError(message="Simulated.", service="s3", original=Exception("sim")),
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" in result or result.get("error_type") is not None
    assert spy_put_vec.call_count == 0


async def test_archive_list_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/active-review", _CONTENT, {**_BASE_S3_META, "status": "active"})
    mocker.patch.object(
        vectors_client_2,
        "list_vectors_by_metadata",
        side_effect=CredentialError(
            message="Simulated.", service="s3vectors", original=Exception("sim")
        ),
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" in result or result.get("error_type") is not None


async def test_archive_get_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """get_vectors raises CredentialError → structured error."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/active-review", _CONTENT, {**_BASE_S3_META, "status": "active"})
    vectors_client_2.put_vector(
        "artifacts/active-review#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/active-review", "status": "active"},
    )
    mocker.patch.object(
        vectors_client_2,
        "get_vectors",
        side_effect=CredentialError(
            message="Simulated.", service="s3vectors", original=Exception("sim")
        ),
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" in result or result.get("error_type") is not None


async def test_archive_put_vector_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """put_vector raises CredentialError on first section → structured error."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/active-review", _CONTENT, {**_BASE_S3_META, "status": "active"})
    vectors_client_2.put_vector(
        "artifacts/active-review#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/active-review", "status": "active"},
    )
    mocker.patch.object(
        vectors_client_2,
        "put_vector",
        side_effect=CredentialError(
            message="Simulated.", service="s3vectors", original=Exception("sim")
        ),
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# Spec 09 — Archive idempotency
# ---------------------------------------------------------------------------


async def test_archive_already_inactive_returns_already_archived(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Archiving already-inactive artifact returns already_archived: True."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "artifacts/already-archived-v2",
        _CONTENT,
        {**_BASE_S3_META, "status": "inactive"},
    )
    vectors_client_2.put_vector(
        "artifacts/already-archived-v2#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/already-archived-v2", "status": "inactive"},
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/already-archived-v2",
    )

    assert result.get("already_archived") is True


async def test_archive_already_inactive_makes_no_writes(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Archiving already-inactive artifact makes no put_object or put_vector calls."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "artifacts/already-archived-v3",
        _CONTENT,
        {**_BASE_S3_META, "status": "inactive"},
    )
    vectors_client_2.put_vector(
        "artifacts/already-archived-v3#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/already-archived-v3", "status": "inactive"},
    )

    count_before_s3 = len(s3_client.list_objects(""))
    count_before_vec = len(vectors_client_2.list_vectors_by_metadata({}))

    spy_put_obj = mocker.spy(s3_client, "put_object")
    spy_put_vec = mocker.spy(vectors_client_2, "put_vector")

    await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/already-archived-v3",
    )

    assert spy_put_obj.call_count == 0
    assert spy_put_vec.call_count == 0
    assert len(s3_client.list_objects("")) == count_before_s3
    assert len(vectors_client_2.list_vectors_by_metadata({})) == count_before_vec
