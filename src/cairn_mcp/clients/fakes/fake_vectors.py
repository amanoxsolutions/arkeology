"""In-memory S3 Vectors fake for unit tests.

Implements VectorsClientInterface entirely in memory using cosine similarity.
Supports metadata filter operators: $eq, $nin, $and.
Supports simulated credential failures via set_credential_failure().
"""

import math
from typing import Any

from cairn_mcp.clients.filter import matches_filter
from cairn_mcp.clients.interfaces import VectorsClientInterface
from cairn_mcp.errors import CredentialError, VectorIndexNotFoundError


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class FakeVectorsClient(VectorsClientInterface):
    """Stateful in-memory S3 Vectors client for use in unit tests."""

    def __init__(self, dimension: int = 1024, index_missing: bool = False) -> None:
        # Maps key -> (vector, metadata)
        self._vectors: dict[str, tuple[list[float], dict[str, Any]]] = {}
        self._dimension = dimension
        self._index_missing = index_missing
        self._credential_failure: bool = False

    def set_credential_failure(self, value: bool) -> None:
        """Toggle simulated credential failure for all subsequent calls."""
        self._credential_failure = value

    def _check_credentials(self) -> None:
        if self._credential_failure:
            raise CredentialError(
                message="AWS credentials are invalid or expired (simulated).",
                service="s3vectors",
                original=Exception("simulated credential failure"),
            )

    def put_vector(self, key: str, vector: list[float], metadata: dict[str, Any]) -> None:
        self._check_credentials()
        self._vectors[key] = (vector, metadata)

    def get_vectors(self, keys: list[str]) -> list[dict[str, Any]]:
        self._check_credentials()
        results = []
        for k in keys:
            if k in self._vectors:
                vec, meta = self._vectors[k]
                results.append({"key": k, "metadata": meta, "data": {"float32": vec}})
        return results

    def query_vectors(
        self,
        vector: list[float],
        top_k: int,
        filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        self._check_credentials()
        candidates: list[dict[str, Any]] = []
        for key, (vec, meta) in self._vectors.items():
            if filter is not None and not matches_filter(meta, filter):
                continue
            score = _cosine_similarity(vector, vec)
            candidates.append({"key": key, "score": score, "metadata": meta})
        candidates.sort(key=lambda r: float(r["score"]), reverse=True)
        return candidates[:top_k]

    def delete_vectors(self, keys: list[str]) -> None:
        self._check_credentials()
        for k in keys:
            self._vectors.pop(k, None)

    def describe_index(self) -> dict[str, Any]:
        self._check_credentials()
        if self._index_missing:
            raise VectorIndexNotFoundError(
                index_name="fake-index",
                bucket_name="fake-bucket",
            )
        return {"dimension": self._dimension}

    def list_vectors_by_metadata(self, filter: dict[str, Any]) -> list[str]:
        self._check_credentials()
        return [k for k, (_, meta) in self._vectors.items() if matches_filter(meta, filter)]
