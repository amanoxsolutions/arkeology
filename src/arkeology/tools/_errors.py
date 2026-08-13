"""arkeology.tools._errors — shared tool-layer error-response helpers.

Collapses the ``except CredentialError`` → structured-response shape repeated
across tool modules into a single helper, so the many uniform call sites stay
in sync automatically. Only sites that catch a bare ``CredentialError`` and
return exactly ``{"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}``
(nothing else — no extra fields, no logging, no failure-log entry) delegate
here; every bespoke variant is intentionally left as its own inline handling.
"""

from typing import Any

from arkeology.constants import ErrorCode
from arkeology.errors import CredentialError


def credential_error_response(exc: CredentialError) -> dict[str, Any]:
    """Build the standard structured error response for a caught CredentialError.

    Args:
        exc: The caught CredentialError.

    Returns:
        ``{"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}``.
    """
    return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}
