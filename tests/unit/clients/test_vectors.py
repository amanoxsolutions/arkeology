"""Unit tests for VectorsClientImpl request chunking against S3 Vectors API limits.

The S3 Vectors API caps GetVectors at 100 keys per call and DeleteVectors at 500 keys
per call (https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html).
moto does not enforce these caps, so these tests spy on the underlying boto3 client to
assert the wrapper splits oversized key lists into compliant chunks rather than issuing a
single over-limit call (which AWS would reject with a ValidationException).
"""

from typing import Any

from pytest_mock import MockerFixture

from cairn_mcp.clients.vectors import (
    _DELETE_VECTORS_CHUNK_SIZE,
    _GET_VECTORS_CHUNK_SIZE,
    VectorsClientImpl,
)


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
