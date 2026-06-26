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

    def put_object(self, key: str, body: str, metadata: dict[str, str]) -> None:
        """Store an object under the given key with optional metadata.

        Args:
            key: S3 object key.
            body: Object content as a UTF-8 string.
            metadata: Key-value metadata to attach to the object.
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
        """
        ...

    def head_object(self, key: str) -> dict[str, Any]:
        """Retrieve object metadata without fetching the content.

        Args:
            key: S3 object key.

        Returns:
            Dict containing the object's metadata.

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

    def get_vectors(self, keys: list[str]) -> list[dict[str, Any]]:
        """Retrieve vectors (with metadata) by key list.

        Args:
            keys: List of vector keys to retrieve.

        Returns:
            List of dicts with keys: ``key``, ``metadata``, ``data``.
            Missing keys are omitted silently.

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
        """
        ...
