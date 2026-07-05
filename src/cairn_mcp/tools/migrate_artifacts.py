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

A-1: bulk migration never overwrites a pre-existing key. Before the write phase, each
candidate's generated key is checked for existence; any candidate that already exists
is skipped (no write, no error) and reported in the ``"skipped_existing"`` list, so
re-running a migration over an already-imported corpus is idempotent and non-destructive.

M-12 (Phase 12 review): a descriptor whose Nova Lite description generation fails is
never written with an empty ``description`` — it is skipped (mirroring the A-1
``skipped_existing`` shape) and reported in the top-level ``"generation_failed"`` list,
in both ``dry_run`` modes. The artifact content interpolated into the generation prompt
is bounded to ``_PROMPT_CONTENT_MAX_CHARS`` — full untruncated content is never sent to
Nova Lite for a task that only needs a single-sentence summary.

Note: A compound artifact_concurrency × section_concurrency ≤ ceiling validation
is intentionally absent from this task; it is noted here as a future concern.
"""

import asyncio
import logging
from typing import Any

from cairn_mcp.artifact import generate_artifact_id
from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.constants import ErrorCode
from cairn_mcp.errors import CredentialError
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

# M-12: bound the artifact content interpolated into the Nova Lite prompt. A
# single-sentence summary never needs the full body of a multi-thousand-line spec
# or log dump — sending it unbounded risks exceeding the text model's input limit
# and wastes tokens well beyond what the task requires. The prompt only needs
# enough context to summarise; truncating to the leading portion is sufficient.
_PROMPT_CONTENT_MAX_CHARS = 8000


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


def _truncate_prompt_content(content: str) -> str:
    """Bound the artifact content interpolated into the description-generation prompt.

    M-12: the prompt previously interpolated the full, untruncated artifact content.
    Truncate to ``_PROMPT_CONTENT_MAX_CHARS`` with a trailing marker so the prompt
    size is bounded regardless of the source artifact's length.
    """
    if len(content) <= _PROMPT_CONTENT_MAX_CHARS:
        return content
    return content[:_PROMPT_CONTENT_MAX_CHARS] + "\n\n[content truncated for prompt]"


def _generation_failed_report(
    descriptors: list[dict[str, Any]], failures: dict[int, str]
) -> list[dict[str, Any]]:
    """Build the top-level ``generation_failed`` report list, one entry per failed index."""
    return [
        {"index": idx, "title": descriptors[idx].get("title", ""), "message": message}
        for idx, message in sorted(failures.items())
    ]


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
        ``dry_run=False``: ``{"results": [...]}`` — one entry per input descriptor,
            positionally aligned. A descriptor whose generated key already exists is
            **skipped** — never overwritten — and its entry is
            ``{"written": False, "skipped": True, "artifact_id": ...}``; all other
            entries are the usual write_artifacts outcome. When any descriptor was
            skipped, a top-level ``"skipped_existing"`` list is also included, one
            entry per skip (``index``, ``artifact_id``, ``title``). Re-running a
            migration over an already-imported corpus is therefore idempotent and
            non-destructive: every already-present artifact is skipped and nothing is
            overwritten or deleted.
        M-12: a descriptor whose Nova Lite description generation fails is never
            written with an empty ``description``. In ``dry_run=False`` its result
            entry is ``{"written": False, "skipped": True,
            "reason": "description_generation_failed", "message": ...}``; in either
            ``dry_run`` mode a top-level ``"generation_failed"`` list is included,
            one entry per failure (``index``, ``title``, ``message``).
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
        return {"error": ErrorCode.INTERNAL_ERROR, "message": str(exc)}


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

    def _with_warning(resp: dict[str, Any]) -> dict[str, Any]:
        """Append the clamp warning to a response only when one was raised.

        When no warning was raised the response is returned unchanged, so the
        warning-absent and warning-present dicts stay byte-identical apart from
        the single trailing ``"warning"`` key.
        """
        if warning is not None:
            resp["warning"] = warning
        return resp

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
            "error": ErrorCode.CONFIGURATION_ERROR,
            "message": (
                "BEDROCK_TEXT_MODEL is not configured. "
                "Set it to use migrate_artifacts with missing descriptions."
            ),
        }

    # ── Step 2: generate missing descriptions concurrently ────────────────────
    # M-12: track which indices failed generation so Step 3/5/6 can skip them
    # instead of letting an empty "description" fall through to a written artifact.
    generation_failures: dict[int, str] = {}
    if missing_indices:
        semaphore = asyncio.Semaphore(effective)

        async def generate_description(idx: int) -> tuple[int, str]:
            descriptor = descriptors[idx]
            prompt = _DESCRIPTION_PROMPT.format(
                title=descriptor.get("title", ""),
                content=_truncate_prompt_content(descriptor.get("content", "")),
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
                generation_failures[i] = str(result)
                continue
            _, text = result
            descriptors[i] = {**descriptors[i], "description": text}

    # ── Step 3: clip all descriptions to _MAX_DESCRIPTION_LENGTH ──────────────
    # M-12: a generation-failed descriptor is carried through unchanged (its
    # "description" stays absent/empty) rather than clipped — it is excluded from
    # writing in Step 5/6 below, so clipping it here would be misleading busywork.
    enriched: list[dict[str, Any]] = []
    for idx, descriptor in enumerate(descriptors):
        if idx in generation_failures:
            enriched.append(descriptor)
            continue
        raw_desc: str = descriptor.get("description", "")
        clipped = _clip_description(raw_desc, descriptor.get("title", ""))
        enriched.append({**descriptor, "description": clipped})

    # ── Step 4: dry_run → return enriched list without writing ────────────────
    if dry_run:
        dry_run_response: dict[str, Any] = {"descriptors": enriched}
        if generation_failures:
            dry_run_response["generation_failed"] = _generation_failed_report(
                descriptors, generation_failures
            )
        return _with_warning(dry_run_response)

    # ── Step 5: skip-existing filter (A-1) ─────────────────────────────────────
    # Bulk migration is commonly re-run over the same corpus (resuming an interrupted
    # import, or re-importing an updated corpus). It must NEVER overwrite: a
    # candidate whose generated key already exists is skipped — not written, not an
    # error — so re-running a migration is idempotent and non-destructive. This is
    # deliberately never bypassed with overwrite=True, which would reopen the
    # silent-overwrite hole C-3's collision guard exists to close.
    to_write_indices: list[int] = []
    skipped_existing: list[dict[str, Any]] = []
    combined_results: list[dict[str, Any] | None] = [None] * len(enriched)

    for idx, descriptor in enumerate(enriched):
        # M-12: a generation-failed descriptor is never written with an empty
        # description — skip it before any key computation or existence check,
        # and report it distinctly from the A-1 "already exists" skip reason.
        if idx in generation_failures:
            combined_results[idx] = {
                "written": False,
                "skipped": True,
                "reason": "description_generation_failed",
                "message": generation_failures[idx],
            }
            continue
        try:
            slug = generate_artifact_id(
                tier=int(descriptor["tier"]),
                type=str(descriptor["type"]),
                date=str(descriptor["date"]),
                title=str(descriptor["title"]),
            )
        except KeyError, ValueError, TypeError:
            # Malformed descriptor — defer to write_artifacts' own per-item
            # validation, which surfaces a clear validation_error for this entry.
            to_write_indices.append(idx)
            continue

        ext = str(descriptor.get("file_extension") or ".md")
        candidate_key = f"{settings.write_prefix}/{slug}{ext}"
        try:
            s3.head_object(candidate_key)
        except KeyError:
            to_write_indices.append(idx)
            continue
        except CredentialError as exc:
            return _with_warning({"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)})

        combined_results[idx] = {
            "written": False,
            "skipped": True,
            "artifact_id": candidate_key,
        }
        skipped_existing.append(
            {"index": idx, "artifact_id": candidate_key, "title": descriptor.get("title", "")}
        )

    # ── Step 6: delegate to write_artifacts for the genuinely-new candidates ──────
    if to_write_indices:
        write_result = await _write_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifacts=[enriched[i] for i in to_write_indices],
            artifact_concurrency=effective,
            overwrite=False,
        )
        if "results" not in write_result:
            # write_artifacts hit its own top-level catch-all — propagate as-is
            # rather than silently dropping the failure.
            return _with_warning(write_result)
        for pos, idx in enumerate(to_write_indices):
            combined_results[idx] = write_result["results"][pos]

    response: dict[str, Any] = {"results": combined_results}
    if skipped_existing:
        response["skipped_existing"] = skipped_existing
    if generation_failures:
        response["generation_failed"] = _generation_failed_report(descriptors, generation_failures)
    return _with_warning(response)
