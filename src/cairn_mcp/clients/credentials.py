"""Shared credential error detection helpers for boto3 clients.

Centralising the error code set and detection function prevents the three
concrete clients (S3, S3 Vectors, Bedrock) from maintaining independent
copies that could silently diverge.
"""

import botocore.exceptions

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


def is_credential_error(exc: botocore.exceptions.ClientError) -> bool:
    """Return True if the ClientError indicates an auth/credential problem."""
    code = exc.response.get("Error", {}).get("Code", "")
    return code in CREDENTIAL_ERROR_CODES
