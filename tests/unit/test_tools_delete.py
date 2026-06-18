"""Unit tests for cairn_mcp.tools.delete.

Tests delete_artifact() using moto-backed S3ClientImpl + VectorsClientImpl.
"""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools.delete import delete_artifact
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
    "tags": "auth",
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
    "tags": ["auth"],
    "author_role": "developer",
    "description": "Review of the auth module.",
}

_CONTENT = "## Summary\n\nAll looks good."


def _seed_all(s3: S3ClientImpl, vectors: VectorsClientImpl) -> None:
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
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t3-active", "tier": 3, "type": "adr"},
    )

    # foreign-scope active
    s3.put_object("other-team/foreign-active", _CONTENT, {**_BASE_S3_META, "team": "network"})

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
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """confirm=False → structured error; no AWS writes."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    spy_delete = mocker.spy(s3_client, "delete_object")

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=False,
    )

    assert "error" in result or result.get("error_type") is not None
    assert spy_delete.call_count == 0


async def test_confirm_missing_returns_error_no_writes(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """confirm not provided → structured error; no AWS writes."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    initial_count = len(s3_client.list_objects(""))

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
    )

    assert "error" in result or result.get("error_type") is not None
    assert len(s3_client.list_objects("")) == initial_count


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_delete_own_scope_artifact_returns_deleted_true(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """confirm=True, own-scope artifact → response has deleted=True."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert result["artifact_id"] == "artifacts/t2-active"
    assert result["deleted"] is True


async def test_delete_removes_from_s3_and_vectors(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """After delete, artifact absent from S3 and vectors."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "artifacts/t2-active" not in s3_client.list_objects("")
    assert "artifacts/t2-active#summary" not in vectors_client_2.list_vectors_by_metadata({})
    assert "artifacts/t2-active#details" not in vectors_client_2.list_vectors_by_metadata({})


async def test_delete_tier2_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Tier 2 artifact is deletable."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert result.get("deleted") is True


async def test_delete_no_synthesis_references_no_warnings(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Artifact not referenced by any synthesis → warnings absent or empty."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
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
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Artifact referenced by one synthesis → warnings contains that synthesis id."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert result.get("deleted") is True
    warnings = result.get("warnings", [])
    assert "artifacts/synthesis-one" in warnings


async def test_delete_with_two_synthesis_references_warns_both(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Artifact referenced by two syntheses → both identifiers in warnings."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
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
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Foreign-scope artifact → access-denied error; no AWS writes."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    spy_delete = mocker.spy(s3_client, "delete_object")

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="other-team/foreign-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "access" in result_str or "denied" in result_str or "forbidden" in result_str
    assert spy_delete.call_count == 0


async def test_delete_unknown_scope_access_denied(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """artifact_id matching no known scope → access-denied error."""
    settings = _make_settings(monkeypatch)

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
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
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Own-scope artifact_id not in S3 → not-found error; no vector deletes."""
    settings = _make_settings(monkeypatch)
    spy_delete_vec = mocker.spy(vectors_client_2, "delete_vectors")

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/nonexistent",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    assert spy_delete_vec.call_count == 0


# ---------------------------------------------------------------------------
# Ordering and partial failure
# ---------------------------------------------------------------------------


async def test_delete_vectors_failure_leaves_s3_intact(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """delete_vectors raises non-credential exception → structured error; S3 object intact."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    mocker.patch.object(
        vectors_client_2,
        "delete_vectors",
        side_effect=RuntimeError("Simulated vector delete failure"),
    )

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    assert "artifacts/t2-active" in s3_client.list_objects("")


async def test_delete_s3_failure_after_vectors_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """S3 delete fails after vectors deleted → partial-failure error; S3 object still present."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/t2-active", _CONTENT, {**_BASE_S3_META, "tier": "2"})
    vectors_client_2.put_vector(
        "artifacts/t2-active#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-active"},
    )
    mocker.patch.object(
        s3_client,
        "delete_object",
        side_effect=RuntimeError("Simulated S3 delete failure"),
    )

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "partial" in result_str or "artifacts/t2-active" in str(result)
    # Vectors are deleted (orphan state)
    assert "artifacts/t2-active#summary" not in vectors_client_2.list_vectors_by_metadata({})
    # S3 still present (recoverable)
    assert "artifacts/t2-active" in s3_client.list_objects("")


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_delete_head_object_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """head_object raises CredentialError → structured error."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/t2-active", _CONTENT, {**_BASE_S3_META})
    mocker.patch.object(
        s3_client,
        "head_object",
        side_effect=CredentialError(message="Simulated.", service="s3", original=Exception("sim")),
    )

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None


async def test_delete_list_vectors_credential_error_s3_intact(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error; no S3 deletes."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/t2-active", _CONTENT, {**_BASE_S3_META})
    mocker.patch.object(
        vectors_client_2,
        "list_vectors_by_metadata",
        side_effect=CredentialError(
            message="Simulated.", service="s3vectors", original=Exception("sim")
        ),
    )

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    assert "artifacts/t2-active" in s3_client.list_objects("")


async def test_delete_vectors_credential_error_s3_intact(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """delete_vectors raises CredentialError → structured error; S3 object intact."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/t2-active", _CONTENT, {**_BASE_S3_META})
    vectors_client_2.put_vector(
        "artifacts/t2-active#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-active"},
    )
    mocker.patch.object(
        vectors_client_2,
        "delete_vectors",
        side_effect=CredentialError(
            message="Simulated.", service="s3vectors", original=Exception("sim")
        ),
    )

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    assert "artifacts/t2-active" in s3_client.list_objects("")


async def test_delete_s3_delete_credential_error_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """delete_object raises CredentialError after vectors deleted → partial-failure error."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/t2-active", _CONTENT, {**_BASE_S3_META})
    vectors_client_2.put_vector(
        "artifacts/t2-active#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-active"},
    )
    mocker.patch.object(
        s3_client,
        "delete_object",
        side_effect=CredentialError(message="Simulated.", service="s3", original=Exception("sim")),
    )

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert "error" in result or result.get("error_type") is not None
    assert "artifacts/t2-active" in str(result)


# ---------------------------------------------------------------------------
# Spec 01 — CredentialError from S3 returns credential_error (not partial_delete)
# ---------------------------------------------------------------------------


async def test_credential_error_on_delete_returns_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """CredentialError during S3 delete → response is credential_error, not partial_delete."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/t2-active", "content", {**_BASE_S3_META})
    vectors_client_2.put_vector(
        "artifacts/t2-active#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-active"},
    )
    mocker.patch.object(
        s3_client,
        "delete_object",
        side_effect=CredentialError(message="Simulated.", service="s3", original=Exception("sim")),
    )

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    assert result.get("error") == "credential_error"
