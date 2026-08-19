"""Direct unit tests for arkeology.tools._search_helper.fetch_vectors_by_metadata.

Task 63 (Phase 12, codebase-hygiene pass): fetch_vectors_by_metadata is a newly
extracted shared helper (review finding F-3), so TDD applies to it directly.
The rest of _search_helper.py (run_search_loop, build_scope_filter, etc.) is
already covered indirectly via search.py/synthesise.py's test suites.
"""

from pytest_mock import MockerFixture

from arkeology.clients.vectors import VectorsClientImpl
from arkeology.tools._search_helper import fetch_vectors_by_metadata


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
