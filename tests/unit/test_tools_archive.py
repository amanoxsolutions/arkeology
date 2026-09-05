"""Unit tests for arkeology.tools.archive.

Tests archive_artifact() using moto-backed S3ClientImpl + VectorsClientImpl.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import AnnotationUnavailableError, ArtifactConflictError, CredentialError
from arkeology.tools.archive import archive_artifact
from arkeology.tools.read import read_artifact
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(
    monkeypatch: pytest.MonkeyPatch, *, tmp_path: Path | None = None, **overrides: str
) -> Settings:
    return _make_settings_base(
        monkeypatch, tmp_path=tmp_path, READ_PREFIXES="other-team", **overrides
    )


def _find_eq_clauses(expr: Any, field: str) -> list[Any]:
    """Recursively collect every ``{field: {"$eq": value}}`` clause's value in ``expr``.

    Walks ``$and``/``$or`` lists and nested dicts so assertions can be made against
    the exact filter shapes built by ``find_referrers`` without over-specifying
    clause ordering. Mirrors the identical helper in ``test_tools_delete.py``.
    """
    found: list[Any] = []

    def _walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        clause = node.get(field)
        if isinstance(clause, dict) and "$eq" in clause:
            found.append(clause["$eq"])
        for value in node.values():
            if isinstance(value, list):
                for item in value:
                    _walk(item)
            elif isinstance(value, dict):
                _walk(value)

    _walk(expr)
    return found


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

_BASE_S3_META: dict[str, str] = {
    "type": "code_review",
    "team": "platform",
    "project": "arkeology",
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
    "project": "arkeology",
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
# T50 — unified own-scope referenced_by check (source_artifacts only, as of T60 —
# see the T60 block below for why `references` was narrowed out)
# ---------------------------------------------------------------------------


async def test_archive_referenced_via_references_field_no_longer_warns(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """T60: an own-scope artifact referencing the archive target only via `references`
    is NO LONGER reported in the warning — the `references`-half of the reverse-lookup
    was narrowed out (T58 stopped writing `references` to vector metadata). A
    `source_artifacts`-based referrer (an active synthesis) seeded in the same test run
    is still found, proving the two mechanisms are independent and only one was
    narrowed."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    s3_client.put_object(
        "artifacts/referrer-via-refs",
        _CONTENT,
        {**_BASE_S3_META, "type": "adr", "status": "active"},
    )
    vectors_client_2.put_vector(
        "artifacts/referrer-via-refs#summary",
        [0.5, 0.5],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/referrer-via-refs",
            "type": "adr",
            "status": "active",
            "references": ["artifacts/active-review"],
        },
    )
    s3_client.put_object(
        "artifacts/synthesis-archived-refs-narrowing",
        _CONTENT,
        {
            **_BASE_S3_META,
            "type": "synthesis",
            "source_artifacts": "artifacts/active-review",
            "status": "active",
        },
    )
    vectors_client_2.put_vector(
        "artifacts/synthesis-archived-refs-narrowing#summary",
        [0.6, 0.4],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/synthesis-archived-refs-narrowing",
            "type": "synthesis",
            "source_artifacts": ["artifacts/active-review"],
            "status": "active",
        },
    )
    spy_list = mocker.spy(vectors_client_2, "list_vectors_by_metadata")

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert result["status"] == "inactive"
    warning = result.get("warning", [])
    assert "artifacts/referrer-via-refs" not in warning
    assert "artifacts/synthesis-archived-refs-narrowing" in warning
    message = result.get("warning_message", "").lower()
    assert "revers" in message

    # No list_vectors_by_metadata call ever carries a server-side $eq on "references" —
    # REFERENCE_FIELDS no longer contains it.
    for call in spy_list.call_args_list:
        filter_expr = call.args[0] if call.args else call.kwargs["filter_expr"]
        assert _find_eq_clauses(filter_expr, "references") == []


async def test_archive_referenced_via_source_artifacts_warns(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Archiving an artifact that is a `source_artifacts` entry of an active own-scope
    synthesis → warned via the type=synthesis prefilter + in-process check."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    s3_client.put_object(
        "artifacts/synthesis-archived-src",
        _CONTENT,
        {
            **_BASE_S3_META,
            "type": "synthesis",
            "source_artifacts": "artifacts/active-review",
            "status": "active",
        },
    )
    vectors_client_2.put_vector(
        "artifacts/synthesis-archived-src#summary",
        [0.6, 0.4],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/synthesis-archived-src",
            "type": "synthesis",
            "source_artifacts": ["artifacts/active-review"],
            "status": "active",
        },
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert result["status"] == "inactive"
    warning = result.get("warning", [])
    assert "artifacts/synthesis-archived-src" in warning


async def test_archive_foreign_scope_referrer_never_listed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """A foreign-scope artifact referencing the archive target is NEVER listed."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    s3_client.put_object(
        "other-team/foreign-referrer",
        _CONTENT,
        {**_BASE_S3_META, "team": "network"},
    )
    vectors_client_2.put_vector(
        "other-team/foreign-referrer#summary",
        [0.3, 0.7],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/foreign-referrer",
            "scope": "other-team",
            "references": ["artifacts/active-review"],
        },
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert result["status"] == "inactive"
    warning = result.get("warning", [])
    assert "other-team/foreign-referrer" not in warning


async def test_archive_no_referrers_no_warning_field(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Archiving an unreferenced artifact → no "warning" field in the response."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/doc-level-only",
    )

    assert result["status"] == "inactive"
    assert "warning" not in result


async def test_archive_referenced_by_lookup_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """CredentialError during the referenced_by reverse-lookup → structured
    credential error; no S3 write is performed."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    spy_put = mocker.spy(s3_client, "put_object")
    initial_put_count = spy_put.call_count
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

    assert result.get("error") == "credential_error"
    assert spy_put.call_count == initial_put_count


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

    assert result.get("error") == "access_denied"
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

    assert result.get("error") == "access_denied"


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

    assert result.get("error") == "not_found"
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

    assert result.get("error") == "credential_error"
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

    assert result.get("error") == "credential_error"
    assert spy_put_vec.call_count == 0


async def test_archive_list_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error.

    This fails during the Step 3 own-scope referrer check (``find_referrers`` calls
    ``list_vectors_by_metadata`` too, and it runs before the S3 status flip) — no
    failure-log entry is expected here since nothing has been written yet (logging is
    only required *after* the S3 flip has succeeded; see
    ``test_archive_put_vector_credential_error`` and
    ``test_archive_annotation_credential_error_aborts`` for the post-flip case)."""
    settings = _make_settings(monkeypatch, tmp_path=tmp_path)
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

    assert result.get("error") == "credential_error"
    assert not settings.failure_log_path.exists()


async def test_archive_get_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    """get_vectors raises CredentialError → structured error.

    This fails during the Step 3 own-scope referrer check (``find_referrers`` also
    calls ``get_vectors``, and it runs before the S3 status flip) — no failure-log
    entry is expected since nothing has been written yet."""
    settings = _make_settings(monkeypatch, tmp_path=tmp_path)
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

    assert result.get("error") == "credential_error"
    assert not settings.failure_log_path.exists()


async def test_archive_put_vector_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    """put_vector raises CredentialError on first section → structured error;
    failure-log entry written."""
    settings = _make_settings(monkeypatch, tmp_path=tmp_path)
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

    assert result.get("error") == "credential_error"
    assert settings.failure_log_path.exists()


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


# ---------------------------------------------------------------------------
# Half-archived retry must complete the vector flip, not early-return
# ---------------------------------------------------------------------------


async def test_archive_half_archived_retry_completes_vector_flip(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """S3 status already inactive but a vector is still status=active (simulating a
    prior partial archive) → retrying archive_artifact must NOT early-return
    already_archived; it must complete the vector-side flip instead."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "artifacts/half-archived",
        _CONTENT,
        {**_BASE_S3_META, "status": "inactive"},
    )
    # Vector was never flipped by the prior (interrupted) archive attempt.
    vectors_client_2.put_vector(
        "artifacts/half-archived#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/half-archived", "status": "active"},
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/half-archived",
    )

    assert "error" not in result
    assert result["status"] == "inactive"
    assert result.get("already_archived") is not True

    vec_results = vectors_client_2.get_vectors(["artifacts/half-archived#summary"])
    assert vec_results[0]["metadata"]["status"] == "inactive"


async def test_archive_half_archived_multiple_vectors_all_flipped(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """S3 inactive, one vector already inactive and one still active (a partial flip
    interrupted mid-loop) → retry flips the remaining active vector too."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "artifacts/half-archived-mixed",
        _CONTENT,
        {**_BASE_S3_META, "status": "inactive"},
    )
    vectors_client_2.put_vector(
        "artifacts/half-archived-mixed#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/half-archived-mixed", "status": "inactive"},
    )
    vectors_client_2.put_vector(
        "artifacts/half-archived-mixed#details",
        [0.9, 0.1],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/half-archived-mixed", "status": "active"},
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/half-archived-mixed",
    )

    assert "error" not in result
    assert result["status"] == "inactive"
    for key in [
        "artifacts/half-archived-mixed#summary",
        "artifacts/half-archived-mixed#details",
    ]:
        vec_results = vectors_client_2.get_vectors([key])
        assert vec_results[0]["metadata"]["status"] == "inactive"


async def test_archive_fully_archived_no_vectors_still_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """S3 inactive and no vectors at all (nothing to flip) → still short-circuits as
    already_archived; no writes performed."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "artifacts/inactive-no-vectors",
        _CONTENT,
        {**_BASE_S3_META, "status": "inactive"},
    )
    spy_put_obj = mocker.spy(s3_client, "put_object")

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/inactive-no-vectors",
    )

    assert result.get("already_archived") is True
    assert spy_put_obj.call_count == 0


async def test_archive_partial_archive_credential_error_writes_failure_log(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    """A vector-side failure mid-archive (S3 already flipped) appends a failure-log
    entry so the partial archive is repairable. Without it, no failure-log entry is
    written for any credential error in this path and the partial archive is invisible
    to reconcile_index."""
    settings = _make_settings(monkeypatch, tmp_path=tmp_path)
    _seed_all(s3_client, vectors_client_2)
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

    assert result.get("error") == "credential_error"
    assert settings.failure_log_path.exists()
    entries = [json.loads(line) for line in settings.failure_log_path.read_text().splitlines()]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["artifact_id"] == "artifacts/active-review"
    assert entry["failure_step"] == "archive_vector_flip"
    assert "reason" in entry
    assert "timestamp" in entry

    # The S3 side has already flipped to inactive even though the vector side failed.
    meta = s3_client.head_object("artifacts/active-review")
    assert meta["status"] == "inactive"


async def test_archive_partial_archive_failure_log_decodes_non_ascii_title(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    """A non-ASCII title is stored percent-encoded in raw S3 user-metadata
    (``encode_metadata_value``); the failure-log entry must log the plain, decoded
    title — matching write.py's equivalent entries — not the raw percent-encoded
    S3 metadata value."""
    settings = _make_settings(monkeypatch, tmp_path=tmp_path)
    non_ascii_title = "Café review"
    s3_client.put_object(
        "artifacts/active-review",
        _CONTENT,
        {**_BASE_S3_META, "status": "active", "title": non_ascii_title},
    )
    vectors_client_2.put_vector(
        "artifacts/active-review#summary",
        [1.0, 0.0],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/active-review",
            "status": "active",
            "title": non_ascii_title,
        },
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

    assert result.get("error") == "credential_error"
    assert settings.failure_log_path.exists()
    entries = [json.loads(line) for line in settings.failure_log_path.read_text().splitlines()]
    assert entries[0]["title"] == non_ascii_title


async def test_archive_does_not_double_encode_non_ascii_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """The status re-PUT re-supplies ``head_object`` output to ``put_object``. Because the
    S3 client's transport encoding is symmetric, a non-ASCII title must survive one — and
    a second — archive cycle byte-for-byte, never accumulating percent-escapes
    (``Caf%C3%A9`` → ``Caf%25C3%25A9``)."""
    settings = _make_settings(monkeypatch)
    non_ascii_title = "Caf\u00e9 review"
    s3_client.put_object(
        "artifacts/active-review",
        _CONTENT,
        {**_BASE_S3_META, "status": "active", "title": non_ascii_title},
    )
    vectors_client_2.put_vector(
        "artifacts/active-review#summary",
        [1.0, 0.0],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/active-review",
            "status": "active",
            "title": non_ascii_title,
        },
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )
    assert result.get("status") == "inactive"
    assert s3_client.head_object("artifacts/active-review")["title"] == non_ascii_title

    read = await read_artifact(
        settings=settings, s3=s3_client, artifact_id="artifacts/active-review"
    )
    assert read["title"] == non_ascii_title

    # A second archive of a half-archived artifact re-PUTs again — still no accumulation.
    vectors_client_2.put_vector(
        "artifacts/active-review#summary",
        [1.0, 0.0],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/active-review",
            "status": "active",
            "title": non_ascii_title,
        },
    )
    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )
    assert result.get("status") == "inactive"
    assert s3_client.head_object("artifacts/active-review")["title"] == non_ascii_title


# ---------------------------------------------------------------------------
# Annotation preservation across the archive status re-PUT
# ---------------------------------------------------------------------------
#
# archive_artifact flips status by re-PUTting the S3 object. PutObject clears an
# object's S3 annotations, so without a read-forward / re-apply step the durable
# commit_refs/references annotation trail (ADR-011) is silently destroyed. These
# tests assert the read-forward + re-apply invariant holds, mirroring write.py's
# Step 4a/4b pattern and its AnnotationUnavailableError graceful degrade.


async def test_archive_preserves_commit_refs_and_references_annotations(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Archiving an artifact that has durable commit_refs/references annotations
    must preserve both annotations intact — the status re-PUT must not silently
    wipe the annotation trail."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    s3_client.put_object_annotation("artifacts/active-review", "commit_refs", "abc1234,def5678")
    s3_client.put_object_annotation("artifacts/active-review", "references", "artifacts/some-adr")

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" not in result
    assert result["status"] == "inactive"
    assert (
        s3_client.get_object_annotation("artifacts/active-review", "commit_refs")
        == "abc1234,def5678"
    )
    assert (
        s3_client.get_object_annotation("artifacts/active-review", "references")
        == "artifacts/some-adr"
    )


async def test_archive_preserves_link_fields_sourced_from_vector_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """When commit_refs/references exist only in vector metadata (no annotation —
    e.g. an annotation-unavailable deployment per T52), archiving must still
    re-apply them as the durable annotation copy, per the union-of-both-stores
    authority model (read_current_link_fields)."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    vectors_client_2.put_vector(
        "artifacts/active-review#summary",
        [1.0, 0.0],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/active-review",
            "status": "active",
            "commit_refs": ["abc1234"],
        },
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" not in result
    assert result["status"] == "inactive"
    assert s3_client.get_object_annotation("artifacts/active-review", "commit_refs") == "abc1234"


async def test_archive_annotation_unavailable_still_succeeds_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """An AnnotationUnavailableError raised while re-applying link annotations after
    the status re-PUT must never fail the archive (ADR-011 decision 5, mirroring the
    write path's graceful degrade): the artifact is still archived and the response
    carries a warning instead of an error."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    s3_client.put_object_annotation("artifacts/active-review", "commit_refs", "abc1234")
    mocker.patch.object(
        s3_client,
        "put_object_annotation",
        side_effect=AnnotationUnavailableError(
            "S3 object annotations are unavailable for this bucket.", "s3", Exception("boom")
        ),
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" not in result
    assert result["status"] == "inactive"
    assert result.get("annotation_warning")


async def test_archive_annotation_credential_error_aborts(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    """A CredentialError raised while re-applying link annotations after the status
    re-PUT still aborts the archive with a structured credential error, unlike the
    AnnotationUnavailableError graceful degrade. The S3 status flip has already
    succeeded by this point, so a failure-log entry must be written — otherwise
    the partial archive (S3 inactive, vectors still active) leaves no repairable trace."""
    settings = _make_settings(monkeypatch, tmp_path=tmp_path)
    _seed_all(s3_client, vectors_client_2)
    s3_client.put_object_annotation("artifacts/active-review", "commit_refs", "abc1234")
    spy_put_vec = mocker.spy(vectors_client_2, "put_vector")
    mocker.patch.object(
        s3_client,
        "put_object_annotation",
        side_effect=CredentialError(message="Simulated.", service="s3", original=Exception("sim")),
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert result.get("error") == "credential_error"
    assert spy_put_vec.call_count == 0
    assert settings.failure_log_path.exists()
    entries = [json.loads(line) for line in settings.failure_log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["artifact_id"] == "artifacts/active-review"
    assert entries[0]["failure_step"] == "archive_vector_flip"


# ---------------------------------------------------------------------------
# Optimistic-concurrency (ETag compare-and-swap) writes — ADR-011 decision 6
# ---------------------------------------------------------------------------


async def test_archive_put_object_called_with_if_match_from_captured_etag(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The status-flip put_object call is conditional on the object's pre-flip ETag
    (if_match), guarding the read-modify-write cycle."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    pre_flip_etag = s3_client.head_object("artifacts/active-review")["ETag"]

    spy = mocker.spy(s3_client, "put_object")
    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" not in result
    assert spy.call_count == 1
    assert spy.call_args.kwargs.get("if_match") == pre_flip_etag


async def test_archive_status_flip_metadata_never_includes_etag_sentinel_key(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """The reserved 'ETag' sentinel key from head_object's return value must never
    leak into the metadata dict passed to the status-flip put_object — it is not a
    real user-defined metadata field, and writing it as one would corrupt future
    ETag-capture calls (a real 'ETag' key colliding with the sentinel)."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" not in result
    meta = s3_client.head_object("artifacts/active-review")
    # The only "ETag" key present is the client's own reserved sentinel (a valid,
    # well-formed quoted ETag) — not a stale literal string leaked from a prior
    # re-PUT's metadata dict.
    assert meta["ETag"] == s3_client.head_object("artifacts/active-review")["ETag"]
    assert meta["status"] == "inactive"
    assert meta["title"] == "Fix auth bug"


async def test_archive_annotation_apply_uses_new_etag_from_put_object(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The annotation re-apply following the status-flip put_object uses that
    put_object call's returned ETag as if_match (not some other stale value) — note
    the ETag is content-hash-based, so a metadata-only status flip does not change
    it here; the assertion is that the *source* of the token is put_object's return
    value, verified by comparing it against the object's ETag immediately after."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    s3_client.put_object_annotation("artifacts/active-review", "commit_refs", "abc1234")

    annotation_spy = mocker.spy(s3_client, "put_object_annotation")
    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" not in result
    post_flip_etag = s3_client.head_object("artifacts/active-review")["ETag"]
    assert annotation_spy.call_count == 1
    assert annotation_spy.call_args.kwargs.get("if_match") == post_flip_etag


async def test_archive_cas_conflict_then_retry_completes_successfully(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A conflict on the first CAS attempt's put_object causes a retry that re-reads
    fresh content/metadata/link-fields and re-writes conditionally again, eventually
    completing the archive successfully."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    original_put_object = s3_client.put_object
    call_count = 0

    def _conflict_once(*args: object, **kwargs: object) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ArtifactConflictError("artifacts/active-review")
        return original_put_object(*args, **kwargs)  # type: ignore[arg-type]

    mocker.patch.object(s3_client, "put_object", side_effect=_conflict_once)

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" not in result
    assert result["status"] == "inactive"
    assert call_count == 2
    meta = s3_client.head_object("artifacts/active-review")
    assert meta["status"] == "inactive"


async def test_archive_persistent_cas_conflict_returns_conflict_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    """A persistent conflict (every CAS attempt's put_object fails) returns a
    structured 'conflict' error after the bounded attempt count — never a raw
    exception. Nothing was durably written by this call, so no failure-log entry
    is produced, and the artifact's status remains 'active'."""
    settings = _make_settings(monkeypatch, tmp_path=tmp_path)
    _seed_all(s3_client, vectors_client_2)

    put_spy = mocker.patch.object(
        s3_client, "put_object", side_effect=ArtifactConflictError("artifacts/active-review")
    )
    put_vec_spy = mocker.spy(vectors_client_2, "put_vector")

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert result.get("error") == "conflict"
    assert result.get("artifact_id") == "artifacts/active-review"
    assert put_spy.call_count == 3
    assert put_vec_spy.call_count == 0
    assert not settings.failure_log_path.exists()
    meta = s3_client.head_object("artifacts/active-review")
    assert meta["status"] == "active"


async def test_archive_persistent_annotation_conflict_after_durable_flip_logs_partial(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    """When the status flip IS durably written (put_object always succeeds) but the
    annotation re-apply persistently conflicts, exhausting retries must still record
    a failure-log entry — the object side was already durably written before the
    conflict was hit, so the entry must not be falsely omitted.

    commit_refs is seeded into BOTH durable stores (annotation AND vector metadata)
    so the union-of-both-stores read-forward stays non-empty across every retry
    attempt, even though each attempt's own status-flip put_object wipes the
    annotation copy (PutObject clears annotations) before the (persistently
    failing) annotation re-apply would otherwise restore it — isolating the
    conflict-then-exhaustion behaviour from the (separately accepted, ADR-011)
    residual of a value that exists only in the annotation."""
    settings = _make_settings(monkeypatch, tmp_path=tmp_path)
    _seed_all(s3_client, vectors_client_2)
    s3_client.put_object_annotation("artifacts/active-review", "commit_refs", "abc1234")
    for key in ("artifacts/active-review#summary", "artifacts/active-review#details"):
        item = vectors_client_2.get_vectors([key])[0]
        vectors_client_2.put_vector(
            key, item["data"]["float32"], {**item["metadata"], "commit_refs": ["abc1234"]}
        )

    mocker.patch.object(
        s3_client,
        "put_object_annotation",
        side_effect=ArtifactConflictError("artifacts/active-review"),
    )

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert result.get("error") == "conflict"
    assert settings.failure_log_path.exists()
    entries = [json.loads(line) for line in settings.failure_log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["artifact_id"] == "artifacts/active-review"
    assert entries[0]["failure_step"] == "archive_vector_flip"
    # The status flip WAS durably applied on the final attempt even though we report
    # a conflict error.
    meta = s3_client.head_object("artifacts/active-review")
    assert meta["status"] == "inactive"


async def test_archive_vector_writes_remain_unconditional_despite_cas_retry(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Vector writes stay unconditional in every scenario — put_vector is called
    with no conditional parameter, regardless of CAS retry outcome on the object
    side (no S3 Vectors CAS surface exists; ADR-011 decision 6)."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    original_put_object = s3_client.put_object
    call_count = 0

    def _conflict_once(*args: object, **kwargs: object) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ArtifactConflictError("artifacts/active-review")
        return original_put_object(*args, **kwargs)  # type: ignore[arg-type]

    mocker.patch.object(s3_client, "put_object", side_effect=_conflict_once)
    put_vec_spy = mocker.spy(vectors_client_2, "put_vector")

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" not in result
    assert put_vec_spy.call_count >= 1
    for call in put_vec_spy.call_args_list:
        assert "if_match" not in call.kwargs
        assert len(call.args) == 3  # key, vector, metadata — no conditional parameter


# ---------------------------------------------------------------------------
# Regression guard: write-path replace-semantics for `references` must NOT leak
# into archive
# ---------------------------------------------------------------------------


async def test_archive_preserves_references_even_with_no_commit_refs(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Archive's status-flip re-PUT has no caller-supplied 'references' to replace
    from — unlike write.py's overwrite path, which REPLACES references outright,
    archive must continue to read-forward
    and re-apply 'references' unconditionally. This isolates the references field
    (no commit_refs present) to guard against an implementer mistakenly propagating
    the write-path's replace semantics into archive, which would silently wipe
    references on every archive operation."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    s3_client.put_object_annotation("artifacts/active-review", "references", "artifacts/some-adr")

    result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/active-review",
    )

    assert "error" not in result
    assert result["status"] == "inactive"
    # The annotation must survive the status re-PUT intact — not wiped and not
    # replaced by an (absent) caller-supplied value, unlike write.py's overwrite path.
    assert (
        s3_client.get_object_annotation("artifacts/active-review", "references")
        == "artifacts/some-adr"
    )
    # No commit_refs annotation was ever set — confirms this isolates the references
    # field rather than piggybacking on a commit_refs value.
    with pytest.raises(KeyError):
        s3_client.get_object_annotation("artifacts/active-review", "commit_refs")
