"""arkeology.tools.write_artifacts — bulk concurrent artifact write MCP tool.

Accepts a list of artifact descriptors and writes all of them concurrently,
bounded by the caller-supplied artifact_concurrency parameter (default 3).
Each entry delegates to write_artifact_inner so all write path logic (section
embedding, orphan cleanup, failure logging) is inherited from the single
implementation. Partial failures are isolated: a failed entry is recorded with
an error field while all other entries continue.

Note: A compound artifact_concurrency × section_concurrency ≤ ceiling validation
is intentionally absent from this task; it is noted here as a future concern.
"""

import asyncio
import logging
from typing import Any

from arkeology.artifact import generate_artifact_id
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ArtifactStatus, ErrorCode
from arkeology.tools._concurrency import (
    ARTIFACT_CONCURRENCY_DEFAULT,
    ARTIFACT_CONCURRENCY_MAX,
    clamp_concurrency,
)
from arkeology.tools.write import write_artifact_inner

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


async def write_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    artifacts: list[dict[str, Any]],
    artifact_concurrency: int = ARTIFACT_CONCURRENCY_DEFAULT,
    file_extension: str = ".md",
    overwrite: bool = False,
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
        overwrite: Batch-level default for the collision guard (default
            ``False`` — a descriptor targeting an already-existing key is
            rejected with ``validation_error``). Each descriptor may also supply
            an ``overwrite`` key to override this default for that entry only,
            mirroring the ``file_extension`` batch-default/per-descriptor shape.

    Returns:
        ``{"results": [...]}`` where each entry corresponds positionally to the
        input descriptor. Successful entries carry ``written=True``, ``artifact_id``,
        and ``sections_indexed``; failed entries carry ``error`` and ``message``.
        When ``artifact_concurrency`` is out of range, a top-level ``"concurrency_warning"`` key
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
            overwrite=overwrite,
        )
    except Exception as exc:
        logger.exception("Unexpected error in write_artifacts")
        return {
            "error": ErrorCode.INTERNAL_ERROR,
            "message": str(exc),
            "results": [],
        }


async def _write_artifacts_inner(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    artifacts: list[dict[str, Any]],
    artifact_concurrency: int = ARTIFACT_CONCURRENCY_DEFAULT,
    file_extension: str = ".md",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Inner implementation: concurrent writes bounded by artifact_concurrency."""
    # ── Clamp artifact_concurrency to [1, 15] ────────────────────────────────
    effective, warning = clamp_concurrency(
        artifact_concurrency, default=ARTIFACT_CONCURRENCY_DEFAULT, max_=ARTIFACT_CONCURRENCY_MAX
    )

    semaphore = asyncio.Semaphore(effective)

    # ── Pre-flight: detect intra-batch duplicate artifact IDs ─────────────────
    # Two descriptors resolving to the same S3 key would race on Step 8 orphan
    # cleanup: each deletes the other's freshly-written vectors.  Mark all but
    # the first occurrence as validation_error before any coroutines are launched.
    seen_keys: dict[str, int] = {}  # full s3 key → first occurrence index
    dup_errors: list[str | None] = [None] * len(artifacts)

    for idx, d in enumerate(artifacts):
        try:
            slug = generate_artifact_id(
                tier=int(d["tier"]),
                type=str(d["type"]),
                date=str(d["date"]),
                title=str(d["title"]),
            )
            ext = str(d.get("file_extension") or file_extension)
            full_key = f"{settings.write_prefix}/{slug}{ext}"
        except KeyError, ValueError, TypeError:
            # Missing or invalid fields — _validate_descriptor will surface this.
            continue

        if full_key in seen_keys:
            dup_errors[idx] = (
                f"duplicate artifact ID '{full_key}' — "
                f"already present at index {seen_keys[full_key]} in this batch"
            )
        else:
            seen_keys[full_key] = idx

    async def write_one(idx: int, descriptor: dict[str, Any]) -> dict[str, Any]:
        dup_msg = dup_errors[idx]
        if dup_msg is not None:
            return {"error": ErrorCode.VALIDATION_ERROR, "message": dup_msg}
        async with semaphore:
            validation_error = _validate_descriptor(descriptor)
            if validation_error:
                return {"error": ErrorCode.VALIDATION_ERROR, "message": validation_error}
            try:
                result = await write_artifact_inner(
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
                    references=descriptor.get("references") or [],
                    status=descriptor.get("status", ArtifactStatus.ACTIVE),
                    file_extension=descriptor.get("file_extension") or file_extension,
                    overwrite=descriptor.get("overwrite", overwrite),
                )
                # write_artifact_inner returns error dict or success dict
                if "error" in result:
                    return result
                return {
                    "written": True,
                    "artifact_id": result.get("artifact_id", ""),
                    "sections_indexed": result.get("sections_indexed", 0),
                }
            except Exception as exc:
                logger.exception("Unexpected error writing artifact '%s'", descriptor.get("title"))
                return {
                    "error": ErrorCode.INTERNAL_ERROR,
                    "message": str(exc),
                }

    raw_results = await asyncio.gather(*[write_one(i, d) for i, d in enumerate(artifacts)])
    response: dict[str, Any] = {"results": list(raw_results)}
    if warning is not None:
        response["concurrency_warning"] = warning
    return response
