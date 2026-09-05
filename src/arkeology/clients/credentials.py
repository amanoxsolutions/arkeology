"""Shared credential error detection helpers for boto3 clients.

Centralising the error code set and detection function prevents the three
concrete clients (S3, S3 Vectors, Bedrock) from maintaining independent
copies that could silently diverge. Also centralises the S3-only annotation-
unavailability detection (ADR-011 decision 5) used by the four object-
annotation client methods.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import botocore.exceptions

from arkeology.errors import CredentialError

# botocore error codes that indicate credential/auth problems.
#
# Both the STS/"Exception"-suffixed forms and the bare S3 XML forms (no "Exception"
# suffix) must be listed: AWS returns either spelling for the same underlying
# conditions — expired session token, malformed/unknown access key, a request signed
# with the wrong secret key, and S3's own plain "AccessDenied" — as well as
# "UnrecognizedClientException", which several services (including Bedrock) return for
# an invalid/malformed SigV4 signature. All are credential/auth problems, not
# authorization-scope problems. Omitting a spelling makes that failure surface as an
# opaque generic error instead of an actionable credential error.
#
# Caution: "AccessDenied" is deliberately also part of ANNOTATION_UNAVAILABLE_ERROR_CODES
# below (T52 / ADR-011 decision 5) for the four S3 object-annotation operations. This is
# not a conflict: every annotation client method (see clients/s3.py) checks
# is_annotation_unavailable_error() and raises AnnotationUnavailableError *before* the
# exception ever reaches wrap_credential_errors' is_credential_error() check — so an
# annotation-path AccessDenied is always classified as annotation-unavailable, never as a
# credential error, regardless of what is in this set. Only non-annotation S3 calls
# (get_object, put_object, head_bucket, list_objects, delete_object) and other services
# fall through to the credential classification below.
CREDENTIAL_ERROR_CODES: frozenset[str] = frozenset(
    {
        "ExpiredTokenException",
        "ExpiredToken",
        "InvalidClientTokenId",
        "InvalidAccessKeyId",
        "SignatureDoesNotMatch",
        "AuthFailure",
        "AccessDeniedException",
        "AccessDenied",
        "UnauthorizedOperation",
        "UnrecognizedClientException",
    }
)

# botocore exception types (raised locally, never wrapped in a ClientError response)
# that indicate a credential/auth problem — missing local credentials or an expired/
# invalid SSO or bearer token. Unlike CREDENTIAL_ERROR_CODES above (which classifies a
# ClientError's response body), these are raised directly by botocore's credential
# resolution machinery before any API call is even made, so wrap_credential_errors must
# catch them independently of the ClientError branch.
_CREDENTIAL_EXCEPTION_TYPES: tuple[type[Exception], ...] = (
    botocore.exceptions.NoCredentialsError,
    botocore.exceptions.SSOError,
    botocore.exceptions.TokenRetrievalError,
)

# botocore error codes that indicate S3 object annotations are unavailable — either
# because the operation is not supported for this region/bucket type (e.g. the UAE
# and Bahrain regions; directory buckets, the bucket type the S3 Express One Zone
# storage class uses; and Outposts buckets) or the caller lacks the
# required IAM permission. Not an official AWS-documented enumeration (annotations
# are a newer S3 feature); this is the set observed/expected per ADR-011 decision 5
# and is deliberately distinct from CREDENTIAL_ERROR_CODES above — "AccessDenied" here
# is the plain S3 code for a missing IAM action, not a credential/auth failure.
ANNOTATION_UNAVAILABLE_ERROR_CODES: frozenset[str] = frozenset(
    {
        "AccessDenied",
        "NotImplemented",
        "MethodNotAllowed",
        "UnsupportedOperation",
    }
)

# Human-readable message attached to every CredentialError raised by the clients.
_CREDENTIAL_ERROR_MESSAGE = (
    "AWS credentials are invalid or expired. "
    "Re-authenticate (e.g. aws sso login) and restart the server."
)

# Human-readable, actionable message attached to every AnnotationUnavailableError.
# Annotations back only the commit_refs/references link feature (ADR-011) — core
# content, vector, and embedding operations are unaffected by this failure.
_ANNOTATION_UNAVAILABLE_MESSAGE = (
    "S3 object annotations are unavailable for this bucket, or the caller lacks the "
    "required IAM permission. Annotations back only the commit_refs/references link "
    "feature — core artifact content, vector, and embedding operations are unaffected. "
    "Verify the deployment's IAM policy grants s3:PutObjectAnnotation, "
    "s3:GetObjectAnnotation, s3:ListObjectAnnotations, and s3:DeleteObjectAnnotation, "
    "and that the bucket is not in an unsupported region (UAE, Bahrain) or bucket type "
    "(directory buckets, the bucket type the S3 Express One Zone storage class uses, "
    "or Outposts buckets)."
)


def _error_code(exc: botocore.exceptions.ClientError) -> str:
    """Extract the boto3 "Error"/"Code" value from a ClientError's response.

    Returns "" if the response has no "Error" key or no "Code" key — never raises.
    Shared by every credential/error-code classifier in the client layer;
    do not hand-roll ``exc.response.get("Error", {}).get("Code", "")`` again.
    """
    return exc.response.get("Error", {}).get("Code", "")


def is_credential_error(exc: botocore.exceptions.ClientError) -> bool:
    """Return True if the ClientError indicates an auth/credential problem."""
    return _error_code(exc) in CREDENTIAL_ERROR_CODES


def is_annotation_unavailable_error(exc: botocore.exceptions.ClientError) -> bool:
    """Return True if the ClientError indicates S3 annotations are unavailable
    (unsupported region/bucket type) or access to the annotation API is denied."""
    return _error_code(exc) in ANNOTATION_UNAVAILABLE_ERROR_CODES


def is_annotation_permission_error(exc: botocore.exceptions.ClientError) -> bool:
    """Return True if an annotation failure is a missing IAM action rather than an
    unsupported region or bucket type.

    Both conditions raise the same ``AnnotationUnavailableError``, but an operator
    fixes them differently — one is an IAM policy edit, the other requires relocating
    the bucket — so the startup gate splits them by error code here rather than
    re-deriving the code at its own call site.
    """
    return _error_code(exc) == "AccessDenied"


@contextmanager
def wrap_credential_errors(service: str) -> Iterator[None]:
    """Translate credential ``ClientError``s into :class:`CredentialError`.

    Any ``botocore.exceptions.ClientError`` raised inside the ``with`` block is
    inspected: credential/auth errors are re-raised as a ``CredentialError`` for
    the given ``service``; all other ``ClientError``s (and every other exception
    type) propagate unchanged so callers can apply their own special-case
    handling (not-found mapping, transient retries, index-not-found, …).

    ``NoCredentialsError`` and the SSO/bearer-token exceptions (``SSOError`` and its
    subclasses, ``TokenRetrievalError``) are caught too: botocore's local credential
    resolution raises them directly rather than delivering a ``ClientError`` response,
    so without a separate branch they escape as an uncaught ``BotoCoreError`` and
    surface to MCP callers as ``internal_error`` instead of the actionable
    ``aws sso login`` remediation path.
    """
    try:
        yield
    except botocore.exceptions.ClientError as exc:
        if is_credential_error(exc):
            raise CredentialError(
                message=_CREDENTIAL_ERROR_MESSAGE,
                service=service,
                original=exc,
            ) from exc
        raise
    except _CREDENTIAL_EXCEPTION_TYPES as exc:
        raise CredentialError(
            message=_CREDENTIAL_ERROR_MESSAGE,
            service=service,
            original=exc,
        ) from exc
