"""Unit tests for arkeology.tools._reference_filter.

Tests resolve_readable_targets() in isolation, using a moto-backed VectorsClientImpl.
This predicate is the single source of truth reused by read.py and list.py to filter
`references` on cross-scope reads (ADR-012, "Cross-scope reference filtering").
"""

import pytest
from pytest_mock import MockerFixture

from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.tools._reference_filter import resolve_readable_targets
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


async def test_skip_guard_does_not_abort_remaining_candidates(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A fetched item whose artifact_id is not in ``unresolved`` (e.g. malformed/empty
    metadata) must be *skipped*, not treated as a reason to abort the whole loop — later,
    genuinely readable candidates must still make it into the result.

    Regresses mutmut survivor mutant 45 (`.docs/issues/issue-2026-09-04-cross-scope-gate
    -mutation-survivors.md`), which flips the guard's ``continue`` to ``break``: under that
    mutant this test's second candidate would be silently dropped.
    """
    settings = _make_settings(monkeypatch)
    mocker.patch(
        "arkeology.tools._reference_filter.fetch_vectors_by_metadata",
        return_value=[
            {"metadata": {}},  # no artifact_id → candidate_id "" not in unresolved
            {
                "metadata": {
                    "artifact_id": "other-team/t3-shared",
                    "tier": 3,
                    "visibility": "shared",
                }
            },
        ],
    )

    result = await resolve_readable_targets(
        vectors_client_2,
        settings,
        {"other-team/does-not-exist", "other-team/t3-shared"},
    )

    assert result == {"other-team/t3-shared"}


async def test_refetch_omits_embedding_data(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The cross-scope re-fetch must request ``include_data=False`` — the readability
    check only ever consults metadata, so pulling embedding vectors here is pure waste.

    Regresses mutmut survivors 21/27 (`.docs/issues/issue-2026-09-04-cross-scope-gate
    -mutation-survivors.md`): no assertion elsewhere in this suite distinguishes
    ``include_data=False`` from ``True`` or from the argument being dropped entirely
    (interface default is ``True``). Asserting on call shape rather than result state is
    the deliberate exception noted in that issue and in
    `.docs/reviews/review-2026-08-20-test-suite-assertion-strength.md` Recommendation 6 —
    here the value protected *is* the call shape (a cost optimisation), not a result.
    """
    settings = _make_settings(monkeypatch)
    _seed(vectors_client_2)
    spy = mocker.spy(vectors_client_2, "get_vectors")

    await resolve_readable_targets(vectors_client_2, settings, {"other-team/t3-shared"})

    assert spy.call_count == 1
    assert spy.call_args.kwargs["include_data"] is False
