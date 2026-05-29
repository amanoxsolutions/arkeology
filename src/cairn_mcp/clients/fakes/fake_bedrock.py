"""Deterministic Bedrock embedding fake for unit tests.

Implements BedrockClientInterface without making any AWS calls.
Produces deterministic hash-derived unit vectors for reproducible tests.
"""

import hashlib
import math
import struct

from cairn_mcp.clients.interfaces import BedrockClientInterface
from cairn_mcp.errors import CredentialError


def _deterministic_unit_vector(text: str, dimension: int) -> list[float]:
    """Produce a deterministic unit-length vector from text.

    Uses SHA-256 to seed a pseudo-random float sequence, then normalises.

    Args:
        text: Input text; the same text always produces the same vector.
        dimension: Desired vector length.

    Returns:
        Unit-normalised list of floats of length ``dimension``.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    chunk_index = 0
    while len(values) < dimension:
        # Hash successive chunks to generate enough floats
        extended = hashlib.sha256(digest + chunk_index.to_bytes(4, "big")).digest()
        # Each 4 bytes → one float in [-1, 1]
        for i in range(0, len(extended) - 3, 4):
            raw = struct.unpack_from(">I", extended, i)[0]
            values.append((raw / 0xFFFFFFFF) * 2.0 - 1.0)
            if len(values) == dimension:
                break
        chunk_index += 1

    # Normalise to unit length
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        return [0.0] * dimension
    return [v / norm for v in values]


class FakeBedrockClient(BedrockClientInterface):
    """Deterministic in-memory Bedrock client for use in unit tests."""

    def __init__(self, dimension: int = 1024) -> None:
        self._dimension = dimension
        self._credential_failure: bool = False

    def set_credential_failure(self, value: bool) -> None:
        """Toggle simulated credential failure for all subsequent calls."""
        self._credential_failure = value

    def embed(self, text: str, model_id: str) -> list[float]:
        """Return a deterministic unit vector derived from the input text.

        Args:
            text: Input text to embed.
            model_id: Ignored in the fake; present for interface compatibility.

        Returns:
            Deterministic unit vector of length ``_dimension``.

        Raises:
            CredentialError: If credential failure has been simulated.
        """
        if self._credential_failure:
            raise CredentialError(
                message="AWS credentials are invalid or expired (simulated).",
                service="bedrock",
                original=Exception("simulated credential failure"),
            )
        return _deterministic_unit_vector(text, self._dimension)
