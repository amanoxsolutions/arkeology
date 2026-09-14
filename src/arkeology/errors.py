"""Structured error types used throughout arkeology.

All errors are data carriers — they hold context for display and logging
but contain no business logic.
"""


class ArkeologyError(Exception):
    """Base class for all arkeology domain errors."""


class CredentialError(ArkeologyError):
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


class StartupValidationError(ArkeologyError):
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


class ConfigurationError(ArkeologyError):
    """Raised when the server cannot start due to invalid or missing configuration.

    Wraps Pydantic's ``ValidationError`` so callers only handle a single domain
    exception type.  Produced by :func:`arkeology.config.load_settings`.

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


class AnnotationUnavailableError(ArkeologyError):
    """Raised when an S3 object annotation call fails because annotations are
    unavailable (unsupported region or bucket type) or the caller lacks the
    required IAM permission.

    Distinct from :class:`CredentialError`: this signals an annotation-specific
    limitation, not a general credential/authentication failure. Annotations are
    the sole durable store for the mutable ``commit_refs`` / ``references`` link
    fields, so this is a hard error, never a degrade: startup check 8 refuses to
    start a deployment that cannot use annotations, and at runtime this error means
    post-setup drift (an IAM policy edited after installation). Callers surface it
    as a structured error and record a failure-log entry where a durable write had
    already partially landed; none of them report the operation as successful.

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


class VectorIndexNotFoundError(ArkeologyError):
    """Raised when the configured S3 Vectors index does not exist.

    Attributes:
        index_name: The name of the missing index.
        bucket_name: The vectors bucket that was queried.
    """

    def __init__(self, index_name: str, bucket_name: str) -> None:
        super().__init__(f"Vector index '{index_name}' not found in bucket '{bucket_name}'")
        self.index_name = index_name
        self.bucket_name = bucket_name


class ArtifactCollisionError(ArkeologyError):
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


class ArtifactConflictError(ArkeologyError):
    """Raised when a conditional-update ``PutObject`` / ``PutObjectAnnotation`` /
    ``DeleteObjectAnnotation`` (``IfMatch`` / ``ObjectIfMatch``) is rejected because the
    object's current ETag no longer matches the value captured on read (HTTP 412
    PreconditionFailed).

    Distinct from :class:`ArtifactCollisionError`, which signals a conditional *create*
    rejected because an object already exists (the ``if_none_match`` case).
    ``ArtifactConflictError`` signals a conditional *update* rejected because someone else
    already changed the object (or, for an annotation write, changed the object body) since
    it was last read — the optimistic-concurrency compare-and-swap guard for durable
    read-modify-write cycles on ``commit_refs`` / ``references`` (ADR-011 decision 6). The
    caller (``write.py``'s overwrite path, ``link_metadata``, ``archive_artifact``) is
    responsible for the bounded re-read/re-merge/re-write retry cycle this error signals.

    Attributes:
        key: The S3 key whose conditional update was rejected.
    """

    def __init__(self, key: str) -> None:
        super().__init__(f"Conditional update rejected: key '{key}' was modified concurrently")
        self.key = key


class MetadataTooLargeError(ArkeologyError):
    """Raised when assembled write-path metadata breaches one of the three byte budgets
    checked before any S3 or vector write — see ``arkeology.artifact.check_metadata_budgets``.

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


class InvalidFilterValueError(ArkeologyError):
    """Raised when a caller-supplied metadata filter value is not one of the
    recognised values for that field.

    Distinct from a legitimate zero-match query: a typo'd or out-of-range filter
    value (e.g. ``type="cod_review"``, ``tier=99``, ``status="actve"``) must
    surface as an explicit ``validation_error`` rather than silently returning
    an empty result set that looks identical to a query that legitimately
    matched nothing.

    Attributes:
        field: The filter field name (e.g. ``"type"``, ``"tier"``, ``"status"``).
        value: The invalid value supplied by the caller.
    """

    def __init__(self, field: str, value: object) -> None:
        super().__init__(f"invalid {field} filter value: {value!r}")
        self.field = field
        self.value = value


class FilterEvaluationError(ArkeologyError):
    """Raised when a metadata filter expression cannot be evaluated against a vector's
    metadata — an unsupported operator, or a comparison between incomparable types
    (e.g. a ``$gte``/``$lte`` operand whose type does not support ordering against the
    field's value). Raised by :func:`arkeology.clients.filter.matches_filter`; never
    caught inside ``VectorsClientImpl.list_vectors_by_metadata``'s pagination loop, so
    it always propagates as a clear, typed signal instead of a bare ``ValueError``/
    ``TypeError`` or a silently discarded partial scan.

    Attributes:
        message: Human-readable explanation of what could not be evaluated.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NonUtf8PayloadError(ArkeologyError):
    """Raised when a stored S3 object body or object-annotation payload is not valid
    UTF-8. Every arkeology write path always UTF-8-encodes content and metadata, so
    this signals external corruption (a non-arkeology writer, or bit rot) rather than
    an in-repo bug — callers must surface it as a classified error instead of letting
    a bare ``UnicodeDecodeError`` propagate unhandled.

    Attributes:
        key: S3 key whose payload could not be decoded.
        original: The original ``UnicodeDecodeError``, preserved for logging.
    """

    def __init__(self, key: str, original: UnicodeDecodeError) -> None:
        super().__init__(f"Payload for key '{key}' is not valid UTF-8: {original}")
        self.key = key
        self.original = original


class DuplicateManifestPathError(ArkeologyError):
    """Raised when a migration manifest contains two entries whose paths normalize to
    the same key. Silently letting the second entry overwrite the first (last-write-
    wins) would discard one manifest entry's mapping with zero signal to the caller
    — a collision must be surfaced instead of swallowed.

    Attributes:
        path: The normalized path shared by both colliding manifest entries.
    """

    def __init__(self, path: str) -> None:
        super().__init__(f"Duplicate manifest path after normalization: {path!r}")
        self.path = path


class VectorDistanceMissingError(ArkeologyError):
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


class AnnotationNotFoundError(KeyError):
    """Raised when ``GetObjectAnnotation`` reports ``NoSuchAnnotation``: the object
    exists, and this annotation does not.

    The **only** not-found cause that may become an empty link-field list.
    :func:`arkeology.annotations._read_one` catches this type alone, so a genuinely
    absent annotation returns ``[]`` while every other not-found propagates — the
    distinction every read-modify-write cycle on ``commit_refs`` / ``references``
    depends on, there being no second store to recover from.

    Subclasses :class:`KeyError` rather than :class:`ArkeologyError`, deliberately
    departing from the hierarchy every other typed error here follows. Three callers
    probe reachability by catching ``KeyError`` to mean "not found, so the call was
    permitted" — ``health_check``'s annotation probe and the startup sequence's
    per-read-prefix probe, whose probe key need not exist — and subclassing keeps all
    of them correct with no edit.
    """


class ObjectNotFoundError(KeyError):
    """Raised when ``GetObjectAnnotation`` reports ``NoSuchKey``: the object itself is
    gone.

    Not an absent annotation, and never degraded to ``[]``. It is a read that
    *succeeded* and answered definitively, so a listing omits the artifact and counts
    it while a single-artifact read reports it as not found — neither reports an
    artifact that merely has no links. A bare ``404`` establishes neither and stays an
    unclassified :class:`KeyError`.

    Subclasses :class:`KeyError` for the same reachability-probe reason as
    :class:`AnnotationNotFoundError`.
    """
