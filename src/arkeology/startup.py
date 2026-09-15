"""Startup validation sequence for arkeology.

Performs eight checks in order before the server enters its MCP event loop:
  1. Credential check (via head_bucket on ARTIFACT_BUCKET)
  2. Write prefix access (read + write round-trip using a probe object)
  3. Read prefix access (list_objects, then a get_object + annotation read on one
     listed object, for each entry in READ_PREFIXES)
  4. Vector index existence (describe_index)
  5. Embedding model dimension vs. index dimension (from BEDROCK_EMBEDDING_DIMENSIONS)
  6. Embedding model probe (embeds a short string via bedrock.embed and asserts the
     returned vector's dimension matches — catches a wrong/unentitled embedding model
     that check 5's configuration-only comparison cannot detect)
  7. Text model accessibility (invoke_text_model probe, only when BEDROCK_TEXT_MODEL is set)
  8. S3 object annotation availability + the four annotation IAM actions (put/get/list/
     delete round trip on a probe object) — annotations are the sole durable store for
     commit_refs/references, so a deployment without them refuses to start

All checks use the client interfaces — no direct boto3 calls.
Failures raise StartupValidationError; credential errors propagate as CredentialError.
"""

import logging
from typing import Any

import botocore.exceptions
from ulid import ULID

from arkeology.clients.credentials import _error_code, is_annotation_permission_error
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ANNOTATION_PROBE_NAME
from arkeology.errors import (
    AnnotationUnavailableError,
    CredentialError,
    StartupValidationError,
    VectorIndexNotFoundError,
)

logger = logging.getLogger(__name__)

# Key suffix for the write probe object. Starts with underscore to distinguish from real artifacts.
# A ULID is appended per invocation so two servers starting concurrently
# against the same WRITE_PREFIX never race on the same S3 key.
_PROBE_KEY_SUFFIX = "_arkeology_startup_probe"

# botocore error codes indicating the bucket itself does not exist — distinct from a
# credential/auth failure: a typo'd ARTIFACT_BUCKET is a configuration
# error, not something "aws sso login" can fix.
_BUCKET_NOT_FOUND_CODES = frozenset({"404", "NoSuchBucket", "NotFound"})

# Key suffix and annotation name for the check-8 annotation probe object. Like the write
# probe above it starts with the reserved "_arkeology_" marker (reconcile_index skips any
# key whose final path segment begins with it) and carries a per-invocation ULID.
_ANNOTATION_PROBE_KEY_SUFFIX = "_arkeology_annotation_probe"

# Short probe string embedded during check 6. Content is irrelevant — only the
# returned vector's dimension and the absence of a credential/entitlement failure matter.
_EMBED_PROBE_TEXT = "arkeology startup embedding probe"


def validate_startup(
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> None:
    """Run all eight startup checks in order.

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
    _check_annotations(settings, s3)
    logger.info("Startup validation passed (8/8 checks). arkeology is ready.")


# ── Individual checks ──────────────────────────────────────────────────────────


def _check_credentials(settings: Settings, s3: S3ClientInterface) -> None:
    """Check 1: Verify credentials are valid via head_bucket on ARTIFACT_BUCKET."""
    try:
        s3.head_bucket(settings.artifact_bucket)
        logger.debug("Check 1/8 passed: credentials valid")
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
        code = _error_code(exc)
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
        # Must be re-raised explicitly: without this branch a real GetObject
        # AccessDenied would propagate as a raw ClientError past this function,
        # crashing the process with an unstructured traceback instead of the
        # structured credential error __main__.py reports.
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
    except Exception as exc:
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

    logger.debug("Check 2/8 passed: write prefix '%s' is readable and writable", write_prefix)


def _check_read_prefixes(settings: Settings, s3: S3ClientInterface) -> None:
    """Check 3: Verify read access — object *and* annotation — to each foreign read prefix."""
    read_prefixes = settings.read_prefixes_list

    if not read_prefixes:
        logger.debug("Check 3/8 skipped: no foreign read prefixes configured")
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

        # ListBucket succeeding does not prove GetObject is granted — a
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

            # GetObject says nothing about GetObjectAnnotation, and check 8's round trip
            # probes the write prefix only — so a prefix-scoped policy (the common shape
            # on a shared bucket) granting the annotation actions there and not here
            # passes both and then fails every foreign-scope read, commit_refs and
            # references living in annotations alone. An absent annotation is the
            # expected outcome: it still proves the read was permitted.
            try:
                s3.get_object_annotation(keys[0], ANNOTATION_PROBE_NAME)
            except KeyError:
                pass
            except CredentialError:
                raise
            except AnnotationUnavailableError as exc:
                denial_message = (
                    f"Read prefix access check failed for '{prefix}': read object "
                    f"content but cannot read object annotations (denied on "
                    f"'{keys[0]}'). commit_refs and references are stored in S3 object "
                    "annotations alone, so ensure the IAM policy includes "
                    "s3:GetObjectAnnotation with condition StringLike s3:prefix "
                    f"'{prefix}*' — granting it on the write prefix only leaves every "
                    "foreign-scope read failing at runtime."
                )
                raise StartupValidationError(
                    check="read_prefix",
                    message=(
                        denial_message
                        if _is_annotation_iam_denial(exc)
                        else _annotation_failure_message(settings, exc)
                    ),
                ) from exc
            except Exception as exc:
                raise StartupValidationError(
                    check="read_prefix",
                    message=(
                        f"Read prefix access check failed for '{prefix}': the annotation "
                        f"read on '{keys[0]}' did not complete. Error: {exc}"
                    ),
                ) from exc

    logger.debug("Check 3/8 passed: %d foreign read prefix(es) accessible", len(read_prefixes))


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
        "Check 4/8 passed: vector index '%s' found with dimension %s",
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
        "Check 5/8 passed: BEDROCK_EMBEDDING_DIMENSIONS=%d matches index dimension %d",
        model_dim,
        index_dim,
    )


def _check_embedding_probe(settings: Settings, bedrock: BedrockClientInterface) -> None:
    """Check 6: Embed a short probe string and confirm the model is actually usable.

    Check 5 only compares two *configured* numbers (``BEDROCK_EMBEDDING_DIMENSIONS`` vs.
    the index dimension) — it never calls Bedrock, so a wrong or unentitled embedding
    model still passes it, and every subsequent write/search then fails. This check
    makes one real ``bedrock.embed`` call and asserts the returned
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

    logger.debug("Check 6/8 passed: embedding probe returned dimension %d", len(vector))


def _check_text_model(settings: Settings, bedrock: BedrockClientInterface) -> None:
    """Check 7: When BEDROCK_TEXT_MODEL is configured, probe it with a minimal call.

    When settings.bedrock_text_model is None, this check is skipped entirely.
    """
    if settings.bedrock_text_model is None:
        logger.debug("Check 7/8 skipped: BEDROCK_TEXT_MODEL not configured")
        return

    try:
        bedrock.invoke_text_model(settings.bedrock_text_model, "ping")
        logger.debug(
            "Check 7/8 passed: BEDROCK_TEXT_MODEL '%s' is reachable",
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


def _is_annotation_iam_denial(exc: AnnotationUnavailableError) -> bool:
    """Tell the two ``AnnotationUnavailableError`` causes apart.

    A missing IAM action (an IAM policy edit fixes it) and a region or bucket type that
    does not offer annotations at all (only relocating the bucket fixes it) reach the
    caller as the same exception, with different remedies — reporting one message for
    both sends the operator down the wrong path. Shared by checks 3 and 8, which probe
    different prefixes but face the same two causes.
    """
    return isinstance(
        exc.original, botocore.exceptions.ClientError
    ) and is_annotation_permission_error(exc.original)


def _annotation_failure_message(settings: Settings, exc: AnnotationUnavailableError) -> str:
    """Build the check-8 failure message for the cause the operator must act on."""
    if _is_annotation_iam_denial(exc):
        return (
            "S3 object annotation check failed: bucket "
            f"'{settings.artifact_bucket}' and its region support object annotations, but "
            "the caller's IAM policy is missing one or more of the four required actions "
            "— s3:PutObjectAnnotation, s3:GetObjectAnnotation, s3:ListObjectAnnotations, "
            "s3:DeleteObjectAnnotation. Add the missing action(s) to the deployment's IAM "
            "policy and restart the server."
        )
    return (
        "S3 object annotation check failed: bucket "
        f"'{settings.artifact_bucket}' does not support object annotations — its region "
        "or bucket type is unsupported. No IAM change fixes this: annotations are "
        "unavailable in the UAE and Bahrain regions and on directory buckets (the bucket "
        "type the S3 Express One Zone storage class uses) and Outposts buckets. Move the "
        "artifact bucket to a supported region and bucket type before starting the server."
    )


def _check_annotations(settings: Settings, s3: S3ClientInterface) -> None:
    """Check 8: Verify S3 object annotations work and all four IAM actions are granted.

    Annotations are the sole durable store for ``commit_refs`` / ``references``, so a
    deployment that cannot use them is unsupported rather than degraded — this check
    refuses to start (requirements C-08 and FR-57). The probe writes a throwaway object
    into WRITE_PREFIX and round-trips one annotation through all four operations, so a
    policy granting three of the four actions fails here rather than at first use.
    """
    probe_key = f"{settings.write_prefix}/{_ANNOTATION_PROBE_KEY_SUFFIX}_{ULID()}"
    try:
        s3.put_object(probe_key, "annotation-probe", {})
        s3.put_object_annotation(probe_key, ANNOTATION_PROBE_NAME, "probe")
        s3.get_object_annotation(probe_key, ANNOTATION_PROBE_NAME)
        s3.list_object_annotations(probe_key)
        s3.delete_object_annotation(probe_key, ANNOTATION_PROBE_NAME)
    except CredentialError:
        raise
    except AnnotationUnavailableError as exc:
        raise StartupValidationError(
            check="annotations",
            message=_annotation_failure_message(settings, exc),
        ) from exc
    except Exception as exc:
        raise StartupValidationError(
            check="annotations",
            message=(
                "S3 object annotation check failed: the put/get/list/delete round trip on "
                f"probe object '{probe_key}' did not complete. Annotations are the sole "
                "durable store for commit_refs/references, so the server cannot start "
                f"without them. Error: {exc}"
            ),
        ) from exc
    finally:
        # Unconditional — a failed probe still leaves the object behind, and abandoning
        # the sequence at the first error is exactly what would strand it.
        try:
            s3.delete_object(probe_key)
        except Exception as cleanup_exc:
            logger.warning("Failed to clean up annotation probe '%s': %s", probe_key, cleanup_exc)

    logger.debug("Check 8/8 passed: S3 object annotations available with all four IAM actions")
