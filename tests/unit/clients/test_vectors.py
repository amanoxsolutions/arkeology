"""Unit tests for VectorsClientImpl request chunking against S3 Vectors API limits.

The S3 Vectors API caps GetVectors at 100 keys per call and DeleteVectors at 500 keys
per call (https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html).
moto does not enforce these caps, so these tests spy on the underlying boto3 client to
assert the wrapper splits oversized key lists into compliant chunks rather than issuing a
single over-limit call (which AWS would reject with a ValidationException).
"""

import math
from typing import Any

import pytest
from pytest_mock import MockerFixture

from cairn_mcp.clients.vectors import (
    _DELETE_VECTORS_CHUNK_SIZE,
    _GET_VECTORS_CHUNK_SIZE,
    VectorsClientImpl,
)
from cairn_mcp.errors import VectorDistanceMissingError


def _put_n_vectors(client: VectorsClientImpl, n: int) -> list[str]:
    """Store *n* tiny (dim-2) vectors and return their keys."""
    items: list[dict[str, Any]] = [
        {"key": f"k{i}", "vector": [0.1, 0.2], "metadata": {"artifact_id": f"a{i}"}}
        for i in range(n)
    ]
    client.put_vectors_batch(items)
    return [item["key"] for item in items]


def test_get_vectors_chunks_oversized_key_list(
    vectors_client_2: VectorsClientImpl, mocker: MockerFixture
) -> None:
    """get_vectors splits a >100-key request into <=100-key API calls and returns all."""
    n = _GET_VECTORS_CHUNK_SIZE * 2 + 5  # 205 → 100 + 100 + 5
    keys = _put_n_vectors(vectors_client_2, n)
    spy = mocker.spy(vectors_client_2._client, "get_vectors")

    results = vectors_client_2.get_vectors(keys)

    assert len(results) == n
    assert spy.call_count == 3
    for call in spy.call_args_list:
        assert len(call.kwargs["keys"]) <= _GET_VECTORS_CHUNK_SIZE


def test_delete_vectors_chunks_oversized_key_list(
    vectors_client_2: VectorsClientImpl, mocker: MockerFixture
) -> None:
    """delete_vectors splits a >500-key request into <=500-key API calls and deletes all."""
    n = _DELETE_VECTORS_CHUNK_SIZE + 10  # 510 → 500 + 10
    keys = _put_n_vectors(vectors_client_2, n)
    spy = mocker.spy(vectors_client_2._client, "delete_vectors")

    vectors_client_2.delete_vectors(keys)

    assert spy.call_count == 2
    for call in spy.call_args_list:
        assert len(call.kwargs["keys"]) <= _DELETE_VECTORS_CHUNK_SIZE
    assert vectors_client_2.get_vectors(keys) == []


def test_get_vectors_empty_keys_makes_no_api_call(
    vectors_client_2: VectorsClientImpl, mocker: MockerFixture
) -> None:
    """get_vectors([]) returns [] without an API call (GetVectors requires >=1 key)."""
    spy = mocker.spy(vectors_client_2._client, "get_vectors")

    assert vectors_client_2.get_vectors([]) == []
    assert spy.call_count == 0


# ---------------------------------------------------------------------------
# C-1: query_vectors must request and honour returnDistance
# ---------------------------------------------------------------------------


def _unit_vec(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        return values
    return [v / norm for v in values]


def test_query_vectors_requests_return_distance(
    vectors_client_8: VectorsClientImpl, mocker: MockerFixture
) -> None:
    """query_vectors sends returnDistance=True to the underlying boto3 client.

    AWS defaults returnDistance to false; omitting it made every score 1.0 in
    production (C-1). Guard the exact request shape sent over the wire.
    """
    vec = _unit_vec([1.0] + [0.0] * 7)
    vectors_client_8.put_vector("k1", vec, {"artifact_id": "a/k1"})
    spy = mocker.spy(vectors_client_8._client, "query_vectors")

    vectors_client_8.query_vectors(vector=vec, top_k=5, filter_expr=None)

    assert spy.call_count == 1
    assert spy.call_args.kwargs["returnDistance"] is True


def test_query_vectors_missing_distance_raises(
    vectors_client_8: VectorsClientImpl, mocker: MockerFixture
) -> None:
    """A query_vectors result missing 'distance' raises, never defaults to score=1.0.

    Simulates a malformed/legacy response (e.g. returnDistance not honoured) by
    stubbing the underlying boto3 call directly — the wrapper must never treat a
    missing distance as perfect similarity.
    """
    mocker.patch.object(
        vectors_client_8._client,
        "query_vectors",
        return_value={"vectors": [{"key": "k1", "metadata": {"artifact_id": "a/k1"}}]},
    )

    with pytest.raises(VectorDistanceMissingError):
        vectors_client_8.query_vectors(vector=[1.0] + [0.0] * 7, top_k=5, filter_expr=None)


def test_query_vectors_scores_non_trivially_ordered(
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Vectors of differing similarity produce distinct, correctly ranked scores.

    Before the C-1 fix, every result scored 1.0 (returnDistance was never
    requested) so ranking silently degenerated to insertion order. This proves
    scores actually vary and rank correctly.
    """
    query = _unit_vec([1.0] + [0.0] * 7)
    near = _unit_vec([1.0, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    mid = _unit_vec([1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    far = _unit_vec([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    vectors_client_8.put_vector("near", near, {"artifact_id": "a/near"})
    vectors_client_8.put_vector("mid", mid, {"artifact_id": "a/mid"})
    vectors_client_8.put_vector("far", far, {"artifact_id": "a/far"})

    results = vectors_client_8.query_vectors(vector=query, top_k=10, filter_expr=None)

    scores_by_key = {r["key"]: r["score"] for r in results}
    assert len({round(s, 6) for s in scores_by_key.values()}) > 1, (
        f"all scores identical — ranking did not occur: {scores_by_key}"
    )
    assert scores_by_key["near"] > scores_by_key["mid"] > scores_by_key["far"]
    assert scores_by_key["near"] != 1.0 or scores_by_key["far"] != 1.0
