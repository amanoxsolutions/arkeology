"""Concrete S3 client implementation using boto3.

All credential errors are caught at this layer and re-raised as CredentialError.
Non-credential errors propagate unchanged.
"""

import logging
from typing import Any

import boto3
import botocore.exceptions

from arkeology.artifact import decode_metadata_value, encode_metadata_value
from arkeology.clients.credentials import (
    _ANNOTATION_UNAVAILABLE_MESSAGE,
    _CREDENTIAL_ERROR_MESSAGE,
    _error_code,
    is_annotation_unavailable_error,
    wrap_credential_errors,
)
from arkeology.clients.interfaces import S3ClientInterface  # noqa: F401 (structural only)
from arkeology.errors import (
    AnnotationNotFoundError,
    AnnotationUnavailableError,
    ArtifactCollisionError,
    ArtifactConflictError,
    CredentialError,
    NonUtf8PayloadError,
    ObjectNotFoundError,
)

logger = logging.getLogger(__name__)


def _transport_safe_metadata(metadata: dict[str, str]) -> dict[str, str]:
    """Return a copy of metadata with all values percent-encoded for safe HTTP transport.

    S3 object metadata is transmitted as HTTP headers, which only support ASCII and
    reject raw control characters. Every value is percent-encoded via
    :func:`arkeology.artifact.encode_metadata_value` (T55) — fully reversible via
    :func:`arkeology.artifact.decode_metadata_value`, unlike the previous NFKD-ASCII-strip
    which silently discarded non-Latin content (e.g. an em dash or "café" losing its é).

    Args:
        metadata: Original metadata dict with potentially non-ASCII string values.

    Returns:
        New dict with all values percent-encoded to ASCII.
    """
    return {k: encode_metadata_value(v) for k, v in metadata.items()}


class S3ClientImpl:
    """boto3-backed S3 client.

    Args:
        region: AWS region name.
        profile: Optional named AWS profile; if None, uses the default credential chain.
        bucket: S3 bucket name for all operations.
    """

    def __init__(self, region: str, profile: str | None, bucket: str) -> None:
        self._bucket = bucket
        if profile is not None:
            session = boto3.Session(profile_name=profile, region_name=region)
        else:
            session = boto3.Session(region_name=region)
        self._s3 = session.client("s3")

    def put_object(
        self,
        key: str,
        body: str,
        metadata: dict[str, str],
        *,
        if_none_match: bool = False,
        if_match: str | None = None,
    ) -> str:
        logger.debug(
            "S3 put_object key=%s if_none_match=%s if_match=%s", key, if_none_match, if_match
        )
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": body.encode("utf-8"),
            "Metadata": _transport_safe_metadata(metadata),
        }
        if if_none_match:
            # Atomic conditional-create: "*" matches any existing object, so the
            # request is rejected with HTTP 412 PreconditionFailed if the key already
            # exists. This closes the head_object-then-put_object TOCTOU race — the
            # existence check and the write happen as a single S3-side atomic operation.
            kwargs["IfNoneMatch"] = "*"
        if if_match is not None:
            # Optimistic-concurrency compare-and-swap (ADR-011 decision 6): the request
            # is rejected with HTTP 412 PreconditionFailed if the object's current ETag
            # no longer matches the value the caller captured on read — a concurrent
            # writer has changed the object since.
            kwargs["IfMatch"] = if_match
        with wrap_credential_errors("s3"):
            try:
                response = self._s3.put_object(**kwargs)
            except botocore.exceptions.ClientError as exc:
                code = _error_code(exc)
                if code == "PreconditionFailed":
                    if if_none_match:
                        raise ArtifactCollisionError(key) from exc
                    if if_match is not None:
                        raise ArtifactConflictError(key) from exc
                raise
        new_etag: str = response["ETag"]
        return new_etag

    def get_object(self, key: str) -> str:
        logger.debug("S3 get_object key=%s", key)
        with wrap_credential_errors("s3"):
            try:
                response = self._s3.get_object(Bucket=self._bucket, Key=key)
                body = response["Body"].read()
                try:
                    return body.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise NonUtf8PayloadError(key, exc) from exc
            except botocore.exceptions.ClientError as exc:
                code = _error_code(exc)
                if code in ("NoSuchKey", "404"):
                    raise KeyError(key) from exc
                raise

    def head_object(self, key: str) -> dict[str, Any]:
        logger.debug("S3 head_object key=%s", key)
        with wrap_credential_errors("s3"):
            try:
                response = self._s3.head_object(Bucket=self._bucket, Key=key)
                # Symmetric with put_object's _transport_safe_metadata: decode every
                # value so callers only ever see (and re-supply) plain Unicode text —
                # a read-modify-write that re-PUTs this dict cannot double-encode.
                metadata = {
                    k: decode_metadata_value(v) for k, v in response.get("Metadata", {}).items()
                }
                # Reserved capitalised key (ADR-011 decision 6) — every real
                # user-defined metadata key is lowercase, so this cannot collide.
                # Lets a single head_object round trip capture both the metadata
                # and the compare-and-swap token for a subsequent conditional write.
                metadata["ETag"] = response["ETag"]
                return metadata
            except botocore.exceptions.ClientError as exc:
                code = _error_code(exc)
                if code == "403":
                    # S3 HEAD requests return HTTP 403 with no body when the caller
                    # lacks s3:GetObject permission — treat as a credential/permission error.
                    raise CredentialError(
                        message=_CREDENTIAL_ERROR_MESSAGE,
                        service="s3",
                        original=exc,
                    ) from exc
                if code in ("NoSuchKey", "404"):
                    raise KeyError(key) from exc
                raise

    def list_objects(self, prefix: str) -> list[str]:
        logger.debug("S3 list_objects prefix=%s", prefix)
        with wrap_credential_errors("s3"):
            paginator = self._s3.get_paginator("list_objects_v2")
            return [
                obj["Key"]
                for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix)
                for obj in page.get("Contents", [])
            ]

    def head_bucket(self, bucket: str) -> None:
        logger.debug("S3 head_bucket bucket=%s", bucket)
        with wrap_credential_errors("s3"):
            self._s3.head_bucket(Bucket=bucket)

    def delete_object(self, key: str) -> None:
        logger.debug("S3 delete_object key=%s", key)
        with wrap_credential_errors("s3"):
            self._s3.delete_object(Bucket=self._bucket, Key=key)

    def put_object_annotation(
        self,
        key: str,
        annotation_name: str,
        payload: str,
        *,
        if_match: str | None = None,
    ) -> None:
        logger.debug(
            "S3 put_object_annotation key=%s annotation_name=%s if_match=%s",
            key,
            annotation_name,
            if_match,
        )
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "AnnotationName": annotation_name,
            "AnnotationPayload": payload.encode("utf-8"),
        }
        if if_match is not None:
            kwargs["ObjectIfMatch"] = if_match
        with wrap_credential_errors("s3"):
            try:
                self._s3.put_object_annotation(**kwargs)
            except botocore.exceptions.ClientError as exc:
                if is_annotation_unavailable_error(exc):
                    raise AnnotationUnavailableError(
                        _ANNOTATION_UNAVAILABLE_MESSAGE, "s3", exc
                    ) from exc
                code = _error_code(exc)
                if if_match is not None and code == "PreconditionFailed":
                    raise ArtifactConflictError(key) from exc
                if code in ("NoSuchKey", "404"):
                    raise KeyError(key) from exc
                raise

    def get_object_annotation(self, key: str, annotation_name: str) -> str:
        logger.debug("S3 get_object_annotation key=%s annotation_name=%s", key, annotation_name)
        with wrap_credential_errors("s3"):
            try:
                response = self._s3.get_object_annotation(
                    Bucket=self._bucket, Key=key, AnnotationName=annotation_name
                )
                payload = response["AnnotationPayload"].read()
                try:
                    return payload.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise NonUtf8PayloadError(key, exc) from exc
            except botocore.exceptions.ClientError as exc:
                if is_annotation_unavailable_error(exc):
                    raise AnnotationUnavailableError(
                        _ANNOTATION_UNAVAILABLE_MESSAGE, "s3", exc
                    ) from exc
                # Three distinct not-found causes, kept distinct: only an absent
                # annotation may ever become an empty link-field list, and a bare 404
                # says nothing about which of the other two it was.
                code = _error_code(exc)
                if code == "NoSuchAnnotation":
                    raise AnnotationNotFoundError(key) from exc
                if code == "NoSuchKey":
                    raise ObjectNotFoundError(key) from exc
                if code == "404":
                    raise KeyError(key) from exc
                raise

    def list_object_annotations(self, key: str) -> list[str]:
        logger.debug("S3 list_object_annotations key=%s", key)
        with wrap_credential_errors("s3"):
            names: list[str] = []
            continuation_token: str | None = None
            while True:
                kwargs: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
                if continuation_token:
                    kwargs["ContinuationToken"] = continuation_token
                try:
                    response = self._s3.list_object_annotations(**kwargs)
                except botocore.exceptions.ClientError as exc:
                    if is_annotation_unavailable_error(exc):
                        raise AnnotationUnavailableError(
                            _ANNOTATION_UNAVAILABLE_MESSAGE, "s3", exc
                        ) from exc
                    code = _error_code(exc)
                    if code in ("NoSuchKey", "404"):
                        raise KeyError(key) from exc
                    raise
                names.extend(
                    annotation["AnnotationName"] for annotation in response.get("Annotations", [])
                )
                continuation_token = response.get("NextContinuationToken")
                if not continuation_token:
                    break
            return names

    def delete_object_annotation(
        self,
        key: str,
        annotation_name: str,
        *,
        if_match: str | None = None,
    ) -> None:
        logger.debug(
            "S3 delete_object_annotation key=%s annotation_name=%s if_match=%s",
            key,
            annotation_name,
            if_match,
        )
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "AnnotationName": annotation_name,
        }
        if if_match is not None:
            kwargs["ObjectIfMatch"] = if_match
        with wrap_credential_errors("s3"):
            try:
                self._s3.delete_object_annotation(**kwargs)
            except botocore.exceptions.ClientError as exc:
                if is_annotation_unavailable_error(exc):
                    raise AnnotationUnavailableError(
                        _ANNOTATION_UNAVAILABLE_MESSAGE, "s3", exc
                    ) from exc
                code = _error_code(exc)
                if if_match is not None and code == "PreconditionFailed":
                    raise ArtifactConflictError(key) from exc
                if code in ("NoSuchKey", "NoSuchAnnotation", "404"):
                    return
                raise
