"""cairn_mcp.tools.migrate_artifacts — bulk migration MCP tool with Nova Lite enrichment.

Accepts a list of artifact descriptors where ``description`` is optional. For any
descriptor missing a description, Nova Lite (BEDROCK_TEXT_MODEL) is called to
generate one. All descriptions are clipped to 280 characters. In dry_run mode the
enriched descriptor list is returned without any writes. In live mode, the enriched
descriptors are handed to write_artifacts for concurrent bulk write.
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

    Returns:
        ``dry_run=True``:  ``{"descriptors": [...]}`` — enriched descriptor list.
        ``dry_run=False``: ``{"results": [...]}`` — per-artifact write results from
            write_artifacts.
    """
    try:
        return await _migrate_artifacts_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            descriptors=descriptors,
            dry_run=dry_run,
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
) -> dict[str, Any]:
    """Inner implementation: enrich descriptions, then write or return."""
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
        semaphore = asyncio.Semaphore(settings.artifact_concurrency)

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
        for result in generated:
            if isinstance(result, BaseException):
                raise result
            idx, text = result
            descriptors[idx] = {**descriptors[idx], "description": text}

    # ── Step 3: clip all descriptions to _MAX_DESCRIPTION_LENGTH ──────────────
    enriched: list[dict[str, Any]] = []
    for descriptor in descriptors:
        raw_desc: str = descriptor.get("description", "")
        clipped = _clip_description(raw_desc, descriptor.get("title", ""))
        enriched.append({**descriptor, "description": clipped})

    # ── Step 4: dry_run → return enriched list without writing ────────────────
    if dry_run:
        return {"descriptors": enriched}

    # ── Step 5: delegate to write_artifacts for the write phase ───────────────
    return await _write_artifacts(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        artifacts=enriched,
    )
