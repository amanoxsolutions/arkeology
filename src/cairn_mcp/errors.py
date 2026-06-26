"""Structured error types used throughout cairn-mcp.

All errors are data carriers — they hold context for display and logging
but contain no business logic.
"""


class CairnError(Exception):
    """Base class for all cairn-mcp domain errors."""


class CredentialError(CairnError):
    """Raised when an AWS call fails due to expired, invalid, or missing credentials.

    Attributes:
        message: Human-readable explanation with re-authentication instructions.
        service: Which AWS service triggered the error (e.g. "s3", "bedrock").
        original: The original botocore exception, preserved for logging.
    """

    def __init__(self, message: str, service: str, original: Exception) -> None:
        super().__init__(message)
        self.message = message
        self.service = service
        self.original = original


class StartupValidationError(CairnError):
    """Raised during the startup sequence when a configuration check fails.

    Attributes:
        check: Which check failed (e.g. "credentials", "write_prefix",
            "vector_index_dimension").
        message: Actionable error message with remediation hint.
    """

    def __init__(self, check: str, message: str) -> None:
        super().__init__(message)
        self.check = check
        self.message = message


class ConfigurationError(CairnError):
    """Raised when the server cannot start due to invalid or missing configuration.

    Wraps Pydantic's ``ValidationError`` so callers only handle a single domain
    exception type.  Produced by :func:`cairn_mcp.config.load_settings`.

    Attributes:
        message: Human-readable, formatted description of all validation failures
            with remediation hints.
        fields: Names of the configuration fields that failed validation
            (may be empty when the error is not field-specific).
    """

    def __init__(self, message: str, fields: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.fields = fields or []


class VectorIndexNotFoundError(CairnError):
    """Raised when the configured S3 Vectors index does not exist.

    Attributes:
        index_name: The name of the missing index.
        bucket_name: The vectors bucket that was queried.
    """

    def __init__(self, index_name: str, bucket_name: str) -> None:
        super().__init__(f"Vector index '{index_name}' not found in bucket '{bucket_name}'")
        self.index_name = index_name
        self.bucket_name = bucket_name
