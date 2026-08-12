"""Unit tests for S3ClientImpl object-annotation operations (T45).

Exercises put_object_annotation / get_object_annotation / list_object_annotations /
delete_object_annotation through the moto self-mock extension registered in
tests/unit/conftest.py (moto 5.2.2 has no native annotation support — see
docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md).

Also exercises the optimistic-concurrency (ETag compare-and-swap) surface added for
ADR-011 decision 6 / the review-followup-2026-07-06 design fixes: ``head_object``'s
reserved ``"ETag"`` key, ``put_object``'s ``if_match`` parameter and ETag return value,
and ``put_object_annotation`` / ``delete_object_annotation``'s ``if_match`` parameter
(sent as boto3's ``ObjectIfMatch``).
"""

import io

import botocore.exceptions
import pytest

from arkeology.clients.s3 import S3ClientImpl
from arkeology.errors import (
    AnnotationUnavailableError,
    ArkeologyError,
    ArtifactConflictError,
    CredentialError,
)

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


def test_list_annotations_follows_continuation_token_across_pages(
    s3_client: S3ClientImpl, mocker: pytest.MonkeyPatch
) -> None:
    """M14: A first page carrying NextContinuationToken must trigger a second
    ListObjectAnnotations call (with that token forwarded as ContinuationToken) and
    the names from both pages must be combined."""
    s3_client.put_object(key="artifacts/a2b.md", body="content", metadata={"title": "A2b"})
    page1 = {
        "Annotations": [{"AnnotationName": "commit_refs"}],
        "NextContinuationToken": "token-1",
    }
    page2 = {"Annotations": [{"AnnotationName": "references"}]}
    spy = mocker.patch.object(s3_client._s3, "list_object_annotations", side_effect=[page1, page2])

    names = s3_client.list_object_annotations("artifacts/a2b.md")

    assert sorted(names) == ["commit_refs", "references"]
    assert spy.call_count == 2
    assert spy.call_args_list[1].kwargs["ContinuationToken"] == "token-1"


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


def test_put_annotation_on_missing_object_raises_key_error(s3_client: S3ClientImpl) -> None:
    """put_object_annotation against a key that does not exist at all raises KeyError
    (M10) — mirrors get_object_annotation's / list_object_annotations's / delete_-
    object_annotation's NoSuchKey mapping, which put_object_annotation lacked. This is
    what lets link_metadata's per-artifact loop skip an orphaned-vector artifact
    (vector indexed, S3 object already deleted) instead of aborting the whole batch
    on an unmapped ClientError."""
    with pytest.raises(KeyError):
        s3_client.put_object_annotation("artifacts/does-not-exist.md", "commit_refs", "abc1234")


def test_list_annotations_on_missing_object_raises_key_error(s3_client: S3ClientImpl) -> None:
    """list_object_annotations against a key that does not exist at all raises KeyError
    (Phase-12 #26) — mirrors get_object_annotation's / put_object_annotation's / delete_-
    object_annotation's NoSuchKey mapping, which list_object_annotations was untested for."""
    with pytest.raises(KeyError):
        s3_client.list_object_annotations("artifacts/does-not-exist.md")


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
# Story 2b — non-UTF-8 stored payload is classified, not a bare UnicodeDecodeError
# (Phase-12 #16)
# ---------------------------------------------------------------------------


def test_get_object_annotation_non_utf8_payload_raises_typed_error(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A stored annotation payload that is not valid UTF-8 (e.g. corrupted, or written
    by a non-arkeology tool) must surface as a typed, classified ArkeologyError — not a
    bare UnicodeDecodeError propagating out as an unhandled exception."""
    s3_client.put_object(key="artifacts/bad-utf8.md", body="content", metadata={"title": "X"})
    mocker.patch.object(
        s3_client._s3,
        "get_object_annotation",
        return_value={"AnnotationPayload": io.BytesIO(b"\xff\xfe not valid utf-8")},
    )

    with pytest.raises(ArkeologyError):
        s3_client.get_object_annotation("artifacts/bad-utf8.md", "commit_refs")


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


# ---------------------------------------------------------------------------
# Story 3 (T52) — annotation-unavailable / access-denied errors are structured
# ---------------------------------------------------------------------------


def _access_denied_error(operation: str) -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError(
        {
            "Error": {
                "Code": "AccessDenied",
                "Message": "Access Denied",
            }
        },
        operation,
    )


def _not_implemented_error(operation: str) -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError(
        {
            "Error": {
                "Code": "NotImplemented",
                "Message": "A header you provided implies functionality that is not implemented",
            }
        },
        operation,
    )


def test_put_object_annotation_access_denied_raises_annotation_unavailable(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """AccessDenied on put_object_annotation raises AnnotationUnavailableError — a
    distinct, structured error, never a raw botocore exception or a CredentialError."""
    mocker.patch.object(
        s3_client._s3,
        "put_object_annotation",
        side_effect=_access_denied_error("PutObjectAnnotation"),
    )

    with pytest.raises(AnnotationUnavailableError) as excinfo:
        s3_client.put_object_annotation("artifacts/a8.md", "commit_refs", "abc")

    # Message is actionable: names the four required IAM actions.
    assert "s3:PutObjectAnnotation" in str(excinfo.value)
    assert "s3:GetObjectAnnotation" in str(excinfo.value)
    assert "s3:ListObjectAnnotations" in str(excinfo.value)
    assert "s3:DeleteObjectAnnotation" in str(excinfo.value)


def test_get_object_annotation_not_implemented_raises_annotation_unavailable(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A NotImplemented response (region/bucket-type rejection) on
    get_object_annotation raises AnnotationUnavailableError, not KeyError or a raw
    botocore exception."""
    mocker.patch.object(
        s3_client._s3,
        "get_object_annotation",
        side_effect=_not_implemented_error("GetObjectAnnotation"),
    )

    with pytest.raises(AnnotationUnavailableError):
        s3_client.get_object_annotation("artifacts/a8.md", "commit_refs")


def test_list_object_annotations_access_denied_raises_annotation_unavailable(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """AccessDenied on list_object_annotations raises AnnotationUnavailableError."""
    mocker.patch.object(
        s3_client._s3,
        "list_object_annotations",
        side_effect=_access_denied_error("ListObjectAnnotations"),
    )

    with pytest.raises(AnnotationUnavailableError):
        s3_client.list_object_annotations("artifacts/a8.md")


def test_delete_object_annotation_not_implemented_raises_annotation_unavailable(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A NotImplemented response on delete_object_annotation raises
    AnnotationUnavailableError rather than being swallowed as a no-op."""
    mocker.patch.object(
        s3_client._s3,
        "delete_object_annotation",
        side_effect=_not_implemented_error("DeleteObjectAnnotation"),
    )

    with pytest.raises(AnnotationUnavailableError):
        s3_client.delete_object_annotation("artifacts/a8.md", "commit_refs")


# ---------------------------------------------------------------------------
# Optimistic-concurrency (ETag compare-and-swap) surface — ADR-011 decision 6
# ---------------------------------------------------------------------------


def test_head_object_includes_etag_key(s3_client: S3ClientImpl) -> None:
    """head_object's returned dict includes a capitalised 'ETag' key alongside the
    (lowercase) user-defined metadata, distinguishable from any real metadata key."""
    s3_client.put_object(key="artifacts/e1.md", body="content", metadata={"title": "E1"})

    meta = s3_client.head_object("artifacts/e1.md")

    assert "ETag" in meta
    assert isinstance(meta["ETag"], str)
    assert meta["ETag"]
    assert meta["title"] == "E1"


def test_put_object_returns_new_etag(s3_client: S3ClientImpl) -> None:
    """put_object returns the object's new ETag."""
    etag = s3_client.put_object(key="artifacts/e2.md", body="content", metadata={"title": "E2"})

    assert isinstance(etag, str)
    assert etag
    assert etag == s3_client.head_object("artifacts/e2.md")["ETag"]


def test_put_object_if_match_matching_etag_succeeds(s3_client: S3ClientImpl) -> None:
    """put_object(if_match=<current ETag>) succeeds and updates the content."""
    etag = s3_client.put_object(key="artifacts/e3.md", body="v1", metadata={"title": "E3"})

    s3_client.put_object(key="artifacts/e3.md", body="v2", metadata={"title": "E3"}, if_match=etag)

    assert s3_client.get_object("artifacts/e3.md") == "v2"


def test_put_object_if_match_stale_etag_raises_conflict(s3_client: S3ClientImpl) -> None:
    """put_object(if_match=<stale ETag>) raises ArtifactConflictError and leaves the
    object's content untouched — distinct from ArtifactCollisionError (create-collision)."""
    s3_client.put_object(key="artifacts/e4.md", body="v1", metadata={"title": "E4"})
    stale_etag = '"0000000000000000000000000000000"'

    with pytest.raises(ArtifactConflictError):
        s3_client.put_object(
            key="artifacts/e4.md", body="v2", metadata={"title": "E4"}, if_match=stale_etag
        )

    assert s3_client.get_object("artifacts/e4.md") == "v1"


def test_put_object_annotation_if_match_matching_etag_succeeds(s3_client: S3ClientImpl) -> None:
    """put_object_annotation(if_match=<current object ETag>) succeeds."""
    etag = s3_client.put_object(key="artifacts/e5.md", body="content", metadata={"title": "E5"})

    s3_client.put_object_annotation("artifacts/e5.md", "commit_refs", "abc", if_match=etag)

    assert s3_client.get_object_annotation("artifacts/e5.md", "commit_refs") == "abc"


def test_put_object_annotation_if_match_stale_etag_raises_conflict(
    s3_client: S3ClientImpl,
) -> None:
    """put_object_annotation(if_match=<stale ETag>) raises ArtifactConflictError and
    does not write the annotation."""
    s3_client.put_object(key="artifacts/e6.md", body="content", metadata={"title": "E6"})
    stale_etag = '"0000000000000000000000000000000"'

    with pytest.raises(ArtifactConflictError):
        s3_client.put_object_annotation(
            "artifacts/e6.md", "commit_refs", "abc", if_match=stale_etag
        )

    with pytest.raises(KeyError):
        s3_client.get_object_annotation("artifacts/e6.md", "commit_refs")


def test_delete_object_annotation_if_match_matching_etag_succeeds(s3_client: S3ClientImpl) -> None:
    """delete_object_annotation(if_match=<current object ETag>) succeeds."""
    etag = s3_client.put_object(key="artifacts/e7.md", body="content", metadata={"title": "E7"})
    s3_client.put_object_annotation("artifacts/e7.md", "commit_refs", "abc")

    s3_client.delete_object_annotation("artifacts/e7.md", "commit_refs", if_match=etag)

    with pytest.raises(KeyError):
        s3_client.get_object_annotation("artifacts/e7.md", "commit_refs")


def test_delete_object_annotation_if_match_stale_etag_raises_conflict(
    s3_client: S3ClientImpl,
) -> None:
    """delete_object_annotation(if_match=<stale ETag>) raises ArtifactConflictError and
    does not delete the annotation."""
    s3_client.put_object(key="artifacts/e8.md", body="content", metadata={"title": "E8"})
    s3_client.put_object_annotation("artifacts/e8.md", "commit_refs", "abc")
    stale_etag = '"0000000000000000000000000000000"'

    with pytest.raises(ArtifactConflictError):
        s3_client.delete_object_annotation("artifacts/e8.md", "commit_refs", if_match=stale_etag)

    assert s3_client.get_object_annotation("artifacts/e8.md", "commit_refs") == "abc"
