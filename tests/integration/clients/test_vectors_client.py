"""Integration tests for VectorsClientImpl.

Requires real AWS credentials and a provisioned S3 Vectors index.
Run with: uv run pytest -m integration tests/integration/clients/test_vectors_client.py

Environment variables required:
    AWS_REGION      — AWS region
    VECTORS_BUCKET  — S3 Vectors bucket name
    VECTORS_INDEX   — S3 Vectors index name
    AWS_PROFILE     — (optional) named AWS profile

Integration checkpoints (document findings in docs/planning-artifacts/plan.md):
    - Verify put_vector on existing key is an upsert (no error, no duplicate).
    - Verify '#' is a valid character in S3 Vectors vector keys.
"""

import math
import os
import uuid

import pytest

from cairn_mcp.clients.vectors import VectorsClientImpl

pytestmark = pytest.mark.integration


def _unit_vec(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


@pytest.fixture
def vectors_client() -> VectorsClientImpl:
    region = os.environ["AWS_REGION"]
    bucket = os.environ["VECTORS_BUCKET"]
    index = os.environ["VECTORS_INDEX"]
    profile = os.environ.get("AWS_PROFILE")
    return VectorsClientImpl(region=region, profile=profile, bucket=bucket, index=index)


@pytest.fixture
def test_key() -> str:
    """Generate a unique vector key for test isolation."""
    return f"_cairn_integration_{uuid.uuid4().hex}"


def test_put_get_round_trip(vectors_client: VectorsClientImpl, test_key: str) -> None:
    """put_vector then get_vectors returns the stored vector and metadata."""
    vec = _unit_vec([1.0] + [0.0] * 1023)
    vectors_client.put_vector(test_key, vec, {"artifact_id": "test-001", "type": "review"})
    try:
        results = vectors_client.get_vectors([test_key])
        assert any(r["key"] == test_key for r in results)
    finally:
        vectors_client.delete_vectors([test_key])


def test_put_vector_upsert_not_duplicate(vectors_client: VectorsClientImpl, test_key: str) -> None:
    """put_vector on existing key is an upsert — not an error, not a duplicate.

    Integration checkpoint: document actual behaviour in plan.md under Learnings.
    """
    vec = _unit_vec([1.0] + [0.0] * 1023)
    vectors_client.put_vector(test_key, vec, {"type": "review"})
    vectors_client.put_vector(test_key, vec, {"type": "adr"})  # should not raise
    try:
        results = vectors_client.get_vectors([test_key])
        assert len([r for r in results if r["key"] == test_key]) == 1
    finally:
        vectors_client.delete_vectors([test_key])


def test_query_vectors_returns_result(vectors_client: VectorsClientImpl, test_key: str) -> None:
    """query_vectors returns a result for a vector close to an indexed one."""
    vec = _unit_vec([1.0] + [0.0] * 1023)
    vectors_client.put_vector(test_key, vec, {"artifact_id": "test-001"})
    try:
        results = vectors_client.query_vectors(vec, top_k=5, filter=None)
        assert any(r["key"] == test_key for r in results)
    finally:
        vectors_client.delete_vectors([test_key])


def test_describe_index_returns_dimension(vectors_client: VectorsClientImpl) -> None:
    """describe_index returns an index info dict with a dimension field."""
    info = vectors_client.describe_index()
    assert "dimension" in info
    assert isinstance(info["dimension"], int)
    assert info["dimension"] > 0


def test_hash_in_vector_key(vectors_client: VectorsClientImpl) -> None:
    """Verify '#' is a valid character in S3 Vectors vector keys.

    Integration checkpoint: document result in plan.md under Learnings.
    If '#' is invalid, '--' is the fallback separator.
    """
    key_with_hash = f"_cairn_integration_{uuid.uuid4().hex}#section-1"
    vec = _unit_vec([1.0] + [0.0] * 1023)
    try:
        vectors_client.put_vector(key_with_hash, vec, {"type": "review"})
        results = vectors_client.get_vectors([key_with_hash])
        assert any(r["key"] == key_with_hash for r in results)
    finally:
        vectors_client.delete_vectors([key_with_hash])
