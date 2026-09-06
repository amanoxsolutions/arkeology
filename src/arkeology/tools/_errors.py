"""arkeology.tools._errors — shared tool-layer error-response helpers.

Collapses the ``except <error>`` → structured-response shape repeated across tool
modules into one helper per condition, so the many uniform call sites stay in sync
automatically. Only sites that catch the bare exception and return exactly
``{"error": <code>, "message": str(exc)}`` (nothing else — no extra fields, no
logging, no failure-log entry) delegate here; every bespoke variant is
intentionally left as its own inline handling.

Two conditions are mapped here. ``CredentialError`` is the original. The
annotation store being unavailable is the second: it surfaces from every tool that
reads the durable link fields, and a mapping duplicated per tool is a mapping that
drifts per tool — which is how one condition came to return three different codes
(see ``s3-annotations.artifact``).
"""

from typing import Any

from arkeology.constants import ErrorCode
from arkeology.errors import AnnotationUnavailableError, CredentialError


def credential_error_response(exc: CredentialError) -> dict[str, Any]:
    """Build the standard structured error response for a caught CredentialError.

    Args:
        exc: The caught CredentialError.

    Returns:
        ``{"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}``.
    """
    return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}


def annotation_unavailable_response(exc: AnnotationUnavailableError) -> dict[str, Any]:
    """Build the standard structured error response for a caught AnnotationUnavailableError.

    Startup check 8 proves the annotation store is available before the server accepts a
    request, so at runtime this condition can only be post-setup IAM drift — a cause with
    a known remedy, which ``internal_error`` would say nothing about.

    Args:
        exc: The caught AnnotationUnavailableError.

    Returns:
        ``{"error": ErrorCode.ANNOTATION_UNAVAILABLE, "message": str(exc)}``.
    """
    return {"error": ErrorCode.ANNOTATION_UNAVAILABLE, "message": str(exc)}
