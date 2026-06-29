"""Shared credential error detection helpers for boto3 clients.

Centralising the error code set and detection function prevents the three
concrete clients (S3, S3 Vectors, Bedrock) from maintaining independent
copies that could silently diverge.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import botocore.exceptions

from cairn_mcp.errors import CredentialError

# botocore error codes that indicate credential/auth problems
CREDENTIAL_ERROR_CODES: frozenset[str] = frozenset(
    {
        "ExpiredTokenException",
        "InvalidClientTokenId",
        "AuthFailure",
        "AccessDeniedException",
        "UnauthorizedOperation",
    }
)

# Human-readable message attached to every CredentialError raised by the clients.
_CREDENTIAL_ERROR_MESSAGE = (
    "AWS credentials are invalid or expired. "
    "Re-authenticate (e.g. aws sso login) and restart the server."
)


def is_credential_error(exc: botocore.exceptions.ClientError) -> bool:
    """Return True if the ClientError indicates an auth/credential problem."""
    code = exc.response.get("Error", {}).get("Code", "")
    return code in CREDENTIAL_ERROR_CODES


@contextmanager
def wrap_credential_errors(service: str) -> Iterator[None]:
    """Translate credential ``ClientError``s into :class:`CredentialError`.

    Any ``botocore.exceptions.ClientError`` raised inside the ``with`` block is
    inspected: credential/auth errors are re-raised as a ``CredentialError`` for
    the given ``service``; all other ``ClientError``s (and every other exception
    type) propagate unchanged so callers can apply their own special-case
    handling (not-found mapping, transient retries, index-not-found, …).
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
