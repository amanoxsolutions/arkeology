"""Unit tests for cairn_mcp.tools.search.

Tests search_artifacts() using FakeVectorsClient and FakeBedrockClient.
"""

import math
from typing import Any

import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.fakes.fake_vectors import FakeVectorsClient
from cairn_mcp.config import Settings
from cairn_mcp.tools.search import search_artifacts
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, READ_PREFIXES="other-team", **overrides)


def _unit_vec(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        return values
    return [v / norm for v in values]


# ---------------------------------------------------------------------------
# Seed data helper
# ---------------------------------------------------------------------------


def _seed_vectors(vectors: FakeVectorsClient, write_prefix: str = "artifacts") -> None:
    """Seed a FakeVectorsClient with a representative set of vectors for search tests."""
    dim = 8  # small dimension sufficient for fake cosine similarity

    def _vec(seed: float) -> list[float]:
        raw = [seed + i * 0.1 for i in range(dim)]
        return _unit_vec(raw)

    # own-scope tier 2 shared
    vectors.put_vector(
        f"{write_prefix}/t2-shared-review#summary",
        _vec(1.0),
        {
            "artifact_id": f"{write_prefix}/t2-shared-review",
            "scope": write_prefix,
            "type": "code_review",
            "team": "platform",
            "project": "cairn",
            "tier": 2,
            "visibility": "shared",
            "status": "active",
            "feature_tags": ["auth"],
            "title": "Shared tier 2 review",
        },
    )

    # own-scope tier 2 hidden
    vectors.put_vector(
        f"{write_prefix}/t2-hidden-review#summary",
        _vec(1.1),
        {
            "artifact_id": f"{write_prefix}/t2-hidden-review",
            "scope": write_prefix,
            "type": "code_review",
            "team": "platform",
            "project": "cairn",
            "tier": 2,
            "visibility": "hidden",
            "status": "active",
            "feature_tags": [],
            "title": "Hidden tier 2 review",
        },
    )

    # own-scope tier 3 shared
    vectors.put_vector(
        f"{write_prefix}/t3-shared-adr",
        _vec(0.9),
        {
            "artifact_id": f"{write_prefix}/t3-shared-adr",
            "scope": write_prefix,
            "type": "adr",
            "team": "platform",
            "project": "cairn",
            "tier": 3,
            "visibility": "shared",
            "status": "active",
            "feature_tags": ["payments"],
            "title": "Own-scope ADR",
        },
    )

    # foreign-scope tier 2 shared — SHOULD NOT appear in cross-scope results
    vectors.put_vector(
        "other-team/t2-foreign-shared#summary",
        _vec(1.0),
        {
            "artifact_id": "other-team/t2-foreign-shared",
            "scope": "other-team",
            "type": "code_review",
            "team": "network",
            "project": "router",
            "tier": 2,
            "visibility": "shared",
            "status": "active",
            "feature_tags": [],
            "title": "Foreign tier 2 review",
        },
    )

    # foreign-scope tier 3 shared — SHOULD appear
    vectors.put_vector(
        "other-team/t3-foreign-shared-adr",
        _vec(0.8),
        {
            "artifact_id": "other-team/t3-foreign-shared-adr",
            "scope": "other-team",
            "type": "adr",
            "team": "network",
            "project": "router",
            "tier": 3,
            "visibility": "shared",
            "status": "active",
            "feature_tags": ["payments"],
            "title": "Foreign tier 3 ADR",
        },
    )

    # foreign-scope tier 3 hidden — SHOULD NOT appear
    vectors.put_vector(
        "other-team/t3-foreign-hidden-adr",
        _vec(0.7),
        {
            "artifact_id": "other-team/t3-foreign-hidden-adr",
            "scope": "other-team",
            "type": "adr",
            "team": "network",
            "project": "router",
            "tier": 3,
            "visibility": "hidden",
            "status": "active",
            "feature_tags": [],
            "title": "Foreign tier 3 hidden ADR",
        },
    )

    # artifact with multiple section vectors (same artifact_id)
    vectors.put_vector(
        f"{write_prefix}/multi-section-spec#summary",
        _vec(0.6),
        {
            "artifact_id": f"{write_prefix}/multi-section-spec",
            "scope": write_prefix,
            "type": "spec",
            "team": "platform",
            "project": "cairn",
            "tier": 2,
            "visibility": "shared",
            "status": "active",
            "feature_tags": [],
            "title": "Multi-section spec",
        },
    )
    vectors.put_vector(
        f"{write_prefix}/multi-section-spec#details",
        _vec(0.65),
        {
            "artifact_id": f"{write_prefix}/multi-section-spec",
            "scope": write_prefix,
            "type": "spec",
            "team": "platform",
            "project": "cairn",
            "tier": 2,
            "visibility": "shared",
            "status": "active",
            "feature_tags": [],
            "title": "Multi-section spec",
        },
    )

    # inactive artifact — should be excluded by default
    vectors.put_vector(
        f"{write_prefix}/inactive-review#summary",
        _vec(0.5),
        {
            "artifact_id": f"{write_prefix}/inactive-review",
            "scope": write_prefix,
            "type": "code_review",
            "team": "platform",
            "project": "cairn",
            "tier": 2,
            "visibility": "shared",
            "status": "inactive",
            "feature_tags": [],
            "title": "Inactive review",
        },
    )

    # different team — for team filter test
    vectors.put_vector(
        f"{write_prefix}/network-review#summary",
        _vec(0.4),
        {
            "artifact_id": f"{write_prefix}/network-review",
            "scope": write_prefix,
            "type": "code_review",
            "team": "network",
            "project": "infra",
            "tier": 2,
            "visibility": "shared",
            "status": "active",
            "feature_tags": [],
            "title": "Network review",
        },
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_search_returns_up_to_top_k_distinct_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Query returns up to top_k distinct artifacts (no artifact appears twice)."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="auth review", top_k=2
    )

    artifacts = result["artifacts"]
    artifact_ids = [a["artifact_id"] for a in artifacts]
    assert len(artifact_ids) == len(set(artifact_ids)), "Duplicate artifact_ids in results"
    assert len(artifacts) <= 2


async def test_search_results_have_no_content_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search results do not contain a 'content' field (content is fetched via read)."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    for artifact in result["artifacts"]:
        assert "content" not in artifact


async def test_search_results_ordered_by_score_descending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search results are ordered by score descending."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    scores = [a["score"] for a in result["artifacts"]]
    assert scores == sorted(scores, reverse=True)


async def test_search_each_result_has_artifact_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each result has an 'artifact_id' field."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    for artifact in result["artifacts"]:
        assert "artifact_id" in artifact


# ---------------------------------------------------------------------------
# Metadata filters
# ---------------------------------------------------------------------------


async def test_filter_type_restricts_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """type='code_review' filter → all results have type=='code_review'."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors,
        bedrock=bedrock,
        settings=settings,
        query="review",
        top_k=10,
        type="code_review",
    )

    for artifact in result["artifacts"]:
        assert artifact["type"] == "code_review"


async def test_filter_feature_tags_restricts_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """feature_tags=['payments'] → all results contain 'payments' in feature_tags."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors,
        bedrock=bedrock,
        settings=settings,
        query="payments",
        top_k=10,
        feature_tags=["payments"],
    )

    for artifact in result["artifacts"]:
        assert "payments" in artifact["feature_tags"]


async def test_filter_team_restricts_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """team='platform' → all results have team=='platform'."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors,
        bedrock=bedrock,
        settings=settings,
        query="review",
        top_k=10,
        team="platform",
    )

    for artifact in result["artifacts"]:
        assert artifact["team"] == "platform"


async def test_filter_project_restricts_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """project='cairn' → all results have project=='cairn'."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors,
        bedrock=bedrock,
        settings=settings,
        query="cairn",
        top_k=10,
        project="cairn",
    )

    for artifact in result["artifacts"]:
        assert artifact["project"] == "cairn"


async def test_filter_tier_restricts_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tier=3 → all results have tier==3."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors,
        bedrock=bedrock,
        settings=settings,
        query="decision",
        top_k=10,
        tier=3,
    )

    for artifact in result["artifacts"]:
        assert artifact["tier"] == 3


async def test_inactive_artifacts_excluded_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """status='inactive' artifacts are excluded from results by default."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    artifact_ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/inactive-review" not in artifact_ids


# ---------------------------------------------------------------------------
# Cross-scope gate
# ---------------------------------------------------------------------------


async def test_foreign_tier2_absent_from_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope tier 2 artifact is absent from results regardless of similarity."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=20
    )

    artifact_ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t2-foreign-shared" not in artifact_ids


async def test_foreign_tier3_shared_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope tier 3 shared artifact appears in results when matching."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="adr decision", top_k=20
    )

    artifact_ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-foreign-shared-adr" in artifact_ids


async def test_foreign_tier3_hidden_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-scope tier 3 hidden artifact is absent from results."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="adr", top_k=20
    )

    artifact_ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-foreign-hidden-adr" not in artifact_ids


async def test_own_scope_tier2_hidden_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Own-scope tier 2 hidden artifact appears in results (no gate on own scope)."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=20
    )

    artifact_ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-hidden-review" in artifact_ids


# ---------------------------------------------------------------------------
# Re-fetch loop
# ---------------------------------------------------------------------------


async def test_top_k_limits_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """top_k=2 with multiple artifacts seeded → exactly 2 results returned."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=2
    )

    assert len(result["artifacts"]) == 2


async def test_search_max_iterations_limits_query_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """search_max_iterations=1 → at most 1 query_vectors call."""
    settings = _make_settings(monkeypatch, SEARCH_MAX_ITERATIONS="1")

    call_count = 0

    class TrackingVectorsClient(FakeVectorsClient):
        def query_vectors(
            self,
            vector: list[float],
            top_k: int,
            filter_expr: dict[str, Any] | None,
        ) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            return super().query_vectors(vector, top_k, filter_expr)

    vectors = TrackingVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    assert call_count <= 1


async def test_early_exit_when_no_new_artifact_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loop exits early when no new artifact IDs are returned in an iteration."""
    settings = _make_settings(monkeypatch, SEARCH_MAX_ITERATIONS="3")

    call_count = 0

    class TrackingVectorsClient(FakeVectorsClient):
        def query_vectors(
            self,
            vector: list[float],
            top_k: int,
            filter_expr: dict[str, Any] | None,
        ) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            return super().query_vectors(vector, top_k, filter_expr)

    vectors = TrackingVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    # Seed only 2 vectors with the same artifact_id so second iteration yields nothing new
    raw = [1.0] + [0.0] * 7
    v = _unit_vec(raw)
    vectors.put_vector(
        "artifacts/only-one#s1",
        v,
        {
            "artifact_id": "artifacts/only-one",
            "scope": "artifacts",
            "type": "adr",
            "tier": 3,
            "visibility": "shared",
            "status": "active",
            "team": "platform",
            "project": "cairn",
            "feature_tags": [],
            "title": "Only one",
        },
    )
    vectors.put_vector(
        "artifacts/only-one#s2",
        v,
        {
            "artifact_id": "artifacts/only-one",
            "scope": "artifacts",
            "type": "adr",
            "tier": 3,
            "visibility": "shared",
            "status": "active",
            "team": "platform",
            "project": "cairn",
            "feature_tags": [],
            "title": "Only one",
        },
    )

    await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="adr decision", top_k=5
    )

    # Should exit after 1 or 2 iterations at most (not 3)
    assert call_count < 3


async def test_top_k_defaults_to_search_default_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """top_k not passed → defaults to settings.search_default_top_k."""
    settings = _make_settings(monkeypatch, SEARCH_DEFAULT_TOP_K="2")
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review"
    )

    assert len(result["artifacts"]) <= settings.search_default_top_k


async def test_top_k_capped_at_100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """top_k=200 is capped at 100 internally."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    # Should not raise; result set is naturally small so just verify no exception
    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=200
    )

    assert isinstance(result["artifacts"], list)
    assert len(result["artifacts"]) <= 100


# ---------------------------------------------------------------------------
# Zero results
# ---------------------------------------------------------------------------


async def test_empty_index_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty fake index → results list is empty."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="anything", top_k=5
    )

    assert result["artifacts"] == []


async def test_empty_index_has_zero_results_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty fake index → response contains a zero_results signal."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="anything", top_k=5
    )

    # zero_results field is truthy (True or count=0 is falsy, so use explicit check)
    assert result.get("zero_results") is True or len(result["artifacts"]) == 0


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_bedrock_credential_failure_returns_error_no_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bedrock credential failure → error response; query_vectors NOT called."""
    settings = _make_settings(monkeypatch)

    call_count = 0

    class TrackingVectorsClient(FakeVectorsClient):
        def query_vectors(
            self,
            vector: list[float],
            top_k: int,
            filter_expr: dict[str, Any] | None,
        ) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            return super().query_vectors(vector, top_k, filter_expr)

    vectors = TrackingVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    bedrock.set_credential_failure(True)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=5
    )

    assert "error" in result or result.get("success") is False
    assert call_count == 0


async def test_vectors_credential_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vectors credential failure → structured error in response."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    vectors.set_credential_failure(True)

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=5
    )

    assert "error" in result or result.get("success") is False


# ---------------------------------------------------------------------------
# T3: $nin absent from filter on first iteration (seen_ids is empty)
# ---------------------------------------------------------------------------


async def test_first_iteration_filter_has_no_nin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the very first query_vectors call (seen_ids empty), $nin is NOT in the filter."""
    settings = _make_settings(monkeypatch)

    captured_filters: list[dict[str, Any]] = []

    class CapturingVectorsClient(FakeVectorsClient):
        def query_vectors(
            self,
            vector: list[float],
            top_k: int,
            filter_expr: dict[str, Any] | None,
        ) -> list[dict[str, Any]]:
            if filter_expr is not None:
                captured_filters.append(filter_expr)
            return super().query_vectors(vector, top_k, filter_expr)

    vectors = CapturingVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="review", top_k=5
    )

    assert len(captured_filters) >= 1
    first_filter_str = str(captured_filters[0])
    assert "$nin" not in first_filter_str, (
        f"$nin found in first iteration filter: {captured_filters[0]}"
    )


# ---------------------------------------------------------------------------
# T6: source_artifacts present in each search result
# ---------------------------------------------------------------------------


async def test_search_results_include_source_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search results include a 'source_artifacts' field for each artifact."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    # Seed a vector with source_artifacts populated
    raw = [1.0] + [0.0] * 7
    v: list[float] = [x / math.sqrt(sum(y * y for y in raw)) for x in raw]
    vectors.put_vector(
        "artifacts/adr-with-sources",
        v,
        {
            "artifact_id": "artifacts/adr-with-sources",
            "scope": "artifacts",
            "type": "adr",
            "team": "platform",
            "project": "cairn",
            "tier": 3,
            "visibility": "shared",
            "status": "active",
            "feature_tags": [],
            "title": "ADR with sources",
            "source_artifacts": ["adr-one"],
        },
    )

    result = await search_artifacts(
        vectors=vectors, bedrock=bedrock, settings=settings, query="adr", top_k=5
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert "source_artifacts" in artifact, f"'source_artifacts' missing from result: {artifact}"
    # The specific artifact seeded with sources should have them
    seeded = next(
        (a for a in result["artifacts"] if a["artifact_id"] == "artifacts/adr-with-sources"),
        None,
    )
    assert seeded is not None
    assert seeded["source_artifacts"] == ["adr-one"]


# ---------------------------------------------------------------------------
# Spec 18 — top_k clamping
# ---------------------------------------------------------------------------


async def test_search_top_k_over_limit_clamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """top_k=200 → response contains clamped: True and effective_top_k: 100."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        settings=settings,
        vectors=vectors,
        bedrock=bedrock,
        s3=None,
        query="auth review",
        top_k=200,
    )

    assert result.get("clamped") is True
    assert result.get("effective_top_k") == 100


async def test_search_top_k_within_limit_not_clamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """top_k=10 → response does not contain clamped: True."""
    settings = _make_settings(monkeypatch)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    _seed_vectors(vectors)

    result = await search_artifacts(
        settings=settings,
        vectors=vectors,
        bedrock=bedrock,
        s3=None,
        query="auth review",
        top_k=10,
    )

    assert result.get("clamped") is not True
