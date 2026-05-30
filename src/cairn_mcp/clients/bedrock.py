"""Concrete Bedrock client implementation using boto3.

Wraps the bedrock-runtime boto3 client to generate text embeddings.
All credential errors are caught and re-raised as CredentialError.
"""

import json
import logging
from typing import Any

import boto3
import botocore.exceptions

from cairn_mcp.clients.credentials import is_credential_error
from cairn_mcp.clients.interfaces import BedrockClientInterface
from cairn_mcp.errors import CredentialError

logger = logging.getLogger(__name__)


class BedrockClientImpl(BedrockClientInterface):
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
        request_body: dict[str, Any] = {"inputText": text, "dimensions": dimensions}
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
            raise
