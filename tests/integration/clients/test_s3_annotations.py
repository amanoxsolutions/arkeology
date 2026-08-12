"""Integration tests for S3ClientImpl object-annotation operations (T45).

Requires real AWS credentials and a provisioned S3 bucket with the four annotation
IAM actions granted (s3:PutObjectAnnotation, s3:GetObjectAnnotation,
s3:ListObjectAnnotations, s3:DeleteObjectAnnotation — see
docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md).
Annotations are unavailable in some regions/bucket types (see the ADR); if the
configured bucket does not support them these tests will fail with a clear
botocore error rather than silently passing.

Run with: uv run pytest -m integration tests/integration/clients/test_s3_annotations.py

Environment variables required:
    AWS_REGION      — AWS region
    ARTIFACT_BUCKET — S3 bucket name for testing
    AWS_PROFILE     — (optional) named AWS profile
"""

import os
import uuid

import pytest

from arkeology.clients.s3 import S3ClientImpl

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
    return f"_arkeology_integration_test/{uuid.uuid4().hex}.md"


def test_put_get_list_delete_annotation_round_trip(
    s3_client: S3ClientImpl, unique_key: str
) -> None:
    """put -> get -> list -> delete round-trips against the real annotation API."""
    s3_client.put_object(unique_key, "content", {"test": "true"})
    try:
        s3_client.put_object_annotation(unique_key, "commit_refs", "abc,def")
        s3_client.put_object_annotation(unique_key, "references", "ghi")

        assert s3_client.get_object_annotation(unique_key, "commit_refs") == "abc,def"
        assert sorted(s3_client.list_object_annotations(unique_key)) == [
            "commit_refs",
            "references",
        ]

        s3_client.delete_object_annotation(unique_key, "commit_refs")
        with pytest.raises(KeyError):
            s3_client.get_object_annotation(unique_key, "commit_refs")
        assert s3_client.list_object_annotations(unique_key) == ["references"]
    finally:
        s3_client.delete_object(unique_key)


def test_get_missing_annotation_raises_key_error(s3_client: S3ClientImpl, unique_key: str) -> None:
    """get_object_annotation for a name never set on an existing key raises KeyError."""
    s3_client.put_object(unique_key, "content", {"test": "true"})
    try:
        with pytest.raises(KeyError):
            s3_client.get_object_annotation(unique_key, "references")
    finally:
        s3_client.delete_object(unique_key)


def test_delete_missing_annotation_does_not_raise(s3_client: S3ClientImpl, unique_key: str) -> None:
    """delete_object_annotation on an absent annotation is a silent no-op."""
    s3_client.put_object(unique_key, "content", {"test": "true"})
    try:
        s3_client.delete_object_annotation(unique_key, "commit_refs")
    finally:
        s3_client.delete_object(unique_key)


def test_overwrite_wipes_annotations(s3_client: S3ClientImpl, unique_key: str) -> None:
    """Re-putting an object's body clears any annotations previously written to it."""
    s3_client.put_object(unique_key, "original", {"test": "true"})
    try:
        s3_client.put_object_annotation(unique_key, "commit_refs", "abc")

        s3_client.put_object(unique_key, "replacement", {"test": "true"})

        with pytest.raises(KeyError):
            s3_client.get_object_annotation(unique_key, "commit_refs")
    finally:
        s3_client.delete_object(unique_key)
