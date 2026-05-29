"""Concrete S3 client implementation using boto3.

All credential errors are caught at this layer and re-raised as CredentialError.
Non-credential errors propagate unchanged.
"""

import logging
from typing import Any

import boto3
import botocore.exceptions

from cairn_mcp.clients.credentials import is_credential_error
from cairn_mcp.clients.interfaces import S3ClientInterface
from cairn_mcp.errors import CredentialError

logger = logging.getLogger(__name__)


class S3ClientImpl(S3ClientInterface):
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
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body.encode("utf-8"),
                Metadata=metadata,
            )
        except botocore.exceptions.ClientError as exc:
            if is_credential_error(exc):
                raise CredentialError(
                    message=(
                        "AWS credentials are invalid or expired. "
                        "Re-authenticate (e.g. aws sso login) and restart the server."
                    ),
                    service="s3",
                    original=exc,
                ) from exc
            raise

    def get_object(self, key: str) -> str:
        logger.debug("S3 get_object key=%s", key)
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read().decode("utf-8")
        except botocore.exceptions.ClientError as exc:
            if is_credential_error(exc):
                raise CredentialError(
                    message=(
                        "AWS credentials are invalid or expired. "
                        "Re-authenticate (e.g. aws sso login) and restart the server."
                    ),
                    service="s3",
                    original=exc,
                ) from exc
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                raise KeyError(key) from exc
            raise

    def head_object(self, key: str) -> dict[str, Any]:
        logger.debug("S3 head_object key=%s", key)
        try:
            response = self._s3.head_object(Bucket=self._bucket, Key=key)
            return dict(response.get("Metadata", {}))
        except botocore.exceptions.ClientError as exc:
            if is_credential_error(exc):
                raise CredentialError(
                    message=(
                        "AWS credentials are invalid or expired. "
                        "Re-authenticate (e.g. aws sso login) and restart the server."
                    ),
                    service="s3",
                    original=exc,
                ) from exc
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "403"):
                raise KeyError(key) from exc
            raise

    def list_objects(self, prefix: str) -> list[str]:
        logger.debug("S3 list_objects prefix=%s", prefix)
        try:
            paginator = self._s3.get_paginator("list_objects_v2")
            keys: list[str] = []
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
            return keys
        except botocore.exceptions.ClientError as exc:
            if is_credential_error(exc):
                raise CredentialError(
                    message=(
                        "AWS credentials are invalid or expired. "
                        "Re-authenticate (e.g. aws sso login) and restart the server."
                    ),
                    service="s3",
                    original=exc,
                ) from exc
            raise

    def head_bucket(self, bucket: str) -> None:
        logger.debug("S3 head_bucket bucket=%s", bucket)
        try:
            self._s3.head_bucket(Bucket=bucket)
        except botocore.exceptions.ClientError as exc:
            if is_credential_error(exc):
                raise CredentialError(
                    message=(
                        "AWS credentials are invalid or expired. "
                        "Re-authenticate (e.g. aws sso login) and restart the server."
                    ),
                    service="s3",
                    original=exc,
                ) from exc
            raise

    def delete_object(self, key: str) -> None:
        logger.debug("S3 delete_object key=%s", key)
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=key)
        except botocore.exceptions.ClientError as exc:
            if is_credential_error(exc):
                raise CredentialError(
                    message=(
                        "AWS credentials are invalid or expired. "
                        "Re-authenticate (e.g. aws sso login) and restart the server."
                    ),
                    service="s3",
                    original=exc,
                ) from exc
            raise
