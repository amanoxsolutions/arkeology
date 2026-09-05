"""Protocol interfaces for all AWS service clients.

Each interface uses ``typing.Protocol`` for structural subtyping. Concrete
implementations and fakes satisfy the contract without inheriting from the
interface class. This decouples the client layer from the interface hierarchy
and enables dependency injection with any structurally compatible object.
"""

from typing import Any, Protocol

# Type alias for vector metadata — values may be strings, numbers, or tag lists.
VectorMetadata = dict[str, str | int | float | list[str]]


class S3ClientInterface(Protocol):
    """Protocol interface for S3 object storage operations."""

    def put_object(
        self,
        key: str,
        body: str,
        metadata: dict[str, str],
        *,
        if_none_match: bool = False,
        if_match: str | None = None,
    ) -> str:
        """Store an object under the given key with optional metadata.

        Args:
            key: S3 object key.
            body: Object content as a UTF-8 string.
            metadata: Key-value metadata to attach to the object.
            if_none_match: When True, perform an atomic conditional-create
                (``IfNoneMatch: "*"``) instead of an unconditional put. Use this to
                close the check-then-act race of a separate ``head_object`` existence
                check followed by an unconditional ``put_object``.
            if_match: When set, perform an atomic conditional-update (``IfMatch``)
                that only succeeds if the object's current ETag equals this value —
                the optimistic-concurrency compare-and-swap guard for a
                read-modify-write cycle on an existing object (ADR-011 decision 6).

        Returns:
            The object's new ETag (as returned by the underlying ``PutObject`` call),
            for use as ``if_match``/``ObjectIfMatch`` on a subsequent conditional
            write that must not race a concurrent change to this object.

        Raises:
            ArtifactCollisionError: If ``if_none_match=True`` and an object already
                exists at ``key`` (HTTP 412 PreconditionFailed).
            ArtifactConflictError: If ``if_match`` is set and does not match the
                object's current ETag (HTTP 412 PreconditionFailed).
            CredentialError: If credentials are invalid or expired.
        """
        ...

    def get_object(self, key: str) -> str:
        """Retrieve object content by key.

        Args:
            key: S3 object key.

        Returns:
            Object content as a UTF-8 string.

        Raises:
            KeyError: If the key does not exist.
            CredentialError: If credentials are invalid or expired.
            NonUtf8PayloadError: If the stored object body cannot be decoded as
                UTF-8.
        """
        ...

    def head_object(self, key: str) -> dict[str, Any]:
        """Retrieve object metadata without fetching the content.

        Args:
            key: S3 object key.

        Returns:
            Dict containing the object's metadata, with every user-defined value
            transport-decoded (symmetric with ``put_object``'s encoding, so callers
            never see or need to handle percent-escapes), plus a reserved capitalised
            ``"ETag"`` key holding the object's current ETag (quoted, as returned by
            S3). Every real user-defined metadata key is lowercase, so ``"ETag"``
            cannot collide with one — this lets a single ``head_object`` round trip
            capture both the metadata and the compare-and-swap token needed for a
            subsequent conditional write (ADR-011 decision 6), avoiding a second
            round trip. ``"ETag"`` itself is never encoded and so is never decoded.

        Raises:
            KeyError: If the key does not exist.
            CredentialError: If credentials are invalid or expired.
        """
        ...

    def list_objects(self, prefix: str) -> list[str]:
        """List all object keys under the given prefix.

        Args:
            prefix: S3 key prefix to filter by.

        Returns:
            List of matching object keys in lexicographic order.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """
        ...

    def head_bucket(self, bucket: str) -> None:
        """Check bucket existence and accessibility.

        Args:
            bucket: S3 bucket name.

        Raises:
            CredentialError: If credentials are invalid or expired.
            Exception: For other S3 errors (bucket not found, permission denied).
        """
        ...

    def delete_object(self, key: str) -> None:
        """Delete an object by key. Silently ignores missing keys.

        Args:
            key: S3 object key to delete.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """
        ...

    def put_object_annotation(
        self,
        key: str,
        annotation_name: str,
        payload: str,
        *,
        if_match: str | None = None,
    ) -> None:
        """Write (or overwrite) a named annotation on an object.

        Annotations are mutable in place and do not disturb the object body, its
        write-time timestamp, or its embeddings (ADR-011).

        Args:
            key: S3 object key.
            annotation_name: Name of the annotation (e.g. "commit_refs").
            payload: Annotation payload as a UTF-8 string.
            if_match: When set, sent as the boto3 ``ObjectIfMatch`` parameter — the
                write only succeeds if the object's current ETag equals this value
                (ADR-011 decision 6). Annotations do not change the object's ETag, so
                this guards against a concurrent change to the object body between a
                caller's read and this write, not against another annotation write.

        Raises:
            ArtifactConflictError: If ``if_match`` is set and does not match the
                object's current ETag (HTTP 412 PreconditionFailed).
            CredentialError: If credentials are invalid or expired.
            AnnotationUnavailableError: If S3 object annotations are unavailable
                for this bucket (unsupported region/bucket type) or the caller
                lacks the required IAM permission (ADR-2026-07-03).
        """
        ...

    def get_object_annotation(self, key: str, annotation_name: str) -> str:
        """Retrieve a named annotation's payload.

        Args:
            key: S3 object key.
            annotation_name: Name of the annotation to retrieve.

        Returns:
            Annotation payload decoded as a UTF-8 string.

        Raises:
            KeyError: If the object or the named annotation does not exist.
            CredentialError: If credentials are invalid or expired.
            AnnotationUnavailableError: If S3 object annotations are unavailable
                for this bucket (unsupported region/bucket type) or the caller
                lacks the required IAM permission (ADR-2026-07-03).
            NonUtf8PayloadError: If the stored annotation payload cannot be
                decoded as UTF-8.
        """
        ...

    def list_object_annotations(self, key: str) -> list[str]:
        """List the names of all annotations present on an object.

        Args:
            key: S3 object key.

        Returns:
            List of annotation names present on the object.

        Raises:
            KeyError: If the object does not exist.
            CredentialError: If credentials are invalid or expired.
            AnnotationUnavailableError: If S3 object annotations are unavailable
                for this bucket (unsupported region/bucket type) or the caller
                lacks the required IAM permission (ADR-2026-07-03).
        """
        ...

    def delete_object_annotation(
        self,
        key: str,
        annotation_name: str,
        *,
        if_match: str | None = None,
    ) -> None:
        """Delete a named annotation from an object.

        Silently ignores an absent object or an already-absent annotation
        (mirrors ``delete_object``).

        Args:
            key: S3 object key.
            annotation_name: Name of the annotation to delete.
            if_match: When set, sent as the boto3 ``ObjectIfMatch`` parameter — the
                delete only succeeds if the object's current ETag equals this value
                (ADR-011 decision 6). See :meth:`put_object_annotation` for the same
                caveat regarding annotation ETag-stability.

        Raises:
            ArtifactConflictError: If ``if_match`` is set and does not match the
                object's current ETag (HTTP 412 PreconditionFailed).
            CredentialError: If credentials are invalid or expired.
            AnnotationUnavailableError: If S3 object annotations are unavailable
                for this bucket (unsupported region/bucket type) or the caller
                lacks the required IAM permission (ADR-2026-07-03).
        """
        ...


class VectorsClientInterface(Protocol):
    """Protocol interface for S3 Vectors index operations."""

    def put_vector(self, key: str, vector: list[float], metadata: VectorMetadata) -> None:
        """Upsert a vector with its key and metadata.

        Args:
            key: Unique vector key.
            vector: Embedding as a list of floats.
            metadata: Arbitrary metadata dict attached to the vector.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """
        ...

    def put_vectors_batch(self, items: list[dict[str, Any]]) -> None:
        """Put a batch of vectors; chunks at 500 per PutVectors API limit.

        Args:
            items: List of dicts with keys ``key`` (str), ``vector`` (list[float]),
                and ``metadata`` (dict).

        Raises:
            CredentialError: If credentials are invalid or expired.
        """
        ...

    def get_vectors(self, keys: list[str], include_data: bool = True) -> list[dict[str, Any]]:
        """Retrieve vectors (with metadata) by key list.

        Args:
            keys: List of vector keys to retrieve.
            include_data: When False, skips requesting the float32 vector data —
                callers that only need metadata should pass this to avoid the
                bandwidth cost of fetching embeddings they never use.

        Returns:
            List of dicts with keys: ``key``, ``metadata``, ``data``. ``data`` is
            an empty dict when ``include_data=False``. Missing keys are omitted
            silently.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """
        ...

    def query_vectors(
        self,
        vector: list[float],
        top_k: int,
        filter_expr: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Semantic search over the index.

        Args:
            vector: Query embedding as a list of floats.
            top_k: Maximum number of results to return.
            filter_expr: Optional metadata filter expression.

        Returns:
            List of dicts with keys: ``key``, ``score``, ``metadata``.
            Ordered by score descending.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """
        ...

    def delete_vectors(self, keys: list[str]) -> None:
        """Delete vectors by key list. Silently ignores missing keys.

        Args:
            keys: List of vector keys to delete.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """
        ...

    def describe_index(self) -> dict[str, Any]:
        """Return index metadata including the ``dimension`` field.

        Returns:
            Dict containing at minimum: ``dimension`` (int).

        Raises:
            VectorIndexNotFoundError: If the index does not exist.
            CredentialError: If credentials are invalid or expired.
        """
        ...

    def list_vectors_by_metadata(self, filter_expr: dict[str, Any]) -> list[str]:
        """Return all vector keys matching a metadata filter.

        Args:
            filter_expr: Metadata filter expression.

        Returns:
            List of matching vector keys.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """
        ...


class BedrockClientInterface(Protocol):
    """Protocol interface for Amazon Bedrock embedding operations."""

    def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
        """Generate an embedding for the given text.

        Args:
            text: Input text to embed.
            model_id: Bedrock model identifier.
            dimensions: Desired output dimension. Must match the configured
                BEDROCK_EMBEDDING_DIMENSIONS and the S3 Vectors index dimension.

        Returns:
            Embedding vector as a list of floats.

        Raises:
            CredentialError: If credentials are invalid or expired.
            botocore.exceptions.ClientError: Re-raised unchanged for any
                non-transient error once the transient-error retry loop is
                exhausted (persistent throttling surfaces this way too).
        """
        ...

    def invoke_text_model(self, model_id: str, prompt: str) -> str:
        """Invoke a Bedrock text generation model and return the response text.

        Args:
            model_id: Bedrock model identifier (e.g. "amazon.nova-lite-v1:0").
            prompt: User prompt text to send to the model.

        Returns:
            Generated text as a string.

        Raises:
            CredentialError: If credentials are invalid or expired.
            botocore.exceptions.ClientError: Re-raised unchanged for any
                non-transient error once the transient-error retry loop is
                exhausted (persistent throttling surfaces this way too).
        """
        ...
