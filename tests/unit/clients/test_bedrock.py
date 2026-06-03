"""Unit tests for invoke_text_model on BedrockClientImpl and FakeBedrockClient
(Z1 — Cycle D, Red phase).

Tests cover:
- invoke_text_model returns a non-empty string (BedrockClientImpl, mocked boto3)
- Credential error → CredentialError raised
- FakeBedrockClient.invoke_text_model returns a deterministic short string
- invoke_text_model retries once on transient ThrottlingException (M3 fix)
"""

import io
import json

import botocore.exceptions
import pytest

from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.errors import CredentialError

_TEXT_MODEL_ID = "amazon.nova-lite-v1:0"
_PROMPT = "Summarise this artifact in one sentence under 280 characters."


def _nova_lite_response(text: str) -> dict:
    """Build a minimal Amazon Nova Lite invoke_model response body."""
    body_bytes = json.dumps({"output": {"message": {"content": [{"text": text}]}}}).encode()
    return {"body": io.BytesIO(body_bytes)}


# ---------------------------------------------------------------------------
# D1 — invoke_text_model returns a non-empty string
# ---------------------------------------------------------------------------


def test_invoke_text_model_returns_nonempty_string(
    aws_mock: None,
    mocker: pytest.MonkeyPatch,
) -> None:
    """invoke_text_model returns a non-empty string when the model responds normally.

    Red: BedrockClientImpl does not have invoke_text_model yet; the call raises
    AttributeError which pytest marks as FAILED.
    """
    client = BedrockClientImpl(region="us-east-1", profile=None)
    mocker.patch.object(
        client._client,
        "invoke_model",
        return_value=_nova_lite_response("Generated description."),
    )

    result = client.invoke_text_model(_TEXT_MODEL_ID, _PROMPT)

    assert isinstance(result, str), f"Expected str, got {type(result)}"
    assert len(result) > 0, "invoke_text_model must return a non-empty string"


# ---------------------------------------------------------------------------
# D2 — Credential error → CredentialError raised
# ---------------------------------------------------------------------------


def test_invoke_text_model_credential_error_raises(
    aws_mock: None,
    mocker: pytest.MonkeyPatch,
) -> None:
    """invoke_text_model raises CredentialError when boto3 raises an auth error.

    Red: BedrockClientImpl does not have invoke_text_model yet.
    """
    client = BedrockClientImpl(region="us-east-1", profile=None)
    exc = botocore.exceptions.ClientError(
        {"Error": {"Code": "ExpiredTokenException", "Message": "Token expired"}},
        "InvokeModel",
    )
    mocker.patch.object(client._client, "invoke_model", side_effect=exc)

    with pytest.raises(CredentialError):
        client.invoke_text_model(_TEXT_MODEL_ID, _PROMPT)


# ---------------------------------------------------------------------------
# D3 — FakeBedrockClient.invoke_text_model returns a deterministic short string
# ---------------------------------------------------------------------------


def test_fake_bedrock_invoke_text_model_returns_deterministic_string() -> None:
    """FakeBedrockClient.invoke_text_model returns a non-empty, deterministic string.

    The same call must always return the same value so tests that spy on it can
    assert call counts and return values reliably.

    Red: FakeBedrockClient does not have invoke_text_model yet; AttributeError raised.
    """
    client = FakeBedrockClient()

    result = client.invoke_text_model(_TEXT_MODEL_ID, _PROMPT)

    assert isinstance(result, str), f"Expected str, got {type(result)}"
    assert len(result) > 0, "invoke_text_model must return a non-empty string"

    # Deterministic: same prompt always returns the same string
    assert client.invoke_text_model(_TEXT_MODEL_ID, _PROMPT) == result, (
        "FakeBedrockClient.invoke_text_model must be deterministic"
    )


# ---------------------------------------------------------------------------
# D4 — invoke_text_model retries once on ThrottlingException (M3)
# ---------------------------------------------------------------------------


def test_invoke_text_model_retries_once_on_throttling(
    aws_mock: None,
    mocker: pytest.MonkeyPatch,
) -> None:
    """invoke_text_model retries exactly once when boto3 raises ThrottlingException
    on the first attempt and succeeds on the second.

    Verifies:
    - The method returns the successful result (not an exception).
    - boto3 invoke_model is called exactly twice (one throttled, one success).

    Red: invoke_text_model has no retry loop yet; the ThrottlingException propagates
    as a raw ClientError on the first call → FAILED.
    """
    client = BedrockClientImpl(region="us-east-1", profile=None)

    throttle_exc = botocore.exceptions.ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "InvokeModel",
    )
    success_response = _nova_lite_response("Retried successfully.")

    # First call throttles, second call succeeds
    mock_invoke = mocker.patch.object(
        client._client,
        "invoke_model",
        side_effect=[throttle_exc, success_response],
    )
    # Patch sleep so the test does not actually wait
    mocker.patch("cairn_mcp.clients.bedrock.time.sleep")

    result = client.invoke_text_model(_TEXT_MODEL_ID, _PROMPT)

    assert result == "Retried successfully.", f"Expected retry to succeed, got: {result!r}"
    assert mock_invoke.call_count == 2, (
        f"Expected exactly 2 invoke_model calls (1 throttle + 1 success), "
        f"got {mock_invoke.call_count}"
    )
