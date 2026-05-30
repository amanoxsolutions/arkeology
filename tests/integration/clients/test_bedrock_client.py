"""Integration tests for BedrockClientImpl.

Requires real AWS credentials and Bedrock model access.
Run with: uv run pytest -m integration tests/integration/clients/test_bedrock_client.py

Environment variables required:
    AWS_REGION  — AWS region with Bedrock enabled
    AWS_PROFILE — (optional) named AWS profile

Integration checkpoint: document actual response shape (field names) in plan.md.
"""

import os

import pytest

from cairn_mcp.clients.bedrock import BedrockClientImpl

pytestmark = pytest.mark.integration

_TITAN_MODEL = "amazon.titan-embed-text-v2:0"


@pytest.fixture
def bedrock_client() -> BedrockClientImpl:
    region = os.environ["AWS_REGION"]
    profile = os.environ.get("AWS_PROFILE")
    return BedrockClientImpl(region=region, profile=profile)


def test_embed_returns_vector_of_expected_length(bedrock_client: BedrockClientImpl) -> None:
    """embed returns a vector of the expected length for Titan Text Embeddings v2.

    Integration checkpoint: document the actual response JSON shape in plan.md.
    """
    result = bedrock_client.embed("hello world", _TITAN_MODEL, 1024)
    # Titan v2 default dimension is 1024
    assert len(result) == 1024
    assert all(isinstance(v, float) for v in result)


def test_embed_is_not_all_zeros(bedrock_client: BedrockClientImpl) -> None:
    """embed result is not a zero vector — confirms the model returned real data."""
    result = bedrock_client.embed("test text for embedding", _TITAN_MODEL, 1024)
    assert any(v != 0.0 for v in result)


def test_embed_different_inputs_differ(bedrock_client: BedrockClientImpl) -> None:
    """Different inputs produce different embeddings."""
    v1 = bedrock_client.embed("authentication and JWT tokens", _TITAN_MODEL, 1024)
    v2 = bedrock_client.embed("database schema migrations", _TITAN_MODEL, 1024)
    assert v1 != v2
