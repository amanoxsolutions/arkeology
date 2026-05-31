"""Startup validation sequence for cairn-mcp.

Performs five checks in order before the server enters its MCP event loop:
  1. Credential check (via head_bucket on ARTIFACT_BUCKET)
  2. Write prefix access (read + write round-trip using a probe object)
  3. Read prefix access (list_objects on each entry in READ_PREFIXES)
  4. Vector index existence (describe_index)
  5. Embedding model dimension vs. index dimension (from BEDROCK_EMBEDDING_DIMENSIONS)

All checks use the client interfaces — no direct boto3 calls.
Failures raise StartupValidationError; credential errors propagate as CredentialError.
"""

import logging
from typing import Any

from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError, StartupValidationError, VectorIndexNotFoundError

logger = logging.getLogger(__name__)

# Key suffix for the write probe object. Starts with underscore to distinguish from real artifacts.
_PROBE_KEY_SUFFIX = "_cairn_mcp_startup_probe"


def validate_startup(
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> None:
    """Run all five startup checks in order.

    Args:
        settings: Validated server configuration.
        s3: S3 client instance.
        vectors: S3 Vectors client instance.
        bedrock: Bedrock client instance (reserved for future checks).

    Returns:
        None on success.

    Raises:
        StartupValidationError: If any check fails.
        CredentialError: If a credential error occurs during any check.
    """
    _check_credentials(settings, s3)
    _check_write_prefix(settings, s3)
    _check_read_prefixes(settings, s3)
    index_info = _check_vector_index(settings, vectors)
    _check_model_dimension(settings, index_info)
    logger.info("Startup validation passed (5/5 checks). cairn-mcp is ready.")


# ── Individual checks ──────────────────────────────────────────────────────────


def _check_credentials(settings: Settings, s3: S3ClientInterface) -> None:
    """Check 1: Verify credentials are valid via head_bucket on ARTIFACT_BUCKET."""
    try:
        s3.head_bucket(settings.artifact_bucket)
        logger.debug("Check 1/5 passed: credentials valid")
    except CredentialError as exc:
        raise StartupValidationError(
            check="credentials",
            message=(
                "Credential check failed: AWS credentials are invalid or expired. "
                "Re-authenticate (e.g. aws sso login --profile "
                f"{settings.aws_profile or '<profile>'}) and restart the server."
            ),
        ) from exc


def _check_write_prefix(settings: Settings, s3: S3ClientInterface) -> None:
    """Check 2: Verify read and write access to WRITE_PREFIX via a probe object."""
    write_prefix = settings.write_prefix
    probe_key = f"{write_prefix}/{_PROBE_KEY_SUFFIX}"
    bucket = settings.artifact_bucket

    try:
        s3.put_object(probe_key, "startup-probe", {})
    except CredentialError:
        raise
    except Exception as exc:
        raise StartupValidationError(
            check="write_prefix",
            message=(
                f"Write prefix access check failed for '{write_prefix}': "
                "cannot write to this prefix. "
                f"Ensure the IAM policy includes s3:PutObject on "
                f"arn:aws:s3:::{bucket}/{write_prefix}*."
            ),
        ) from exc

    try:
        s3.get_object(probe_key)
    except KeyError as exc:
        raise StartupValidationError(
            check="write_prefix",
            message=(
                f"Write prefix access check failed for '{write_prefix}': "
                "cannot read from this prefix. "
                f"Ensure the IAM policy includes s3:GetObject on "
                f"arn:aws:s3:::{bucket}/{write_prefix}*."
            ),
        ) from exc
    finally:
        # Best-effort cleanup; log a warning rather than raising so the original
        # exception (if any) is not masked.
        try:
            s3.delete_object(probe_key)
        except Exception as cleanup_exc:
            logger.warning("Failed to clean up write probe '%s': %s", probe_key, cleanup_exc)

    logger.debug("Check 2/5 passed: write prefix '%s' is readable and writable", write_prefix)


def _check_read_prefixes(settings: Settings, s3: S3ClientInterface) -> None:
    """Check 3: Verify read access to each foreign read prefix."""
    read_prefixes = settings.read_prefixes_list

    if not read_prefixes:
        logger.debug("Check 3/5 skipped: no foreign read prefixes configured")
        return

    for prefix in read_prefixes:
        try:
            s3.list_objects(prefix)
        except CredentialError:
            raise
        except Exception as exc:
            raise StartupValidationError(
                check="read_prefix",
                message=(
                    f"Read prefix access check failed for '{prefix}': cannot list objects. "
                    "Ensure the IAM policy includes s3:ListBucket with condition "
                    f"StringLike s3:prefix '{prefix}*'."
                ),
            ) from exc

    logger.debug("Check 3/5 passed: %d foreign read prefix(es) accessible", len(read_prefixes))


def _check_vector_index(settings: Settings, vectors: VectorsClientInterface) -> dict[str, Any]:
    """Check 4: Verify the vector index exists via describe_index.

    Returns:
        The index info dict (reused in check 5 to avoid a second describe_index call).

    Raises:
        StartupValidationError: If the index does not exist.
    """
    try:
        index_info = vectors.describe_index()
    except CredentialError:
        raise
    except VectorIndexNotFoundError as exc:
        raise StartupValidationError(
            check="vector_index",
            message=(
                f"Vector index check failed: index '{settings.vectors_index}' "
                f"does not exist in bucket '{settings.vectors_bucket}'. "
                f"Create it with the correct dimension for model "
                f"'{settings.bedrock_embedding_model}' before starting the server."
            ),
        ) from exc
    dim = index_info.get("dimension")
    logger.debug(
        "Check 4/5 passed: vector index '%s' found with dimension %s",
        settings.vectors_index,
        dim,
    )
    return index_info


def _check_model_dimension(
    settings: Settings,
    index_info: dict[str, Any],
) -> None:
    """Check 5: Compare index dimension against BEDROCK_EMBEDDING_DIMENSIONS."""
    raw_dim = index_info.get("dimension")
    if raw_dim is None:
        raise StartupValidationError(
            check="vector_index_dimension",
            message=(
                f"Vector index '{settings.vectors_index}' did not return a dimension. "
                "Check that the index exists and is correctly provisioned."
            ),
        )
    try:
        index_dim = int(raw_dim)
    except (TypeError, ValueError) as exc:
        raise StartupValidationError(
            check="vector_index_dimension",
            message=(
                f"Vector index '{settings.vectors_index}' returned a non-numeric "
                f"dimension value: '{raw_dim}'. Expected an integer."
            ),
        ) from exc
    model_dim = settings.bedrock_embedding_dimensions

    if model_dim != index_dim:
        raise StartupValidationError(
            check="vector_index_dimension",
            message=(
                f"Embedding model dimension mismatch: BEDROCK_EMBEDDING_DIMENSIONS is "
                f"{model_dim} but index '{settings.vectors_index}' "
                f"expects {index_dim} dimensions. "
                f"Either recreate the index with dimension {model_dim}, "
                f"or set BEDROCK_EMBEDDING_DIMENSIONS={index_dim} to match the index."
            ),
        )

    logger.debug(
        "Check 5/5 passed: BEDROCK_EMBEDDING_DIMENSIONS=%d matches index dimension %d",
        model_dim,
        index_dim,
    )
