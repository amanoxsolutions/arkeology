"""Unit tests for arkeology.tools.purge.

Tests purge_archived() using moto-backed S3ClientImpl + VectorsClientImpl.

Covers the best-effort bulk partial-failure contract (spec p3-t13, revised
2026-06-29): the deletion phase is best-effort for non-credential failures
(collected in a ``failed`` list, purge continues) and aborts only on a
systemic CredentialError, still reporting what was purged so far.
"""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.constants import ErrorCode
from arkeology.errors import CredentialError
from arkeology.tools.purge import purge_archived
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, READ_PREFIXES="other-team", **overrides)


def _credential_error(service: str) -> CredentialError:
    return CredentialError(message="Simulated.", service=service, original=Exception("sim"))


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

_BASE_S3_META: dict[str, str] = {
    "type": "code_review",
    "team": "platform",
    "project": "arkeology",
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
    "project": "arkeology",
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


def _seed_inactive(
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    artifact_id: str,
    *,
    vec: list[float] | None = None,
) -> None:
    """Seed a single own-scope inactive artifact (S3 object + one section vector)."""
    s3.put_object(artifact_id, _CONTENT, {**_BASE_S3_META})
    vectors.put_vector(
        f"{artifact_id}#summary",
        vec or [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": artifact_id},
    )


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

    assert result["error"] == ErrorCode.CONFIRMATION_REQUIRED
    assert spy_delete.call_count == 0


async def test_purge_confirm_absent_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """confirm not provided → structured error; nothing deleted."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    initial_count = len(s3_client.list_objects(""))

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None
    )

    assert result["error"] == ErrorCode.CONFIRMATION_REQUIRED
    assert len(s3_client.list_objects("")) == initial_count


# ---------------------------------------------------------------------------
# Empty purge set
# ---------------------------------------------------------------------------


async def test_purge_no_inactive_artifacts_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """No inactive artifacts in own scope → zero purged, empty lists incl. failed, no error."""
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

    assert result == {
        "purged_count": 0,
        "purged_ids": [],
        "cascade_deleted": [],
        "failed": [],
    }


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
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-only")

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert result["cascade_deleted"] == []


# ---------------------------------------------------------------------------
# All-success reporting
# ---------------------------------------------------------------------------


async def test_purge_all_success_failed_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """All deletes succeed → purged_ids/purged_count reflect deleted set; failed is empty."""
    settings = _make_settings(monkeypatch)
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-a", vec=[1.0, 0.0])
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-b", vec=[0.9, 0.1])
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-c", vec=[0.8, 0.2])

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert result["failed"] == []
    assert result["purged_count"] == 3
    assert sorted(result["purged_ids"]) == [
        "artifacts/inactive-a",
        "artifacts/inactive-b",
        "artifacts/inactive-c",
    ]


# ---------------------------------------------------------------------------
# Best-effort partial failure (non-credential)
# ---------------------------------------------------------------------------


async def test_purge_delete_vectors_failure_one_artifact_continues(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Non-credential delete_vectors failure on ONE artifact → it lands in failed and stays
    fully intact; the other artifacts are still purged."""
    settings = _make_settings(monkeypatch)
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-fail", vec=[1.0, 0.0])
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-ok", vec=[0.9, 0.1])

    original_delete_vectors = vectors_client_2.delete_vectors

    def fail_for_target(keys: list[str]) -> None:
        if any(k.startswith("artifacts/inactive-fail") for k in keys):
            raise RuntimeError("Simulated vector delete failure")
        original_delete_vectors(keys)

    mocker.patch.object(vectors_client_2, "delete_vectors", side_effect=fail_for_target)

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    # Failed artifact is reported and excluded from purged_ids
    failed_ids = [f["artifact_id"] for f in result["failed"]]
    assert "artifacts/inactive-fail" in failed_ids
    assert "artifacts/inactive-fail" not in result["purged_ids"]
    failed_entry = next(
        f for f in result["failed"] if f["artifact_id"] == "artifacts/inactive-fail"
    )
    assert failed_entry["error"] == ErrorCode.DELETE_VECTORS_FAILED
    assert failed_entry["message"]

    # Failed artifact remains fully intact (S3 object + vectors present)
    all_s3_keys = s3_client.list_objects("")
    all_vec_keys = vectors_client_2.list_vectors_by_metadata({})
    assert "artifacts/inactive-fail" in all_s3_keys
    assert "artifacts/inactive-fail#summary" in all_vec_keys

    # The other artifact is purged
    assert "artifacts/inactive-ok" in result["purged_ids"]
    assert "artifacts/inactive-ok" not in all_s3_keys
    assert "artifacts/inactive-ok#summary" not in all_vec_keys


async def test_purge_delete_object_failure_one_artifact_continues(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Non-credential delete_object failure after vectors deleted → orphan; the artifact lands
    in failed, is excluded from purged_ids; other artifacts are purged."""
    settings = _make_settings(monkeypatch)
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-fail", vec=[1.0, 0.0])
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-ok", vec=[0.9, 0.1])

    original_delete_object = s3_client.delete_object

    def fail_for_target(key: str) -> None:
        if key == "artifacts/inactive-fail":
            raise RuntimeError("Simulated S3 delete failure")
        original_delete_object(key)

    mocker.patch.object(s3_client, "delete_object", side_effect=fail_for_target)

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    failed_ids = [f["artifact_id"] for f in result["failed"]]
    assert "artifacts/inactive-fail" in failed_ids
    assert "artifacts/inactive-fail" not in result["purged_ids"]
    failed_entry = next(
        f for f in result["failed"] if f["artifact_id"] == "artifacts/inactive-fail"
    )
    assert failed_entry["error"] == ErrorCode.PARTIAL_DELETE
    assert failed_entry["message"]

    # Recoverable orphan state: S3 object present, vectors gone
    all_s3_keys = s3_client.list_objects("")
    all_vec_keys = vectors_client_2.list_vectors_by_metadata({})
    assert "artifacts/inactive-fail" in all_s3_keys
    assert "artifacts/inactive-fail#summary" not in all_vec_keys

    # The other artifact is purged
    assert "artifacts/inactive-ok" in result["purged_ids"]
    assert "artifacts/inactive-ok" not in all_s3_keys


async def test_purge_cascade_synthesis_failure_lands_in_failed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A cascade synthesis that fails to delete (non-credential) → appears in failed, not in
    cascade_deleted; the source inactive artifacts are still purged."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    original_delete_object = s3_client.delete_object

    def fail_for_synthesis(key: str) -> None:
        if key == "artifacts/synthesis-cascade":
            raise RuntimeError("Simulated synthesis delete failure")
        original_delete_object(key)

    mocker.patch.object(s3_client, "delete_object", side_effect=fail_for_synthesis)

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    failed_ids = [f["artifact_id"] for f in result["failed"]]
    assert "artifacts/synthesis-cascade" in failed_ids
    assert "artifacts/synthesis-cascade" not in result["cascade_deleted"]

    # Source inactive artifacts are still purged
    assert "artifacts/inactive-t2" in result["purged_ids"]
    assert "artifacts/inactive-t3" in result["purged_ids"]


async def test_purge_multiple_failures_aggregated(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Multiple non-credential failures in one purge → all appear in failed; all successful
    deletions appear in purged_ids."""
    settings = _make_settings(monkeypatch)
    _seed_inactive(s3_client, vectors_client_2, "artifacts/fail-a", vec=[1.0, 0.0])
    _seed_inactive(s3_client, vectors_client_2, "artifacts/fail-b", vec=[0.9, 0.1])
    _seed_inactive(s3_client, vectors_client_2, "artifacts/ok-c", vec=[0.8, 0.2])

    original_delete_object = s3_client.delete_object

    def fail_two(key: str) -> None:
        if key in ("artifacts/fail-a", "artifacts/fail-b"):
            raise RuntimeError(f"Simulated failure on {key}")
        original_delete_object(key)

    mocker.patch.object(s3_client, "delete_object", side_effect=fail_two)

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    failed_ids = {f["artifact_id"] for f in result["failed"]}
    assert failed_ids == {"artifacts/fail-a", "artifacts/fail-b"}
    assert result["purged_ids"] == ["artifacts/ok-c"]
    assert result["purged_count"] == 1
    # No failed artifact leaks into purged_ids
    assert not failed_ids & set(result["purged_ids"])


# ---------------------------------------------------------------------------
# Credential failures — discovery phase aborts with no deletes
# ---------------------------------------------------------------------------


async def test_purge_list_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_vectors_by_metadata (discovery) CredentialError → structured error, no deletes."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    spy_delete = mocker.spy(s3_client, "delete_object")
    mocker.patch.object(
        vectors_client_2,
        "list_vectors_by_metadata",
        side_effect=_credential_error("s3vectors"),
    )

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert result["error"] == ErrorCode.CREDENTIAL_ERROR
    assert spy_delete.call_count == 0


async def test_purge_get_vectors_cascade_credential_error_no_deletes(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """get_vectors during cascade discovery CredentialError → structured error, no deletes."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    spy_delete = mocker.spy(s3_client, "delete_object")
    mocker.patch.object(
        vectors_client_2,
        "get_vectors",
        side_effect=_credential_error("s3vectors"),
    )

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert result["error"] == ErrorCode.CREDENTIAL_ERROR
    assert spy_delete.call_count == 0


# ---------------------------------------------------------------------------
# Credential failures — deletion phase aborts, reports purged-so-far
# ---------------------------------------------------------------------------


async def test_purge_delete_vectors_credential_error_mid_loop_aborts(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """delete_vectors raises CredentialError mid-loop → deletion phase aborts; structured
    credential error; artifacts purged before the failure are in purged_ids."""
    settings = _make_settings(monkeypatch)
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-a", vec=[1.0, 0.0])
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-b", vec=[0.9, 0.1])

    original_delete_vectors = vectors_client_2.delete_vectors
    seen: list[str] = []

    def fail_second(keys: list[str]) -> None:
        seen.append(keys[0])
        if len(seen) >= 2:
            raise _credential_error("s3vectors")
        original_delete_vectors(keys)

    mocker.patch.object(vectors_client_2, "delete_vectors", side_effect=fail_second)

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert result["error"] == ErrorCode.CREDENTIAL_ERROR
    # First artifact (fully deleted before the credential failure) is reported as purged.
    assert len(result["purged_ids"]) == 1


async def test_purge_delete_object_credential_error_mid_loop_aborts(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """delete_object raises CredentialError mid-loop → deletion phase aborts; structured
    credential error; artifacts purged before the failure are in purged_ids."""
    settings = _make_settings(monkeypatch)
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-a", vec=[1.0, 0.0])
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-b", vec=[0.9, 0.1])

    original_delete_object = s3_client.delete_object
    seen: list[str] = []

    def fail_second(key: str) -> None:
        seen.append(key)
        if len(seen) >= 2:
            raise _credential_error("s3")
        original_delete_object(key)

    mocker.patch.object(s3_client, "delete_object", side_effect=fail_second)

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert result["error"] == ErrorCode.CREDENTIAL_ERROR
    assert len(result["purged_ids"]) == 1
    # The id purged before the abort is the first one deleted.
    assert result["purged_ids"] == [seen[0]]


async def test_purge_single_artifact_delete_object_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """CredentialError during the only S3 delete → credential_error response, nothing purged."""
    settings = _make_settings(monkeypatch)
    _seed_inactive(s3_client, vectors_client_2, "artifacts/inactive-t2")
    mocker.patch.object(
        s3_client,
        "delete_object",
        side_effect=_credential_error("s3"),
    )

    result = await purge_archived(
        settings=settings, s3=s3_client, vectors=vectors_client_2, bedrock=None, confirm=True
    )

    assert result["error"] == ErrorCode.CREDENTIAL_ERROR
    assert result["purged_ids"] == []
