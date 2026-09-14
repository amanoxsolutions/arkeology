"""Unit tests for arkeology.tools.list.

Tests list_artifacts() using moto-backed VectorsClientImpl and S3ClientImpl — the link
fields are read from each artifact's S3 object annotations. No Bedrock calls.
"""

import math
import threading
from typing import Any

import pytest
from pytest_mock import MockerFixture

from arkeology.annotations import apply_link_annotations
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import AnnotationUnavailableError, CredentialError
from arkeology.tools.list import list_artifacts
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, READ_PREFIXES="other-team", **overrides)


# ---------------------------------------------------------------------------
# Vector seed helpers
# ---------------------------------------------------------------------------


def _unit_vec(seed: float, dim: int = 8) -> list[float]:
    raw = [seed + i * 0.1 for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


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


def _put_listable(
    vectors: VectorsClientImpl,
    s3: S3ClientImpl,
    key: str,
    vector: list[float],
    meta: dict[str, Any],
) -> None:
    """Seed a section vector and, unless one already exists, the S3 object behind it.

    An artifact with no object is a *dangling* artifact: ``list_artifacts`` reads every
    listed artifact's durable link annotations, and one whose object is found to be gone
    is omitted from the page and counted under ``skipped_deleted_count``. Seeding only
    vectors would therefore model a condition no test in this file means to exercise.

    An existing object is left alone, because ``put_object`` clears an object's
    annotations — real S3 semantics, mirrored by the moto self-mock — and would wipe a
    link annotation the test had just applied.
    """
    vectors.put_vector(key, vector, meta)
    artifact_id = meta.get("artifact_id")
    if not artifact_id:
        return
    try:
        s3.head_object(artifact_id)
    except KeyError:
        s3.put_object(artifact_id, "## Summary\n\nseeded", {"title": "seeded"})


def _seed_vectors(vectors: VectorsClientImpl, s3: S3ClientImpl) -> None:
    """Seed a rich set of vectors for list tests, and the S3 object each one names.

    The object is not optional decoration. ``list_artifacts`` reads every listed
    artifact's durable link-field annotations, and an artifact whose object is found to
    be gone is omitted from the page and counted under ``skipped_deleted_count``. A
    vector with no object behind it is a dangling artifact — the condition
    ``reconcile_index`` prunes — not a listable one, so seeding vectors alone would model
    something no test in this file means to exercise.
    """

    def _put(key: str, vector: list[float], meta: dict[str, Any]) -> None:
        _put_listable(vectors, s3, key, vector, meta)

    # own-scope active tier 2 (two section vectors — dedup test)
    for section in ["#summary", "#details"]:
        _put(
            f"artifacts/t2-active-review{section}",
            _unit_vec(1.0),
            {
                **_BASE_VECTOR_META,
                "artifact_id": "artifacts/t2-active-review",
                "tier": 2,
                "status": "active",
                "type": "code_review",
                "tags": ["auth"],
            },
        )

    # own-scope active tier 3 shared (two section vectors)
    for section in ["#summary", "#details"]:
        _put(
            f"artifacts/t3-shared-adr{section}",
            _unit_vec(0.9),
            {
                **_BASE_VECTOR_META,
                "artifact_id": "artifacts/t3-shared-adr",
                "tier": 3,
                "visibility": "shared",
                "type": "adr",
                "tags": ["payments"],
                "status": "active",
            },
        )

    # own-scope inactive tier 2 (two section vectors)
    for section in ["#summary", "#details"]:
        _put(
            f"artifacts/t2-inactive-review{section}",
            _unit_vec(0.8),
            {
                **_BASE_VECTOR_META,
                "artifact_id": "artifacts/t2-inactive-review",
                "tier": 2,
                "status": "inactive",
                "type": "code_review",
                "tags": [],
            },
        )

    # own-scope active tier 2 code_review tagged "auth"
    _put(
        "artifacts/t2-auth-review#summary",
        _unit_vec(0.7),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/t2-auth-review",
            "tier": 2,
            "status": "active",
            "type": "code_review",
            "tags": ["auth"],
            "team": "platform",
            "project": "infra",
        },
    )

    # foreign-scope active tier 3 shared — ALLOWED
    _put(
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
            "tags": [],
        },
    )
    # second section vector for the foreign t3 shared — dedup test
    _put(
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
            "tags": [],
        },
    )

    # foreign-scope active tier 2 — DENIED
    _put(
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
            "tags": [],
        },
    )

    # foreign-scope active tier 3 hidden — DENIED
    _put(
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
            "tags": [],
        },
    )


# ---------------------------------------------------------------------------
# Default behaviour
# ---------------------------------------------------------------------------


async def test_no_filters_returns_own_scope_and_foreign_tier3_shared(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """No filters → own-scope active artifacts and foreign-scope tier 3 shared returned."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-active-review" in ids
    assert "artifacts/t3-shared-adr" in ids
    assert "other-team/t3-foreign-shared-adr" in ids


async def test_default_status_active_excludes_inactive(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """No status filter → status defaults to 'active'; inactive artifacts absent."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-inactive-review" not in ids


async def test_status_inactive_override_returns_only_inactive(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """status='inactive' → only inactive artifacts returned."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None, status="inactive"
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-inactive-review" in ids
    for artifact in result["artifacts"]:
        assert artifact["status"] == "inactive"


async def test_status_all_returns_active_and_inactive(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """status='all' → both active and inactive own-scope artifacts returned;
    previously the browser Studio's "All" filter was unreachable because omitting the
    status arg fell back to the "active" default."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None, status="all"
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-active-review" in ids
    assert "artifacts/t2-inactive-review" in ids


# ---------------------------------------------------------------------------
# Filter combinations
# ---------------------------------------------------------------------------


async def test_filter_type_code_review(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """type='code_review' → only code reviews in results."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None, type="code_review"
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert artifact["type"] == "code_review"


async def test_filter_tags(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """tags=['auth'] → only artifacts with 'auth' tag."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None, tags=["auth"]
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert "auth" in artifact["tags"]


async def test_filter_type_and_tags_intersection(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """type='code_review' + tags=['auth'] → intersection of both constraints."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
        type="code_review",
        tags=["auth"],
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert artifact["type"] == "code_review"
        assert "auth" in artifact["tags"]


async def test_filter_team(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """team='platform' → only platform team artifacts."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None, team="platform"
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert artifact["team"] == "platform"


async def test_filter_project(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """project='infra' → only infra project artifacts."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None, project="infra"
    )

    for artifact in result["artifacts"]:
        assert artifact["project"] == "infra"


async def test_filter_tier3(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """tier=3 → only tier 3 artifacts."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None, tier=3
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert artifact["tier"] == 3


async def test_no_matching_artifacts_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Filters that match no artifacts → empty list, no error."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
        type="session_summary",
    )

    assert result["artifacts"] == []


# ---------------------------------------------------------------------------
# Filter enum validation — typos must error, not silently return []
# ---------------------------------------------------------------------------


async def test_filter_type_typo_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """type='cod_review' (typo, not a real artifact type) must return
    validation_error — distinguishable from the legitimate zero-match case
    covered by test_no_matching_artifacts_returns_empty_list.
    """
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None, type="cod_review"
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for invalid type, got: {result}"
    )


async def test_filter_tier_out_of_range_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """tier=99 (not 2 or 3) must return validation_error, not a silent empty list."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None, tier=99
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for out-of-range tier, got: {result}"
    )


async def test_filter_status_typo_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """status='actve' (typo) must return validation_error, not a silent empty list."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None, status="actve"
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for invalid status, got: {result}"
    )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


async def test_deduplication_two_sections_one_record(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Two section vectors for same artifact_id → exactly one record in results."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert ids.count("artifacts/t2-active-review") == 1
    assert ids.count("other-team/t3-foreign-shared-adr") == 1


async def test_result_has_required_fields(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Each result contains all required metadata fields; no 'content' field."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    assert len(result["artifacts"]) > 0
    required = [
        "artifact_id",
        "type",
        "team",
        "project",
        "tier",
        "date",
        "status",
        "title",
        "visibility",
        "tags",
        "author_role",
        "description",
        "commit_refs",
        "references",
        "last_edited_ulid",
    ]
    for artifact in result["artifacts"]:
        for field in required:
            assert field in artifact, f"Missing field '{field}' in result: {artifact}"
        assert "content" not in artifact, "Unexpected 'content' field in list result"


async def test_tags_in_response_is_list(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """tags in response is a list, not a comma-separated string."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    for artifact in result["artifacts"]:
        assert isinstance(artifact["tags"], list), f"Expected list, got {type(artifact['tags'])}"


# ---------------------------------------------------------------------------
# Cross-scope gate
# ---------------------------------------------------------------------------


async def test_foreign_tier3_shared_included(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Foreign-scope tier 3 shared artifact appears in results."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-foreign-shared-adr" in ids


async def test_foreign_tier2_excluded(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Foreign-scope tier 2 artifact is excluded from results."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t2-foreign-review" not in ids


async def test_foreign_tier3_hidden_excluded(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Foreign-scope tier 3 hidden artifact is excluded from results."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-foreign-hidden-adr" not in ids


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_list_vectors_by_metadata_credential_error_returns_structured(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
    s3_client: S3ClientImpl,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    mocker.patch.object(
        vectors_client_8,
        "list_vectors_by_metadata",
        side_effect=CredentialError(
            message="Credential failure (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    assert result.get("error") == "credential_error"


async def test_get_vectors_credential_error_returns_structured(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
    s3_client: S3ClientImpl,
) -> None:
    """get_vectors raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)
    mocker.patch.object(
        vectors_client_8,
        "get_vectors",
        side_effect=CredentialError(
            message="Credential failure on get_vectors (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    assert result.get("error") == "credential_error"


# ---------------------------------------------------------------------------
# Spec 10 — Scope filter in vector query
# ---------------------------------------------------------------------------


async def test_list_vectors_called_with_scope_filter(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
    s3_client: S3ClientImpl,
) -> None:
    """list_artifacts with a known scope → filter arg contains scope clause."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    spy = mocker.spy(vectors_client_8, "list_vectors_by_metadata")

    await list_artifacts(settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None)

    assert spy.call_count >= 1
    all_filter_args = [str(call.args[0]) for call in spy.call_args_list]
    filter_str = " ".join(all_filter_args)
    assert "scope" in filter_str or "artifacts" in filter_str


# ---------------------------------------------------------------------------
# Spec 18 — source_artifacts in list result
# ---------------------------------------------------------------------------


async def test_list_result_includes_source_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Artifact with source_artifacts metadata → present in result dict."""
    settings = _make_settings(monkeypatch)
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/synth-t3#summary",
        _unit_vec(2.0),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/synth-t3",
            "tier": 3,
            "type": "synthesis",
            "source_artifacts": ["adr-2026-x"],
        },
    )

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    artifacts = result.get("artifacts", [])
    synth = [a for a in artifacts if a.get("artifact_id") == "artifacts/synth-t3"]
    assert len(synth) == 1
    assert "source_artifacts" in synth[0]


# ---------------------------------------------------------------------------
# T36 — commit_refs filter and new metadata fields in list response
# ---------------------------------------------------------------------------


async def test_list_commit_refs_filter_returns_matching_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """list_artifacts with commit_refs=['abc1234'] returns only matching artifacts.

    The filter clause is the one thing that legitimately reads the vector-metadata copy
    of commit_refs: that copy exists as a derived, server-side filter index. Only the
    vector copy is seeded here, and only artifact ids are asserted — the value returned
    in each entry's commit_refs field comes from the annotation, which this test does
    not exercise.
    """
    settings = _make_settings(monkeypatch)
    # Filter-index data only — deliberately no annotation, so a regression that sourced
    # the filter from annotations instead would fail here.
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/with-ref#summary",
        _unit_vec(3.0),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/with-ref",
            "commit_refs": ["abc1234"],
        },
    )
    # artifact without commit ref
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/no-ref#summary",
        _unit_vec(3.1),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/no-ref",
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
        commit_refs=["abc1234"],
    )

    artifacts = result.get("artifacts", [])
    ids = [a["artifact_id"] for a in artifacts]
    assert "artifacts/with-ref" in ids
    assert "artifacts/no-ref" not in ids


async def test_list_no_commit_refs_filter_returns_all(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Omitting the commit_refs argument adds no filter clause, so an artifact carrying
    no commit_refs in the filter index is listed alongside one that does."""
    settings = _make_settings(monkeypatch)
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/with-ref2#summary",
        _unit_vec(3.2),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/with-ref2",
            "commit_refs": ["def5678"],
        },
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/no-ref2#summary",
        _unit_vec(3.3),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/no-ref2",
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    ids = [a["artifact_id"] for a in artifacts]
    assert "artifacts/with-ref2" in ids
    assert "artifacts/no-ref2" in ids


async def test_list_result_includes_commit_refs_field(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Each artifact entry includes 'commit_refs' list, sourced from the annotation."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/with-ref3", "Content.", {"title": "x"})
    apply_link_annotations(s3_client, "artifacts/with-ref3", commit_refs=["abc1234"], references=[])
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/with-ref3#summary",
        _unit_vec(3.4),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/with-ref3",
            "commit_refs": ["abc1234"],
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    with_ref = [a for a in artifacts if a.get("artifact_id") == "artifacts/with-ref3"]
    assert len(with_ref) == 1
    assert with_ref[0]["commit_refs"] == ["abc1234"]


async def test_list_result_commit_refs_empty_when_no_annotation(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """An artifact carrying no commit_refs annotation reports commit_refs=[]. The stale
    value on its vector is a derived filter-index entry and must not surface in the
    returned field."""
    settings = _make_settings(monkeypatch)
    # The object exists with no annotations on it, so [] here means "genuinely none"
    # rather than "the key was missing".
    s3_client.put_object("artifacts/no-ref3", "Content.", {"title": "x"})
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/no-ref3#summary",
        _unit_vec(3.5),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/no-ref3",
            "commit_refs": ["stale-filter-index-sha"],
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    no_ref = [a for a in artifacts if a.get("artifact_id") == "artifacts/no-ref3"]
    assert len(no_ref) == 1
    assert no_ref[0]["commit_refs"] == []


# ---------------------------------------------------------------------------
# T59 — references= filter parameter removed; references field in list response
# ---------------------------------------------------------------------------


async def test_list_references_kwarg_rejected(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """list_artifacts no longer accepts a references= filter parameter (T59):
    since T58 stopped writing references into vector metadata, the old
    {"references": {"$eq": ref}} clause could never match anything again — the
    parameter is removed outright rather than silently ignored or returning an
    empty result set."""
    settings = _make_settings(monkeypatch)

    with pytest.raises(TypeError):
        await list_artifacts(  # type: ignore[call-arg]
            settings=settings,
            vectors=vectors_client_8,
            s3=s3_client,
            bedrock=None,
            references=["a-1"],
        )


async def test_list_no_references_filter_returns_all(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """list_artifacts without a references filter returns artifacts with and without references."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/with-ref-field2", "Content.", {"title": "x"})
    apply_link_annotations(
        s3_client, "artifacts/with-ref-field2", commit_refs=[], references=["c-3"]
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/with-ref-field2#summary",
        _unit_vec(4.4),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/with-ref-field2",
            "references": ["c-3"],
        },
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/no-ref-field2#summary",
        _unit_vec(4.5),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/no-ref-field2",
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    ids = [a["artifact_id"] for a in artifacts]
    assert "artifacts/with-ref-field2" in ids
    assert "artifacts/no-ref-field2" in ids


async def test_list_result_includes_references_field(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Each artifact entry includes 'references' list, sourced from the annotation."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/with-ref-field3", "Content.", {"title": "x"})
    apply_link_annotations(
        s3_client, "artifacts/with-ref-field3", commit_refs=[], references=["a-1"]
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/with-ref-field3#summary",
        _unit_vec(4.6),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/with-ref-field3",
            "references": ["a-1"],
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    with_ref = [a for a in artifacts if a.get("artifact_id") == "artifacts/with-ref-field3"]
    assert len(with_ref) == 1
    assert with_ref[0]["references"] == ["a-1"]


async def test_list_result_references_empty_when_absent(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Artifact without references in vector metadata → references=[] in response."""
    settings = _make_settings(monkeypatch)
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/no-ref-field3#summary",
        _unit_vec(4.7),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/no-ref-field3",
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    no_ref = [a for a in artifacts if a.get("artifact_id") == "artifacts/no-ref-field3"]
    assert len(no_ref) == 1
    assert no_ref[0]["references"] == []


async def test_list_result_includes_last_edited_ulid(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Artifact with last_edited_ulid in vector metadata → field present in response."""
    settings = _make_settings(monkeypatch)
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/with-ulid#summary",
        _unit_vec(3.6),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/with-ulid",
            "last_edited_ulid": "01JXXXXXXXXXXXXXXXXXXXXXXXXX",
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    with_ulid = [a for a in artifacts if a.get("artifact_id") == "artifacts/with-ulid"]
    assert len(with_ulid) == 1
    assert with_ulid[0]["last_edited_ulid"] == "01JXXXXXXXXXXXXXXXXXXXXXXXXX"


async def test_list_legacy_artifact_last_edited_ulid_is_none(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Artifact without last_edited_ulid in vector metadata → last_edited_ulid=None."""
    settings = _make_settings(monkeypatch)
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/legacy#summary",
        _unit_vec(3.7),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/legacy",
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    legacy = [a for a in artifacts if a.get("artifact_id") == "artifacts/legacy"]
    assert len(legacy) == 1
    assert legacy[0]["last_edited_ulid"] is None


# ---------------------------------------------------------------------------
# Batched get_vectors — S3 Vectors API limit of 100 keys per call
# ---------------------------------------------------------------------------


async def test_more_than_100_artifacts_all_returned(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Seeding 105 artifacts (one section vector each) → all 105 returned without error.

    Exercises the batched get_vectors loop in _list_artifacts_inner; previously a single
    get_vectors call with 105 keys raised a ValidationException from the S3 Vectors API.
    """
    settings = _make_settings(monkeypatch)

    artifact_count = 105
    artifact_ids = [f"artifacts/bulk-artifact-{i:03d}" for i in range(artifact_count)]
    for i, artifact_id in enumerate(artifact_ids):
        _put_listable(
            vectors_client_8,
            s3_client,
            f"{artifact_id}#summary",
            _unit_vec(float(i) * 0.01 + 5.0),
            {
                **_BASE_VECTOR_META,
                "artifact_id": artifact_id,
            },
        )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
    )

    assert "artifacts" in result, f"Expected 'artifacts' key, got: {result}"
    returned_ids = {a["artifact_id"] for a in result["artifacts"]}
    for artifact_id in artifact_ids:
        assert artifact_id in returned_ids, f"Missing artifact: {artifact_id}"
    assert len(result["artifacts"]) == artifact_count


# ---------------------------------------------------------------------------
# M17 — legacy vector missing "tier" key must not raise KeyError
# ---------------------------------------------------------------------------


async def test_vector_missing_tier_key_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """M17: A vector whose metadata dict has no "tier" key causes int(meta["tier"]) to raise
    KeyError at list.py line ~200.  After the fix, the artifact is returned with a safe
    default tier (e.g. 0 or None) rather than raising.

    Scenario:
    - Seed one own-scope vector with no "tier" in metadata.
    - Call list_artifacts.
    - Expect: no KeyError; the artifact appears in the result.
    """
    settings = _make_settings(monkeypatch)
    # Seed a vector that has no "tier" key at all (simulates a legacy artifact)
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/legacy-no-tier#summary",
        _unit_vec(1.0),
        {
            "artifact_id": "artifacts/legacy-no-tier",
            "scope": "artifacts",
            "type": "implementation_note",
            # "tier" is intentionally absent
            "date": "2025-01-01",
            "status": "active",
            "title": "Legacy artifact without tier",
            "visibility": "shared",
            "tags": [],
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=s3_client,
        bedrock=None,
    )

    assert "error" not in result, f"M17: Expected no error, got: {result}"
    returned_ids = {a["artifact_id"] for a in result.get("artifacts", [])}
    assert "artifacts/legacy-no-tier" in returned_ids, (
        "M17: Legacy artifact without 'tier' key should appear in list results, not raise KeyError"
    )


# ---------------------------------------------------------------------------
# list_artifacts's blocking client calls are offloaded off the event loop
# ---------------------------------------------------------------------------


async def test_list_vector_calls_run_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
    s3_client: S3ClientImpl,
) -> None:
    """list_vectors_by_metadata and get_vectors execute on a worker thread, never on
    the calling event-loop thread — proves the calls are routed through
    asyncio.to_thread."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []

    original_list = vectors_client_8.list_vectors_by_metadata
    original_get_vectors = vectors_client_8.get_vectors

    def spy_list(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_list(*args, **kwargs)

    def spy_get_vectors(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_get_vectors(*args, **kwargs)

    mocker.patch.object(vectors_client_8, "list_vectors_by_metadata", side_effect=spy_list)
    mocker.patch.object(vectors_client_8, "get_vectors", side_effect=spy_get_vectors)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    assert "error" not in result
    assert seen_threads, "list_vectors_by_metadata/get_vectors were never called"
    assert all(t is not main_thread for t in seen_threads), (
        "Vector calls ran on the event-loop thread — they must be offloaded"
    )


# ---------------------------------------------------------------------------
# Cross-scope reference filtering (ADR-012)
# ---------------------------------------------------------------------------


async def test_list_cross_scope_reference_filtering_batched_across_page(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
    s3_client: S3ClientImpl,
) -> None:
    """Multiple foreign tier-3-shared entries on the same page, each referencing a
    distinct target → unreadable targets dropped, readable targets kept, and the
    whole page's reference resolution costs exactly one additional
    list_vectors_by_metadata call (batched, not per-entry)."""
    settings = _make_settings(monkeypatch)
    # Foreign entry A references a foreign tier-2 target (unreadable).
    s3_client.put_object("other-team/t3-with-refs-a", "Content.", {"title": "x"})
    apply_link_annotations(
        s3_client, "other-team/t3-with-refs-a", commit_refs=[], references=["other-team/t2-target"]
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "other-team/t3-with-refs-a#summary",
        _unit_vec(2.1),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-with-refs-a",
            "scope": "other-team",
            "tier": 3,
            "visibility": "shared",
            "references": ["other-team/t2-target"],
        },
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "other-team/t2-target#summary",
        _unit_vec(2.2),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t2-target",
            "scope": "other-team",
            "tier": 2,
        },
    )
    # Foreign entry B references a foreign tier-3-shared target (readable).
    s3_client.put_object("other-team/t3-with-refs-b", "Content.", {"title": "x"})
    apply_link_annotations(
        s3_client, "other-team/t3-with-refs-b", commit_refs=[], references=["other-team/t3-target"]
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "other-team/t3-with-refs-b#summary",
        _unit_vec(2.3),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-with-refs-b",
            "scope": "other-team",
            "tier": 3,
            "visibility": "shared",
            "references": ["other-team/t3-target"],
        },
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "other-team/t3-target#summary",
        _unit_vec(2.4),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-target",
            "scope": "other-team",
            "tier": 3,
            "visibility": "shared",
        },
    )
    spy = mocker.spy(vectors_client_8, "list_vectors_by_metadata")

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    artifacts = {a["artifact_id"]: a for a in result.get("artifacts", [])}
    assert artifacts["other-team/t3-with-refs-a"]["references"] == []
    assert artifacts["other-team/t3-with-refs-b"]["references"] == ["other-team/t3-target"]
    # One call for the main page query plus one batched call for cross-scope reference
    # resolution (Step 5). Step 4b reads annotations, not the vector index, so the page's
    # link fields cost no scan at all.
    assert spy.call_count == 2


async def test_list_own_scope_reference_filtering_issues_no_extra_vector_query(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
    s3_client: S3ClientImpl,
) -> None:
    """A page containing only own-scope entries never triggers cross-scope reference
    filtering (Step 5) — references are returned unfiltered and no batched
    resolve_readable_targets query is issued. The main page query is the only vector-index
    scan the whole call makes."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/own-with-refs-spy", "Content.", {"title": "x"})
    apply_link_annotations(
        s3_client,
        "artifacts/own-with-refs-spy",
        commit_refs=[],
        references=["other-team/does-not-exist"],
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/own-with-refs-spy#summary",
        _unit_vec(2.5),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/own-with-refs-spy",
            "references": ["other-team/does-not-exist"],
        },
    )
    spy = mocker.spy(vectors_client_8, "list_vectors_by_metadata")

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    artifacts = {a["artifact_id"]: a for a in result.get("artifacts", [])}
    assert artifacts["artifacts/own-with-refs-spy"]["references"] == ["other-team/does-not-exist"]
    # Main page query only — Step 4b reads annotations, and there is no Step 5 call.
    assert spy.call_count == 1


async def test_list_cross_scope_reference_missing_target_stripped(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Foreign tier-3-shared entry referencing a target with no matching vector entry
    (deleted or never existed) → target stripped, fail safe."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("other-team/t3-with-missing-ref", "Content.", {"title": "x"})
    apply_link_annotations(
        s3_client,
        "other-team/t3-with-missing-ref",
        commit_refs=[],
        references=["other-team/does-not-exist"],
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "other-team/t3-with-missing-ref#summary",
        _unit_vec(2.6),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-with-missing-ref",
            "scope": "other-team",
            "tier": 3,
            "visibility": "shared",
            "references": ["other-team/does-not-exist"],
        },
    )

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    artifacts = {a["artifact_id"]: a for a in result.get("artifacts", [])}
    assert artifacts["other-team/t3-with-missing-ref"]["references"] == []


async def test_list_cross_scope_reference_resolving_into_own_scope_kept(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Foreign tier-3-shared entry referencing a target in the reader's own scope →
    kept, even though no vector entry exists for that own-scope target."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("other-team/t3-with-own-ref", "Content.", {"title": "x"})
    apply_link_annotations(
        s3_client,
        "other-team/t3-with-own-ref",
        commit_refs=[],
        references=["artifacts/own-hidden-target"],
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "other-team/t3-with-own-ref#summary",
        _unit_vec(2.7),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-with-own-ref",
            "scope": "other-team",
            "tier": 3,
            "visibility": "shared",
            "references": ["artifacts/own-hidden-target"],
        },
    )

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    artifacts = {a["artifact_id"]: a for a in result.get("artifacts", [])}
    assert artifacts["other-team/t3-with-own-ref"]["references"] == ["artifacts/own-hidden-target"]


# ---------------------------------------------------------------------------
# commit_refs/references — annotations are the sole source of truth
# ---------------------------------------------------------------------------


async def test_list_link_fields_come_from_annotations_not_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """When the two stores disagree, the annotation wins outright. The vector-metadata
    copy of commit_refs is a capped, derived filter index, never a source of truth, and
    references is not written to vector metadata at all."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/list-annotation-only-ref", "Content.", {"title": "x"})
    apply_link_annotations(
        s3_client,
        "artifacts/list-annotation-only-ref",
        commit_refs=["sha-annotation"],
        references=["ref-annotation"],
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/list-annotation-only-ref#summary",
        _unit_vec(5.7),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/list-annotation-only-ref",
            "commit_refs": ["sha-vector"],
            "references": ["ref-vector"],
        },
    )

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    artifacts = {a["artifact_id"]: a for a in result.get("artifacts", [])}
    entry = artifacts["artifacts/list-annotation-only-ref"]
    assert entry["commit_refs"] == ["sha-annotation"]
    assert entry["references"] == ["ref-annotation"]


async def test_list_page_costs_exactly_one_vector_index_scan(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The regression guard for the retired union read model: a page of N own-scope
    artifacts costs exactly one vector-index scan — its own page query — not one more per
    artifact. The vector copy of commit_refs has no server-side filter, so reading it back
    means paginating the whole index in memory, once per artifact."""
    settings = _make_settings(monkeypatch)
    for n, seed in enumerate((6.1, 6.2, 6.3)):
        artifact_id = f"artifacts/scan-count-{n}"
        s3_client.put_object(artifact_id, "Content.", {"title": "x"})
        apply_link_annotations(s3_client, artifact_id, commit_refs=[f"sha-{n}"], references=[])
        _put_listable(
            vectors_client_8,
            s3_client,
            f"{artifact_id}#summary",
            _unit_vec(seed),
            {**_BASE_VECTOR_META, "artifact_id": artifact_id},
        )
    spy = mocker.spy(vectors_client_8, "list_vectors_by_metadata")

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    artifacts = {a["artifact_id"]: a for a in result.get("artifacts", [])}
    for n in range(3):
        assert artifacts[f"artifacts/scan-count-{n}"]["commit_refs"] == [f"sha-{n}"]
    assert spy.call_count == 1


async def test_list_annotation_failure_errors_rather_than_degrading_the_page(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """One artifact's failed annotation read fails the call. Annotations are the sole
    source of truth, so silently reporting empty link fields would be indistinguishable
    from an artifact that genuinely has none."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/degrade-guard", "Content.", {"title": "x"})
    apply_link_annotations(
        s3_client, "artifacts/degrade-guard", commit_refs=["abc1234"], references=[]
    )
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/degrade-guard#summary",
        _unit_vec(6.4),
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/degrade-guard"},
    )
    mocker.patch.object(
        s3_client, "get_object_annotation", side_effect=RuntimeError("transient S3 failure")
    )

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    assert "error" in result
    assert "artifacts" not in result


# ---------------------------------------------------------------------------
# T74.4 — one error code for AnnotationUnavailableError
# ---------------------------------------------------------------------------


async def test_list_annotation_unavailable_returns_the_annotation_unavailable_code(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """A failed link-field annotation read names its cause instead of collapsing to
    ``internal_error``.

    It is the same condition, and so the same code, that ``read_artifact``,
    ``propose_commit_links``, ``link_metadata``, ``write_artifact`` and
    ``archive_artifact`` return — one condition gets one code, because an operator
    diagnosing post-setup IAM drift should not have to know which tool they called.
    """
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)
    mocker.patch.object(
        s3_client,
        "get_object_annotation",
        side_effect=AnnotationUnavailableError(
            "S3 object annotations are unavailable for this bucket.", "s3", Exception("boom")
        ),
    )

    result = await list_artifacts(settings=settings, s3=s3_client, vectors=vectors_client_8)

    assert result.get("error") == "annotation_unavailable"
    assert "artifacts" not in result


# ---------------------------------------------------------------------------
# Malformed records are skipped; a deleted object is skipped separately
# ---------------------------------------------------------------------------


async def test_list_skips_a_candidate_with_no_artifact_id_and_still_returns_the_page(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """One unreadable record must not withhold every readable one on the page. Without
    an id the candidate cannot be identified, deduplicated, or fetched."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/no-id#summary",
        _unit_vec(0.5),
        {**_BASE_VECTOR_META, "status": "active"},
    )

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    assert "error" not in result
    assert result["artifacts"], "readable records must survive an unreadable neighbour"
    assert result["skipped_malformed_count"] == 1


async def test_list_skips_a_candidate_whose_tier_will_not_coerce(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """The candidate is genuinely absent from the page rather than present with a
    defaulted tier — ``tier`` is one of the two fields the cross-scope gate keys on."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/bad-tier#summary",
        _unit_vec(0.5),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/bad-tier",
            "status": "active",
            "tier": "high",
        },
    )

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/bad-tier" not in ids
    assert result["skipped_malformed_count"] == 1


async def test_list_omits_both_skip_counts_when_nothing_was_skipped(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """Absent rather than zero: the presence of either key is itself the signal."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    assert "skipped_malformed_count" not in result
    assert "skipped_deleted_count" not in result


async def test_list_never_counts_a_gated_out_foreign_candidate_as_a_skip(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
) -> None:
    """A candidate the gate denied is not a skip. Counting it would disclose that a
    foreign artifact exists — including one whose own ``tier`` the gate could not
    read, which denies rather than raising."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)
    _put_listable(
        vectors_client_8,
        s3_client,
        "other-team/gated-bad-tier#summary",
        _unit_vec(0.5),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/gated-bad-tier",
            "scope": "other-team",
            "status": "active",
            "tier": "high",
            "visibility": "shared",
        },
    )

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/gated-bad-tier" not in ids
    assert "skipped_malformed_count" not in result


async def test_list_omits_an_artifact_whose_object_is_gone_and_counts_it_separately(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """``ObjectNotFoundError`` is a read that *succeeded* and answered definitively.

    Omitting a deleted artifact from a listing is the correct result, not a lossy one,
    and failing a read-only call over a benign concurrent delete would be
    disproportionate when a retry can meet the same race.
    """
    from arkeology.errors import ObjectNotFoundError

    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)
    gone = "artifacts/t2-active-review"

    real_get = s3_client.get_object_annotation

    def _gone_for_one(key: str, annotation_name: str) -> str:
        if key == gone:
            raise ObjectNotFoundError(key)
        return real_get(key, annotation_name)

    mocker.patch.object(s3_client, "get_object_annotation", side_effect=_gone_for_one)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert gone not in ids
    assert ids, "the rest of the page must survive one concurrent delete"
    assert result["skipped_deleted_count"] == 1
    assert "skipped_malformed_count" not in result


async def test_list_keeps_the_deleted_and_malformed_counts_separate(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """Two counters, never merged. Ordinary churn is routinely non-zero and self-heals;
    corrupt stored data wants investigation. One shared number would sit at the floor
    the benign cause sets, and the serious one would never surface."""
    from arkeology.errors import ObjectNotFoundError

    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)
    gone = "artifacts/t2-active-review"
    _put_listable(
        vectors_client_8,
        s3_client,
        "artifacts/bad-tier#summary",
        _unit_vec(0.5),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/bad-tier",
            "status": "active",
            "tier": "high",
        },
    )
    real_get = s3_client.get_object_annotation

    def _gone_for_one(key: str, annotation_name: str) -> str:
        if key == gone:
            raise ObjectNotFoundError(key)
        return real_get(key, annotation_name)

    mocker.patch.object(s3_client, "get_object_annotation", side_effect=_gone_for_one)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    assert result["skipped_deleted_count"] == 1
    assert result["skipped_malformed_count"] == 1


async def test_list_still_fails_the_page_on_an_unclassified_link_field_not_found(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """A bare ``KeyError`` established nothing about absence, so it is not the
    definitive-delete case. It must not become an artifact listed with empty link
    fields, which is indistinguishable from one that genuinely has none."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8, s3_client)
    mocker.patch.object(
        s3_client, "get_object_annotation", side_effect=KeyError("artifacts/t2-active-review")
    )

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=s3_client, bedrock=None
    )

    assert "error" in result
    assert "artifacts" not in result
