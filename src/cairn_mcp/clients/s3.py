"""Concrete S3 client implementation using boto3.

All credential errors are caught at this layer and re-raised as CredentialError.
Non-credential errors propagate unchanged.
"""

import logging
import unicodedata
from typing import Any

import boto3
import botocore.exceptions

from cairn_mcp.clients.credentials import (
    _CREDENTIAL_ERROR_MESSAGE,
    wrap_credential_errors,
)
from cairn_mcp.clients.interfaces import S3ClientInterface  # noqa: F401 (structural only)
from cairn_mcp.errors import CredentialError

logger = logging.getLogger(__name__)


def _ascii_safe_metadata(metadata: dict[str, str]) -> dict[str, str]:
    """Return a copy of metadata with all values sanitized to ASCII.

    S3 object metadata is transmitted as HTTP headers, which only support ASCII.
    NFKD normalization decomposes accented characters to their ASCII base
    (e.g. é → e); remaining non-ASCII characters (e.g. em dash) are dropped.

    Args:
        metadata: Original metadata dict with potentially non-ASCII string values.

    Returns:
        New dict with all values sanitized to ASCII.
    """
    return {
        k: unicodedata.normalize("NFKD", v).encode("ascii", errors="ignore").decode("ascii")
        for k, v in metadata.items()
    }


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

    def put_object(self, key: str, body: str, metadata: dict[str, str]) -> None:
        logger.debug("S3 put_object key=%s", key)
        with wrap_credential_errors("s3"):
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body.encode("utf-8"),
                Metadata=_ascii_safe_metadata(metadata),
            )

    def get_object(self, key: str) -> str:
        logger.debug("S3 get_object key=%s", key)
        with wrap_credential_errors("s3"):
            try:
                response = self._s3.get_object(Bucket=self._bucket, Key=key)
                return response["Body"].read().decode("utf-8")
            except botocore.exceptions.ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in ("NoSuchKey", "404"):
                    raise KeyError(key) from exc
                raise

    def head_object(self, key: str) -> dict[str, Any]:
        logger.debug("S3 head_object key=%s", key)
        with wrap_credential_errors("s3"):
            try:
                response = self._s3.head_object(Bucket=self._bucket, Key=key)
                return dict(response.get("Metadata", {}))
            except botocore.exceptions.ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
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
