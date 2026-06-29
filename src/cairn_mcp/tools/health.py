"""cairn_mcp.tools.health — health_check MCP tool implementation.

Performs independent connectivity probes for each configured component
(S3, S3 Vectors, Bedrock, write prefix, read prefixes) and returns a
structured per-component status report. Never raises — all exceptions are
caught and reported as component-level "error" entries.
"""

import functools
import logging
from collections.abc import Callable
from typing import Any

from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.constants import ErrorCode
from cairn_mcp.errors import CredentialError

logger = logging.getLogger(__name__)


def _probe(fn: Callable[[], Any]) -> dict[str, Any]:
    """Run a single connectivity probe and map the outcome to a status dict.

    Returns ``{"status": "ok"}`` on success, an ``"error"`` dict with
    ``"cause": "credential_error"`` on :class:`CredentialError`, and a plain
    ``"error"`` dict for any other exception. Never raises.

    Args:
        fn: Zero-argument callable performing the probe (return value ignored).

    Returns:
        Status dict for the probed component.
    """
    try:
        fn()
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
        Dict with keys: "s3", "vectors", "bedrock", "write_prefix", and one
        "read_prefix:{prefix}" key per configured read prefix. Each value is
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
    result["s3"] = _probe(lambda: s3.head_bucket(settings.artifact_bucket))

    # ── Vectors index probe ───────────────────────────────────────────────────
    result["vectors"] = _probe(vectors.describe_index)

    # ── Bedrock embedding probe ───────────────────────────────────────────────
    result["bedrock"] = _probe(
        lambda: bedrock.embed(
            "health",
            settings.bedrock_embedding_model,
            settings.bedrock_embedding_dimensions,
        )
    )

    # ── Bedrock text model probe (only when BEDROCK_TEXT_MODEL is configured) ─
    if settings.bedrock_text_model is not None:
        text_model = settings.bedrock_text_model
        result["bedrock_text_model"] = _probe(lambda: bedrock.invoke_text_model(text_model, "ping"))

    # ── Write prefix probe (put + get + delete) ───────────────────────────────
    probe_key = f"{settings.write_prefix}/_cairn_health_probe"
    probe_written = False
    try:
        s3.put_object(probe_key, "health-probe", {})
        probe_written = True
        s3.get_object(probe_key)
        s3.delete_object(probe_key)
        probe_written = False
        result["write_prefix"] = {"status": "ok"}
    except CredentialError as exc:
        result["write_prefix"] = {
            "status": "error",
            "message": str(exc),
            "cause": ErrorCode.CREDENTIAL_ERROR,
        }
    except Exception as exc:
        result["write_prefix"] = {"status": "error", "message": str(exc)}
    finally:
        if probe_written:
            try:
                s3.delete_object(probe_key)
            except Exception as cleanup_exc:
                logger.warning("Failed to clean up health probe '%s': %s", probe_key, cleanup_exc)

    # ── Read prefix probes ────────────────────────────────────────────────────
    for prefix in settings.read_prefixes_list:
        result[f"read_prefix:{prefix}"] = _probe(functools.partial(s3.list_objects, prefix))

    return result
