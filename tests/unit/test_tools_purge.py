"""Unit tests for cairn_mcp.tools.purge.

Tests purge_archived() using moto-backed S3ClientImpl + VectorsClientImpl.
"""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools.purge import purge_archived
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
    "status": "inactive",
    "title": "Stale review",
    "visibility": "shared",
    "tags": "",
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
    "tags": [],
    "author_role": "developer",
    "description": "A stale artifact.",
}

_CONTENT = "## Old content."


def _seed_all(s3: S3ClientImpl, vectors: VectorsClientImpl) -> None:
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
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """confirm=False → structured error; no AWS writes."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    spy_delete = mocker.spy(s3_client, "delete_object")

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=False
    )

    assert "error" in result or result.get("error_type") is not None
    assert spy_delete.call_count == 0


async def test_purge_confirm_absent_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """confirm not provided → structured error."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    initial_count = len(s3_client.list_objects(""))

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None
    )

    assert "error" in result or result.get("error_type") is not None
    assert len(s3_client.list_objects("")) == initial_count


# ---------------------------------------------------------------------------
# Empty purge set
# ---------------------------------------------------------------------------


async def test_purge_no_inactive_artifacts_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """No inactive artifacts in own scope → purged_count=0, empty lists, no error."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/active-only", _CONTENT, {**_BASE_S3_META, "status": "active"})
    vectors_client_2.put_vector(
        "artifacts/active-only#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/active-only", "status": "active"},
    )

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert result["purged_count"] == 0
    assert result["purged_ids"] == []
    assert result["cascade_deleted"] == []


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_purge_removes_all_inactive_own_scope(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Multiple inactive artifacts → all absent from S3 and vectors after purge."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    all_s3_keys = s3_client.list_objects("")
    all_vec_keys = vectors_client_2.list_vectors_by_metadata({})
    assert "artifacts/inactive-t2" not in all_s3_keys
    assert "artifacts/inactive-t3" not in all_s3_keys
    assert "artifacts/inactive-t2#summary" not in all_vec_keys
    assert "artifacts/inactive-t3#summary" not in all_vec_keys
    assert result["purged_count"] == 2
    assert "artifacts/inactive-t2" in result["purged_ids"]
    assert "artifacts/inactive-t3" in result["purged_ids"]


async def test_purge_leaves_active_artifacts_untouched(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Active artifacts in own scope are untouched after purge."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert "artifacts/active-keep" in s3_client.list_objects("")


async def test_purge_leaves_foreign_scope_inactive_untouched(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Foreign-scope inactive artifact is NOT purged."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert "other-team/foreign-inactive" in s3_client.list_objects("")


# ---------------------------------------------------------------------------
# Cascade
# ---------------------------------------------------------------------------


async def test_purge_cascade_deletes_synthesis_all_sources_in_purge_set(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Synthesis with all sources in purge set → cascade-deleted; in cascade_deleted list."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert "artifacts/synthesis-cascade" in result["cascade_deleted"]
    assert "artifacts/synthesis-cascade" not in s3_client.list_objects("")
    all_vec_keys = vectors_client_2.list_vectors_by_metadata({})
    assert "artifacts/synthesis-cascade#summary" not in all_vec_keys


async def test_purge_does_not_cascade_delete_synthesis_with_surviving_source(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Synthesis with one source outside purge set → NOT cascade-deleted; still present."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert "artifacts/synthesis-safe" not in result["cascade_deleted"]
    assert "artifacts/synthesis-safe" in s3_client.list_objects("")


async def test_purge_no_synthesis_cascade_deleted_empty(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """No synthesis artifacts → cascade_deleted is empty list; no error."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/inactive-only", _CONTENT, {**_BASE_S3_META})
    vectors_client_2.put_vector(
        "artifacts/inactive-only#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/inactive-only"},
    )

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert result["cascade_deleted"] == []


# ---------------------------------------------------------------------------
# Partial failure
# ---------------------------------------------------------------------------


async def test_purge_s3_delete_failure_partial_failure_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """delete_object failure on one artifact → structured partial-failure error."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/inactive-t2", _CONTENT, {**_BASE_S3_META})
    vectors_client_2.put_vector(
        "artifacts/inactive-t2#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/inactive-t2"},
    )

    call_count: dict[str, int] = {"n": 0}
    original_delete = s3_client.delete_object

    def fail_first(key: str) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("Simulated S3 delete failure")
        original_delete(key)

    mocker.patch.object(s3_client, "delete_object", side_effect=fail_first)

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_purge_list_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error; no deletes."""
    settings = _make_settings(monkeypatch)
    mocker.patch.object(
        vectors_client_2,
        "list_vectors_by_metadata",
        side_effect=CredentialError(
            message="Simulated.", service="s3vectors", original=Exception("sim")
        ),
    )

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert "error" in result or result.get("error_type") is not None


async def test_purge_delete_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """delete_vectors raises CredentialError → structured error."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/inactive-t2", _CONTENT, {**_BASE_S3_META})
    vectors_client_2.put_vector(
        "artifacts/inactive-t2#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/inactive-t2"},
    )
    mocker.patch.object(
        vectors_client_2,
        "delete_vectors",
        side_effect=CredentialError(
            message="Simulated.", service="s3vectors", original=Exception("sim")
        ),
    )

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert "error" in result or result.get("error_type") is not None


async def test_purge_delete_object_credential_error_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """delete_object raises CredentialError → structured partial-failure error with artifact_id."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/inactive-t2", _CONTENT, {**_BASE_S3_META})
    vectors_client_2.put_vector(
        "artifacts/inactive-t2#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/inactive-t2"},
    )
    mocker.patch.object(
        s3_client,
        "delete_object",
        side_effect=CredentialError(message="Simulated.", service="s3", original=Exception("sim")),
    )

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result)
    assert "artifacts/inactive-t2" in result_str


# ---------------------------------------------------------------------------
# Spec 01 — CredentialError from S3 returns credential_error (not partial_purge)
# ---------------------------------------------------------------------------


async def test_credential_error_on_purge_returns_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """CredentialError during S3 delete → response is credential_error, not partial_purge."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "artifacts/inactive-t2",
        "archived content",
        {**_BASE_S3_META, "status": "inactive"},
    )
    vectors_client_2.put_vector(
        "artifacts/inactive-t2#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/inactive-t2", "status": "inactive"},
    )
    mocker.patch.object(
        s3_client,
        "delete_object",
        side_effect=CredentialError(message="Simulated.", service="s3", original=Exception("sim")),
    )

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert result.get("error") == "credential_error"
