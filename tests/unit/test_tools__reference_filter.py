"""Unit tests for cairn_mcp.tools._reference_filter.

Tests resolve_readable_targets() in isolation, using a moto-backed VectorsClientImpl.
This predicate is the single source of truth reused by read.py and list.py to filter
`references` on cross-scope reads (ADR-012, "Cross-scope reference filtering").
"""

import pytest
from pytest_mock import MockerFixture

from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.tools._reference_filter import resolve_readable_targets
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, READ_PREFIXES="other-team", **overrides)


def _seed(vectors: VectorsClientImpl) -> None:
    """Seed representative candidate targets for resolve_readable_targets tests."""
    vectors.put_vector(
        "artifacts/own-hidden#summary",
        [1.0, 0.0],
        {"artifact_id": "artifacts/own-hidden", "tier": 2, "visibility": "hidden"},
    )
    vectors.put_vector(
        "other-team/t3-shared#summary",
        [0.0, 1.0],
        {"artifact_id": "other-team/t3-shared", "tier": 3, "visibility": "shared"},
    )
    vectors.put_vector(
        "other-team/t2-hidden#summary",
        [0.5, 0.5],
        {"artifact_id": "other-team/t2-hidden", "tier": 2, "visibility": "shared"},
    )
    vectors.put_vector(
        "other-team/t3-hidden#summary",
        [0.2, 0.8],
        {"artifact_id": "other-team/t3-hidden", "tier": 3, "visibility": "hidden"},
    )


async def test_own_scope_always_readable(
    monkeypatch: pytest.MonkeyPatch, vectors_client_2: VectorsClientImpl
) -> None:
    """Own-scope candidate → always readable, regardless of tier/visibility."""
    settings = _make_settings(monkeypatch)
    _seed(vectors_client_2)

    result = await resolve_readable_targets(vectors_client_2, settings, {"artifacts/own-hidden"})

    assert result == {"artifacts/own-hidden"}


async def test_foreign_tier3_shared_readable(
    monkeypatch: pytest.MonkeyPatch, vectors_client_2: VectorsClientImpl
) -> None:
    """Foreign-scope candidate with tier=3 and visibility=shared → readable."""
    settings = _make_settings(monkeypatch)
    _seed(vectors_client_2)

    result = await resolve_readable_targets(vectors_client_2, settings, {"other-team/t3-shared"})

    assert result == {"other-team/t3-shared"}


async def test_foreign_tier2_not_readable(
    monkeypatch: pytest.MonkeyPatch, vectors_client_2: VectorsClientImpl
) -> None:
    """Foreign-scope candidate with tier=2 (even if visibility=shared) → not readable."""
    settings = _make_settings(monkeypatch)
    _seed(vectors_client_2)

    result = await resolve_readable_targets(vectors_client_2, settings, {"other-team/t2-hidden"})

    assert result == set()


async def test_foreign_tier3_hidden_not_readable(
    monkeypatch: pytest.MonkeyPatch, vectors_client_2: VectorsClientImpl
) -> None:
    """Foreign-scope candidate with tier=3 but visibility != shared → not readable."""
    settings = _make_settings(monkeypatch)
    _seed(vectors_client_2)

    result = await resolve_readable_targets(vectors_client_2, settings, {"other-team/t3-hidden"})

    assert result == set()


async def test_missing_target_not_readable(
    monkeypatch: pytest.MonkeyPatch, vectors_client_2: VectorsClientImpl
) -> None:
    """Candidate with no matching vector entry (deleted/never existed) → excluded, fail safe."""
    settings = _make_settings(monkeypatch)
    _seed(vectors_client_2)

    result = await resolve_readable_targets(
        vectors_client_2, settings, {"other-team/does-not-exist"}
    )

    assert result == set()


async def test_empty_candidate_set_returns_empty(
    monkeypatch: pytest.MonkeyPatch, vectors_client_2: VectorsClientImpl
) -> None:
    """Empty candidate set → empty result, no vector-client calls."""
    settings = _make_settings(monkeypatch)

    result = await resolve_readable_targets(vectors_client_2, settings, set())

    assert result == set()


async def test_mixed_candidates_resolved_in_single_batched_query(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Own-scope + multiple foreign candidates → exactly one list_vectors_by_metadata call
    covers the whole unresolved (foreign) subset."""
    settings = _make_settings(monkeypatch)
    _seed(vectors_client_2)
    spy = mocker.spy(vectors_client_2, "list_vectors_by_metadata")

    result = await resolve_readable_targets(
        vectors_client_2,
        settings,
        {"artifacts/own-hidden", "other-team/t3-shared", "other-team/t2-hidden"},
    )

    assert result == {"artifacts/own-hidden", "other-team/t3-shared"}
    assert spy.call_count == 1


async def test_all_own_scope_candidates_issue_no_vector_query(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """All-own-scope candidate set → resolved by prefix alone, zero vector-client calls."""
    settings = _make_settings(monkeypatch)
    spy = mocker.spy(vectors_client_2, "list_vectors_by_metadata")

    result = await resolve_readable_targets(
        vectors_client_2, settings, {"artifacts/own-a", "artifacts/own-b"}
    )

    assert result == {"artifacts/own-a", "artifacts/own-b"}
    assert spy.call_count == 0
