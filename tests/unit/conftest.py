"""Shared test helpers and fixtures for all unit tests.

Centralises _make_settings so a new env var requires only one edit.

Also applies the moto query_vectors extension for S3 Vectors at module load time
and provides shared AWS-mocked fixtures for unit tests.
"""

import math
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws
from moto.core.responses import ActionResult
from moto.s3vectors.models import S3VectorsBackend
from moto.s3vectors.responses import S3VectorsResponse
from moto.s3vectors.urls import url_paths

from cairn_mcp.clients.filter import matches_filter
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings

# ---------------------------------------------------------------------------
# moto query_vectors extension — applied once at module load
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _backend_query_vectors(
    self: Any,
    vector_bucket_name: str,
    index_name: str,
    query_vector: list[float],
    top_k: int,
    filter_expr: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Moto extension: cosine similarity search over moto's in-memory vector store.

    Score = 1.0 - cosine_distance = cosine_similarity, range [-1, 1].
    Matches VectorsClientImpl.query_vectors score semantics exactly.
    """
    bucket = next(
        (b for b in self.vector_buckets.values() if b.vector_bucket_name == vector_bucket_name),
        None,
    )
    if bucket is None:
        raise KeyError(f"Vector bucket not found: {vector_bucket_name}")
    index = next(
        (i for i in bucket.indexes.values() if i.index_name == index_name),
        None,
    )
    if index is None:
        raise KeyError(f"Index not found: {index_name}")
    candidates: list[dict[str, Any]] = []
    for key, entry in index.vectors.items():
        meta = entry.metadata or {}
        if filter_expr is not None and not matches_filter(meta, filter_expr):
            continue
        vec = entry.data["float32"]
        cosine_dist = 1.0 - _cosine_similarity(query_vector, vec)
        candidates.append({"key": key, "distance": cosine_dist, "metadata": meta})
    candidates.sort(key=lambda r: float(r["distance"]))
    return candidates[:top_k]


def _response_query_vectors(self: Any) -> ActionResult:
    vector_bucket_name = self._get_param("vectorBucketName")
    index_name = self._get_param("indexName")
    query_vector_raw = self._get_param("queryVector")
    query_vector: list[float] = query_vector_raw.get("float32", [])
    top_k: int = self._get_param("topK")
    filter_expr = self._get_param("filter")
    results = self.s3vectors_backend.query_vectors(
        vector_bucket_name=vector_bucket_name,
        index_name=index_name,
        query_vector=query_vector,
        top_k=top_k,
        filter_expr=filter_expr,
    )
    return ActionResult(result={"vectors": results})


# Patch backend and response class, then register the URL route.
S3VectorsBackend.query_vectors = _backend_query_vectors  # type: ignore[attr-defined]
S3VectorsResponse.query_vectors = _response_query_vectors  # type: ignore[attr-defined]
url_paths["{0}/QueryVectors$"] = S3VectorsResponse.dispatch


# ---------------------------------------------------------------------------
# Settings helper (shared across all unit tests)
# ---------------------------------------------------------------------------


def _make_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path | None = None,
    **overrides: str,
) -> Settings:
    """Build a Settings object with required env vars set, plus any overrides.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        tmp_path: If provided, sets FAILURE_LOG_PATH to a temp file (needed by
            reconcile and freshness tests).
        **overrides: Additional env vars to set before constructing Settings.
    """
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-bucket")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")
    monkeypatch.setenv("WRITE_PREFIX", "artifacts")
    if tmp_path is not None:
        monkeypatch.setenv("FAILURE_LOG_PATH", str(tmp_path / ".cairn_failures.jsonl"))
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    return Settings()


# ---------------------------------------------------------------------------
# Shared moto fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with standard test defaults. Shadows per-file overrides where needed."""
    return _make_settings(monkeypatch)


@pytest.fixture
def aws_mock():
    """Activate moto for all AWS services for the duration of the test."""
    with mock_aws():
        yield


@pytest.fixture
def s3_client(aws_mock: None, settings: Settings) -> S3ClientImpl:
    """S3ClientImpl backed by moto with the test bucket pre-created."""
    boto3.client("s3", region_name=settings.aws_region).create_bucket(
        Bucket=settings.artifact_bucket,
    )
    return S3ClientImpl(
        region=settings.aws_region,
        profile=None,
        bucket=settings.artifact_bucket,
    )


def _make_vectors_client(settings: Settings, dimension: int) -> VectorsClientImpl:
    """Create a VectorsClientImpl backed by moto with bucket + index pre-created."""
    s3v = boto3.client("s3vectors", region_name=settings.aws_region)
    s3v.create_vector_bucket(vectorBucketName=settings.vectors_bucket)
    s3v.create_index(
        vectorBucketName=settings.vectors_bucket,
        indexName=settings.vectors_index,
        dataType="float32",
        dimension=dimension,
        distanceMetric="cosine",
    )
    return VectorsClientImpl(
        region=settings.aws_region,
        profile=None,
        bucket=settings.vectors_bucket,
        index=settings.vectors_index,
    )


@pytest.fixture
def vectors_client(aws_mock: None, settings: Settings) -> VectorsClientImpl:
    """VectorsClientImpl backed by moto with dim=1024 index (default for write tests)."""
    return _make_vectors_client(settings, dimension=1024)


@pytest.fixture
def vectors_client_8(aws_mock: None, settings: Settings) -> VectorsClientImpl:
    """VectorsClientImpl backed by moto with dim=8 index (health, search, list, etc.)."""
    return _make_vectors_client(settings, dimension=8)


@pytest.fixture
def vectors_client_2(aws_mock: None, settings: Settings) -> VectorsClientImpl:
    """VectorsClientImpl backed by moto with dim=2 index (archive, delete, purge)."""
    return _make_vectors_client(settings, dimension=2)


@pytest.fixture
def vectors_client_no_index(aws_mock: None, settings: Settings) -> VectorsClientImpl:
    """VectorsClientImpl backed by moto with bucket only — no index created."""
    s3v = boto3.client("s3vectors", region_name=settings.aws_region)
    s3v.create_vector_bucket(vectorBucketName=settings.vectors_bucket)
    return VectorsClientImpl(
        region=settings.aws_region,
        profile=None,
        bucket=settings.vectors_bucket,
        index=settings.vectors_index,
    )
