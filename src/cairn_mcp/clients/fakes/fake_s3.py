"""In-memory S3 fake for unit tests.

Implements S3ClientInterface entirely in memory. No AWS calls are made.
Supports simulated credential failures via set_credential_failure().
"""

from typing import Any

from cairn_mcp.clients.interfaces import S3ClientInterface  # noqa: F401 (structural only)
from cairn_mcp.errors import CredentialError


class FakeS3Client:
    """Stateful in-memory S3 client for use in unit tests."""

    def __init__(self) -> None:
        # Maps key -> (content, metadata)
        self._objects: dict[str, tuple[str, dict[str, str]]] = {}
        self._credential_failure: bool = False

    def set_credential_failure(self, value: bool) -> None:
        """Toggle simulated credential failure for all subsequent calls."""
        self._credential_failure = value

    def _check_credentials(self) -> None:
        if self._credential_failure:
            raise CredentialError(
                message="AWS credentials are invalid or expired (simulated).",
                service="s3",
                original=Exception("simulated credential failure"),
            )

    def put_object(self, key: str, body: str, metadata: dict[str, str]) -> None:
        self._check_credentials()
        self._objects[key] = (body, metadata)

    def get_object(self, key: str) -> str:
        self._check_credentials()
        if key not in self._objects:
            raise KeyError(key)
        return self._objects[key][0]

    def head_object(self, key: str) -> dict[str, Any]:
        self._check_credentials()
        if key not in self._objects:
            raise KeyError(key)
        return dict(self._objects[key][1])

    def list_objects(self, prefix: str) -> list[str]:
        self._check_credentials()
        return sorted(k for k in self._objects if k.startswith(prefix))

    def head_bucket(self, bucket: str) -> None:
        self._check_credentials()

    def delete_object(self, key: str) -> None:
        self._check_credentials()
        self._objects.pop(key, None)

    @property
    def _store(self) -> dict[str, tuple[str, dict[str, str]]]:
        """Alias for _objects, used in tests."""
        return self._objects
