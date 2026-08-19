"""Unit tests for arkeology.clients.credentials.

Covers:
- The newly-added botocore error codes classify as CredentialError.
- NoCredentialsError and the SSO/token exceptions are caught by
  wrap_credential_errors (not only ClientError).
- The annotation-unavailable AccessDenied path (T52) is unaffected by adding
  "AccessDenied" to CREDENTIAL_ERROR_CODES — reconciled explicitly with a
  dedicated test using the real client method ordering.
"""

import botocore.exceptions
import pytest

from arkeology.clients.credentials import (
    CREDENTIAL_ERROR_CODES,
    _error_code,
    is_annotation_unavailable_error,
    is_credential_error,
    wrap_credential_errors,
)
from arkeology.clients.s3 import S3ClientImpl
from arkeology.errors import AnnotationUnavailableError, CredentialError

# ---------------------------------------------------------------------------
# _error_code (F-2)
# ---------------------------------------------------------------------------


def test_error_code_extracts_code_from_client_error() -> None:
    """_error_code returns the "Error"/"Code" value from a ClientError's response."""
    exc = botocore.exceptions.ClientError(
        {"Error": {"Code": "SomeCode", "Message": "x"}}, "GetObject"
    )
    assert _error_code(exc) == "SomeCode"


def test_error_code_returns_empty_string_when_error_key_absent() -> None:
    """_error_code returns "" (never raises) when the response has no "Error" key."""
    exc = botocore.exceptions.ClientError({}, "GetObject")
    assert _error_code(exc) == ""


# ---------------------------------------------------------------------------
# Credential error codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "ExpiredToken",
        "InvalidAccessKeyId",
        "SignatureDoesNotMatch",
        "AccessDenied",
        "UnrecognizedClientException",
    ],
)
def test_new_credential_error_codes_classified(code: str) -> None:
    """Each newly-added code is present in CREDENTIAL_ERROR_CODES and is_credential_error
    recognises a ClientError carrying it."""
    assert code in CREDENTIAL_ERROR_CODES
    exc = botocore.exceptions.ClientError({"Error": {"Code": code, "Message": "x"}}, "GetObject")
    assert is_credential_error(exc) is True


@pytest.mark.parametrize(
    "code",
    [
        "ExpiredToken",
        "InvalidAccessKeyId",
        "SignatureDoesNotMatch",
        "AccessDenied",
        "UnrecognizedClientException",
    ],
)
def test_wrap_credential_errors_translates_new_codes(code: str) -> None:
    """wrap_credential_errors converts each newly-added code into CredentialError."""
    exc = botocore.exceptions.ClientError({"Error": {"Code": code, "Message": "x"}}, "GetObject")
    with pytest.raises(CredentialError), wrap_credential_errors("s3"):
        raise exc


# ---------------------------------------------------------------------------
# NoCredentialsError / SSO / token exceptions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        botocore.exceptions.NoCredentialsError(),
        botocore.exceptions.UnauthorizedSSOTokenError(),
        botocore.exceptions.SSOTokenLoadError(error_msg="expired"),
        botocore.exceptions.TokenRetrievalError(provider="sso", error_msg="expired"),
    ],
)
def test_wrap_credential_errors_catches_non_client_error_credential_exceptions(
    exc: Exception,
) -> None:
    """NoCredentialsError and every SSO/token exception are caught (not only ClientError)
    and re-raised as CredentialError — previously these escaped as a raw BotoCoreError."""
    with pytest.raises(CredentialError) as exc_info, wrap_credential_errors("s3"):
        raise exc
    assert exc_info.value.original is exc


def test_wrap_credential_errors_other_botocore_error_still_propagates() -> None:
    """A BotoCoreError that is NOT a credential exception still propagates unchanged."""
    exc = botocore.exceptions.EndpointConnectionError(endpoint_url="https://example.invalid")
    with pytest.raises(botocore.exceptions.EndpointConnectionError), wrap_credential_errors("s3"):
        raise exc


# ---------------------------------------------------------------------------
# Reconciliation: the annotation-unavailable AccessDenied path is unaffected
# ---------------------------------------------------------------------------


def test_access_denied_is_both_credential_and_annotation_unavailable_code() -> None:
    """'AccessDenied' is intentionally present in both classifiers — the annotation
    client methods check is_annotation_unavailable_error() first, before the exception
    ever reaches is_credential_error(), so the two consumers never actually collide."""
    exc = botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "x"}}, "PutObjectAnnotation"
    )
    assert is_credential_error(exc) is True
    assert is_annotation_unavailable_error(exc) is True


def test_annotation_access_denied_still_raises_annotation_unavailable_not_credential(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """End-to-end: put_object_annotation's AccessDenied still raises
    AnnotationUnavailableError (T52), never CredentialError, even though 'AccessDenied'
    is now also a member of CREDENTIAL_ERROR_CODES."""
    s3_client.put_object(key="artifacts/a1.md", body="content", metadata={"title": "A1"})
    exc = botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "PutObjectAnnotation"
    )
    mocker.patch.object(s3_client._s3, "put_object_annotation", side_effect=exc)

    with pytest.raises(AnnotationUnavailableError):
        s3_client.put_object_annotation("artifacts/a1.md", "commit_refs", "abc")


def test_get_object_access_denied_raises_credential_error(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A plain (non-annotation) S3 operation's 'AccessDenied' now correctly raises
    CredentialError — previously it propagated as a raw, unclassified ClientError."""
    exc = botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "GetObject"
    )
    mocker.patch.object(s3_client._s3, "get_object", side_effect=exc)

    with pytest.raises(CredentialError):
        s3_client.get_object("artifacts/does-not-matter.md")
