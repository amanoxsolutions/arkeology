"""Shared test helpers and fixtures for all unit tests.

Centralises _make_settings so a new env var requires only one edit.

Also applies the moto query_vectors extension for S3 Vectors at module load time
and provides shared AWS-mocked fixtures for unit tests.
"""

import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws
from moto.core.responses import ActionResult
from moto.s3.exceptions import MissingKey, PreconditionFailed, S3ClientError
from moto.s3.models import S3Backend
from moto.s3.responses import S3Response
from moto.s3vectors.models import S3VectorsBackend
from moto.s3vectors.responses import S3VectorsResponse
from moto.s3vectors.urls import url_paths

from arkeology.clients.filter import matches_filter
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings

# ---------------------------------------------------------------------------
# moto query_vectors extension — applied once at module load
#
# NOTE: this extension filters using the exact
# same production `matches_filter` that VectorsClientImpl.query_vectors hands
# to boto3 as the real `filter` request parameter — so it is circular for
# anything QueryVectors evaluates server-side (if matches_filter's assumptions
# about AWS's real semantics were wrong, this simulation could never catch
# it). It is kept as-is for unit speed; its fidelity to real AWS server-side
# filter semantics ($eq list-membership, the plain-equality shorthand, $gte on
# a String operand, and behaviour at/over the Top-K and filter-size caps) is
# now backed by the real-AWS integration assertions in
# tests/integration/clients/test_vectors_filter_semantics.py instead.
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
    return_distance: bool = False,
) -> list[dict[str, Any]]:
    """Moto extension: cosine similarity search over moto's in-memory vector store.

    Score = 1.0 - cosine_distance = cosine_similarity, range [-1, 1].
    Matches VectorsClientImpl.query_vectors score semantics exactly.

    ``return_distance`` mirrors the real S3 Vectors ``returnDistance`` request flag
    (AWS default: false) — 'distance' is only included in each result when it is
    truthy. This is required so a client that forgets to request distances (as
    production code would if it stopped requesting distances) sees the same missing-field shape a
    real S3 Vectors response would return, rather than the fixture masking the bug.
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
    scored: list[tuple[float, dict[str, Any]]] = []
    for key, entry in index.vectors.items():
        meta = entry.metadata or {}
        if filter_expr is not None and not matches_filter(meta, filter_expr):
            continue
        vec = entry.data["float32"]
        cosine_dist = 1.0 - _cosine_similarity(query_vector, vec)
        result: dict[str, Any] = {"key": key, "metadata": meta}
        if return_distance:
            result["distance"] = cosine_dist
        scored.append((cosine_dist, result))
    scored.sort(key=lambda pair: pair[0])
    return [result for _, result in scored[:top_k]]


def _response_query_vectors(self: Any) -> ActionResult:
    vector_bucket_name = self._get_param("vectorBucketName")
    index_name = self._get_param("indexName")
    query_vector_raw = self._get_param("queryVector")
    query_vector: list[float] = query_vector_raw.get("float32", [])
    top_k: int = self._get_param("topK")
    filter_expr = self._get_param("filter")
    return_distance = self._get_bool_param("returnDistance", False)
    results = self.s3vectors_backend.query_vectors(
        vector_bucket_name=vector_bucket_name,
        index_name=index_name,
        query_vector=query_vector,
        top_k=top_k,
        filter_expr=filter_expr,
        return_distance=return_distance,
    )
    return ActionResult(result={"vectors": results})


# Patch backend and response class, then register the URL route.
S3VectorsBackend.query_vectors = _backend_query_vectors  # type: ignore[attr-defined]
S3VectorsResponse.query_vectors = _response_query_vectors  # type: ignore[attr-defined]
url_paths["{0}/QueryVectors$"] = S3VectorsResponse.dispatch


# ---------------------------------------------------------------------------
# moto S3 object-annotation self-mock extension — applied once at module load
#
# moto 5.2.2 has no native support for the four S3 object-annotation operations
# (PutObjectAnnotation / GetObjectAnnotation / ListObjectAnnotations /
# DeleteObjectAnnotation — see ADR-011). This extension self-mocks them by
# intercepting S3Response's existing key-level GET/PUT/DELETE dispatch for the
# "?annotation" subresource — the same seam moto itself uses to dispatch "?tagging"
# / "?acl" — and backs them with a module-level in-memory store keyed by
# (bucket, key). It also wraps S3Backend.put_object so that writing a new object
# version clears that key's annotations, matching real S3 overwrite-wipe semantics.
#
# ADR-011 decision 6: PutObjectAnnotation and
# DeleteObjectAnnotation also accept an optional ``ObjectIfMatch`` compare-and-swap
# parameter. Inspecting the installed botocore S3 service model
# (botocore/data/s3/2006-03-01/service-2.json.gz, PutObjectAnnotationRequest /
# DeleteObjectAnnotationRequest shapes) confirms ``ObjectIfMatch`` is a *header*
# (`location: header`, `locationName: x-amz-object-if-match`) — unlike
# `annotationName`, which is a query-string parameter — so it must be read from
# ``self.headers``, not ``query``. This mirrors moto's own native ``If-Match``
# handling on the object body (moto/s3/responses.py), which also reads from
# ``self.headers``.
# ---------------------------------------------------------------------------

_ANNOTATION_STORE: dict[tuple[str, str], dict[str, bytes]] = {}


class _NoSuchAnnotation(S3ClientError):
    """Mirrors the real S3 ``NoSuchAnnotation`` error (404) for an absent annotation."""

    code = "NoSuchAnnotation"

    def __init__(self, annotation_name: str) -> None:
        super().__init__("The specified annotation does not exist.")
        self.annotation_name = annotation_name


def _require_object(self: Any, bucket_name: str, key_name: str) -> None:
    if self.backend.get_object(bucket_name, key_name) is None:
        raise MissingKey(key_name)


def _annotation_get_or_list(self: Any, query: dict[str, Any], key_name: str) -> Any:
    _require_object(self, self.bucket_name, key_name)
    store = _ANNOTATION_STORE.get((self.bucket_name, key_name), {})
    if "annotationName" in query:
        name = query["annotationName"][0]
        if name not in store:
            raise _NoSuchAnnotation(name)
        self.data["Action"] = "GetObjectAnnotation"
        return self.serialized(ActionResult({"AnnotationPayload": store[name]}))
    self.data["Action"] = "ListObjectAnnotations"
    names = sorted(store)
    return self.serialized(
        ActionResult(
            {
                "Annotations": [{"AnnotationName": n} for n in names],
                "AnnotationCount": len(names),
            }
        )
    )


def _check_object_if_match(self: Any, bucket_name: str, key_name: str) -> None:
    """Honour ``ObjectIfMatch`` (sent as the ``x-amz-object-if-match`` header) on
    PutObjectAnnotation / DeleteObjectAnnotation — the compare-and-swap guard added
    for ADR-011 decision 6. Absent header → no check (unconditional call, today's
    behaviour). Present and mismatched → raise moto's own ``PreconditionFailed``
    (HTTP 412), exactly like moto's native ``If-Match`` handling on the object body.
    """
    if_match = self.headers.get("x-amz-object-if-match")
    if if_match is None:
        return
    obj = self.backend.get_object(bucket_name, key_name)
    if obj is None or obj.etag != if_match:
        raise PreconditionFailed("ObjectIfMatch")


def _annotation_put(self: Any, query: dict[str, Any], key_name: str) -> Any:
    _require_object(self, self.bucket_name, key_name)
    _check_object_if_match(self, self.bucket_name, key_name)
    name = query["annotationName"][0]
    payload = self.body.encode("utf-8") if isinstance(self.body, str) else (self.body or b"")
    _ANNOTATION_STORE.setdefault((self.bucket_name, key_name), {})[name] = payload
    self.data["Action"] = "PutObjectAnnotation"
    return self.serialized(ActionResult({"AnnotationName": name}))


def _annotation_delete(self: Any, bucket_name: str, key_name: str, query: dict[str, Any]) -> Any:
    _require_object(self, bucket_name, key_name)
    _check_object_if_match(self, bucket_name, key_name)
    name = query["annotationName"][0]
    store = _ANNOTATION_STORE.get((bucket_name, key_name), {})
    if name not in store:
        raise _NoSuchAnnotation(name)
    del store[name]
    self.data["Action"] = "DeleteObjectAnnotation"
    return self.serialized(ActionResult({}))


_orig_key_response_get = S3Response._key_response_get
_orig_key_response_put = S3Response._key_response_put
_orig_key_response_delete = S3Response._key_response_delete


def _key_response_get_with_annotations(self: Any, query: dict[str, Any], key_name: str) -> Any:
    if "annotation" in query:
        return _annotation_get_or_list(self, query, key_name)
    return _orig_key_response_get(self, query, key_name)


def _key_response_put_with_annotations(self: Any, query: dict[str, Any], key_name: str) -> Any:
    if "annotation" in query:
        return _annotation_put(self, query, key_name)
    return _orig_key_response_put(self, query, key_name)


def _key_response_delete_with_annotations(
    self: Any, bucket_name: str, query: dict[str, Any], key_name: str
) -> Any:
    if "annotation" in query:
        return _annotation_delete(self, bucket_name, key_name, query)
    return _orig_key_response_delete(self, bucket_name, query, key_name)


S3Response._key_response_get = _key_response_get_with_annotations  # type: ignore[method-assign]
S3Response._key_response_put = _key_response_put_with_annotations  # type: ignore[method-assign]
S3Response._key_response_delete = (  # type: ignore[method-assign]
    _key_response_delete_with_annotations
)


_orig_backend_put_object = S3Backend.put_object


def _backend_put_object_clears_annotations(
    self: Any, bucket_name: str, key_name: str, *args: Any, **kwargs: Any
) -> Any:
    # Real S3 clears an object's annotations whenever it is overwritten (ADR-011).
    _ANNOTATION_STORE.pop((bucket_name, key_name), None)
    return _orig_backend_put_object(self, bucket_name, key_name, *args, **kwargs)


S3Backend.put_object = _backend_put_object_clears_annotations  # type: ignore[method-assign]


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
    # Disable min-length filter by default so short test section bodies are not filtered.
    # Tests that exercise the filter explicitly override this via **overrides.
    if "EMBED_MIN_SECTION_LENGTH" not in overrides:
        monkeypatch.setenv("EMBED_MIN_SECTION_LENGTH", "0")
    if tmp_path is not None:
        monkeypatch.setenv("FAILURE_LOG_PATH", str(tmp_path / ".arkeology_failures.jsonl"))
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


@pytest.fixture(autouse=True)
def _reset_annotation_store() -> Iterator[None]:
    """Reset the self-mocked S3-annotation in-memory store between tests.

    ``_ANNOTATION_STORE`` is a module-level dict keyed by ``(bucket, key)`` backing the
    moto self-mock extension above. Without a reset, annotation state written by one
    test could leak into another test that happens to reuse the same bucket/key pair
    (e.g. the shared "my-bucket" / "artifacts/a1.md" defaults many tests fall back on).
    """
    _ANNOTATION_STORE.clear()
    yield
    _ANNOTATION_STORE.clear()


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
