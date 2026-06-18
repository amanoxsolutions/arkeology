"""cairn_mcp.tools.write_artifacts — bulk concurrent artifact write MCP tool.

Accepts a list of artifact descriptors and writes all of them concurrently,
bounded by the caller-supplied artifact_concurrency parameter (default 3).
Each entry delegates to _write_artifact_inner so all write path logic (section
embedding, orphan cleanup, failure logging) is inherited from the single
implementation. Partial failures are isolated: a failed entry is recorded with
an error field while all other entries continue.

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
from cairn_mcp.tools.write import _write_artifact_inner

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS: tuple[str, ...] = (
    "type",
    "team",
    "project",
    "tier",
    "date",
    "title",
    "description",
    "content",
    "visibility",
)


def _validate_descriptor(descriptor: dict[str, Any]) -> str | None:
    """Return a human-readable error message if any required field is missing, else None."""
    for field in _REQUIRED_FIELDS:
        if field not in descriptor:
            return f"missing required field: {field}"
    return None


_ARTIFACT_CONCURRENCY_DEFAULT: int = 3
_ARTIFACT_CONCURRENCY_MAX: int = 15


async def write_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    artifacts: list[dict[str, Any]],
    artifact_concurrency: int = _ARTIFACT_CONCURRENCY_DEFAULT,
    file_extension: str = ".md",
) -> dict[str, Any]:
    """Write a list of artifact descriptors concurrently.

    Args:
        settings: Server configuration.
        s3: S3 client for content storage.
        vectors: S3 Vectors client for semantic index.
        bedrock: Bedrock client for embedding generation.
        artifacts: List of artifact descriptor dicts. Each must contain the same
            fields as write_artifact; ``description`` is required.
        file_extension: File extension for the S3 key, including the leading dot
            (e.g. ``".md"``, ``".txt"``). Defaults to ``".md"``. Each descriptor
            may also supply a ``file_extension`` key to override this per-artifact.
        artifact_concurrency: Maximum number of artifacts processed concurrently.
            Must be in [1, 15]. Values > 15 are capped to 15 (with a warning in
            the response). Values < 1 are substituted with the default 3 (with a
            warning). Out-of-range values are never an error. Defaults to 3.

    Returns:
        ``{"results": [...]}`` where each entry corresponds positionally to the
        input descriptor. Successful entries carry ``written=True``, ``artifact_id``,
        and ``sections_indexed``; failed entries carry ``error`` and ``message``.
        When ``artifact_concurrency`` is out of range, a top-level ``"warning"`` key
        is included in the response.
    """
    try:
        return await _write_artifacts_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifacts=artifacts,
            artifact_concurrency=artifact_concurrency,
            file_extension=file_extension,
        )
    except Exception as exc:
        logger.exception("Unexpected error in write_artifacts")
        return {"error": "internal_error", "message": str(exc), "results": []}


async def _write_artifacts_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    artifacts: list[dict[str, Any]],
    artifact_concurrency: int = _ARTIFACT_CONCURRENCY_DEFAULT,
    file_extension: str = ".md",
) -> dict[str, Any]:
    """Inner implementation: concurrent writes bounded by artifact_concurrency."""
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

    semaphore = asyncio.Semaphore(effective)

    async def write_one(descriptor: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            validation_error = _validate_descriptor(descriptor)
            if validation_error:
                return {"error": "validation_error", "message": validation_error}
            try:
                result = await _write_artifact_inner(
                    settings=settings,
                    s3=s3,
                    vectors=vectors,
                    bedrock=bedrock,
                    type=descriptor["type"],
                    team=descriptor["team"],
                    project=descriptor["project"],
                    tier=descriptor["tier"],
                    date=descriptor["date"],
                    title=descriptor["title"],
                    description=descriptor["description"],
                    content=descriptor["content"],
                    visibility=descriptor["visibility"],
                    tags=descriptor.get("tags") or [],
                    author_role=descriptor.get("author_role"),
                    sources=descriptor.get("source_artifacts") or [],
                    refs=descriptor.get("commit_refs") or [],
                    status=descriptor.get("status", "active"),
                    file_extension=descriptor.get("file_extension") or file_extension,
                )
                # _write_artifact_inner returns error dict or success dict
                if "error" in result:
                    return result
                return {
                    "written": True,
                    "artifact_id": result.get("artifact_id", ""),
                    "sections_indexed": result.get("sections_indexed", 0),
                }
            except Exception as exc:
                logger.exception("Unexpected error writing artifact '%s'", descriptor.get("title"))
                return {"error": "internal_error", "message": str(exc)}

    raw_results = await asyncio.gather(*[write_one(d) for d in artifacts])
    response: dict[str, Any] = {"results": list(raw_results)}
    if warning is not None:
        response["warning"] = warning
    return response
