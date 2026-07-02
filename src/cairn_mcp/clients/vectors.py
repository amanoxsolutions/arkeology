"""Concrete S3 Vectors client implementation using boto3.

All credential errors are caught at this layer and re-raised as CredentialError.
Non-credential errors (including missing index) are wrapped in typed exceptions.

Note on list_vectors_by_metadata: S3 Vectors ListVectors does not support server-side
metadata filtering. This method paginates through all vectors and filters client-side.
This is acceptable for Phase 1; future phases may optimise with QueryVectors if a
zero-query approach is deemed appropriate.
"""

import logging
from collections.abc import Iterator, Sequence
from typing import Any, cast

import boto3
import botocore.exceptions

from cairn_mcp.clients.credentials import wrap_credential_errors
from cairn_mcp.clients.filter import matches_filter
from cairn_mcp.clients.interfaces import VectorsClientInterface  # noqa: F401 (structural only)
from cairn_mcp.errors import VectorDistanceMissingError, VectorIndexNotFoundError

logger = logging.getLogger(__name__)

# S3 Vectors per-request key/vector limits — every batched call MUST chunk to these
# so large key lists do not exceed the API caps (a ValidationException otherwise).
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html
_PUT_VECTORS_CHUNK_SIZE: int = 500  # S3 Vectors PutVectors API limit
_DELETE_VECTORS_CHUNK_SIZE: int = 500  # S3 Vectors DeleteVectors API limit
_GET_VECTORS_CHUNK_SIZE: int = 100  # S3 Vectors GetVectors API limit

# Error codes that indicate the index does not exist

_INDEX_NOT_FOUND_CODES = frozenset(
    {
        "NoSuchIndex",
        "IndexNotFoundException",
        "ResourceNotFoundException",
        "NoSuchResource",
        "NotFoundException",
    }
)


def _is_index_not_found(exc: botocore.exceptions.ClientError) -> bool:
    code = exc.response.get("Error", {}).get("Code", "")
    return code in _INDEX_NOT_FOUND_CODES


def _chunked[T](seq: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    """Yield successive ``size``-length slices of ``seq``."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


class VectorsClientImpl:
    """boto3-backed S3 Vectors client.

    Args:
        region: AWS region name.
        profile: Optional named AWS profile; if None, uses the default credential chain.
        bucket: S3 Vectors bucket name.
        index: S3 Vectors index name within the bucket.
    """

    def __init__(self, region: str, profile: str | None, bucket: str, index: str) -> None:
        self._bucket = bucket
        self._index = index
        if profile is not None:
            session = boto3.Session(profile_name=profile, region_name=region)
        else:
            session = boto3.Session(region_name=region)
        self._client = session.client("s3vectors")

    def put_vector(self, key: str, vector: list[float], metadata: dict[str, Any]) -> None:
        logger.debug("S3Vectors put_vector key=%s", key)
        self.put_vectors_batch([{"key": key, "vector": vector, "metadata": metadata}])

    def put_vectors_batch(self, items: list[dict[str, Any]]) -> None:
        """Put a batch of vectors, chunked at 500 per PutVectors API limit."""
        if not items:
            return
        with wrap_credential_errors("s3vectors"):
            for chunk in _chunked(items, _PUT_VECTORS_CHUNK_SIZE):
                vectors_payload = [
                    {
                        "key": item["key"],
                        "data": {"float32": item["vector"]},
                        "metadata": item["metadata"],
                    }
                    for item in chunk
                ]
                logger.debug("S3Vectors put_vectors_batch chunk size=%d", len(chunk))
                self._client.put_vectors(
                    vectorBucketName=self._bucket,
                    indexName=self._index,
                    vectors=cast(list[Any], vectors_payload),
                )

    def get_vectors(self, keys: list[str]) -> list[dict[str, Any]]:
        logger.debug("S3Vectors get_vectors count=%d", len(keys))
        if not keys:
            return []
        results: list[dict[str, Any]] = []
        with wrap_credential_errors("s3vectors"):
            for chunk in _chunked(keys, _GET_VECTORS_CHUNK_SIZE):
                response = self._client.get_vectors(
                    vectorBucketName=self._bucket,
                    indexName=self._index,
                    keys=chunk,
                    returnMetadata=True,
                    returnData=True,
                )
                for item in response.get("vectors", []):
                    results.append(
                        {
                            "key": item["key"],
                            "metadata": item.get("metadata", {}),
                            "data": item.get("data", {}),
                        }
                    )
            return results

    def query_vectors(
        self,
        vector: list[float],
        top_k: int,
        filter_expr: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        logger.debug("S3Vectors query_vectors top_k=%d", top_k)
        kwargs: dict[str, Any] = {
            "vectorBucketName": self._bucket,
            "indexName": self._index,
            "topK": top_k,
            "queryVector": {"float32": vector},
            "returnMetadata": True,
            # AWS defaults returnDistance to false; without it every result comes back
            # with no 'distance' field and ranking silently degenerates (see C-1).
            "returnDistance": True,
        }
        if filter_expr is not None:
            kwargs["filter"] = filter_expr
        with wrap_credential_errors("s3vectors"):
            response = self._client.query_vectors(**kwargs)
            results = []
            for item in response.get("vectors", []):
                # S3 Vectors returns 'distance'; lower is more similar (cosine distance
                # for normalised vectors is in [0, 2]). score = 1.0 - distance → [-1, 1],
                # matching the moto query_vectors extension in tests/unit/conftest.py.
                # A missing 'distance' must never be treated as perfect similarity
                # (score 1.0) — that silently breaks ranking — so it is a hard error.
                if "distance" not in item:
                    raise VectorDistanceMissingError(key=item.get("key", "<unknown>"))
                distance = item["distance"]
                results.append(
                    {
                        "key": item["key"],
                        "score": 1.0 - distance,
                        "metadata": item.get("metadata", {}),
                    }
                )
            return results

    def delete_vectors(self, keys: list[str]) -> None:
        logger.debug("S3Vectors delete_vectors count=%d", len(keys))
        if not keys:
            return
        with wrap_credential_errors("s3vectors"):
            for chunk in _chunked(keys, _DELETE_VECTORS_CHUNK_SIZE):
                self._client.delete_vectors(
                    vectorBucketName=self._bucket,
                    indexName=self._index,
                    keys=chunk,
                )

    def describe_index(self) -> dict[str, Any]:
        logger.debug("S3Vectors describe_index bucket=%s index=%s", self._bucket, self._index)
        with wrap_credential_errors("s3vectors"):
            try:
                response = self._client.get_index(
                    vectorBucketName=self._bucket,
                    indexName=self._index,
                )
                return dict(response.get("index", {}))
            except botocore.exceptions.ClientError as exc:
                if _is_index_not_found(exc):
                    raise VectorIndexNotFoundError(
                        index_name=self._index,
                        bucket_name=self._bucket,
                    ) from exc
                raise

    def list_vectors_by_metadata(self, filter_expr: dict[str, Any]) -> list[str]:
        """Return all vector keys matching the given filter.

        Uses ListVectors with pagination and filters client-side because the
        S3 Vectors ListVectors API does not support server-side metadata filtering.
        """
        logger.debug("S3Vectors list_vectors_by_metadata")
        matching_keys: list[str] = []
        next_token: str | None = None
        with wrap_credential_errors("s3vectors"):
            while True:
                kwargs: dict[str, Any] = {
                    "vectorBucketName": self._bucket,
                    "indexName": self._index,
                    "returnMetadata": True,
                    "maxResults": 1000,
                }
                if next_token is not None:
                    kwargs["nextToken"] = next_token
                response = self._client.list_vectors(**kwargs)
                for item in response.get("vectors", []):
                    meta = item.get("metadata") or {}
                    if matches_filter(meta, filter_expr):
                        matching_keys.append(item["key"])
                next_token = response.get("nextToken")
                if not next_token:
                    break
        return matching_keys
