"""Deterministic Bedrock embedding fake for unit tests.

Implements BedrockClientInterface without making any AWS calls.
Produces deterministic hash-derived unit vectors for reproducible tests.
"""

import hashlib
import math
import struct

from cairn_mcp.clients.interfaces import BedrockClientInterface  # noqa: F401 (structural only)
from cairn_mcp.errors import CredentialError


class ThrottlingError(Exception):
    """Simulates a Bedrock ThrottlingException for testing retry logic."""


class ModelTimeoutError(Exception):
    """Simulates a Bedrock ModelTimeoutException for testing retry logic."""


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


class FakeBedrockClient:
    """Deterministic in-memory Bedrock client for use in unit tests."""

    def __init__(self, dimension: int = 1024) -> None:
        self._dimension = dimension
        self._credential_failure: bool = False
        self._throttle_remaining: int = 0
        self._timeout_remaining: int = 0

    def set_credential_failure(self, value: bool) -> None:
        """Toggle simulated credential failure for all subsequent calls."""
        self._credential_failure = value

    def set_throttle_once(self) -> None:
        """Simulate a single throttle on the next embed call."""
        self._throttle_remaining = 1

    def set_throttle_count(self, count: int) -> None:
        """Simulate multiple consecutive throttles."""
        self._throttle_remaining = count

    def set_timeout_once(self) -> None:
        """Simulate a single model timeout on the next embed call."""
        self._timeout_remaining = 1

    def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
        """Return a deterministic unit vector derived from the input text.

        Includes single-retry logic for transient errors (throttling, timeout).
        Unlike the real Bedrock client, the fake retries immediately with no
        sleep or jitter between attempts — callers that assert on retry count
        behave correctly, but timing-sensitive tests are not covered here.

        Args:
            text: Input text to embed.
            model_id: Ignored in the fake; present for interface compatibility.
            dimensions: Desired vector length.

        Returns:
            Deterministic unit vector of length ``dimensions``.

        Raises:
            CredentialError: If credential failure has been simulated.
            ThrottlingError: If throttle persists after retry.
            ModelTimeoutError: If timeout persists after retry.
        """
        if self._credential_failure:
            raise CredentialError(
                message="AWS credentials are invalid or expired (simulated).",
                service="bedrock",
                original=Exception("simulated credential failure"),
            )
        for attempt in range(2):
            try:
                return self._do_embed(text, dimensions)
            except ThrottlingError, ModelTimeoutError:
                if attempt == 1:
                    raise
        raise RuntimeError("Unreachable: retry loop always returns or raises")

    def _do_embed(self, text: str, dimensions: int) -> list[float]:
        """Single embed attempt — may raise transient errors."""
        if self._throttle_remaining > 0:
            self._throttle_remaining -= 1
            raise ThrottlingError("simulated throttle")
        if self._timeout_remaining > 0:
            self._timeout_remaining -= 1
            raise ModelTimeoutError("simulated model timeout")
        return _deterministic_unit_vector(text, dimensions)

    def invoke_text_model(self, model_id: str, prompt: str) -> str:
        """Return a deterministic short string for any prompt.

        The return value is fixed regardless of model_id or prompt, making call
        count assertions reliable in tests.

        Args:
            model_id: Ignored in the fake; present for interface compatibility.
            prompt: Ignored in the fake; present for interface compatibility.

        Returns:
            The constant string ``"Fake description."``
        """
        return "Fake description."
