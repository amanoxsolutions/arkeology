"""Unit tests for arkeology.tools.delete.

Tests delete_artifact() using moto-backed S3ClientImpl + VectorsClientImpl.
"""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import CredentialError
from arkeology.tools._search_helper import find_referrers
from arkeology.tools.archive import archive_artifact
from arkeology.tools.delete import delete_artifact
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, READ_PREFIXES="other-team", **overrides)


def _find_eq_clauses(expr: Any, field: str) -> list[Any]:
    """Recursively collect every ``{field: {"$eq": value}}`` clause's value in ``expr``.

    Walks ``$and``/``$or`` lists and nested dicts so assertions can be made against
    the exact filter shapes built by ``find_referrers`` without over-specifying
    clause ordering.
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
    "tags": "auth",
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
# T50 — unified own-scope referenced_by check (source_artifacts only, as of T60 —
# see the T60 block below for why `references` was narrowed out)
# ---------------------------------------------------------------------------


async def test_delete_referenced_via_references_field_no_longer_warns(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """T60: an own-scope artifact referencing the delete target only via `references`
    is NO LONGER reported in the warning — the `references`-half of the reverse-lookup
    was narrowed out (T58 stopped writing `references` to vector metadata). The
    `source_artifacts`-based mechanism (the pre-existing synthesis referrers seeded by
    `_seed_all`) is unaffected, proving the two mechanisms are independent and only one
    was narrowed."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    # Own-scope referrer whose `references` field points at the delete target — must
    # NOT be found post-T60.
    s3_client.put_object(
        "artifacts/referrer-via-refs",
        _CONTENT,
        {**_BASE_S3_META, "type": "adr"},
    )
    vectors_client_2.put_vector(
        "artifacts/referrer-via-refs#summary",
        [0.5, 0.5],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/referrer-via-refs",
            "type": "adr",
            "references": ["artifacts/t2-active"],
        },
    )
    spy_list = mocker.spy(vectors_client_2, "list_vectors_by_metadata")

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
    assert "artifacts/referrer-via-refs" not in warnings
    # source_artifacts-based referrers (seeded by _seed_all) are still found.
    assert "artifacts/synthesis-one" in warnings
    assert "artifacts/synthesis-two" in warnings

    # No list_vectors_by_metadata call ever carries a server-side $eq on "references" —
    # REFERENCE_FIELDS no longer contains it.
    for call in spy_list.call_args_list:
        filter_expr = call.args[0] if call.args else call.kwargs["filter_expr"]
        assert _find_eq_clauses(filter_expr, "references") == []


async def test_delete_never_issues_server_side_eq_on_source_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The non-filterable `source_artifacts` field is NEVER used in a server-side
    $eq clause — resolved only via the type=synthesis prefilter + in-process check."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    spy_list = mocker.spy(vectors_client_2, "list_vectors_by_metadata")

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    # Sanity: the synthesis referrers are still found (existing behaviour preserved).
    warnings = result.get("warnings", [])
    assert "artifacts/synthesis-one" in warnings
    assert "artifacts/synthesis-two" in warnings

    for call in spy_list.call_args_list:
        filter_expr = call.args[0] if call.args else call.kwargs["filter_expr"]
        assert _find_eq_clauses(filter_expr, "source_artifacts") == []


def test_find_referrers_issues_single_list_vectors_by_metadata_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """find_referrers must not issue two separate full-index
    list_vectors_by_metadata scans per delete/archive call — one for the
    filterable-fields ($or of reference-field $eq clauses) branch, one for the
    non-filterable source_artifacts / type=synthesis prefilter branch. Both
    predicates are safely combinable under one top-level $or (own-scope + active +
    ($or: [references $eq target, type=synthesis])), with in-process branching per
    candidate's type deciding which check applies — so a single query suffices
    without changing find_referrers' documented return value."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    spy_list = mocker.spy(vectors_client_2, "list_vectors_by_metadata")

    referrers = find_referrers(
        vectors=vectors_client_2, settings=settings, artifact_id="artifacts/t2-active"
    )

    # Existing behaviour (both referrer mechanisms) must be preserved by the merge.
    assert "artifacts/synthesis-one" in referrers
    assert "artifacts/synthesis-two" in referrers
    assert spy_list.call_count == 1


# ---------------------------------------------------------------------------
# T60 — narrow the reverse-lookup warning to source_artifacts only
# ---------------------------------------------------------------------------


async def test_delete_source_artifacts_dedupe_unaffected_by_references_narrowing(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """T60: with `references` narrowed out, a `references`-only referrer never appears
    in the warning, while the remaining `source_artifacts`-based referrers are still
    found and still deduplicated (each appears exactly once, even with multiple
    section vectors) — the narrowing removes one mechanism entirely rather than
    degrading the one that remains."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)
    s3_client.put_object(
        "artifacts/referrer-via-refs-2",
        _CONTENT,
        {**_BASE_S3_META, "type": "adr"},
    )
    vectors_client_2.put_vector(
        "artifacts/referrer-via-refs-2#summary",
        [0.4, 0.6],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/referrer-via-refs-2",
            "type": "adr",
            "references": ["artifacts/t2-active"],
        },
    )

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
    assert "artifacts/referrer-via-refs-2" not in warnings
    # Deduplicated — each referrer appears exactly once even though it may have
    # multiple section vectors.
    assert len(warnings) == len(set(warnings))


async def test_delete_foreign_scope_referrer_never_listed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """A foreign-scope artifact referencing T via `references` is NEVER listed as a
    referrer — the own-scope filter clause excludes it."""
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
            "references": ["artifacts/t2-active"],
        },
    )

    result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    warnings = result.get("warnings", [])
    assert "other-team/foreign-referrer" not in warnings


async def test_delete_warning_message_stronger_than_archive(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """The delete warning is phrased as a stronger, permanent-action warning while
    the archive warning is phrased as informational/reversible for the same
    referenced-artifact scenario."""
    settings = _make_settings(monkeypatch)
    _seed_all(s3_client, vectors_client_2)

    delete_result = await delete_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active",
        confirm=True,
    )

    # Re-seed an equivalent scenario for archive (delete already removed t2-active).
    s3_client.put_object("artifacts/t2-active-2", _CONTENT, {**_BASE_S3_META, "tier": "2"})
    vectors_client_2.put_vector(
        "artifacts/t2-active-2#summary",
        [1.0, 0.0],
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-active-2", "tier": 2},
    )
    s3_client.put_object(
        "artifacts/synthesis-three",
        _CONTENT,
        {
            **_BASE_S3_META,
            "type": "synthesis",
            "source_artifacts": "artifacts/t2-active-2",
            "status": "active",
        },
    )
    vectors_client_2.put_vector(
        "artifacts/synthesis-three#summary",
        [0.7, 0.3],
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/synthesis-three",
            "type": "synthesis",
            "source_artifacts": ["artifacts/t2-active-2"],
            "status": "active",
        },
    )

    archive_result = await archive_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=None,
        artifact_id="artifacts/t2-active-2",
    )

    delete_message = delete_result.get("warning_message", "").lower()
    archive_message = archive_result.get("warning_message", "").lower()
    assert delete_message and archive_message
    assert "revers" not in delete_message
    assert "revers" in archive_message
    assert "permanent" in delete_message or "cannot be undone" in delete_message


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
