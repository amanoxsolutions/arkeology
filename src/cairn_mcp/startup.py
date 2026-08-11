"""Startup validation sequence for cairn-mcp.

Performs seven checks in order before the server enters its MCP event loop:
  1. Credential check (via head_bucket on ARTIFACT_BUCKET)
  2. Write prefix access (read + write round-trip using a probe object)
  3. Read prefix access (list_objects on each entry in READ_PREFIXES)
  4. Vector index existence (describe_index)
  5. Embedding model dimension vs. index dimension (from BEDROCK_EMBEDDING_DIMENSIONS)
  6. Embedding model probe (embeds a short string via bedrock.embed and asserts the
     returned vector's dimension matches — catches a wrong/unentitled embedding model
     that check 5's configuration-only comparison cannot detect; Phase 12 review M-9)
  7. Text model accessibility (invoke_text_model probe, only when BEDROCK_TEXT_MODEL is set)

All checks use the client interfaces — no direct boto3 calls.
Failures raise StartupValidationError; credential errors propagate as CredentialError.
"""

import logging
from typing import Any

import botocore.exceptions
from ulid import ULID

from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError, StartupValidationError, VectorIndexNotFoundError

logger = logging.getLogger(__name__)

# Key suffix for the write probe object. Starts with underscore to distinguish from real artifacts.
# A ULID is appended per invocation (07-02 #9) so two servers starting concurrently
# against the same WRITE_PREFIX never race on the same S3 key.
_PROBE_KEY_SUFFIX = "_cairn_mcp_startup_probe"

# botocore error codes indicating the bucket itself does not exist — distinct from a
# credential/auth failure (07-02 #11): a typo'd ARTIFACT_BUCKET is a configuration
# error, not something "aws sso login" can fix.
_BUCKET_NOT_FOUND_CODES = frozenset({"404", "NoSuchBucket", "NotFound"})

# Short probe string embedded during check 6 (M-9). Content is irrelevant — only the
# returned vector's dimension and the absence of a credential/entitlement failure matter.
_EMBED_PROBE_TEXT = "cairn-mcp startup embedding probe"


def validate_startup(
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> None:
    """Run all seven startup checks in order.

    Args:
        settings: Validated server configuration.
        s3: S3 client instance.
        vectors: S3 Vectors client instance.
        bedrock: Bedrock client instance (used for checks 6 and 7).

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
    _check_embedding_probe(settings, bedrock)
    _check_text_model(settings, bedrock)
    logger.info("Startup validation passed (7/7 checks). cairn-mcp is ready.")


# ── Individual checks ──────────────────────────────────────────────────────────


def _check_credentials(settings: Settings, s3: S3ClientInterface) -> None:
    """Check 1: Verify credentials are valid via head_bucket on ARTIFACT_BUCKET."""
    try:
        s3.head_bucket(settings.artifact_bucket)
        logger.debug("Check 1/7 passed: credentials valid")
    except CredentialError as exc:
        raise StartupValidationError(
            check="credentials",
            message=(
                "Credential check failed: AWS credentials are invalid or expired. "
                "Re-authenticate (e.g. aws sso login --profile "
                f"{settings.aws_profile or '<profile>'}) and restart the server."
            ),
        ) from exc
    except botocore.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in _BUCKET_NOT_FOUND_CODES:
            raise StartupValidationError(
                check="credentials",
                message=(
                    f"Bucket check failed: ARTIFACT_BUCKET '{settings.artifact_bucket}' "
                    "does not exist (or is not visible in this region). This is a "
                    "configuration error, not a credentials problem — verify the "
                    "bucket name and AWS_REGION are correct."
                ),
            ) from exc
        raise StartupValidationError(
            check="credentials",
            message=f"Credential check failed: {exc}",
        ) from exc
    except Exception as exc:
        raise StartupValidationError(
            check="credentials",
            message=f"Credential check failed: {exc}",
        ) from exc


def _check_write_prefix(settings: Settings, s3: S3ClientInterface) -> None:
    """Check 2: Verify read and write access to WRITE_PREFIX via a probe object."""
    write_prefix = settings.write_prefix
    probe_key = f"{write_prefix}/{_PROBE_KEY_SUFFIX}_{ULID()}"
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
    except CredentialError:
        # M-7: previously uncaught here — a real GetObject AccessDenied propagated as a
        # raw ClientError past this function (only KeyError was handled), crashing the
        # process with an unstructured traceback instead of the structured credential
        # error __main__.py already knows how to report.
        raise
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

    logger.debug("Check 2/7 passed: write prefix '%s' is readable and writable", write_prefix)


def _check_read_prefixes(settings: Settings, s3: S3ClientInterface) -> None:
    """Check 3: Verify read access to each foreign read prefix."""
    read_prefixes = settings.read_prefixes_list

    if not read_prefixes:
        logger.debug("Check 3/7 skipped: no foreign read prefixes configured")
        return

    for prefix in read_prefixes:
        try:
            keys = s3.list_objects(prefix)
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

        # 07-02 #10: ListBucket succeeding does not prove GetObject is granted — a
        # policy can allow listing a prefix while denying reads on its objects, which
        # would only surface later as a read_artifact failure. Probe actual object
        # read access on one listed key (if any exist yet).
        if keys:
            try:
                s3.head_object(keys[0])
            except CredentialError:
                raise
            except KeyError:
                # Listed a moment ago but now gone (race) — not a permission problem.
                continue
            except Exception as exc:
                raise StartupValidationError(
                    check="read_prefix",
                    message=(
                        f"Read prefix access check failed for '{prefix}': listed "
                        f"objects but cannot read object content (denied on "
                        f"'{keys[0]}'). Ensure the IAM policy includes s3:GetObject "
                        f"with condition StringLike s3:prefix '{prefix}*'."
                    ),
                ) from exc

    logger.debug("Check 3/7 passed: %d foreign read prefix(es) accessible", len(read_prefixes))


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
    except Exception as exc:
        raise StartupValidationError(
            check="vector_index",
            message=f"Vector index check failed: {exc}",
        ) from exc
    dim = index_info.get("dimension")
    logger.debug(
        "Check 4/7 passed: vector index '%s' found with dimension %s",
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
        "Check 5/7 passed: BEDROCK_EMBEDDING_DIMENSIONS=%d matches index dimension %d",
        model_dim,
        index_dim,
    )


def _check_embedding_probe(settings: Settings, bedrock: BedrockClientInterface) -> None:
    """Check 6: Embed a short probe string and confirm the model is actually usable.

    Check 5 only compares two *configured* numbers (``BEDROCK_EMBEDDING_DIMENSIONS`` vs.
    the index dimension) — it never calls Bedrock, so a wrong or unentitled embedding
    model still passes it, and every subsequent write/search then fails (Phase 12 review
    M-9). This check makes one real ``bedrock.embed`` call and asserts the returned
    vector's length matches ``BEDROCK_EMBEDDING_DIMENSIONS`` (already confirmed equal to
    the index dimension by check 5).
    """
    try:
        vector = bedrock.embed(
            _EMBED_PROBE_TEXT,
            settings.bedrock_embedding_model,
            settings.bedrock_embedding_dimensions,
        )
    except CredentialError:
        raise
    except Exception as exc:
        raise StartupValidationError(
            check="embedding_probe",
            message=(
                f"Embedding probe failed: BEDROCK_EMBEDDING_MODEL "
                f"'{settings.bedrock_embedding_model}' could not be invoked. "
                "Verify the model ID is correct, the IAM policy includes "
                "bedrock:InvokeModel for this model, and the account/region is entitled "
                f"to use it. Error: {exc}"
            ),
        ) from exc

    if len(vector) != settings.bedrock_embedding_dimensions:
        raise StartupValidationError(
            check="embedding_probe",
            message=(
                f"Embedding probe returned a vector of dimension {len(vector)}, but "
                f"BEDROCK_EMBEDDING_DIMENSIONS is {settings.bedrock_embedding_dimensions}. "
                f"Verify that model '{settings.bedrock_embedding_model}' actually supports "
                "this dimension."
            ),
        )

    logger.debug("Check 6/7 passed: embedding probe returned dimension %d", len(vector))


def _check_text_model(settings: Settings, bedrock: BedrockClientInterface) -> None:
    """Check 7: When BEDROCK_TEXT_MODEL is configured, probe it with a minimal call.

    When settings.bedrock_text_model is None, this check is skipped entirely.
    """
    if settings.bedrock_text_model is None:
        logger.debug("Check 7/7 skipped: BEDROCK_TEXT_MODEL not configured")
        return

    try:
        bedrock.invoke_text_model(settings.bedrock_text_model, "ping")
        logger.debug(
            "Check 7/7 passed: BEDROCK_TEXT_MODEL '%s' is reachable",
            settings.bedrock_text_model,
        )
    except CredentialError:
        raise
    except Exception as exc:
        raise StartupValidationError(
            check="bedrock_text_model",
            message=(
                f"Text model startup check failed: BEDROCK_TEXT_MODEL "
                f"'{settings.bedrock_text_model}' is unreachable. "
                f"Verify the model ID is correct and the IAM policy includes "
                f"bedrock:InvokeModel for this model. Error: {exc}"
            ),
        ) from exc
