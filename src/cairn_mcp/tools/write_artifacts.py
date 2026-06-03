"""cairn_mcp.tools.write_artifacts — bulk concurrent artifact write MCP tool.

Accepts a list of artifact descriptors and writes all of them concurrently,
bounded by ARTIFACT_CONCURRENCY. Each entry delegates to _write_artifact_inner
so all write path logic (section embedding, orphan cleanup, failure logging) is
inherited from the single implementation. Partial failures are isolated: a failed
entry is recorded with an error field while all other entries continue.
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


async def write_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a list of artifact descriptors concurrently.

    Args:
        settings: Server configuration.
        s3: S3 client for content storage.
        vectors: S3 Vectors client for semantic index.
        bedrock: Bedrock client for embedding generation.
        artifacts: List of artifact descriptor dicts. Each must contain the same
            fields as write_artifact; ``description`` is required.

    Returns:
        ``{"results": [...]}`` where each entry corresponds positionally to the
        input descriptor. Successful entries carry ``written=True``, ``artifact_id``,
        and ``sections_indexed``; failed entries carry ``error`` and ``message``.
    """
    try:
        return await _write_artifacts_inner(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifacts=artifacts,
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
) -> dict[str, Any]:
    """Inner implementation: concurrent writes bounded by ARTIFACT_CONCURRENCY."""
    semaphore = asyncio.Semaphore(settings.artifact_concurrency)

    async def write_one(descriptor: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
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
                    tags=descriptor.get("feature_tags") or [],
                    author_role=descriptor.get("author_role"),
                    sources=descriptor.get("source_artifacts") or [],
                    status=descriptor.get("status", "active"),
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
    return {"results": list(raw_results)}
