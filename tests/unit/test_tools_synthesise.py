"""Unit tests for arkeology.tools.synthesise.

Tests synthesise_artifacts() using moto-backed S3 + Vectors clients and FakeBedrockClient.
"""

import logging
import math
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pytest_mock import MockerFixture

from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import CredentialError, VectorDistanceMissingError
from arkeology.tools.search import search_artifacts
from arkeology.tools.synthesise import synthesise_artifacts
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, READ_PREFIXES="other-team", **overrides)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _unit_vec(seed: float, dim: int = 8) -> list[float]:
    raw = [seed + i * 0.1 for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


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
    """Seed S3 + vectors with representative artifacts for synthesise tests."""
    s3.put_object("artifacts/t2-review", _CONTENT + " (T2)", {**_BASE_S3_META})
    vectors.put_vector(
        "artifacts/t2-review#summary",
        _unit_vec(1.0),
        {**_BASE_VECTOR_META, "artifact_id": "artifacts/t2-review"},
    )

    s3.put_object(
        "artifacts/t3-shared-adr",
        _CONTENT + " (T3S)",
        {**_BASE_S3_META, "tier": "3", "type": "adr", "tags": "adr"},
    )
    vectors.put_vector(
        "artifacts/t3-shared-adr#summary",
        _unit_vec(0.9),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "artifacts/t3-shared-adr",
            "tier": 3,
            "type": "adr",
            "visibility": "shared",
        },
    )

    # foreign-scope tier 2 — should be EXCLUDED
    s3.put_object(
        "other-team/t2-foreign",
        _CONTENT + " (foreign T2)",
        {**_BASE_S3_META, "team": "network"},
    )
    vectors.put_vector(
        "other-team/t2-foreign#summary",
        _unit_vec(0.8),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t2-foreign",
            "scope": "other-team",
            "team": "network",
            "tier": 2,
        },
    )

    # foreign-scope tier 3 shared — should be INCLUDED
    s3.put_object(
        "other-team/t3-shared-foreign",
        _CONTENT + " (foreign T3S)",
        {**_BASE_S3_META, "tier": "3", "visibility": "shared", "team": "network"},
    )
    vectors.put_vector(
        "other-team/t3-shared-foreign#summary",
        _unit_vec(0.7),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-shared-foreign",
            "scope": "other-team",
            "team": "network",
            "tier": 3,
            "visibility": "shared",
        },
    )

    # foreign-scope tier 3 hidden — should be EXCLUDED
    s3.put_object(
        "other-team/t3-hidden-foreign",
        _CONTENT + " (foreign T3C)",
        {**_BASE_S3_META, "tier": "3", "visibility": "hidden", "team": "network"},
    )
    vectors.put_vector(
        "other-team/t3-hidden-foreign#summary",
        _unit_vec(0.6),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/t3-hidden-foreign",
            "scope": "other-team",
            "team": "network",
            "tier": 3,
            "visibility": "hidden",
        },
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_synthesise_returns_results_with_content(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Query with no filters → results contain full content."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        assert "content" in artifact
        assert artifact["content"] is not None


async def test_synthesise_result_has_all_required_fields(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Each result dict contains all required fields including content."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    required = [
        "artifact_id",
        "content",
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
    ]
    assert len(result["artifacts"]) > 0
    for artifact in result["artifacts"]:
        for field in required:
            assert field in artifact, f"Missing field '{field}' in result: {artifact}"


async def test_synthesise_result_missing_tier_metadata_defaults_gracefully(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """A vector whose metadata lacks 'tier' must not hard-crash the
    whole synthesise call. synthesise.py currently does ``int(meta["tier"])``
    (a plain dict subscript) instead of the ``.get("tier", 0)`` pattern
    already used by list.py — this raises a bare KeyError, caught only by
    the outer blanket except-Exception and surfaced as an unhelpful
    internal_error for the whole response, not just the malformed artifact.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    s3_client.put_object("artifacts/no-tier-artifact", _CONTENT, {**_BASE_S3_META})
    vectors_client_8.put_vector(
        "artifacts/no-tier-artifact#s1",
        _unit_vec(1.0),
        {
            **{k: v for k, v in _BASE_VECTOR_META.items() if k != "tier"},
            "artifact_id": "artifacts/no-tier-artifact",
            # "tier" deliberately omitted
        },
    )

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert "error" not in result, (
        f"A missing 'tier' field must not surface as an error, got: {result}"
    )
    assert result["artifacts"][0]["tier"] == 0, (
        f"Expected tier to default to 0 (mirroring list.py's .get('tier', 0) "
        f"convention), got: {result}"
    )


async def test_synthesise_tags_is_list(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """tags in results is a list, not a comma-separated string."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    for artifact in result["artifacts"]:
        assert isinstance(artifact["tags"], list)


async def test_synthesise_content_matches_s3_content(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """content in results matches what was written to S3."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    for artifact in result["artifacts"]:
        expected_content = s3_client.get_object(artifact["artifact_id"])
        assert artifact["content"] == expected_content


# ---------------------------------------------------------------------------
# top_k
# ---------------------------------------------------------------------------


async def test_synthesise_top_k_limits_results(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=2 → at most 2 results."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=2,
    )

    assert len(result["artifacts"]) <= 2


async def test_synthesise_top_k_default_is_10(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k absent → at most 10 results."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock, query="review"
    )

    assert len(result["artifacts"]) <= 10


async def test_synthesise_top_k_above_ceiling_clamped(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=150 → clamped to 100; no error."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=150,
    )

    assert len(result["artifacts"]) <= 100
    assert isinstance(result["artifacts"], list)


async def test_synthesise_top_k_zero_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=0 has no floor guard in the clamp — must return validation_error,
    not a silent empty artifacts list indistinguishable from a legitimate
    no-match query.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=0,
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for top_k=0, got: {result}"
    )


async def test_synthesise_top_k_negative_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=-5 has no floor guard in the clamp — must return validation_error."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=-5,
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for top_k=-5, got: {result}"
    )


async def test_synthesise_filter_type_typo_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """type='cod_review' (typo) must return validation_error — not a
    silent, misleadingly-empty result set that looks identical to a legitimate
    zero-match query.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        type="cod_review",
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for invalid type, got: {result}"
    )


# ---------------------------------------------------------------------------
# Cross-scope gate
# ---------------------------------------------------------------------------


async def test_synthesise_foreign_tier2_excluded(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Foreign-scope tier 2 artifact excluded from results."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=20,
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t2-foreign" not in ids


async def test_synthesise_foreign_tier3_shared_included(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Foreign-scope tier 3 shared artifact included with full content."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=20,
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-shared-foreign" in ids
    foreign = next(
        a for a in result["artifacts"] if a["artifact_id"] == "other-team/t3-shared-foreign"
    )
    assert "content" in foreign


async def test_synthesise_foreign_tier3_hidden_excluded(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Foreign-scope tier 3 hidden artifact excluded from results."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=20,
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/t3-hidden-foreign" not in ids


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


async def test_synthesise_s3_read_failure_skips_artifact(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """S3 get_object raises KeyError for one artifact → that artifact skipped; others returned."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    call_count: dict[str, int] = {"n": 0}
    original_get = s3_client.get_object

    def fail_first(key: str) -> str:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise KeyError(key)
        return original_get(key)

    mocker.patch.object(s3_client, "get_object", side_effect=fail_first)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert isinstance(result["artifacts"], list)


async def test_synthesise_s3_read_failure_reports_skip_count(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A non-credential S3 read failure for one candidate must be surfaced in the
    response (e.g. a skipped count), not silently vanish. Today the
    `except Exception: continue` branch in the content-fetch loop drops the failed
    candidate with no trace in the returned payload — a caller cannot tell the
    difference between "fewer results legitimately matched" and "a result was
    dropped due to a fetch error"."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    call_count: dict[str, int] = {"n": 0}
    original_get = s3_client.get_object

    def fail_first(key: str) -> str:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise KeyError(key)
        return original_get(key)

    mocker.patch.object(s3_client, "get_object", side_effect=fail_first)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert result.get("skipped_count") == 1, (
        "One candidate's content fetch failed and was skipped — that must be "
        f"reported in the response (e.g. skipped_count), got: {result}"
    )


async def test_synthesise_empty_search_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Search returns no results → empty list, no error."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="anything",
        top_k=5,
    )

    assert result["artifacts"] == []


async def test_synthesise_empty_search_includes_zero_results_field(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Zero matches must set zero_results=True, mirroring search_artifacts' shape
    — synthesise_artifacts currently returns a bare
    {"artifacts": []} with no equivalent signal that nothing matched."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="anything",
        top_k=5,
    )

    assert result.get("zero_results") is True, (
        f"Expected zero_results=True for a zero-match query, got: {result}"
    )


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_synthesise_embed_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Embed call raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=CredentialError("simulated", "bedrock", Exception("simulated")),
    )
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=5,
    )

    assert result.get("error") == "credential_error"


async def test_synthesise_query_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """query_vectors raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)
    mocker.patch.object(
        vectors_client_8,
        "query_vectors",
        side_effect=CredentialError(
            message="Credential failure (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=5,
    )

    assert result.get("error") == "credential_error"


async def test_synthesise_get_object_credential_error_is_hard_failure(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """get_object raises CredentialError (not KeyError) → structured error (hard failure)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)
    mocker.patch.object(
        s3_client,
        "get_object",
        side_effect=CredentialError(
            message="Simulated.",
            service="s3",
            original=Exception("sim"),
        ),
    )

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=5,
    )

    assert result.get("error") == "credential_error"


async def test_synthesise_vector_distance_missing_mid_loop_returns_partial_with_signal(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T66/C-1: a VectorDistanceMissingError raised by query_vectors after the first
    iteration already collected results is a soft signal, not a hard abort — the
    call still returns whatever partial results were already collected (never the
    structured error response CredentialError gets) and the response carries a
    distinct `index_corruption_detected` flag. Confirms the flag surfaces through
    synthesise_artifacts's own response assembly, not just search_artifacts's.
    """
    settings = _make_settings(monkeypatch, SEARCH_MAX_ITERATIONS="5", SEARCH_FETCH_TOP_K="1")
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

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
        result = await synthesise_artifacts(
            settings=settings,
            s3=s3_client,
            vectors=vectors_client_8,
            bedrock=bedrock,
            query="review",
            top_k=5,
        )

    assert "error" not in result, f"Expected partial success, got error response: {result}"
    assert len(result["artifacts"]) == 1
    assert call_count == 2
    assert result.get("index_corruption_detected") is True, (
        f"Expected index_corruption_detected=True, got: {result}"
    )
    assert any(
        r.levelno == logging.ERROR and "index corruption" in r.getMessage() for r in caplog.records
    ), f"Expected a distinct ERROR-level index-corruption log line, got: {caplog.records}"
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("Non-credential error" in r.getMessage() for r in warning_records), (
        "VectorDistanceMissingError must not be logged via the generic "
        "non-credential-failure WARNING message"
    )


# ---------------------------------------------------------------------------
# Spec 18 — top_k clamping
# ---------------------------------------------------------------------------


async def test_synthesise_top_k_over_limit_clamped(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=200 → response contains clamped: True and effective_top_k: 100."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=200,
    )

    assert result.get("clamped") is True
    assert result.get("effective_top_k") == 100


async def test_synthesise_top_k_within_limit_not_clamped(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=5 → response does not contain clamped: True."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_8)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=5,
    )

    assert result.get("clamped") is not True


# ---------------------------------------------------------------------------
# Response-size (byte) budget
# ---------------------------------------------------------------------------
#
# These tests patch run_search_loop (as imported into synthesise.py) with a
# fixed, already rank-ordered candidate list rather than relying on the real
# embedding-based search: FakeBedrockClient's hash-derived vectors make the
# relative ranking of the manually-seeded section vectors used elsewhere in
# this file non-deterministic across artifacts, and the budget logic
# depends on processing candidates in a known rank order.


def _content_of_size(n: int) -> str:
    """A deterministic ASCII string of exactly n UTF-8 bytes."""
    return "x" * n


def _entry(artifact_id: str, score: float) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "score": score,
        "meta": {**_BASE_VECTOR_META, "artifact_id": artifact_id},
    }


def _mock_search_loop(mocker: MockerFixture, entries: list[dict[str, Any]]) -> None:
    # run_search_loop returns (results, fetch_exhausted, index_corruption_detected,
    # skipped_malformed_count) on success.
    mocker.patch(
        "arkeology.tools.synthesise.run_search_loop",
        new=AsyncMock(return_value=(entries, False, False, 0)),
    )


async def test_synthesise_response_size_budget_default_unaffected(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Normal-sized artifacts well under the default 1 MB budget → response
    unaffected: no truncated/included fields, all matching results included."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    for i in range(3):
        aid = f"artifacts/normal-{i}"
        s3_client.put_object(aid, _content_of_size(1000), {**_BASE_S3_META})
    _mock_search_loop(mocker, [_entry(f"artifacts/normal-{i}", 1.0 - i * 0.01) for i in range(3)])

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert len(result["artifacts"]) == 3
    assert "truncated" not in result
    assert "included" not in result


async def test_synthesise_byte_budget_stops_assembly(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A budget too small to fit all rank-ordered candidates stops assembly before
    exceeding it; response sets truncated=True and included matches the actual
    number of results returned."""
    settings = _make_settings(monkeypatch, SYNTHESISE_MAX_RESPONSE_BYTES="1500")
    bedrock = FakeBedrockClient()
    for i in range(3):
        aid = f"artifacts/big-{i}"
        s3_client.put_object(aid, _content_of_size(1000), {**_BASE_S3_META})
    _mock_search_loop(mocker, [_entry(f"artifacts/big-{i}", 1.0 - i * 0.01) for i in range(3)])

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert [a["artifact_id"] for a in result["artifacts"]] == ["artifacts/big-0"]
    assert result.get("truncated") is True
    assert result.get("included") == 1


async def test_synthesise_count_ceiling_and_byte_budget_both_active(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """top_k over the 100 ceiling AND an unusually small byte budget → both guards
    apply simultaneously; clamped/effective_top_k and truncated/included co-occur."""
    settings = _make_settings(monkeypatch, SYNTHESISE_MAX_RESPONSE_BYTES="1000")
    bedrock = FakeBedrockClient()
    for i in range(3):
        aid = f"artifacts/ceiling-{i}"
        s3_client.put_object(aid, _content_of_size(800), {**_BASE_S3_META})
    _mock_search_loop(mocker, [_entry(f"artifacts/ceiling-{i}", 1.0 - i * 0.01) for i in range(3)])

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=200,
    )

    assert result.get("clamped") is True
    assert result.get("effective_top_k") == 100
    assert result.get("truncated") is True
    assert result.get("included") == 1


async def test_synthesise_single_oversized_first_result_included_anyway(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The single top-ranked candidate alone exceeds the budget → included anyway
    (never zero results for a single relevant oversized hit), with truncated=True."""
    settings = _make_settings(monkeypatch, SYNTHESISE_MAX_RESPONSE_BYTES="500")
    bedrock = FakeBedrockClient()
    aid = "artifacts/oversized-solo"
    s3_client.put_object(aid, _content_of_size(1000), {**_BASE_S3_META})
    _mock_search_loop(mocker, [_entry(aid, 1.0)])

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert [a["artifact_id"] for a in result["artifacts"]] == [aid]
    assert result.get("truncated") is True
    assert result.get("included") == 1


# ---------------------------------------------------------------------------
# Result-entry completeness — the fields the contract promises
# ---------------------------------------------------------------------------

_LINKED_ULID = "01KT07NV00FN74309G4MXHQ1KN"
_SOURCES = ["artifacts/src-a", "artifacts/src-b"]


async def test_synthesise_entry_carries_score_sources_and_last_edited(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """A result entry carries every metadata field plus content — including score,
    source_artifacts, last_edited_ulid and last_edited_at — and its score is the same
    value search_artifacts reports for the same artifact and query, so a caller can rank
    or age-discount synthesis results exactly as it ranks search results."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    aid = "artifacts/synthesis-with-links"
    s3_client.put_object(
        aid,
        _CONTENT,
        {
            **_BASE_S3_META,
            "source_artifacts": ",".join(_SOURCES),
            "last_edited_ulid": _LINKED_ULID,
        },
    )
    vectors_client_8.put_vector(
        f"{aid}#summary",
        _unit_vec(1.0),
        {
            **_BASE_VECTOR_META,
            "artifact_id": aid,
            "source_artifacts": _SOURCES,
            "last_edited_ulid": _LINKED_ULID,
        },
    )

    synthesised = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=5,
    )
    searched = await search_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=5,
    )

    entry = next(a for a in synthesised["artifacts"] if a["artifact_id"] == aid)
    search_entry = next(a for a in searched["artifacts"] if a["artifact_id"] == aid)

    assert entry["content"] == _CONTENT
    assert entry["source_artifacts"] == _SOURCES
    assert entry["last_edited_ulid"] == _LINKED_ULID
    assert entry["last_edited_at"] == search_entry["last_edited_at"]
    assert entry["score"] == pytest.approx(search_entry["score"])


async def test_synthesise_surfaces_fetch_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A budget-limited result set is distinguishable from an exhaustive one: when the
    re-fetch loop reports exhaustion, synthesise surfaces it under the same key and with
    the same meaning as search_artifacts."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    aid = "artifacts/exhausted"
    s3_client.put_object(aid, _CONTENT, {**_BASE_S3_META})
    mocker.patch(
        "arkeology.tools.synthesise.run_search_loop",
        new=AsyncMock(return_value=([_entry(aid, 1.0)], True, False, 0)),
    )

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert result.get("fetch_exhausted") is True


async def test_synthesise_omits_fetch_exhausted_when_loop_not_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The flag means something: a complete result set carries no fetch_exhausted key at
    all, matching search_artifacts' include-only-when-true convention."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    aid = "artifacts/not-exhausted"
    s3_client.put_object(aid, _CONTENT, {**_BASE_S3_META})
    _mock_search_loop(mocker, [_entry(aid, 1.0)])

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert "fetch_exhausted" not in result


# ---------------------------------------------------------------------------
# A malformed index record is skipped and counted, never fatal
# ---------------------------------------------------------------------------


async def test_synthesise_skips_a_malformed_candidate_and_still_assembles_the_rest(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Same rule, same shared helpers, same reported key as ``search_artifacts``: one
    candidate whose ``tier`` will not coerce is dropped, and every readable candidate
    beside it is still assembled."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    for aid in ("artifacts/good", "artifacts/bad-tier"):
        s3_client.put_object(aid, _CONTENT, {**_BASE_S3_META})
    entries = [
        _entry("artifacts/good", 1.0),
        {
            "artifact_id": "artifacts/bad-tier",
            "score": 0.9,
            "meta": {**_BASE_VECTOR_META, "artifact_id": "artifacts/bad-tier", "tier": "high"},
        },
    ]
    _mock_search_loop(mocker, entries)

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert [a["artifact_id"] for a in result["artifacts"]] == ["artifacts/good"]
    assert result["skipped_malformed_count"] == 1


async def test_synthesise_malformed_skip_is_disjoint_from_the_content_skip_count(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Two counters, because the operator's next action differs: ``skipped_count`` is a
    transient or permissions failure against S3, ``skipped_malformed_count`` is corrupt
    index metadata that ``reconcile_index`` repairs.

    The metadata check precedes the content fetch, so a malformed candidate is dropped
    before it costs an S3 read and can never appear in both.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    # Deliberately seeded in S3: if the malformed candidate were content-fetched at all,
    # it would succeed and reveal the ordering by never reaching either counter.
    s3_client.put_object("artifacts/bad-tier", _CONTENT, {**_BASE_S3_META})
    get_object = mocker.spy(s3_client, "get_object")
    _mock_search_loop(
        mocker,
        [
            {
                "artifact_id": "artifacts/bad-tier",
                "score": 0.9,
                "meta": {**_BASE_VECTOR_META, "artifact_id": "artifacts/bad-tier", "tier": "high"},
            }
        ],
    )

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert result["skipped_malformed_count"] == 1
    assert "skipped_count" not in result
    assert get_object.call_count == 0


async def test_synthesise_omits_the_skip_count_when_nothing_was_skipped(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Absent rather than falsy, like every other conditional key on this response."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    s3_client.put_object("artifacts/good", _CONTENT, {**_BASE_S3_META})
    _mock_search_loop(mocker, [_entry("artifacts/good", 1.0)])

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert "skipped_malformed_count" not in result


async def test_synthesise_reports_the_skip_count_beside_a_zero_result(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """On the zero-result short-circuit the count is deliberately on the short list of
    keys present: a zero result reached because every candidate was unreadable must not
    be mistaken for "no such artifact exists"."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    mocker.patch(
        "arkeology.tools.synthesise.run_search_loop",
        new=AsyncMock(return_value=([], False, False, 2)),
    )

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    assert result["zero_results"] is True
    assert result["skipped_malformed_count"] == 2


@pytest.mark.parametrize(
    ("tier", "visibility"),
    [([3], "shared"), (3, ["shared"])],
    ids=["list-valued-tier", "list-valued-visibility"],
)
async def test_synthesise_never_returns_a_candidate_the_predicate_denies(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    tier: object,
    visibility: object,
) -> None:
    """Same property as ``search_artifacts``, and it matters more here: this tool returns
    the artifact's full content, so a candidate the scope filter admits but the predicate
    denies would hand a foreign scope the body of a hidden artifact."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    s3_client.put_object("other-team/non-scalar", _CONTENT, {**_BASE_S3_META})
    vectors_client_8.put_vector(
        "other-team/non-scalar#summary",
        _unit_vec(1.0),
        {
            **_BASE_VECTOR_META,
            "artifact_id": "other-team/non-scalar",
            "scope": "other-team",
            "tier": tier,
            "visibility": visibility,
        },
    )

    result = await synthesise_artifacts(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=bedrock,
        query="review",
        top_k=10,
    )

    ids = [a["artifact_id"] for a in result["artifacts"]]
    assert "other-team/non-scalar" not in ids
    assert "skipped_malformed_count" not in result
