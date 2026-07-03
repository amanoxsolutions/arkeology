"""Unit tests for S3ClientImpl object-annotation operations (T45).

Exercises put_object_annotation / get_object_annotation / list_object_annotations /
delete_object_annotation through the moto self-mock extension registered in
tests/unit/conftest.py (moto 5.2.2 has no native annotation support — see
docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md).
"""

import botocore.exceptions
import pytest

from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.errors import CredentialError

# ---------------------------------------------------------------------------
# Story 1 — annotation round-trip through the client
# ---------------------------------------------------------------------------


def test_put_then_get_annotation_roundtrip(s3_client: S3ClientImpl) -> None:
    """put_object_annotation followed by get_object_annotation returns the same payload."""
    s3_client.put_object(key="artifacts/a1.md", body="content", metadata={"title": "A1"})

    s3_client.put_object_annotation("artifacts/a1.md", "commit_refs", "abc,def")

    assert s3_client.get_object_annotation("artifacts/a1.md", "commit_refs") == "abc,def"


def test_list_returns_all_annotation_names(s3_client: S3ClientImpl) -> None:
    """list_object_annotations returns every annotation name written to the key."""
    s3_client.put_object(key="artifacts/a2.md", body="content", metadata={"title": "A2"})
    s3_client.put_object_annotation("artifacts/a2.md", "commit_refs", "abc")
    s3_client.put_object_annotation("artifacts/a2.md", "references", "def")

    names = s3_client.list_object_annotations("artifacts/a2.md")

    assert sorted(names) == ["commit_refs", "references"]


def test_delete_annotation_removes_it(s3_client: S3ClientImpl) -> None:
    """After delete_object_annotation, get_object_annotation raises KeyError."""
    s3_client.put_object(key="artifacts/a3.md", body="content", metadata={"title": "A3"})
    s3_client.put_object_annotation("artifacts/a3.md", "commit_refs", "abc")

    s3_client.delete_object_annotation("artifacts/a3.md", "commit_refs")

    with pytest.raises(KeyError):
        s3_client.get_object_annotation("artifacts/a3.md", "commit_refs")


def test_get_missing_annotation_raises_key_error(s3_client: S3ClientImpl) -> None:
    """get_object_annotation for a name never set on an existing key raises KeyError."""
    s3_client.put_object(key="artifacts/a4.md", body="content", metadata={"title": "A4"})

    with pytest.raises(KeyError):
        s3_client.get_object_annotation("artifacts/a4.md", "references")


def test_get_annotation_on_missing_object_raises_key_error(s3_client: S3ClientImpl) -> None:
    """get_object_annotation against a key that does not exist at all raises KeyError."""
    with pytest.raises(KeyError):
        s3_client.get_object_annotation("artifacts/does-not-exist.md", "commit_refs")


def test_delete_missing_annotation_does_not_raise(s3_client: S3ClientImpl) -> None:
    """delete_object_annotation on an absent annotation is a silent no-op (mirrors delete)."""
    s3_client.put_object(key="artifacts/a5.md", body="content", metadata={"title": "A5"})

    s3_client.delete_object_annotation("artifacts/a5.md", "commit_refs")


def test_delete_annotation_on_missing_object_does_not_raise(s3_client: S3ClientImpl) -> None:
    """delete_object_annotation against a non-existent key is also a silent no-op."""
    s3_client.delete_object_annotation("artifacts/does-not-exist.md", "commit_refs")


# ---------------------------------------------------------------------------
# Story 2 — overwrite wipes annotations
# ---------------------------------------------------------------------------


def test_overwrite_wipes_annotations(s3_client: S3ClientImpl) -> None:
    """Re-putting an object's body clears any annotations previously written to it."""
    s3_client.put_object(key="artifacts/a6.md", body="original", metadata={"title": "A6"})
    s3_client.put_object_annotation("artifacts/a6.md", "commit_refs", "abc")

    s3_client.put_object(key="artifacts/a6.md", body="replacement", metadata={"title": "A6"})

    with pytest.raises(KeyError):
        s3_client.get_object_annotation("artifacts/a6.md", "commit_refs")


# ---------------------------------------------------------------------------
# Story 3 — credential errors are structured
# ---------------------------------------------------------------------------


def _credential_error(operation: str) -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError(
        {
            "Error": {
                "Code": "ExpiredTokenException",
                "Message": "The security token included in the request is expired.",
            }
        },
        operation,
    )


def test_put_object_annotation_credential_error(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """put_object_annotation raises CredentialError, never a raw botocore exception."""
    mocker.patch.object(
        s3_client._s3,
        "put_object_annotation",
        side_effect=_credential_error("PutObjectAnnotation"),
    )

    with pytest.raises(CredentialError):
        s3_client.put_object_annotation("artifacts/a7.md", "commit_refs", "abc")


def test_get_object_annotation_credential_error(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """get_object_annotation raises CredentialError, never a raw botocore exception."""
    mocker.patch.object(
        s3_client._s3,
        "get_object_annotation",
        side_effect=_credential_error("GetObjectAnnotation"),
    )

    with pytest.raises(CredentialError):
        s3_client.get_object_annotation("artifacts/a7.md", "commit_refs")


def test_list_object_annotations_credential_error(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """list_object_annotations raises CredentialError, never a raw botocore exception."""
    mocker.patch.object(
        s3_client._s3,
        "list_object_annotations",
        side_effect=_credential_error("ListObjectAnnotations"),
    )

    with pytest.raises(CredentialError):
        s3_client.list_object_annotations("artifacts/a7.md")


def test_delete_object_annotation_credential_error(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """delete_object_annotation raises CredentialError, never a raw botocore exception."""
    mocker.patch.object(
        s3_client._s3,
        "delete_object_annotation",
        side_effect=_credential_error("DeleteObjectAnnotation"),
    )

    with pytest.raises(CredentialError):
        s3_client.delete_object_annotation("artifacts/a7.md", "commit_refs")
