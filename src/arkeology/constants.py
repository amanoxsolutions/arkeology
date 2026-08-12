"""arkeology.constants — centralised string-literal constants.

Holds the error-code strings returned to MCP callers (as the ``"error"`` field
of a tool result dict) and the artifact status values stored in S3 object
metadata and vector metadata.

These are :class:`enum.StrEnum` members, so each member *is* a ``str``: it
compares equal to its literal value, formats to that value in f-strings, and
JSON-serialises to the bare string (e.g. ``ErrorCode.CREDENTIAL_ERROR`` becomes
``"credential_error"``). Centralising them aids IDE-wide refactoring without
changing any serialised value.

This module is AWS-free and dependency-free; it contains only constant
definitions.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Error-code values returned as the ``"error"`` field of a tool result dict.

    Each member's value is the exact string surfaced to MCP callers; do not
    change a value — only the reference is centralised here.
    """

    CREDENTIAL_ERROR = "credential_error"
    INTERNAL_ERROR = "internal_error"
    VALIDATION_ERROR = "validation_error"
    CONFIGURATION_ERROR = "configuration_error"
    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"
    CONFIRMATION_REQUIRED = "confirmation_required"
    PARTIAL_WRITE = "partial_write"
    PARTIAL_DELETE = "partial_delete"
    DELETE_VECTORS_FAILED = "delete_vectors_failed"
    ANNOTATION_UNAVAILABLE = "annotation_unavailable"
    CONFLICT = "conflict"


class ArtifactStatus(StrEnum):
    """Artifact status values stored in S3 and vector metadata.

    ``ACTIVE`` is the default for newly written artifacts; ``INACTIVE`` marks an
    archived artifact. Each member's value is the exact string persisted to AWS
    metadata; do not change a value.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
