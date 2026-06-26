"""cairn_mcp.tools.health — health_check MCP tool implementation.

Performs independent connectivity probes for each configured component
(S3, S3 Vectors, Bedrock, write prefix, read prefixes) and returns a
structured per-component status report. Never raises — all exceptions are
caught and reported as component-level "error" entries.
"""

import logging
from typing import Any

from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError

logger = logging.getLogger(__name__)


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
        return {"error": "internal_error", "message": str(exc)}


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
    try:
        s3.head_bucket(settings.artifact_bucket)
        result["s3"] = {"status": "ok"}
    except CredentialError as exc:
        result["s3"] = {"status": "error", "message": str(exc), "cause": "credential_error"}
    except Exception as exc:
        result["s3"] = {"status": "error", "message": str(exc)}

    # ── Vectors index probe ───────────────────────────────────────────────────
    try:
        vectors.describe_index()
        result["vectors"] = {"status": "ok"}
    except CredentialError as exc:
        result["vectors"] = {"status": "error", "message": str(exc), "cause": "credential_error"}
    except Exception as exc:
        result["vectors"] = {"status": "error", "message": str(exc)}

    # ── Bedrock embedding probe ───────────────────────────────────────────────
    try:
        bedrock.embed(
            "health",
            settings.bedrock_embedding_model,
            settings.bedrock_embedding_dimensions,
        )
        result["bedrock"] = {"status": "ok"}
    except CredentialError as exc:
        result["bedrock"] = {"status": "error", "message": str(exc), "cause": "credential_error"}
    except Exception as exc:
        result["bedrock"] = {"status": "error", "message": str(exc)}

    # ── Bedrock text model probe (only when BEDROCK_TEXT_MODEL is configured) ─
    if settings.bedrock_text_model is not None:
        try:
            bedrock.invoke_text_model(settings.bedrock_text_model, "ping")
            result["bedrock_text_model"] = {"status": "ok"}
        except CredentialError as exc:
            result["bedrock_text_model"] = {
                "status": "error",
                "message": str(exc),
                "cause": "credential_error",
            }
        except Exception as exc:
            result["bedrock_text_model"] = {"status": "error", "message": str(exc)}

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
            "cause": "credential_error",
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
        key = f"read_prefix:{prefix}"
        try:
            s3.list_objects(prefix)
            result[key] = {"status": "ok"}
        except CredentialError as exc:
            result[key] = {
                "status": "error",
                "message": str(exc),
                "cause": "credential_error",
            }
        except Exception as exc:
            result[key] = {"status": "error", "message": str(exc)}

    return result
