"""Concrete Bedrock client implementation using boto3.

Wraps the bedrock-runtime boto3 client to generate text embeddings.
All credential errors are caught and re-raised as CredentialError.
"""

import json
import logging
import time

import boto3
import botocore.exceptions

from cairn_mcp.clients.credentials import is_credential_error
from cairn_mcp.clients.interfaces import BedrockClientInterface  # noqa: F401 (structural only)
from cairn_mcp.errors import CredentialError

logger = logging.getLogger(__name__)

# Transient error codes that warrant a single retry
_TRANSIENT_ERROR_CODES = frozenset(
    {"ThrottlingException", "ModelTimeoutException", "ServiceUnavailableException"}
)

# Sleep duration between attempts for transient errors (seconds)
_RETRY_SLEEP_SECONDS: float = 2.0


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
        for attempt in range(2):
            try:
                response = self._client.invoke_model(
                    modelId=model_id,
                    body=json.dumps(request_body),
                    contentType="application/json",
                    accept="application/json",
                )
                response_body = json.loads(response["body"].read())
                embedding: list[float] = response_body["embedding"]
                return embedding
            except botocore.exceptions.ClientError as exc:
                if is_credential_error(exc):
                    raise CredentialError(
                        message=(
                            "AWS credentials are invalid or expired. "
                            "Re-authenticate (e.g. aws sso login) and restart the server."
                        ),
                        service="bedrock",
                        original=exc,
                    ) from exc
                code = exc.response.get("Error", {}).get("Code", "")
                if code in _TRANSIENT_ERROR_CODES and attempt == 0:
                    logger.warning(
                        "Bedrock transient error %s on attempt 1; retrying after %.1fs",
                        code,
                        _RETRY_SLEEP_SECONDS,
                    )
                    time.sleep(_RETRY_SLEEP_SECONDS)
                    continue
                raise
        # Should not reach here, but satisfies type checker
        raise RuntimeError("Unreachable")
