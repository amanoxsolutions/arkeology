"""Unit tests for FakeVectorsClient — full interface coverage."""

import math

import pytest

from cairn_mcp.clients.fakes.fake_vectors import FakeVectorsClient
from cairn_mcp.errors import CredentialError, VectorIndexNotFoundError


def _unit_vec(values: list[float]) -> list[float]:
    """Normalise a vector to unit length."""
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        return values
    return [v / norm for v in values]


def test_put_get_round_trip() -> None:
    """put_vector then get_vectors returns the stored vector and metadata."""
    client = FakeVectorsClient()
    vec = _unit_vec([1.0, 0.0, 0.0])
    client.put_vector("section#001", vec, {"artifact_id": "art-001", "type": "review"})
    results = client.get_vectors(["section#001"])
    assert len(results) == 1
    assert results[0]["key"] == "section#001"
    assert results[0]["metadata"]["artifact_id"] == "art-001"


def test_put_vector_upsert_overwrites() -> None:
    """put_vector twice with same key overwrites, leaving one entry."""
    client = FakeVectorsClient()
    vec = _unit_vec([1.0, 0.0, 0.0])
    client.put_vector("section#001", vec, {"type": "review"})
    client.put_vector("section#001", vec, {"type": "adr"})
    results = client.get_vectors(["section#001"])
    assert len(results) == 1
    assert results[0]["metadata"]["type"] == "adr"


def test_get_vectors_omits_missing_keys() -> None:
    """get_vectors omits keys that are not found."""
    client = FakeVectorsClient()
    vec = _unit_vec([1.0, 0.0, 0.0])
    client.put_vector("section#001", vec, {})
    results = client.get_vectors(["section#001", "nonexistent"])
    keys = [r["key"] for r in results]
    assert "section#001" in keys
    assert "nonexistent" not in keys


def test_query_vectors_returns_most_similar() -> None:
    """query_vectors with top_k=1 returns the most similar vector."""
    client = FakeVectorsClient()
    vec_close = _unit_vec([1.0, 0.1, 0.0])
    vec_far = _unit_vec([0.0, 0.0, 1.0])
    client.put_vector("close", vec_close, {"artifact_id": "art-close"})
    client.put_vector("far", vec_far, {"artifact_id": "art-far"})
    query = _unit_vec([1.0, 0.0, 0.0])
    results = client.query_vectors(query, top_k=1, filter=None)
    assert len(results) == 1
    assert results[0]["key"] == "close"


def test_query_vectors_results_ordered_by_score_descending() -> None:
    """query_vectors returns results ordered by score descending."""
    client = FakeVectorsClient()
    vec_a = _unit_vec([1.0, 0.1, 0.0])
    vec_b = _unit_vec([0.8, 0.3, 0.0])
    vec_c = _unit_vec([0.0, 0.0, 1.0])
    client.put_vector("a", vec_a, {"artifact_id": "art-a"})
    client.put_vector("b", vec_b, {"artifact_id": "art-b"})
    client.put_vector("c", vec_c, {"artifact_id": "art-c"})
    query = _unit_vec([1.0, 0.0, 0.0])
    results = client.query_vectors(query, top_k=3, filter=None)
    assert len(results) == 3
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_query_vectors_eq_filter() -> None:
    """query_vectors with $eq filter excludes non-matching vectors."""
    client = FakeVectorsClient()
    vec = _unit_vec([1.0, 0.0, 0.0])
    client.put_vector("review-01", vec, {"type": "review", "artifact_id": "a1"})
    client.put_vector("adr-01", vec, {"type": "adr", "artifact_id": "a2"})
    results = client.query_vectors(vec, top_k=10, filter={"type": {"$eq": "review"}})
    assert len(results) == 1
    assert results[0]["key"] == "review-01"


def test_query_vectors_nin_filter() -> None:
    """query_vectors with $nin filter excludes listed values."""
    client = FakeVectorsClient()
    vec = _unit_vec([1.0, 0.0, 0.0])
    client.put_vector("key-a", vec, {"artifact_id": "art-a"})
    client.put_vector("key-b", vec, {"artifact_id": "art-b"})
    client.put_vector("key-c", vec, {"artifact_id": "art-c"})
    results = client.query_vectors(
        vec, top_k=10, filter={"artifact_id": {"$nin": ["art-a", "art-b"]}}
    )
    assert len(results) == 1
    assert results[0]["metadata"]["artifact_id"] == "art-c"


def test_query_vectors_and_filter() -> None:
    """query_vectors with $and filter applies all conditions."""
    client = FakeVectorsClient()
    vec = _unit_vec([1.0, 0.0, 0.0])
    client.put_vector("k1", vec, {"type": "review", "status": "active"})
    client.put_vector("k2", vec, {"type": "review", "status": "archived"})
    client.put_vector("k3", vec, {"type": "adr", "status": "active"})
    results = client.query_vectors(
        vec,
        top_k=10,
        filter={"$and": [{"type": {"$eq": "review"}}, {"status": {"$eq": "active"}}]},
    )
    assert len(results) == 1
    assert results[0]["key"] == "k1"


def test_delete_vectors_removes_keys() -> None:
    """delete_vectors removes the keys; subsequent get_vectors omits them."""
    client = FakeVectorsClient()
    vec = _unit_vec([1.0, 0.0, 0.0])
    client.put_vector("key-a", vec, {})
    client.put_vector("key-b", vec, {})
    client.delete_vectors(["key-a"])
    results = client.get_vectors(["key-a", "key-b"])
    keys = [r["key"] for r in results]
    assert "key-a" not in keys
    assert "key-b" in keys


def test_delete_vectors_missing_key_does_not_raise() -> None:
    """delete_vectors on missing key does not raise."""
    client = FakeVectorsClient()
    client.delete_vectors(["nonexistent"])  # should not raise


def test_describe_index_returns_configured_dimension() -> None:
    """describe_index returns the dimension configured at construction."""
    client = FakeVectorsClient(dimension=512)
    info = client.describe_index()
    assert info["dimension"] == 512


def test_describe_index_default_dimension() -> None:
    """describe_index returns 1024 by default."""
    client = FakeVectorsClient()
    info = client.describe_index()
    assert info["dimension"] == 1024


def test_describe_index_missing_raises_vector_index_not_found() -> None:
    """describe_index raises VectorIndexNotFoundError when index is set to missing."""
    client = FakeVectorsClient(index_missing=True)
    with pytest.raises(VectorIndexNotFoundError):
        client.describe_index()


def test_list_vectors_by_metadata_returns_matching_keys() -> None:
    """list_vectors_by_metadata returns keys matching the filter."""
    client = FakeVectorsClient()
    vec = _unit_vec([1.0, 0.0, 0.0])
    client.put_vector("k1", vec, {"status": "active", "type": "review"})
    client.put_vector("k2", vec, {"status": "archived", "type": "review"})
    client.put_vector("k3", vec, {"status": "active", "type": "adr"})
    keys = client.list_vectors_by_metadata({"status": {"$eq": "active"}})
    assert sorted(keys) == ["k1", "k3"]


def test_credential_failure_all_methods() -> None:
    """All methods raise CredentialError when credential failure is set."""
    client = FakeVectorsClient()
    client.set_credential_failure(True)
    vec = [1.0, 0.0, 0.0]

    with pytest.raises(CredentialError):
        client.put_vector("k", vec, {})
    with pytest.raises(CredentialError):
        client.get_vectors(["k"])
    with pytest.raises(CredentialError):
        client.query_vectors(vec, top_k=1, filter=None)
    with pytest.raises(CredentialError):
        client.delete_vectors(["k"])
    with pytest.raises(CredentialError):
        client.describe_index()
    with pytest.raises(CredentialError):
        client.list_vectors_by_metadata({})
