"""cairn_mcp.tools.migrate_artifacts — bulk migration MCP tool with Nova Lite enrichment.

Accepts a list of artifact descriptors where ``description`` is optional. For any
descriptor missing a description, Nova Lite (BEDROCK_TEXT_MODEL) is called to
generate one. All descriptions are clipped to 280 characters. In dry_run mode the
enriched descriptor list is returned without any writes. In live mode, the enriched
descriptors are handed to write_artifacts for concurrent bulk write.

The caller-supplied ``artifact_concurrency`` parameter (default 3, range [1, 15])
controls both the Nova Lite description semaphore (enrichment phase) and is forwarded
to write_artifacts for the write semaphore (live phase). Out-of-range values are
clamped silently with a top-level ``"warning"`` field in the response.

Note: A compound artifact_concurrency × section_concurrency ≤ ceiling validation
is intentionally absent from this task; it is noted here as a future concern.
"""

import asyncio
import logging
from typing import Any

from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.tools.write_artifacts import write_artifacts as _write_artifacts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Nova Lite prompt constant — hardcoded and visible for easy review/editing.
# The prompt is intentionally concise: it asks for a single-sentence summary
# under 280 characters so the output fits the description field without
# further truncation in the common case. Clipping to 280 is still applied
# regardless, as the model may not perfectly honour the length constraint.
# ---------------------------------------------------------------------------
_DESCRIPTION_PROMPT = (
    "You are a documentation assistant. Read the artifact title and content below "
    "and write a single-sentence description that summarises what this artifact is "
    "about. The description must be under 280 characters, plain text, no markdown.\n\n"
    "Title: {title}\n\nContent:\n{content}"
)

_MAX_DESCRIPTION_LENGTH = 280
_ARTIFACT_CONCURRENCY_DEFAULT: int = 3
_ARTIFACT_CONCURRENCY_MAX: int = 15


def _clip_description(description: str, title: str) -> str:
    """Clip description to _MAX_DESCRIPTION_LENGTH and log at DEBUG if clipped."""
    if len(description) > _MAX_DESCRIPTION_LENGTH:
        clipped = description[:_MAX_DESCRIPTION_LENGTH]
        logger.debug(
            "Description for '%s' clipped from %d to %d chars",
            title,
            len(description),
            _MAX_DESCRIPTION_LENGTH,
        )
        return clipped
    return description


async def migrate_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    descriptors: list[dict[str, Any]],
    dry_run: bool = True,
    artifact_concurrency: int = _ARTIFACT_CONCURRENCY_DEFAULT,
) -> dict[str, Any]:
    """Migrate a list of artifact descriptors, generating missing descriptions via Nova Lite.

    Args:
        settings: Server configuration.
        s3: S3 client for content storage.
        vectors: S3 Vectors client for semantic index.
        bedrock: Bedrock client (used for both embeddings and text generation).
        descriptors: List of artifact descriptor dicts. ``description`` is optional;
            missing descriptions are generated via BEDROCK_TEXT_MODEL.
        dry_run: When True, enrich descriptors and return them without writing to S3
            or S3 Vectors. When False, enrich and then delegate to write_artifacts.
        artifact_concurrency: Maximum number of artifacts / Nova Lite calls processed
            concurrently. Must be in [1, 15]. Values > 15 are capped to 15 (with a
            warning). Values < 1 are substituted with the default 3 (with a warning).
            Out-of-range values are never an error. Defaults to 3.

    Returns:
        ``dry_run=True``:  ``{"descriptors": [...]}`` — enriched descriptor list.
        ``dry_run=False``: ``{"results": [...]}`` — per-artifact write results from
            write_artifacts.
        When ``artifact_concurrency`` is out of range, a top-level ``"warning"`` key
        is included in the response.
    """
    try:
        return await _migrate_artifacts_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            descriptors=descriptors,
            dry_run=dry_run,
            artifact_concurrency=artifact_concurrency,
        )
    except Exception as exc:
        logger.exception("Unexpected error in migrate_artifacts")
        return {"error": "internal_error", "message": str(exc)}


async def _migrate_artifacts_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    descriptors: list[dict[str, Any]],
    dry_run: bool,
    artifact_concurrency: int = _ARTIFACT_CONCURRENCY_DEFAULT,
) -> dict[str, Any]:
    """Inner implementation: enrich descriptions, then write or return."""
    # ── Clamp artifact_concurrency to [1, 15] ────────────────────────────────
    warning: str | None = None
    if artifact_concurrency > _ARTIFACT_CONCURRENCY_MAX:
        warning = (
            f"artifact_concurrency={artifact_concurrency} exceeds the maximum of "
            f"{_ARTIFACT_CONCURRENCY_MAX}; effective concurrency capped to "
            f"{_ARTIFACT_CONCURRENCY_MAX}."
        )
        effective = _ARTIFACT_CONCURRENCY_MAX
    elif artifact_concurrency < 1:
        warning = (
            f"artifact_concurrency={artifact_concurrency} is below the minimum of 1; "
            f"effective concurrency substituted with the default "
            f"{_ARTIFACT_CONCURRENCY_DEFAULT}."
        )
        effective = _ARTIFACT_CONCURRENCY_DEFAULT
    else:
        effective = artifact_concurrency

    # Defensive copy — never mutate the caller's list
    descriptors = [dict(d) for d in descriptors]

    # ── Guard: BEDROCK_TEXT_MODEL must be configured when any description is missing ──
    missing_indices = [i for i, d in enumerate(descriptors) if not d.get("description")]
    if missing_indices and not settings.bedrock_text_model:
        return {
            "error": "configuration_error",
            "message": (
                "BEDROCK_TEXT_MODEL is not configured. "
                "Set it to use migrate_artifacts with missing descriptions."
            ),
        }

    # ── Step 2: generate missing descriptions concurrently ────────────────────
    if missing_indices:
        semaphore = asyncio.Semaphore(effective)

        async def generate_description(idx: int) -> tuple[int, str]:
            descriptor = descriptors[idx]
            prompt = _DESCRIPTION_PROMPT.format(
                title=descriptor.get("title", ""),
                content=descriptor.get("content", ""),
            )
            async with semaphore:
                text = await asyncio.to_thread(
                    bedrock.invoke_text_model,
                    settings.bedrock_text_model or "",
                    prompt,
                )
            return idx, text

        generated = await asyncio.gather(
            *[generate_description(i) for i in missing_indices],
            return_exceptions=True,
        )
        for i, result in zip(missing_indices, generated):
            if isinstance(result, BaseException):
                logger.warning(
                    "Description generation failed for descriptor at index %d: %s", i, result
                )
                continue
            _, text = result
            descriptors[i] = {**descriptors[i], "description": text}

    # ── Step 3: clip all descriptions to _MAX_DESCRIPTION_LENGTH ──────────────
    enriched: list[dict[str, Any]] = []
    for descriptor in descriptors:
        raw_desc: str = descriptor.get("description", "")
        clipped = _clip_description(raw_desc, descriptor.get("title", ""))
        enriched.append({**descriptor, "description": clipped})

    # ── Step 4: dry_run → return enriched list without writing ────────────────
    if dry_run:
        response: dict[str, Any] = {"descriptors": enriched}
        if warning is not None:
            response["warning"] = warning
        return response

    # ── Step 5: delegate to write_artifacts for the write phase ───────────────
    write_result = await _write_artifacts(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        artifacts=enriched,
        artifact_concurrency=effective,
    )
    if warning is not None:
        return {**write_result, "warning": warning}
    return write_result
