"""Direct unit tests for arkeology.tools._search_helper.

Task 63 (Phase 12, codebase-hygiene pass): fetch_vectors_by_metadata is a newly
extracted shared helper (review finding F-3), so TDD applies to it directly.
Task 68 (Phase 13, codebase-hygiene batch 2) adds build_artifact_summary (F-4),
clamp_top_k (F-5), and derive_last_edited_at (F-6) — each is a newly extracted
shared helper, so TDD applies directly to those too.
The rest of _search_helper.py (run_search_loop, build_scope_filter, etc.) is
already covered indirectly via search.py/synthesise.py's test suites.
"""

from pytest_mock import MockerFixture

from arkeology.clients.vectors import VectorsClientImpl
from arkeology.constants import ErrorCode
from arkeology.tools._search_helper import (
    build_artifact_summary,
    clamp_top_k,
    derive_last_edited_at,
    fetch_vectors_by_metadata,
)


def test_returns_empty_list_when_no_keys_match(vectors_client_2: VectorsClientImpl) -> None:
    result = fetch_vectors_by_metadata(vectors_client_2, {"artifact_id": {"$eq": "missing"}})
    assert result == []


def test_short_circuits_before_calling_get_vectors(
    vectors_client_2: VectorsClientImpl, mocker: MockerFixture
) -> None:
    """Empty keys → get_vectors is never called (no pointless round trip)."""
    spy = mocker.spy(vectors_client_2, "get_vectors")

    fetch_vectors_by_metadata(vectors_client_2, {"artifact_id": {"$eq": "missing"}})

    assert spy.call_count == 0


def test_returns_matching_vector_entries(vectors_client_2: VectorsClientImpl) -> None:
    vectors_client_2.put_vector(
        "artifacts/thing#section",
        [1.0, 0.0],
        {"artifact_id": "artifacts/thing", "tier": 2, "visibility": "hidden"},
    )

    result = fetch_vectors_by_metadata(
        vectors_client_2, {"artifact_id": {"$eq": "artifacts/thing"}}
    )

    assert len(result) == 1
    assert result[0]["metadata"]["artifact_id"] == "artifacts/thing"


def test_include_data_false_by_default(vectors_client_2: VectorsClientImpl) -> None:
    vectors_client_2.put_vector(
        "artifacts/thing#section",
        [1.0, 0.0],
        {"artifact_id": "artifacts/thing", "tier": 2, "visibility": "hidden"},
    )

    result = fetch_vectors_by_metadata(
        vectors_client_2, {"artifact_id": {"$eq": "artifacts/thing"}}
    )

    assert not result[0].get("data")


def test_include_data_true_returns_vector_data(vectors_client_2: VectorsClientImpl) -> None:
    vectors_client_2.put_vector(
        "artifacts/thing#section",
        [1.0, 0.0],
        {"artifact_id": "artifacts/thing", "tier": 2, "visibility": "hidden"},
    )

    result = fetch_vectors_by_metadata(
        vectors_client_2, {"artifact_id": {"$eq": "artifacts/thing"}}, include_data=True
    )

    assert result[0]["data"]["float32"] == [1.0, 0.0]


# ---------------------------------------------------------------------------
# build_artifact_summary (F-4)
# ---------------------------------------------------------------------------


def test_build_artifact_summary_returns_the_shared_fourteen_keys() -> None:
    meta = {
        "type": "code-review",
        "team": "platform",
        "project": "arkeology",
        "tier": 2,
        "date": "2026-08-19",
        "status": "active",
        "title": "A Title",
        "visibility": "hidden",
        "author_role": "developer",
        "description": "A description",
    }
    summary = build_artifact_summary(meta, "artifacts/a1", ["tag1"], ["artifacts/src1"])

    assert summary == {
        "artifact_id": "artifacts/a1",
        "type": "code-review",
        "team": "platform",
        "project": "arkeology",
        "tier": 2,
        "date": "2026-08-19",
        "status": "active",
        "title": "A Title",
        "visibility": "hidden",
        "tags": ["tag1"],
        "author_role": "developer",
        "description": "A description",
        "source_artifacts": ["artifacts/src1"],
        "last_edited_ulid": None,
    }


def test_build_artifact_summary_defaults_missing_author_role_and_ulid_to_none() -> None:
    summary = build_artifact_summary({}, "artifacts/a1", [], [])

    assert summary["author_role"] is None
    assert summary["last_edited_ulid"] is None


def test_build_artifact_summary_surfaces_last_edited_ulid_when_present() -> None:
    summary = build_artifact_summary(
        {"last_edited_ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAV"}, "artifacts/a1", [], []
    )

    assert summary["last_edited_ulid"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"


# ---------------------------------------------------------------------------
# clamp_top_k (F-5)
# ---------------------------------------------------------------------------


def test_clamp_top_k_passes_through_value_within_range() -> None:
    result = clamp_top_k(10)
    assert result == (10, False)


def test_clamp_top_k_clamps_value_above_ceiling() -> None:
    result = clamp_top_k(150)
    assert result == (100, True)


def test_clamp_top_k_rejects_zero_with_validation_error_dict() -> None:
    result = clamp_top_k(0)
    assert result == {
        "error": ErrorCode.VALIDATION_ERROR,
        "message": "top_k must be a positive integer, got 0",
    }


def test_clamp_top_k_rejects_negative_with_validation_error_dict() -> None:
    result = clamp_top_k(-1)
    assert result == {
        "error": ErrorCode.VALIDATION_ERROR,
        "message": "top_k must be a positive integer, got -1",
    }


# ---------------------------------------------------------------------------
# derive_last_edited_at (F-6)
# ---------------------------------------------------------------------------


def test_derive_last_edited_at_returns_none_for_falsy_ulid() -> None:
    assert derive_last_edited_at(None) is None
    assert derive_last_edited_at("") is None


def test_derive_last_edited_at_derives_iso_timestamp_from_valid_ulid() -> None:
    result = derive_last_edited_at("01ARZ3NDEKTSV4RRFFQ69G5FAV")
    assert result is not None
    assert "T" in result


def test_derive_last_edited_at_returns_none_for_malformed_ulid() -> None:
    result = derive_last_edited_at("not-a-valid-ulid")
    assert result is None
