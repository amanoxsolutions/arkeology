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


class AnnotationUnavailableError(CairnError):
    """Raised when an S3 object annotation call fails because annotations are
    unavailable (unsupported region or bucket type) or the caller lacks the
    required IAM permission.

    Distinct from :class:`CredentialError`: this signals an annotation-specific
    limitation, not a general credential/authentication failure. Annotations
    back only the mutable ``commit_refs`` / ``references`` link fields
    (ADR-011) — core content, vector, and embedding operations are unaffected
    and must keep functioning when this error is raised. Per ADR-011
    decision 5, callers degrade gracefully (a warning on the write path, a
    structured error from ``link_metadata``) rather than treating this as a
    hard failure, and it is never used as a startup gate.

    Attributes:
        message: Human-readable, actionable explanation (required IAM actions,
            unsupported regions/bucket types).
        service: Which AWS service triggered the error (always ``"s3"``).
        original: The original botocore exception, preserved for logging.
    """

    def __init__(self, message: str, service: str, original: Exception) -> None:
        super().__init__(message)
        self.message = message
        self.service = service
        self.original = original


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


class ArtifactCollisionError(CairnError):
    """Raised when a conditional-create ``PutObject`` (``IfNoneMatch: "*"``) is rejected
    because an object already exists at the target key (HTTP 412 PreconditionFailed).

    This is the authoritative, atomic collision signal for the write-path's
    ``overwrite=False`` guard (see ``tools/write.py``). A prior ``head_object``-based
    existence check is a friendly fast path only and is inherently racy (check-then-act);
    this error is raised from the same atomic S3 call that performs the write itself, so
    two concurrent same-key writes cannot both succeed — the loser of the race gets this
    error instead of silently overwriting the winner.

    Attributes:
        key: The S3 key whose conditional create was rejected.
    """

    def __init__(self, key: str) -> None:
        super().__init__(f"Conditional create rejected: an object already exists at key '{key}'")
        self.key = key


class MetadataTooLargeError(CairnError):
    """Raised when assembled write-path metadata breaches one of the three byte budgets
    checked before any S3 or vector write — see ``cairn_mcp.artifact.check_metadata_budgets``.

    Attributes:
        budget: Which budget was breached: ``"s3_user_metadata"``,
            ``"vector_filterable_metadata"``, or ``"vector_total_metadata"``.
        actual_bytes: The measured size of the offending representation, in bytes.
        max_bytes: The budget's maximum allowed size, in bytes.
    """

    def __init__(self, budget: str, actual_bytes: int, max_bytes: int) -> None:
        super().__init__(
            f"Metadata exceeds the {budget} budget: {actual_bytes} bytes > {max_bytes} bytes"
        )
        self.budget = budget
        self.actual_bytes = actual_bytes
        self.max_bytes = max_bytes


class VectorDistanceMissingError(CairnError):
    """Raised when a ``query_vectors`` result is missing the ``distance`` field.

    S3 Vectors only returns ``distance`` when the request sets ``returnDistance: true``.
    A missing distance must never be silently treated as perfect similarity
    (``score = 1.0``) — that would make ranked semantic recall degenerate to an
    arbitrary tie order. Raise instead of defaulting.

    Attributes:
        key: The vector key whose result was missing a ``distance`` value.
    """

    def __init__(self, key: str) -> None:
        super().__init__(
            f"query_vectors result for key '{key}' is missing 'distance' — "
            "the request must set returnDistance=True to receive scored results"
        )
        self.key = key
