"""Abstract base classes for all AWS service clients.

Each interface declares the methods that every concrete implementation and every
fake must satisfy. No boto3 calls are made here.
"""

from abc import ABC, abstractmethod
from typing import Any


class S3ClientInterface(ABC):
    """Abstract interface for S3 object storage operations."""

    @abstractmethod
    def put_object(self, key: str, body: str, metadata: dict[str, str]) -> None:
        """Store an object under the given key with optional metadata.

        Args:
            key: S3 object key.
            body: Object content as a UTF-8 string.
            metadata: Key-value metadata to attach to the object.
        """

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
    def list_objects(self, prefix: str) -> list[str]:
        """List all object keys under the given prefix.

        Args:
            prefix: S3 key prefix to filter by.

        Returns:
            List of matching object keys.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """

    @abstractmethod
    def head_bucket(self, bucket: str) -> None:
        """Check bucket existence and accessibility.

        Args:
            bucket: S3 bucket name.

        Raises:
            CredentialError: If credentials are invalid or expired.
            Exception: For other S3 errors (bucket not found, permission denied).
        """

    @abstractmethod
    def delete_object(self, key: str) -> None:
        """Delete an object by key. Silently ignores missing keys.

        Args:
            key: S3 object key to delete.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """


class VectorsClientInterface(ABC):
    """Abstract interface for S3 Vectors index operations."""

    @abstractmethod
    def put_vector(self, key: str, vector: list[float], metadata: dict[str, Any]) -> None:
        """Upsert a vector with its key and metadata.

        Args:
            key: Unique vector key.
            vector: Embedding as a list of floats.
            metadata: Arbitrary metadata dict attached to the vector.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """

    @abstractmethod
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

    @abstractmethod
    def query_vectors(
        self,
        vector: list[float],
        top_k: int,
        filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Semantic search over the index.

        Args:
            vector: Query embedding as a list of floats.
            top_k: Maximum number of results to return.
            filter: Optional metadata filter expression.

        Returns:
            List of dicts with keys: ``key``, ``score``, ``metadata``.
            Ordered by score descending.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """

    @abstractmethod
    def delete_vectors(self, keys: list[str]) -> None:
        """Delete vectors by key list. Silently ignores missing keys.

        Args:
            keys: List of vector keys to delete.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """

    @abstractmethod
    def describe_index(self) -> dict[str, Any]:
        """Return index metadata including the ``dimension`` field.

        Returns:
            Dict containing at minimum: ``dimension`` (int).

        Raises:
            VectorIndexNotFoundError: If the index does not exist.
            CredentialError: If credentials are invalid or expired.
        """

    @abstractmethod
    def list_vectors_by_metadata(self, filter: dict[str, Any]) -> list[str]:
        """Return all vector keys matching a metadata filter.

        Args:
            filter: Metadata filter expression.

        Returns:
            List of matching vector keys.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """


class BedrockClientInterface(ABC):
    """Abstract interface for Amazon Bedrock embedding operations."""

    @abstractmethod
    def embed(self, text: str, model_id: str) -> list[float]:
        """Generate an embedding for the given text.

        Args:
            text: Input text to embed.
            model_id: Bedrock model identifier.

        Returns:
            Embedding vector as a list of floats.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """
