"""arkeology.tools.health — health_check MCP tool implementation.

Performs independent connectivity probes for each configured component
(S3, S3 Vectors, Bedrock, write prefix, annotation store, read prefixes) and returns a
structured per-component status report. Never raises — all exceptions are
caught and reported as component-level "error" entries.
"""

import asyncio
import functools
import logging
from collections.abc import Callable
from typing import Any

from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ANNOTATION_PROBE_NAME, ErrorCode
from arkeology.errors import CredentialError

logger = logging.getLogger(__name__)


async def _probe(fn: Callable[[], Any]) -> dict[str, Any]:
    """Run a single connectivity probe and map the outcome to a status dict.

    Every probe is a blocking boto3 round trip, so it runs on a worker thread rather
    than the calling event loop — the same offloading every other tool applies to its
    AWS calls.

    Returns ``{"status": "ok"}`` on success, an ``"error"`` dict with
    ``"cause": "credential_error"`` on :class:`CredentialError`, and a plain
    ``"error"`` dict for any other exception. Never raises.

    Args:
        fn: Zero-argument callable performing the probe (return value ignored).

    Returns:
        Status dict for the probed component.
    """
    try:
        await asyncio.to_thread(fn)
        return {"status": "ok"}
    except CredentialError as exc:
        return {"status": "error", "message": str(exc), "cause": ErrorCode.CREDENTIAL_ERROR}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def health_check(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> dict[str, Any]:
    """Probe all configured components and return a per-component status dict.

    Each component is probed independently; failure in one never skips others.
    The function never raises — all exceptions produce an "error" status entry.

    Args:
        settings: Server configuration.
        s3: S3 client.
        vectors: S3 Vectors client.
        bedrock: Bedrock client.

    Returns:
        Dict with keys: "s3", "vectors", "bedrock", "write_prefix", "annotations",
        and one "read_prefix:{prefix}" key per configured read prefix. Each value is
        either ``{"status": "ok"}`` or ``{"status": "error", "message": str}``.
    """
    try:
        return await _health_check_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
        )
    except Exception as exc:
        logger.exception("Unexpected error in health_check")
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


async def _health_check_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> dict[str, Any]:
    """Inner implementation of health_check (separated to enable top-level catch-all)."""
    result: dict[str, Any] = {}

    # ── S3 bucket probe ───────────────────────────────────────────────────────
    result["s3"] = await _probe(lambda: s3.head_bucket(settings.artifact_bucket))

    # ── Vectors index probe ───────────────────────────────────────────────────
    result["vectors"] = await _probe(vectors.describe_index)

    # ── Bedrock embedding probe ───────────────────────────────────────────────
    result["bedrock"] = await _probe(
        lambda: bedrock.embed(
            "health",
            settings.bedrock_embedding_model,
            settings.bedrock_embedding_dimensions,
        )
    )

    # ── Bedrock text model probe (only when BEDROCK_TEXT_MODEL is configured) ─
    if settings.bedrock_text_model is not None:
        text_model = settings.bedrock_text_model
        result["bedrock_text_model"] = await _probe(
            lambda: bedrock.invoke_text_model(text_model, "ping")
        )

    # ── Write prefix probe (put + get + delete) ───────────────────────────────
    # The whole round trip is one probe: it shares _probe's outcome mapping, and the
    # probe_written flag is what lets the object be cleaned up when a step between the
    # put and the delete is the one that failed.
    probe_key = f"{settings.write_prefix}/_arkeology_health_probe"
    probe_written = False

    def _write_prefix_roundtrip() -> None:
        nonlocal probe_written
        s3.put_object(probe_key, "health-probe", {})
        probe_written = True
        s3.get_object(probe_key)
        s3.delete_object(probe_key)
        probe_written = False

    result["write_prefix"] = await _probe(_write_prefix_roundtrip)
    if probe_written:
        try:
            await asyncio.to_thread(s3.delete_object, probe_key)
        except Exception as cleanup_exc:
            logger.warning("Failed to clean up health probe '%s': %s", probe_key, cleanup_exc)

    # ── Annotation store probe ────────────────────────────────────────────────
    # commit_refs and references live in S3 object annotations alone, so an IAM policy
    # edited after startup check 8 passed leaves every link-field read failing while
    # every other component still reports ok. Read-only — it reads an annotation and
    # never writes one — and reported under its own key, because an annotation denial
    # is not a write-permission problem and sends the operator somewhere else entirely.
    # The probe key need not exist: a missing object or annotation (KeyError) still
    # proves the call was permitted, which is the only question being asked. That rests
    # on the principal holding s3:ListBucket over the write prefix — without it real S3
    # masks a missing key with AccessDenied, which maps to AnnotationUnavailableError and
    # would report a healthy annotation store as drifted. Assumed rather than worked
    # around, on two grounds: reconcile_index lists the write prefix, and it is the sole
    # repair path for every failure-log entry, so a principal that cannot list it is an
    # already-broken deployment; and the misreport would be a false alarm, never a false
    # all-clear. Note the moto self-mock does not model the masking, so the green test
    # below is not evidence either way.
    def _annotation_read_probe() -> None:
        try:
            s3.get_object_annotation(probe_key, ANNOTATION_PROBE_NAME)
        except KeyError:
            pass

    result["annotations"] = await _probe(_annotation_read_probe)

    # ── Read prefix probes ────────────────────────────────────────────────────
    for prefix in settings.read_prefixes_list:
        result[f"read_prefix:{prefix}"] = await _probe(functools.partial(s3.list_objects, prefix))

    return result
