"""Integration tests for S3ClientImpl.

Requires real AWS credentials and a provisioned S3 bucket.
Run with: uv run pytest -m integration tests/integration/clients/test_s3_client.py

Environment variables required:
    AWS_REGION      — AWS region
    ARTIFACT_BUCKET — S3 bucket name for testing
    AWS_PROFILE     — (optional) named AWS profile
"""

import os
import uuid

import pytest

from cairn_mcp.clients.s3 import S3ClientImpl

pytestmark = pytest.mark.integration


@pytest.fixture
def s3_client() -> S3ClientImpl:
    region = os.environ["AWS_REGION"]
    bucket = os.environ["ARTIFACT_BUCKET"]
    profile = os.environ.get("AWS_PROFILE")
    return S3ClientImpl(region=region, profile=profile, bucket=bucket)


@pytest.fixture
def unique_key() -> str:
    """Generate a unique test key that won't collide with real artifacts."""
    return f"_cairn_mcp_integration_test/{uuid.uuid4().hex}.md"


def test_put_get_round_trip(s3_client: S3ClientImpl, unique_key: str) -> None:
    """put_object then get_object returns the same content."""
    content = "integration test content"
    s3_client.put_object(unique_key, content, {"test": "true"})
    try:
        result = s3_client.get_object(unique_key)
        assert result == content
    finally:
        s3_client.delete_object(unique_key)


def test_list_objects_returns_expected_keys(s3_client: S3ClientImpl) -> None:
    """list_objects returns expected keys after writes."""
    prefix = f"_cairn_mcp_integration_test/{uuid.uuid4().hex}/"
    keys = [f"{prefix}file{i}.md" for i in range(3)]
    for key in keys:
        s3_client.put_object(key, "content", {})
    try:
        result = s3_client.list_objects(prefix)
        assert sorted(result) == sorted(keys)
    finally:
        for key in keys:
            s3_client.delete_object(key)


def test_head_bucket_succeeds(s3_client: S3ClientImpl) -> None:
    """head_bucket on the configured bucket returns without error."""
    bucket = os.environ["ARTIFACT_BUCKET"]
    s3_client.head_bucket(bucket)  # should not raise


def test_delete_object_removes_key(s3_client: S3ClientImpl, unique_key: str) -> None:
    """delete_object removes the key; subsequent get_object raises KeyError."""
    s3_client.put_object(unique_key, "content", {})
    s3_client.delete_object(unique_key)
    with pytest.raises(KeyError):
        s3_client.get_object(unique_key)
