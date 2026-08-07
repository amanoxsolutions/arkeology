"""Unit tests for cairn_mcp.tools.list.

Tests list_artifacts() using moto-backed VectorsClientImpl — no S3 or Bedrock calls.
"""

import math
import threading
from typing import Any

import pytest
from pytest_mock import MockerFixture

from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools.list import list_artifacts
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


def _seed_vectors(vectors: VectorsClientImpl) -> None:
    """Seed a rich set of vectors for list tests."""
    # own-scope active tier 2 (two section vectors — dedup test)
    for section in ["#summary", "#details"]:
        vectors.put_vector(
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
        vectors.put_vector(
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
        vectors.put_vector(
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
    vectors.put_vector(
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
    vectors.put_vector(
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
    vectors.put_vector(
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
    vectors.put_vector(
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
    vectors.put_vector(
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
) -> None:
    """No filters → own-scope active artifacts and foreign-scope tier 3 shared returned."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-active-review" in ids
    assert "artifacts/t3-shared-adr" in ids
    assert "other-team/t3-foreign-shared-adr" in ids


async def test_default_status_active_excludes_inactive(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """No status filter → status defaults to 'active'; inactive artifacts absent."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-inactive-review" not in ids


async def test_status_inactive_override_returns_only_inactive(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """status='inactive' → only inactive artifacts returned."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None, status="inactive"
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-inactive-review" in ids
    for artifact in result["artifacts"]:
        assert artifact["status"] == "inactive"


async def test_status_all_returns_active_and_inactive(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """status='all' (M-11d) → both active and inactive own-scope artifacts returned;
    previously the browser Studio's "All" filter was unreachable because omitting the
    status arg fell back to the "active" default."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None, status="all"
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
) -> None:
    """type='code_review' → only code reviews in results."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None, type="code_review"
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert artifact["type"] == "code_review"


async def test_filter_tags(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """tags=['auth'] → only artifacts with 'auth' tag."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None, tags=["auth"]
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert "auth" in artifact["tags"]


async def test_filter_type_and_tags_intersection(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """type='code_review' + tags=['auth'] → intersection of both constraints."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=None,
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
) -> None:
    """team='platform' → only platform team artifacts."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None, team="platform"
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert artifact["team"] == "platform"


async def test_filter_project(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """project='infra' → only infra project artifacts."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None, project="infra"
    )

    for artifact in result["artifacts"]:
        assert artifact["project"] == "infra"


async def test_filter_tier3(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """tier=3 → only tier 3 artifacts."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None, tier=3
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert artifact["tier"] == 3


async def test_no_matching_artifacts_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Filters that match no artifacts → empty list, no error."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None, type="session_summary"
    )

    assert result["artifacts"] == []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


async def test_deduplication_two_sections_one_record(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Two section vectors for same artifact_id → exactly one record in results."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert ids.count("artifacts/t2-active-review") == 1
    assert ids.count("other-team/t3-foreign-shared-adr") == 1


async def test_result_has_required_fields(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Each result contains all required metadata fields; no 'content' field."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
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
) -> None:
    """tags in response is a list, not a comma-separated string."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    for artifact in result["artifacts"]:
        assert isinstance(artifact["tags"], list), f"Expected list, got {type(artifact['tags'])}"


# ---------------------------------------------------------------------------
# Cross-scope gate
# ---------------------------------------------------------------------------


async def test_foreign_tier3_shared_included(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Foreign-scope tier 3 shared artifact appears in results."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-foreign-shared-adr" in ids


async def test_foreign_tier2_excluded(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Foreign-scope tier 2 artifact is excluded from results."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t2-foreign-review" not in ids


async def test_foreign_tier3_hidden_excluded(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Foreign-scope tier 3 hidden artifact is excluded from results."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    result = await list_artifacts(
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
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
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    assert "error" in result or result.get("error_type") is not None


async def test_get_vectors_credential_error_returns_structured(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """get_vectors raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)
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
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# Spec 10 — Scope filter in vector query
# ---------------------------------------------------------------------------


async def test_list_vectors_called_with_scope_filter(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_artifacts with a known scope → filter arg contains scope clause."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)

    spy = mocker.spy(vectors_client_8, "list_vectors_by_metadata")

    await list_artifacts(settings=settings, vectors=vectors_client_8, s3=None, bedrock=None)

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
) -> None:
    """Artifact with source_artifacts metadata → present in result dict."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
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
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
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
) -> None:
    """list_artifacts with commit_refs=['abc1234'] returns only matching artifacts."""
    settings = _make_settings(monkeypatch)
    # artifact with matching commit ref
    vectors_client_8.put_vector(
        "artifacts/with-ref#summary",
        _unit_vec(3.0),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/with-ref",
            "commit_refs": ["abc1234"],
        },
    )
    # artifact without commit ref
    vectors_client_8.put_vector(
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
        s3=None,
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
) -> None:
    """list_artifacts without commit_refs filter returns artifacts with and without commit_refs."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
        "artifacts/with-ref2#summary",
        _unit_vec(3.2),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/with-ref2",
            "commit_refs": ["def5678"],
        },
    )
    vectors_client_8.put_vector(
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
        s3=None,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    ids = [a["artifact_id"] for a in artifacts]
    assert "artifacts/with-ref2" in ids
    assert "artifacts/no-ref2" in ids


async def test_list_result_includes_commit_refs_field(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Each artifact entry includes 'commit_refs' list."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
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
        s3=None,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    with_ref = [a for a in artifacts if a.get("artifact_id") == "artifacts/with-ref3"]
    assert len(with_ref) == 1
    assert with_ref[0]["commit_refs"] == ["abc1234"]


async def test_list_result_commit_refs_empty_when_absent(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Artifact without commit_refs in vector metadata → commit_refs=[] in response."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
        "artifacts/no-ref3#summary",
        _unit_vec(3.5),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/no-ref3",
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=None,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    no_ref = [a for a in artifacts if a.get("artifact_id") == "artifacts/no-ref3"]
    assert len(no_ref) == 1
    assert no_ref[0]["commit_refs"] == []


# ---------------------------------------------------------------------------
# T46 — references filter (AND semantics) and references field in list response
# ---------------------------------------------------------------------------


async def test_list_references_filter_returns_matching_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """list_artifacts with references=['a-1'] returns only matching artifacts."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
        "artifacts/with-ref-field#summary",
        _unit_vec(4.0),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/with-ref-field",
            "references": ["a-1"],
        },
    )
    vectors_client_8.put_vector(
        "artifacts/no-ref-field#summary",
        _unit_vec(4.1),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/no-ref-field",
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=None,
        bedrock=None,
        references=["a-1"],
    )

    artifacts = result.get("artifacts", [])
    ids = [a["artifact_id"] for a in artifacts]
    assert "artifacts/with-ref-field" in ids
    assert "artifacts/no-ref-field" not in ids


async def test_list_references_filter_two_identifiers_is_and_semantics(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """references=['a-1', 'b-2'] requires BOTH identifiers to be present (AND semantics)."""
    settings = _make_settings(monkeypatch)
    # matches both
    vectors_client_8.put_vector(
        "artifacts/both-refs#summary",
        _unit_vec(4.2),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/both-refs",
            "references": ["a-1", "b-2"],
        },
    )
    # matches only one
    vectors_client_8.put_vector(
        "artifacts/one-ref#summary",
        _unit_vec(4.3),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/one-ref",
            "references": ["a-1"],
        },
    )

    result = await list_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        s3=None,
        bedrock=None,
        references=["a-1", "b-2"],
    )

    artifacts = result.get("artifacts", [])
    ids = [a["artifact_id"] for a in artifacts]
    assert "artifacts/both-refs" in ids
    assert "artifacts/one-ref" not in ids


async def test_list_no_references_filter_returns_all(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """list_artifacts without a references filter returns artifacts with and without references."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
        "artifacts/with-ref-field2#summary",
        _unit_vec(4.4),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/with-ref-field2",
            "references": ["c-3"],
        },
    )
    vectors_client_8.put_vector(
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
        s3=None,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    ids = [a["artifact_id"] for a in artifacts]
    assert "artifacts/with-ref-field2" in ids
    assert "artifacts/no-ref-field2" in ids


async def test_list_result_includes_references_field(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Each artifact entry includes 'references' list."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
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
        s3=None,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    with_ref = [a for a in artifacts if a.get("artifact_id") == "artifacts/with-ref-field3"]
    assert len(with_ref) == 1
    assert with_ref[0]["references"] == ["a-1"]


async def test_list_result_references_empty_when_absent(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Artifact without references in vector metadata → references=[] in response."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
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
        s3=None,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    no_ref = [a for a in artifacts if a.get("artifact_id") == "artifacts/no-ref-field3"]
    assert len(no_ref) == 1
    assert no_ref[0]["references"] == []


async def test_list_result_includes_last_edited_ulid(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Artifact with last_edited_ulid in vector metadata → field present in response."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
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
        s3=None,
        bedrock=None,
    )

    artifacts = result.get("artifacts", [])
    with_ulid = [a for a in artifacts if a.get("artifact_id") == "artifacts/with-ulid"]
    assert len(with_ulid) == 1
    assert with_ulid[0]["last_edited_ulid"] == "01JXXXXXXXXXXXXXXXXXXXXXXXXX"


async def test_list_legacy_artifact_last_edited_ulid_is_none(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Artifact without last_edited_ulid in vector metadata → last_edited_ulid=None."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
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
        s3=None,
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
) -> None:
    """Seeding 105 artifacts (one section vector each) → all 105 returned without error.

    Exercises the batched get_vectors loop in _list_artifacts_inner; previously a single
    get_vectors call with 105 keys raised a ValidationException from the S3 Vectors API.
    """
    settings = _make_settings(monkeypatch)

    artifact_count = 105
    artifact_ids = [f"artifacts/bulk-artifact-{i:03d}" for i in range(artifact_count)]
    for i, artifact_id in enumerate(artifact_ids):
        vectors_client_8.put_vector(
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
        s3=None,
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


async def test_m17_vector_missing_tier_key_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
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
    vectors_client_8.put_vector(
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
        s3=None,
        bedrock=None,
    )

    assert "error" not in result, f"M17: Expected no error, got: {result}"
    returned_ids = {a["artifact_id"] for a in result.get("artifacts", [])}
    assert "artifacts/legacy-no-tier" in returned_ids, (
        "M17: Legacy artifact without 'tier' key should appear in list results, not raise KeyError"
    )


# ---------------------------------------------------------------------------
# M-8 — list_artifacts's blocking client calls are offloaded off the event loop
# ---------------------------------------------------------------------------


async def test_list_vector_calls_run_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_vectors_by_metadata and get_vectors execute on a worker thread, never on
    the calling event-loop thread — proves the calls are routed through
    asyncio.to_thread."""
    settings = _make_settings(monkeypatch)
    _seed_vectors(vectors_client_8)
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
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    assert "error" not in result
    assert seen_threads, "list_vectors_by_metadata/get_vectors were never called"
    assert all(t is not main_thread for t in seen_threads), (
        "Vector calls ran on the event-loop thread — they must be offloaded"
    )


# ---------------------------------------------------------------------------
# M5 — cross-scope reference filtering (ADR-012)
# ---------------------------------------------------------------------------


async def test_list_cross_scope_reference_filtering_batched_across_page(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Multiple foreign tier-3-shared entries on the same page, each referencing a
    distinct target → unreadable targets dropped, readable targets kept, and the
    whole page's reference resolution costs exactly one additional
    list_vectors_by_metadata call (batched, not per-entry)."""
    settings = _make_settings(monkeypatch)
    # Foreign entry A references a foreign tier-2 target (unreadable).
    vectors_client_8.put_vector(
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
    vectors_client_8.put_vector(
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
    vectors_client_8.put_vector(
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
    vectors_client_8.put_vector(
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
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    artifacts = {a["artifact_id"]: a for a in result.get("artifacts", [])}
    assert artifacts["other-team/t3-with-refs-a"]["references"] == []
    assert artifacts["other-team/t3-with-refs-b"]["references"] == ["other-team/t3-target"]
    # One call for the main page query + one batched call for reference resolution.
    assert spy.call_count == 2


async def test_list_own_scope_reference_filtering_issues_no_extra_vector_query(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A page containing only own-scope entries never triggers reference filtering —
    references are returned unfiltered and no additional vector-client query is
    issued beyond the main page query."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
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
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    artifacts = {a["artifact_id"]: a for a in result.get("artifacts", [])}
    assert artifacts["artifacts/own-with-refs-spy"]["references"] == ["other-team/does-not-exist"]
    assert spy.call_count == 1


async def test_list_cross_scope_reference_missing_target_stripped(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Foreign tier-3-shared entry referencing a target with no matching vector entry
    (deleted or never existed) → target stripped, fail safe."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
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
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    artifacts = {a["artifact_id"]: a for a in result.get("artifacts", [])}
    assert artifacts["other-team/t3-with-missing-ref"]["references"] == []


async def test_list_cross_scope_reference_resolving_into_own_scope_kept(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Foreign tier-3-shared entry referencing a target in the reader's own scope →
    kept, even though no vector entry exists for that own-scope target."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
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
        settings=settings, vectors=vectors_client_8, s3=None, bedrock=None
    )

    artifacts = {a["artifact_id"]: a for a in result.get("artifacts", [])}
    assert artifacts["other-team/t3-with-own-ref"]["references"] == ["artifacts/own-hidden-target"]
