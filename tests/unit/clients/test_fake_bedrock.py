"""Unit tests for FakeBedrockClient — full interface coverage.

Also contains T27 retry-jitter tests for BedrockClientImpl, which live here
because they test the client layer in isolation alongside the fake.
"""

import io
import json

import botocore.exceptions
import pytest

from arkeology.clients.bedrock import _RETRY_SLEEP_SECONDS, BedrockClientImpl
from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.errors import CredentialError

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


def test_embed_returns_a_vector_of_the_requested_length() -> None:
    """``dimensions`` is a required argument to ``embed`` and is the only thing that
    determines the returned vector's length.

    There is no client-level default to fall back on: ``FakeBedrockClient()`` takes no
    constructor arguments, matching ``BedrockClientInterface.embed``, where the real
    client also derives length from the per-call ``dimensions`` value. These two cases
    previously read as "default" vs "custom" dimension, which described a constructor
    parameter that was assigned and never used.
    """
    client = FakeBedrockClient()
    for dimensions in (8, 512, 1024, 2048):
        result = client.embed("hello", _MODEL_ID, dimensions)
        assert len(result) == dimensions, f"dimensions={dimensions}"


# ---------------------------------------------------------------------------
# Spec 07 — Throttle-retry behaviour
# ---------------------------------------------------------------------------


def test_throttle_on_first_call_succeeds_on_retry() -> None:
    """Fake simulates throttle on first call; second call succeeds."""
    client = FakeBedrockClient()
    client.set_throttle_count(1)  # type: ignore[attr-defined]
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
    client.set_timeout_count(1)  # type: ignore[attr-defined]
    result = client.embed("hello", _MODEL_ID, 1024)
    assert len(result) == 1024


def test_non_transient_error_not_retried(mocker: pytest.MonkeyPatch) -> None:
    """A non-transient error (e.g. CredentialError) is not retried — the retry loop
    only catches ThrottlingError/ModelTimeoutError, so it propagates immediately."""
    client = FakeBedrockClient()
    mocker.patch.object(
        client,
        "_do_embed",
        side_effect=CredentialError("simulated", "bedrock", Exception("simulated")),
    )
    with pytest.raises(CredentialError):
        client.embed("hello", _MODEL_ID, 1024)


# ---------------------------------------------------------------------------
# T27 — BedrockClientImpl retry sleep jitter
# ---------------------------------------------------------------------------


def _make_throttle_exc() -> botocore.exceptions.ClientError:
    """Build a ThrottlingException ClientError matching what Bedrock raises."""
    return botocore.exceptions.ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "InvokeModel",
    )


def _make_good_invoke_response(embedding: list[float]) -> dict:
    """Build a minimal Bedrock invoke_model response dict."""
    body_bytes = json.dumps({"embedding": embedding}).encode()
    return {"body": io.BytesIO(body_bytes)}


def test_retry_sleep_includes_jitter(
    aws_mock: None,
    mocker: pytest.MonkeyPatch,
) -> None:
    """BedrockClientImpl sleep duration on throttle retry equals _RETRY_SLEEP_SECONDS + jitter.

    Verifies that the retry sleep uses random.uniform so the jitter is included.
    """
    # Arrange
    client = BedrockClientImpl(region="us-east-1", profile=None)
    embedding = [0.1] * 1024

    call_count = 0

    def invoke_side_effect(**kwargs: object) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_throttle_exc()
        return _make_good_invoke_response(embedding)

    mocker.patch.object(client._client, "invoke_model", side_effect=invoke_side_effect)
    # Patch random.uniform in bedrock module to return a known jitter value
    mocker.patch("arkeology.clients.bedrock.random.uniform", return_value=0.5)
    sleep_mock = mocker.patch("arkeology.clients.bedrock.time.sleep")

    # Act
    result = client.embed("hello", _MODEL_ID, 1024)

    # Assert
    assert len(result) == 1024
    sleep_mock.assert_called_once_with(_RETRY_SLEEP_SECONDS + 0.5)


def test_retry_sleep_jitter_varies(
    aws_mock: None,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Consecutive retry sleeps produce different durations (live jitter, not a constant).

    This is a probabilistic guard: if jitter is truly random, two independent
    sleep durations will almost certainly differ. If sleep is always called with
    the same constant, both will be equal and the test fails.
    """
    # Arrange
    client = BedrockClientImpl(region="us-east-1", profile=None)
    embedding = [0.1] * 1024

    invoke_call_count = 0

    def invoke_side_effect(**kwargs: object) -> dict:
        nonlocal invoke_call_count
        invoke_call_count += 1
        # Throttle on 1st and 3rd invoke calls; succeed on 2nd and 4th
        if invoke_call_count in (1, 3):
            raise _make_throttle_exc()
        return _make_good_invoke_response(embedding)

    mocker.patch.object(client._client, "invoke_model", side_effect=invoke_side_effect)

    sleep_durations: list[float] = []

    def capture_sleep(duration: float) -> None:
        sleep_durations.append(duration)

    mocker.patch("arkeology.clients.bedrock.time.sleep", side_effect=capture_sleep)

    # Act — two separate embed calls, each with a throttle on first attempt
    client.embed("hello world", _MODEL_ID, 1024)
    client.embed("different text entirely", _MODEL_ID, 1024)

    # Assert — both calls should have slept, and the durations should differ
    assert len(sleep_durations) == 2
    # Jitter from random.uniform should make the two values different (probabilistic)
    assert sleep_durations[0] != sleep_durations[1]
