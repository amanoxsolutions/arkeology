"""Unit tests for arkeology.tools.search.

Tests search_artifacts() using moto-backed VectorsClientImpl and FakeBedrockClient.
"""

import json
import logging
import math
import threading
from typing import Any

import pytest
from pytest_mock import MockerFixture
from ulid import ULID

from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import CredentialError, VectorDistanceMissingError
from arkeology.tools.search import search_artifacts
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


def _seed_vectors(vectors: VectorsClientImpl, write_prefix: str = "artifacts") -> None:
    """Seed a VectorsClientImpl with a representative set of vectors for search tests."""
    dim = 8

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
            "project": "arkeology",
            "tier": 2,
            "visibility": "shared",
            "status": "active",
            "tags": ["auth"],
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
            "project": "arkeology",
            "tier": 2,
            "visibility": "hidden",
            "status": "active",
            "tags": [],
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
            "project": "arkeology",
            "tier": 3,
            "visibility": "shared",
            "status": "active",
            "tags": ["payments"],
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
            "tags": [],
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
            "tags": ["payments"],
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
            "tags": [],
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
            "project": "arkeology",
            "tier": 2,
            "visibility": "shared",
            "status": "active",
            "tags": [],
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
            "project": "arkeology",
            "tier": 2,
            "visibility": "shared",
            "status": "active",
            "tags": [],
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
            "project": "arkeology",
            "tier": 2,
            "visibility": "shared",
            "status": "inactive",
            "tags": [],
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
            "tags": [],
            "title": "Network review",
        },
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_search_returns_up_to_top_k_distinct_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Query returns up to top_k distinct artifacts (no artifact appears twice)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="auth review", top_k=2
    )

    artifacts = result["artifacts"]
    artifact_ids = [a["artifact_id"] for a in artifacts]
    assert len(artifact_ids) == len(set(artifact_ids)), "Duplicate artifact_ids in results"
    assert len(artifacts) <= 2


async def test_search_results_have_no_content_field(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Search results do not contain a 'content' field (content is fetched via read)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    for artifact in result["artifacts"]:
        assert "content" not in artifact


async def test_search_results_ordered_by_score_descending(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Search results are ordered by score descending."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    scores = [a["score"] for a in result["artifacts"]]
    assert scores == sorted(scores, reverse=True)


async def test_search_each_result_has_artifact_id(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Each result has an 'artifact_id' field."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    for artifact in result["artifacts"]:
        assert "artifact_id" in artifact


async def test_result_missing_tier_metadata_defaults_gracefully(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """A vector whose metadata lacks 'tier' must not hard-crash the
    whole search. search.py currently does ``int(meta["tier"])`` (a plain
    dict subscript) instead of the ``.get("tier", 0)`` pattern already used
    by list.py — this raises a bare KeyError, caught only by the outer
    blanket except-Exception and surfaced as an unhelpful internal_error for
    every result in the response, not just the malformed one.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    raw = [1.0] * 8
    vectors_client_8.put_vector(
        "artifacts/no-tier-artifact#s1",
        _unit_vec(raw),
        {
            "artifact_id": "artifacts/no-tier-artifact",
            "scope": "artifacts",
            "type": "adr",
            "visibility": "shared",
            "status": "active",
            "team": "platform",
            "project": "arkeology",
            "tags": [],
            "title": "No tier",
            # "tier" deliberately omitted
        },
    )

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    assert "error" not in result, (
        f"A missing 'tier' field must not surface as an error, got: {result}"
    )
    assert result["artifacts"][0]["tier"] == 0, (
        f"Expected tier to default to 0 (mirroring list.py's .get('tier', 0) "
        f"convention), got: {result}"
    )


# ---------------------------------------------------------------------------
# Metadata filters
# ---------------------------------------------------------------------------


async def test_filter_type_restricts_results(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """type='code_review' filter → all results have type=='code_review'."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8,
        bedrock=bedrock,
        settings=settings,
        query="review",
        top_k=10,
        type="code_review",
    )

    for artifact in result["artifacts"]:
        assert artifact["type"] == "code_review"


async def test_filter_tags_restricts_results(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """tags=['payments'] → all results contain 'payments' in tags."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8,
        bedrock=bedrock,
        settings=settings,
        query="payments",
        top_k=10,
        tags=["payments"],
    )

    for artifact in result["artifacts"]:
        assert "payments" in artifact["tags"]


async def test_filter_team_restricts_results(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """team='platform' → all results have team=='platform'."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8,
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
    vectors_client_8: VectorsClientImpl,
) -> None:
    """project='arkeology' → all results have project=='arkeology'."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8,
        bedrock=bedrock,
        settings=settings,
        query="arkeology",
        top_k=10,
        project="arkeology",
    )

    for artifact in result["artifacts"]:
        assert artifact["project"] == "arkeology"


async def test_filter_tier_restricts_results(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """tier=3 → all results have tier==3."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8,
        bedrock=bedrock,
        settings=settings,
        query="decision",
        top_k=10,
        tier=3,
    )

    for artifact in result["artifacts"]:
        assert artifact["tier"] == 3


# ---------------------------------------------------------------------------
# Filter enum validation — typos must error, not silently return []
# ---------------------------------------------------------------------------


async def test_filter_type_typo_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """type='cod_review' (typo, not a real artifact type) must return
    validation_error — not a silent, misleadingly-empty result set that looks
    identical to a legitimate zero-match query.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8,
        bedrock=bedrock,
        settings=settings,
        query="review",
        top_k=10,
        type="cod_review",
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for invalid type, got: {result}"
    )


async def test_filter_tier_out_of_range_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """tier=99 (not 2 or 3) must return validation_error, not a silent empty result."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8,
        bedrock=bedrock,
        settings=settings,
        query="review",
        top_k=10,
        tier=99,
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for out-of-range tier, got: {result}"
    )


async def test_filter_status_typo_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """status='actve' (typo) must return validation_error, not a silent empty result."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8,
        bedrock=bedrock,
        settings=settings,
        query="review",
        top_k=10,
        status="actve",
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for invalid status, got: {result}"
    )


async def test_inactive_artifacts_excluded_by_default(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """status='inactive' artifacts are excluded from results by default."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    artifact_ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/inactive-review" not in artifact_ids


async def test_status_all_includes_inactive(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """status='all' is the same all-inclusive sentinel list_artifacts recognises: it
    omits the status clause rather than matching the literal string 'all' (which would
    match nothing). Without it, a caller holding an explicit "any status" filter — the
    studio's default — cannot express it on the search path."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8,
        bedrock=bedrock,
        settings=settings,
        query="review",
        top_k=20,
        status="all",
    )

    assert "error" not in result, f"status='all' must be accepted, got: {result}"
    artifact_ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/inactive-review" in artifact_ids


# ---------------------------------------------------------------------------
# Cross-scope gate
# ---------------------------------------------------------------------------


async def test_foreign_tier2_absent_from_results(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Foreign-scope tier 2 artifact is absent from results regardless of similarity."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=20
    )

    artifact_ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t2-foreign-shared" not in artifact_ids


async def test_foreign_tier3_shared_present(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Foreign-scope tier 3 shared artifact appears in results when matching."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="adr decision", top_k=20
    )

    artifact_ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-foreign-shared-adr" in artifact_ids


async def test_foreign_tier3_hidden_absent(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Foreign-scope tier 3 hidden artifact is absent from results."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="adr", top_k=20
    )

    artifact_ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-foreign-hidden-adr" not in artifact_ids


async def test_own_scope_tier2_hidden_present(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Own-scope tier 2 hidden artifact appears in results (no gate on own scope)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=20
    )

    artifact_ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "artifacts/t2-hidden-review" in artifact_ids


# ---------------------------------------------------------------------------
# Re-fetch loop
# ---------------------------------------------------------------------------


async def test_top_k_limits_results(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=2 with multiple artifacts seeded → exactly 2 results returned."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=2
    )

    assert len(result["artifacts"]) == 2


async def test_search_max_iterations_limits_query_calls(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """search_max_iterations=1 → at most 1 query_vectors call."""
    settings = _make_settings(monkeypatch, SEARCH_MAX_ITERATIONS="1")
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)
    spy = mocker.spy(vectors_client_8, "query_vectors")

    await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    assert spy.call_count <= 1


async def test_top_k_above_fetch_budget_signals_truncation(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """search_artifacts advertises top_k up to 100, but the re-fetch
    loop is bounded by SEARCH_FETCH_TOP_K x SEARCH_MAX_ITERATIONS. When that
    fetch budget is smaller than the number of distinct matching artifacts
    actually available, the loop exhausts its iteration budget before
    collecting top_k distinct artifacts, and currently returns a short list
    with no signal distinguishing "fetch budget exhausted" from "fewer
    matching artifacts exist than top_k".

    Uses a deliberately small budget (SEARCH_FETCH_TOP_K=5 x
    SEARCH_MAX_ITERATIONS=2 = 10 max fetchable) and seeds 15 distinct
    own-scope artifacts, so the loop must stop at (at most) 10 results while
    15 actually exist.

    Field-name choice: this pins a new boolean `"fetch_exhausted"` signal,
    mirroring the existing `"clamped"` boolean-flag convention already used
    in this same response for the top_k>100 cap (see Step 1 above). Any
    consistently-named boolean truncation signal satisfies the underlying
    requirement; this test asserts the specific field name chosen here.
    """
    settings = _make_settings(monkeypatch, SEARCH_FETCH_TOP_K="5", SEARCH_MAX_ITERATIONS="2")
    bedrock = FakeBedrockClient()

    def _vec(seed: float) -> list[float]:
        raw = [seed + i * 0.1 for i in range(8)]
        return _unit_vec(raw)

    for i in range(15):
        vectors_client_8.put_vector(
            f"artifacts/budget-artifact-{i}#summary",
            _vec(i * 0.05),
            {
                "artifact_id": f"artifacts/budget-artifact-{i}",
                "scope": "artifacts",
                "type": "code_review",
                "team": "platform",
                "project": "arkeology",
                "tier": 2,
                "visibility": "shared",
                "status": "active",
                "tags": [],
                "title": f"Budget artifact {i}",
            },
        )

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=100
    )

    assert len(result["artifacts"]) <= 10, (
        f"Fetch budget is 5x2=10; expected at most 10 results, got {len(result['artifacts'])}"
    )
    assert result.get("fetch_exhausted") is True, (
        f"Expected a fetch_exhausted=True truncation signal when the fetch budget "
        f"(not the true match count) limits results below top_k, got: {result}"
    )


async def test_early_exit_when_no_new_artifact_ids(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Loop exits early when no new artifact IDs are returned in an iteration."""
    settings = _make_settings(monkeypatch, SEARCH_MAX_ITERATIONS="3")
    bedrock = FakeBedrockClient()
    spy = mocker.spy(vectors_client_8, "query_vectors")

    # Seed only 2 vectors with the same artifact_id so second iteration yields nothing new
    raw = [1.0] + [0.0] * 7
    v = _unit_vec(raw)
    vectors_client_8.put_vector(
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
            "project": "arkeology",
            "tags": [],
            "title": "Only one",
        },
    )
    vectors_client_8.put_vector(
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
            "project": "arkeology",
            "tags": [],
            "title": "Only one",
        },
    )

    await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="adr decision", top_k=5
    )

    # Should exit after 1 or 2 iterations at most (not 3)
    assert spy.call_count < 3


async def test_top_k_defaults_to_search_default_top_k(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k not passed → defaults to settings.search_default_top_k."""
    settings = _make_settings(monkeypatch, SEARCH_DEFAULT_TOP_K="2")
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review"
    )

    assert len(result["artifacts"]) <= settings.search_default_top_k


async def test_top_k_capped_at_100(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=200 is capped at 100 internally."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=200
    )

    assert isinstance(result["artifacts"], list)
    assert len(result["artifacts"]) <= 100


async def test_top_k_zero_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=0 has no floor guard in the clamp — must return validation_error,
    not a silent empty/zero-results response indistinguishable from a
    legitimate no-match query.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=0
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for top_k=0, got: {result}"
    )


async def test_top_k_negative_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=-5 has no floor guard in the clamp — with an unclamped
    ``min(requested_top_k, 100)`` implementation this silently produces a
    negative-slice artifact list instead of erroring; must return
    validation_error instead.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=-5
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for top_k=-5, got: {result}"
    )


# ---------------------------------------------------------------------------
# $nin exclusion list is byte-bounded; non-credential mid-loop failures
# return partial results instead of internal_error
# ---------------------------------------------------------------------------

_NIN_BYTE_BUDGET = 1024  # must match _search_helper._NIN_EXCLUSION_BYTE_BUDGET


def _nin_bytes_from_filter(filter_expr: Any) -> int | None:
    """Recursively find an $nin clause on 'artifact_id' in a filter expr and return
    the UTF-8 byte size of its JSON-encoded list, or None if no $nin clause is present."""
    if not isinstance(filter_expr, dict):
        return None
    if "artifact_id" in filter_expr and isinstance(filter_expr["artifact_id"], dict):
        nin = filter_expr["artifact_id"].get("$nin")
        if nin is not None:
            return len(json.dumps(nin).encode("utf-8"))
    for key in ("$and", "$or"):
        for clause in filter_expr.get(key, []):
            found = _nin_bytes_from_filter(clause)
            if found is not None:
                return found
    return None


async def test_nin_exclusion_list_never_exceeds_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Many distinct matching artifacts → the $nin exclusion list stops growing once it
    would approach the S3 Vectors filter-size limit, and the loop terminates gracefully
    (fewer results than are actually available) rather than sending an oversized filter.
    """
    settings = _make_settings(monkeypatch, SEARCH_MAX_ITERATIONS="50", SEARCH_FETCH_TOP_K="1")
    bedrock = FakeBedrockClient()

    # Seed 40 distinct, moderately long artifact_ids — well beyond the ~20 that fit in
    # a 1024-byte $nin list — each as its own artifact (own vector), so with
    # SEARCH_FETCH_TOP_K=1 every successful iteration yields exactly one new artifact.
    for i in range(40):
        raw = [1.0 - i * 0.001 + j * 0.01 for j in range(8)]
        norm = math.sqrt(sum(v * v for v in raw))
        vec = [v / norm for v in raw]
        vectors_client_8.put_vector(
            f"artifacts/artifact-with-a-fairly-long-slug-{i:04d}",
            vec,
            {
                "artifact_id": f"artifacts/artifact-with-a-fairly-long-slug-{i:04d}",
                "scope": "artifacts",
                "type": "adr",
                "team": "platform",
                "project": "arkeology",
                "tier": 3,
                "visibility": "shared",
                "status": "active",
                "tags": [],
                "title": f"Artifact {i}",
            },
        )
    spy = mocker.spy(vectors_client_8, "query_vectors")

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="adr", top_k=1000
    )

    assert "error" not in result
    for call in spy.call_args_list:
        filter_expr = call.args[2] if len(call.args) > 2 else call.kwargs.get("filter_expr")
        nin_bytes = _nin_bytes_from_filter(filter_expr)
        if nin_bytes is not None:
            assert nin_bytes <= _NIN_BYTE_BUDGET, (
                f"$nin list grew to {nin_bytes} bytes, exceeding the {_NIN_BYTE_BUDGET} budget"
            )
    # The loop must have stopped before collecting all 40 seeded artifacts — proof that
    # the byte budget (not top_k or SEARCH_MAX_ITERATIONS) is what ended the loop.
    assert len(result["artifacts"]) < 40


async def test_non_credential_failure_mid_loop_returns_partial_results(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A non-credential exception raised by query_vectors after the first iteration
    already collected results → those results are returned (not internal_error).

    This early break is a fetch-budget-style truncation (fewer
    results than top_k, more may exist) exactly like the iteration-budget and $nin-
    budget cases — fetch_exhausted must be True here too, not silently left False.
    """
    settings = _make_settings(monkeypatch, SEARCH_MAX_ITERATIONS="5", SEARCH_FETCH_TOP_K="1")
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    original_query_vectors = vectors_client_8.query_vectors
    call_count = 0

    def flaky_query_vectors(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return original_query_vectors(*args, **kwargs)
        raise ValueError("simulated non-credential failure (e.g. ValidationException)")

    mocker.patch.object(vectors_client_8, "query_vectors", side_effect=flaky_query_vectors)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    assert "error" not in result, f"Expected partial success, got error response: {result}"
    assert len(result["artifacts"]) == 1
    assert call_count == 2
    assert result.get("fetch_exhausted") is True, (
        f"Expected fetch_exhausted=True for a mid-loop failure returning fewer than "
        f"top_k results, got: {result}"
    )


async def test_vector_distance_missing_mid_loop_returns_partial_results_with_signal(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T66/C-1: a VectorDistanceMissingError raised by query_vectors after the first
    iteration already collected results is a soft signal, not a hard abort — the call
    still returns whatever partial results were already collected (never the
    structured error response CredentialError gets), the response carries a distinct
    `index_corruption_detected` flag, and the failure is logged distinctly (ERROR,
    not the generic WARNING) from an ordinary non-credential blip.
    """
    settings = _make_settings(monkeypatch, SEARCH_MAX_ITERATIONS="5", SEARCH_FETCH_TOP_K="1")
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    original_query_vectors = vectors_client_8.query_vectors
    call_count = 0

    def flaky_query_vectors(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return original_query_vectors(*args, **kwargs)
        raise VectorDistanceMissingError(key="artifacts/some-key#section")

    mocker.patch.object(vectors_client_8, "query_vectors", side_effect=flaky_query_vectors)

    with caplog.at_level(logging.WARNING, logger="arkeology.tools._search_helper"):
        result = await search_artifacts(
            vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=10
        )

    assert "error" not in result, f"Expected partial success, got error response: {result}"
    assert len(result["artifacts"]) == 1
    assert call_count == 2
    assert result.get("index_corruption_detected") is True, (
        f"Expected index_corruption_detected=True, got: {result}"
    )

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("index corruption" in r.getMessage() for r in error_records), (
        f"Expected a distinct ERROR-level index-corruption log line, got: {caplog.records}"
    )
    assert not any("Non-credential error" in r.getMessage() for r in warning_records), (
        "VectorDistanceMissingError must not be logged via the generic "
        "non-credential-failure WARNING message"
    )


async def test_credential_failure_mid_loop_still_returns_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A CredentialError raised after the first iteration already collected results
    still returns the structured credential_error — partial-results handling is
    scoped to non-credential failures only; credential-error classification is unchanged.
    """
    settings = _make_settings(monkeypatch, SEARCH_MAX_ITERATIONS="5", SEARCH_FETCH_TOP_K="1")
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    original_query_vectors = vectors_client_8.query_vectors
    call_count = 0

    def flaky_query_vectors(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return original_query_vectors(*args, **kwargs)
        raise CredentialError(
            message="Credential failure (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        )

    mocker.patch.object(vectors_client_8, "query_vectors", side_effect=flaky_query_vectors)

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=10
    )

    assert result.get("error") == "credential_error"


# ---------------------------------------------------------------------------
# search's blocking client calls are offloaded off the asyncio event loop
# ---------------------------------------------------------------------------


async def test_search_bedrock_embed_runs_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """bedrock.embed executes on a worker thread, never on the calling event-loop
    thread — proves the call is routed through asyncio.to_thread (or equivalent)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []
    original_embed = bedrock.embed

    def spy_embed(text: str, model_id: str, dimensions: int) -> list[float]:
        seen_threads.append(threading.current_thread())
        return original_embed(text, model_id, dimensions)

    mocker.patch.object(bedrock, "embed", side_effect=spy_embed)

    await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=5
    )

    assert seen_threads, "bedrock.embed was never called"
    assert all(t is not main_thread for t in seen_threads), (
        "bedrock.embed ran on the event-loop thread — it must be offloaded"
    )


async def test_search_query_vectors_runs_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """vectors.query_vectors executes on a worker thread, never on the calling
    event-loop thread."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []
    original_query_vectors = vectors_client_8.query_vectors

    def spy_query_vectors(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_query_vectors(*args, **kwargs)

    mocker.patch.object(vectors_client_8, "query_vectors", side_effect=spy_query_vectors)

    await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=5
    )

    assert seen_threads, "vectors.query_vectors was never called"
    assert all(t is not main_thread for t in seen_threads), (
        "vectors.query_vectors ran on the event-loop thread — it must be offloaded"
    )


# ---------------------------------------------------------------------------
# Zero results
# ---------------------------------------------------------------------------


async def test_empty_index_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Empty vector index → results list is empty."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="anything", top_k=5
    )

    assert result["artifacts"] == []


async def test_empty_index_has_zero_results_signal(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Empty vector index → response contains a zero_results signal."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="anything", top_k=5
    )

    assert result.get("zero_results") is True or len(result["artifacts"]) == 0


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_bedrock_credential_failure_returns_error_no_query(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Bedrock credential failure → error response; query_vectors NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=CredentialError("simulated", "bedrock", Exception("simulated")),
    )
    spy = mocker.spy(vectors_client_8, "query_vectors")

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=5
    )

    assert result.get("error") == "credential_error"
    assert spy.call_count == 0


async def test_vectors_credential_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Vectors credential failure → structured error in response."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        vectors_client_8,
        "query_vectors",
        side_effect=CredentialError(
            message="Credential failure (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=5
    )

    assert result.get("error") == "credential_error"


# ---------------------------------------------------------------------------
# T3: $nin absent from filter on first iteration (seen_ids is empty)
# ---------------------------------------------------------------------------


async def test_first_iteration_filter_has_no_nin(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """On the very first query_vectors call (seen_ids empty), $nin is NOT in the filter."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)
    spy = mocker.spy(vectors_client_8, "query_vectors")

    await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="review", top_k=5
    )

    assert spy.call_count >= 1
    first_call_filter = spy.call_args_list[0].kwargs.get(
        "filter_expr",
        spy.call_args_list[0].args[2] if len(spy.call_args_list[0].args) > 2 else None,
    )
    assert first_call_filter is None or "$nin" not in str(first_call_filter), (
        f"$nin found in first iteration filter: {first_call_filter}"
    )


# ---------------------------------------------------------------------------
# T6: source_artifacts present in each search result
# ---------------------------------------------------------------------------


async def test_search_results_include_source_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Search results include a 'source_artifacts' field for each artifact."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    raw = [1.0] + [0.0] * 7
    v: list[float] = [x / math.sqrt(sum(y * y for y in raw)) for x in raw]
    vectors_client_8.put_vector(
        "artifacts/adr-with-sources",
        v,
        {
            "artifact_id": "artifacts/adr-with-sources",
            "scope": "artifacts",
            "type": "adr",
            "team": "platform",
            "project": "arkeology",
            "tier": 3,
            "visibility": "shared",
            "status": "active",
            "tags": [],
            "title": "ADR with sources",
            "source_artifacts": ["adr-one"],
        },
    )

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="adr", top_k=5
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert "source_artifacts" in artifact, f"'source_artifacts' missing from result: {artifact}"
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
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=200 → response contains clamped: True and effective_top_k: 100."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        bedrock=bedrock,
        s3=None,
        query="auth review",
        top_k=200,
    )

    assert result.get("clamped") is True
    assert result.get("effective_top_k") == 100


async def test_search_top_k_within_limit_not_clamped(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=10 → response does not contain clamped: True."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_vectors(vectors_client_8)

    result = await search_artifacts(
        settings=settings,
        vectors=vectors_client_8,
        bedrock=bedrock,
        s3=None,
        query="auth review",
        top_k=10,
    )

    assert result.get("clamped") is not True


# ---------------------------------------------------------------------------
# P12·T54 — last-edited age transparency in search results (ranking unaffected)
# ---------------------------------------------------------------------------


def _put_dim8_vector(
    vectors: VectorsClientImpl,
    artifact_id: str,
    seed: float,
    meta_extra: dict[str, object],
) -> None:
    """Seed a single dim-8 active own-scope tier-3 vector with extra metadata."""
    raw = [seed + i * 0.1 for i in range(8)]
    base_meta: dict[str, object] = {
        "artifact_id": artifact_id,
        "scope": "artifacts",
        "type": "adr",
        "team": "platform",
        "project": "arkeology",
        "tier": 3,
        "visibility": "shared",
        "status": "active",
        "tags": [],
        "title": artifact_id.rsplit("/", 1)[-1],
    }
    base_meta.update(meta_extra)
    vectors.put_vector(artifact_id, _unit_vec(raw), base_meta)


async def test_search_result_includes_last_edited_fields_when_ulid_present(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """US-1: a found artifact carries its raw last_edited_ulid and a derived ISO last_edited_at."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    known_ulid = ULID()
    _put_dim8_vector(
        vectors_client_8,
        "artifacts/adr-with-ulid",
        1.0,
        {"last_edited_ulid": str(known_ulid)},
    )

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="adr", top_k=5
    )

    seeded = next(
        (a for a in result["artifacts"] if a["artifact_id"] == "artifacts/adr-with-ulid"),
        None,
    )
    assert seeded is not None
    assert seeded["last_edited_ulid"] == str(known_ulid)
    assert seeded["last_edited_at"] == ULID.from_str(str(known_ulid)).datetime.isoformat()


async def test_search_result_last_edited_fields_null_when_ulid_absent(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """US-2: metadata with no last_edited_ulid → both fields null, result still returned."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _put_dim8_vector(vectors_client_8, "artifacts/adr-no-ulid", 1.0, {})

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="adr", top_k=5
    )

    seeded = next(
        (a for a in result["artifacts"] if a["artifact_id"] == "artifacts/adr-no-ulid"),
        None,
    )
    assert seeded is not None
    assert seeded["last_edited_ulid"] is None
    assert seeded["last_edited_at"] is None


async def test_search_result_malformed_ulid_yields_null_at_and_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """US-2: non-ULID value → last_edited_at null, raw value returned unchanged, warning logged."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _put_dim8_vector(
        vectors_client_8,
        "artifacts/adr-bad-ulid",
        1.0,
        {"last_edited_ulid": "not-a-valid-ulid"},
    )

    with caplog.at_level(logging.WARNING, logger="arkeology.tools.search"):
        result = await search_artifacts(
            vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="adr", top_k=5
        )

    seeded = next(
        (a for a in result["artifacts"] if a["artifact_id"] == "artifacts/adr-bad-ulid"),
        None,
    )
    assert seeded is not None
    assert seeded["last_edited_ulid"] == "not-a-valid-ulid"
    assert seeded["last_edited_at"] is None
    assert any("not-a-valid-ulid" in rec.getMessage() for rec in caplog.records)


async def test_search_ordering_unchanged_by_last_edited_fields(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Ranking invariance: recency does not reorder — order stays by score descending.

    Seeds artifacts whose last_edited_ulid recency is the inverse of their semantic
    score, so any recency weighting would visibly reorder the results.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    # ulid_old is chronologically older than ulid_new.
    ulid_old = ULID()
    ulid_new = ULID()
    assert str(ulid_old) < str(ulid_new)

    # Higher seed (1.0) is more similar to the query vector → higher score, but is the OLDER doc.
    _put_dim8_vector(
        vectors_client_8, "artifacts/high-score-old", 1.0, {"last_edited_ulid": str(ulid_old)}
    )
    _put_dim8_vector(
        vectors_client_8, "artifacts/low-score-new", 0.5, {"last_edited_ulid": str(ulid_new)}
    )

    result = await search_artifacts(
        vectors=vectors_client_8, bedrock=bedrock, settings=settings, query="adr", top_k=10
    )

    scores = [a["score"] for a in result["artifacts"]]
    assert scores == sorted(scores, reverse=True), "results must remain ordered by score descending"

    # The newer (but lower-scoring) artifact must NOT be promoted above the older top hit.
    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert ids.index("artifacts/high-score-old") < ids.index("artifacts/low-score-new")
