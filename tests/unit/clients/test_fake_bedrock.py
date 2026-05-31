"""Unit tests for FakeBedrockClient — full interface coverage."""

import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.errors import CredentialError

_MODEL_ID = "amazon.titan-embed-text-v2:0"


def test_embed_returns_vector_of_expected_length() -> None:
    """embed returns a vector of the requested dimension."""
    client = FakeBedrockClient()
    result = client.embed("hello world", _MODEL_ID, 1024)
    assert len(result) == 1024


def test_embed_is_deterministic() -> None:
    """Same input always produces the same output vector."""
    client = FakeBedrockClient()
    v1 = client.embed("test text", _MODEL_ID, 1024)
    v2 = client.embed("test text", _MODEL_ID, 1024)
    assert v1 == v2


def test_embed_different_inputs_produce_different_vectors() -> None:
    """Different inputs produce different vectors."""
    client = FakeBedrockClient()
    v1 = client.embed("text about authentication", _MODEL_ID, 1024)
    v2 = client.embed("text about databases", _MODEL_ID, 1024)
    assert v1 != v2


def test_embed_default_dimension_is_1024() -> None:
    """Default dimension is 1024 when 1024 is passed as dimensions."""
    client = FakeBedrockClient()
    result = client.embed("hello", _MODEL_ID, 1024)
    assert len(result) == 1024


def test_embed_custom_dimension() -> None:
    """Custom dimension is respected when passed as argument."""
    client = FakeBedrockClient()
    result = client.embed("hello", _MODEL_ID, 512)
    assert len(result) == 512


def test_embed_credential_failure_raises() -> None:
    """embed raises CredentialError when credential failure is set."""
    client = FakeBedrockClient()
    client.set_credential_failure(True)
    with pytest.raises(CredentialError):
        client.embed("hello", _MODEL_ID, 1024)


def test_embed_credential_failure_can_be_cleared() -> None:
    """Credential failure can be cleared; subsequent calls succeed."""
    client = FakeBedrockClient()
    client.set_credential_failure(True)
    client.set_credential_failure(False)
    result = client.embed("hello", _MODEL_ID, 1024)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Spec 07 — Throttle-retry behaviour
# ---------------------------------------------------------------------------


def test_throttle_on_first_call_succeeds_on_retry() -> None:
    """Fake simulates throttle on first call; second call succeeds."""
    client = FakeBedrockClient()
    client.set_throttle_once()  # type: ignore[attr-defined]
    # After throttle simulation + retry, embed should succeed
    result = client.embed("hello", _MODEL_ID, 1024)
    assert len(result) == 1024


def test_two_consecutive_throttles_raises_error() -> None:
    """Two consecutive throttles → error propagates (retry exhausted)."""
    client = FakeBedrockClient()
    client.set_throttle_count(2)  # type: ignore[attr-defined]
    with pytest.raises(Exception):
        client.embed("hello", _MODEL_ID, 1024)


def test_model_timeout_retried_once() -> None:
    """ModelTimeoutException on first call, succeed on second → embedding returned."""
    client = FakeBedrockClient()
    client.set_timeout_once()  # type: ignore[attr-defined]
    result = client.embed("hello", _MODEL_ID, 1024)
    assert len(result) == 1024


def test_non_transient_error_not_retried() -> None:
    """CredentialError is not retried — propagates immediately."""
    client = FakeBedrockClient()
    client.set_credential_failure(True)
    with pytest.raises(CredentialError):
        client.embed("hello", _MODEL_ID, 1024)
