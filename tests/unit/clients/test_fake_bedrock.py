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
