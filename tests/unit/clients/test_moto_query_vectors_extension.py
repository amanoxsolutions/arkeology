"""Tests for the moto query_vectors extension patched in tests/unit/conftest.py.

These tests verify that the extension correctly implements cosine similarity
search over moto's in-memory vector store, matching VectorsClientImpl semantics.
"""

import math

from cairn_mcp.clients.vectors import VectorsClientImpl


def _unit_vec(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        return values
    return [v / norm for v in values]


# ---------------------------------------------------------------------------
# Score semantics
# ---------------------------------------------------------------------------


async def test_identical_vectors_score_equals_one(
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Identical query and stored unit vector → score == 1.0 (cosine similarity)."""
    vec = _unit_vec([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    vectors_client_8.put_vector("key1", vec, {"artifact_id": "a/key1", "scope": "artifacts"})

    results = vectors_client_8.query_vectors(vector=vec, top_k=10, filter_expr=None)

    assert len(results) == 1
    assert abs(results[0]["score"] - 1.0) < 1e-6


async def test_orthogonal_vectors_score_equals_zero(
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Orthogonal stored and query vector → score == 0.0."""
    stored = _unit_vec([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    query = _unit_vec([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    vectors_client_8.put_vector("key1", stored, {"artifact_id": "a/key1", "scope": "artifacts"})

    results = vectors_client_8.query_vectors(vector=query, top_k=10, filter_expr=None)

    assert len(results) == 1
    assert abs(results[0]["score"] - 0.0) < 1e-6


async def test_results_ordered_by_score_descending(
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Multiple stored vectors → results ordered by score descending (most similar first)."""
    query = _unit_vec([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    # near_vec is closer to query than far_vec
    near_vec = _unit_vec([1.0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    far_vec = _unit_vec([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    vectors_client_8.put_vector("near", near_vec, {"scope": "artifacts", "artifact_id": "a/near"})
    vectors_client_8.put_vector("far", far_vec, {"scope": "artifacts", "artifact_id": "a/far"})

    results = vectors_client_8.query_vectors(vector=query, top_k=10, filter_expr=None)

    assert len(results) == 2
    assert results[0]["key"] == "near"
    assert results[1]["key"] == "far"
    assert results[0]["score"] > results[1]["score"]


async def test_filter_expr_excludes_non_matching(
    vectors_client_8: VectorsClientImpl,
) -> None:
    """filter_expr removes vectors whose metadata does not match."""
    vec = _unit_vec([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    vectors_client_8.put_vector("match", vec, {"scope": "team-a", "artifact_id": "team-a/x"})
    vectors_client_8.put_vector("no-match", vec, {"scope": "team-b", "artifact_id": "team-b/y"})

    results = vectors_client_8.query_vectors(
        vector=vec,
        top_k=10,
        filter_expr={"scope": {"$eq": "team-a"}},
    )

    keys = [r["key"] for r in results]
    assert "match" in keys
    assert "no-match" not in keys


async def test_top_k_limits_results(
    vectors_client_8: VectorsClientImpl,
) -> None:
    """top_k=2 with 4 stored vectors → exactly 2 results returned."""
    query = _unit_vec([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    for i in range(4):
        vec = _unit_vec([float(i + 1)] + [0.0] * 7)
        vectors_client_8.put_vector(f"key{i}", vec, {"scope": "artifacts", "artifact_id": f"a/{i}"})

    results = vectors_client_8.query_vectors(vector=query, top_k=2, filter_expr=None)

    assert len(results) == 2


async def test_empty_index_returns_empty_list(
    vectors_client_8: VectorsClientImpl,
) -> None:
    """No stored vectors → query returns empty list."""
    query = _unit_vec([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    results = vectors_client_8.query_vectors(vector=query, top_k=10, filter_expr=None)

    assert results == []
