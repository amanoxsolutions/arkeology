"""Concrete Bedrock client implementation using boto3.

Wraps the bedrock-runtime boto3 client to generate text embeddings.
All credential errors are caught and re-raised as CredentialError.
"""

import json
import logging
import random
import time
from collections.abc import Callable
from typing import Any

import boto3
import botocore.exceptions

from cairn_mcp.clients.credentials import wrap_credential_errors
from cairn_mcp.clients.interfaces import BedrockClientInterface  # noqa: F401 (structural only)

logger = logging.getLogger(__name__)

# Transient error codes that warrant a single retry
_TRANSIENT_ERROR_CODES = frozenset(
    {"ThrottlingException", "ModelTimeoutException", "ServiceUnavailableException"}
)

# Sleep duration between attempts for transient errors (seconds)
_RETRY_SLEEP_SECONDS: float = 2.0

# M-8 (Phase 12 review): embed()/invoke_text_model() are synchronous Protocol methods
# (BedrockClientInterface) — making the retry sleep below `await asyncio.sleep(...)`
# would require turning both methods (and the interface, every concrete/fake
# implementation, and every direct caller — startup.py, health.py) into coroutines, far
# beyond a surgical fix. Instead, the guarantee that this blocking `time.sleep` (and the
# blocking `invoke_model` call itself) never freezes the asyncio event loop is provided
# by every async caller: search.py, synthesise.py, and reconcile.py route their
# embed()/invoke_text_model() calls through `asyncio.to_thread`, and write.py routes
# them through its bounded `_EMBED_EXECUTOR` — the entire synchronous call, retry sleep
# included, runs on a worker thread, never on the event-loop thread. startup.py calls
# these methods directly, but synchronously before the event loop starts. health.py's
# direct (non-offloaded) calls are a known, separately-tracked gap — out of scope for
# this cluster, which covers only search/read/list/reconcile/freshness (M-8 acceptance).


class BedrockClientImpl:
    """boto3-backed Bedrock embeddings client.

    Args:
        region: AWS region name where Bedrock is enabled.
        profile: Optional named AWS profile; if None, uses the default credential chain.
    """

    def __init__(self, region: str, profile: str | None) -> None:
        if profile is not None:
            session = boto3.Session(profile_name=profile, region_name=region)
        else:
            session = boto3.Session(region_name=region)
        self._client = session.client("bedrock-runtime")

    def _invoke(
        self,
        model_id: str,
        request_body: dict[str, Any],
        extract: Callable[[dict[str, Any]], Any],
    ) -> Any:
        """Invoke a Bedrock model with one transient-error retry.

        Wraps ``invoke_model`` with the shared retry/credential semantics used by
        both ``embed`` and ``invoke_text_model``: credential errors surface as
        ``CredentialError`` (via ``wrap_credential_errors``); transient errors
        (throttle/timeout/unavailable) are retried exactly once after a jittered
        sleep; all other errors propagate unchanged. ``extract`` maps the parsed
        response body to the value the caller wants.
        """
        with wrap_credential_errors("bedrock"):
            for attempt in range(2):
                try:
                    response = self._client.invoke_model(
                        modelId=model_id,
                        body=json.dumps(request_body),
                        contentType="application/json",
                        accept="application/json",
                    )
                    response_body = json.loads(response["body"].read())
                    return extract(response_body)
                except botocore.exceptions.ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code in _TRANSIENT_ERROR_CODES and attempt == 0:
                        logger.warning(
                            "Bedrock transient error %s on attempt 1; retrying after %.1fs",
                            code,
                            _RETRY_SLEEP_SECONDS,
                        )
                        time.sleep(_RETRY_SLEEP_SECONDS + random.uniform(0, 1))
                        continue
                    raise

    def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
        """Generate a text embedding using the specified Bedrock model.

        For Titan Text Embeddings v2, the request body is:
            {"inputText": text, "dimensions": dimensions}
        The response body contains:
            {"embedding": [...], "inputTextTokenCount": N}

        Args:
            text: Input text to embed.
            model_id: Bedrock model identifier (e.g. "amazon.titan-embed-text-v2:0").
            dimensions: Desired output dimension. Must match the S3 Vectors index
                dimension. For Titan v2 the supported values are 256, 512, or 1024.

        Returns:
            Embedding vector as a list of floats of length ``dimensions``.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """
        logger.debug(
            "Bedrock embed model_id=%s dimensions=%d text_len=%d",
            model_id,
            dimensions,
            len(text),
        )
        request_body: dict[str, str | int] = {"inputText": text, "dimensions": dimensions}
        embedding: list[float] = self._invoke(
            model_id, request_body, lambda body: body["embedding"]
        )
        return embedding

    def invoke_text_model(self, model_id: str, prompt: str) -> str:
        """Invoke a Bedrock text generation model and return the response text.

        Uses the Amazon Nova Lite / Nova cross-region inference profile request/response shape:
          Request body:  {"messages": [{"role": "user", "content": [{"text": prompt}]}],
                          "inferenceConfig": {"maxTokens": 300}}
          Response:      response["output"]["message"]["content"][0]["text"]

        Note: the ``"type"`` key is intentionally omitted from the content dict — cross-region
        inference profiles (e.g. ``eu.amazon.nova-lite-v1:0``) reject it with a validation
        error. Omitting it is also valid for on-demand Nova invocations in ``us-east-1``.

        Retries once on transient errors (ThrottlingException, ModelTimeoutException,
        ServiceUnavailableException), matching the retry behaviour of ``embed``.

        Args:
            model_id: Bedrock model identifier (e.g. "amazon.nova-lite-v1:0").
            prompt: User prompt text.

        Returns:
            Generated text as a string.

        Raises:
            CredentialError: If credentials are invalid or expired.
        """
        logger.debug("Bedrock invoke_text_model model_id=%s prompt_len=%d", model_id, len(prompt))
        request_body = {
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": 300},
        }
        text: str = self._invoke(
            model_id,
            request_body,
            lambda body: body["output"]["message"]["content"][0]["text"],
        )
        return text
