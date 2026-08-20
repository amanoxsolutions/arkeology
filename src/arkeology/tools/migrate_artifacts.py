"""arkeology.tools.migrate_artifacts — bulk migration MCP tool with Nova Lite enrichment.

Accepts a list of artifact descriptors where ``description`` is optional. For any
descriptor missing a description, Nova Lite (BEDROCK_TEXT_MODEL) is called to
generate one. All descriptions are clipped to 280 characters. In dry_run mode the
enriched descriptor list is returned without any writes. In live mode, the enriched
descriptors are handed to write_artifacts for concurrent bulk write.

The caller-supplied ``artifact_concurrency`` parameter (default 3, range [1, 15])
controls both the Nova Lite description semaphore (enrichment phase) and is forwarded
to write_artifacts for the write semaphore (live phase). Out-of-range values are
clamped silently with a top-level ``"warning"`` field in the response.

Bulk migration never overwrites a pre-existing key. Before the write phase, each
candidate's generated key is checked for existence; any candidate that already exists
is skipped (no write, no error) and reported in the ``"skipped_existing"`` list, so
re-running a migration over an already-imported corpus is idempotent and non-destructive.

T61: "S3 object exists" is not the same fact as "fully migrated" — a prior attempt can
have written S3 successfully and then failed on the vector write. For each already-
existing candidate, one bounded, per-candidate ``vectors.list_vectors_by_metadata``
query distinguishes the two: if vectors are indexed, the candidate is
``skipped_existing`` exactly as before; if not, it is reported distinctly in the new
``"skipped_unindexed"`` list (``combined_results[idx]["reason"] = "unindexed"``),
with a message pointing at ``reconcile_index`` for remediation. Detection and
reporting only — ``migrate_artifacts`` never writes to or re-indexes an unindexed
candidate itself.

A descriptor whose Nova Lite description generation fails is never written with an
empty ``description`` — it is skipped (mirroring the skip-existing
``skipped_existing`` shape) and reported in the top-level ``"generation_failed"`` list,
in both ``dry_run`` modes. The artifact content interpolated into the generation prompt
is bounded to ``_PROMPT_CONTENT_MAX_CHARS`` — full untruncated content is never sent to
Nova Lite for a task that only needs a single-sentence summary.

T56/FR-52 extension (ADR-012 Revision 2026-07-06): a descriptor may carry a transient
``resolved_references_map`` key (``{original_reference_text: artifact_id}``, built by
the caller reusing the unchanged T51 resolution algorithm in ``references.py``). When
present, its ``content`` is rewritten via ``rewrite_content_references`` — every
already-resolved reference path, in the frontmatter ``references:`` list AND in
matching markdown body link targets, is replaced with ``arkeology://artifact/{id}`` — before
the skip-existing check and the ``write_artifacts`` delegation, in both ``dry_run``
modes, so the content stored in S3 and the content embedded are always the same
(already-rewritten) text. The key is popped before the descriptor is returned or
written; it never reaches ``write_artifacts``, stored metadata, the ``Artifact`` model,
or any response. This capability is ``migrate_artifacts``-only.

Note: A compound artifact_concurrency × section_concurrency ≤ ceiling validation
is intentionally absent from this task; it is noted here as a future concern.
"""

import asyncio
import logging
from typing import Any

from arkeology.artifact import DESCRIPTION_MAX_LENGTH, generate_artifact_id
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ErrorCode
from arkeology.errors import CredentialError
from arkeology.references import rewrite_content_references
from arkeology.tools._concurrency import (
    _ARTIFACT_CONCURRENCY_DEFAULT,
    _ARTIFACT_CONCURRENCY_MAX,
    _clamp_concurrency,
)
from arkeology.tools._errors import credential_error_response
from arkeology.tools.write_artifacts import write_artifacts as _write_artifacts

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

# Mirrors arkeology.artifact.DESCRIPTION_MAX_LENGTH — descriptions clipped here must
# never drift from the limit Artifact.validate_description actually enforces (I-1).
_MAX_DESCRIPTION_LENGTH = DESCRIPTION_MAX_LENGTH

# Bound the artifact content interpolated into the Nova Lite prompt. A
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

    Truncate to ``_PROMPT_CONTENT_MAX_CHARS`` with a trailing marker so the prompt
    size stays bounded regardless of the source artifact's length — an unbounded
    body risks exceeding the text model's input limit on large specs and log dumps.
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
        A candidate whose S3 object exists but has no indexed vectors (a partial
            write) is skipped distinctly: its entry is ``{"written": False,
            "skipped": True, "artifact_id": ..., "reason": "unindexed", "message":
            ...}``, and a top-level ``"skipped_unindexed"`` list is included
            (``index``, ``artifact_id``, ``title``, ``message``), one entry per
            such candidate, with the message pointing at ``reconcile_index`` as the
            remediation path. Never folded into ``skipped_existing`` and never
            written to by ``migrate_artifacts`` itself.
        A descriptor whose Nova Lite description generation fails is never
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
    effective, warning = _clamp_concurrency(
        artifact_concurrency, default=_ARTIFACT_CONCURRENCY_DEFAULT, max_=_ARTIFACT_CONCURRENCY_MAX
    )

    def _with_warning(resp: dict[str, Any]) -> dict[str, Any]:
        """Append the clamp warning to a response only when one was raised.

        When no warning was raised the response is returned unchanged, so the
        warning-absent and warning-present dicts stay byte-identical apart from
        the single trailing ``"warning"`` key.
        """
        if warning is not None:
            resp["warning"] = warning
        return resp

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
    # Track which indices failed generation so Step 3/5/6 can skip them
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
    # A generation-failed descriptor is carried through unchanged (its
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

    # ── Step 3.5 (T56/FR-52 extension): deterministic content reference rewrite ──
    # For each descriptor carrying a resolved_references_map ({original_reference_text:
    # artifact_id}), rewrite its content so every already-resolved reference path — the
    # frontmatter references: list item AND any matching markdown body link target — is
    # replaced with arkeology://artifact/{id} (ADR-012 Revision 2026-07-06). Applied
    # identically in BOTH dry_run modes, and before the skip-existing check / the
    # write_artifacts delegation below, so the content stored in S3 and the content
    # parsed into sections and embedded are always the same (already-rewritten) text —
    # no separate re-embed step is introduced. The transient key is popped here so it
    # never reaches write_artifacts, any stored metadata, the Artifact model, or any
    # response — this capability is migrate_artifacts-only.
    rewritten: list[dict[str, Any]] = []
    for descriptor in enriched:
        if "resolved_references_map" not in descriptor:
            rewritten.append(descriptor)
            continue
        descriptor = dict(descriptor)
        resolved_references_map = descriptor.pop("resolved_references_map")
        descriptor["content"] = rewrite_content_references(
            descriptor.get("content", ""), resolved_references_map
        )
        rewritten.append(descriptor)
    enriched = rewritten

    # ── Step 4: dry_run → return enriched list without writing ────────────────
    if dry_run:
        dry_run_response: dict[str, Any] = {"descriptors": enriched}
        if generation_failures:
            dry_run_response["generation_failed"] = _generation_failed_report(
                descriptors, generation_failures
            )
        return _with_warning(dry_run_response)

    # ── Step 5: skip-existing filter ───────────────────────────────────────────
    # Bulk migration is commonly re-run over the same corpus (resuming an interrupted
    # import, or re-importing an updated corpus). It must NEVER overwrite: a
    # candidate whose generated key already exists is skipped — not written, not an
    # error — so re-running a migration is idempotent and non-destructive. This is
    # deliberately never bypassed with overwrite=True, which would reopen the
    # silent-overwrite hole that write_artifact's collision guard exists to close.
    to_write_indices: list[int] = []
    skipped_existing: list[dict[str, Any]] = []
    skipped_unindexed: list[dict[str, Any]] = []
    combined_results: list[dict[str, Any] | None] = [None] * len(enriched)

    # First pass (synchronous, CPU-only): resolve each descriptor's candidate S3
    # key, or route it straight to to_write_indices / combined_results when no I/O
    # check is needed (generation-failed, malformed descriptor).
    candidate_keys: dict[int, str] = {}
    for idx, descriptor in enumerate(enriched):
        # A generation-failed descriptor is never written with an empty
        # description — skip it before any key computation or existence check,
        # and report it distinctly from the "already exists" skip reason.
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
        if not ext.startswith("."):
            # Mirror write.py's own guard exactly (same error shape) so this
            # pre-check enforces the identical invariant instead of silently
            # probing a key write_artifacts/write.py would refuse to construct.
            combined_results[idx] = {
                "error": ErrorCode.VALIDATION_ERROR,
                "message": "file_extension must start with '.'",
            }
            continue
        candidate_keys[idx] = f"{settings.write_prefix}/{slug}{ext}"

    # Second pass: bounded-concurrency existence + indexing check for every
    # candidate key (H-1), reusing the same artifact_concurrency semaphore as the
    # description-generation phase above. Read-only (head_object,
    # list_vectors_by_metadata) — no side effects — so dispatching every check
    # concurrently and then deciding in original index order below reproduces the
    # exact sequential response deterministically, including which candidate's
    # CredentialError (if any) is surfaced.
    check_semaphore = asyncio.Semaphore(effective)

    async def _check_candidate(idx: int, candidate_key: str) -> tuple[int, str, Any]:
        async with check_semaphore:
            try:
                await asyncio.to_thread(s3.head_object, candidate_key)
            except KeyError:
                return idx, "new", None
            except CredentialError as exc:
                return idx, "credential_error", exc

            # T61 self-heal detection: "S3 object exists" and "fully migrated" are
            # not the same fact — a prior attempt can have written S3 successfully
            # and then failed on the vector write (the incident's exact
            # partial-write shape). One bounded, per-candidate existence query
            # distinguishes the two so an unindexed candidate is reported
            # distinctly instead of silently folded into skipped_existing forever.
            # This is detection-and-reporting only: the skip-existing guard still
            # applies and no write happens for either case; remediation is
            # reconcile_index's job, not migrate_artifacts'.
            try:
                indexed_vector_keys = await asyncio.to_thread(
                    vectors.list_vectors_by_metadata, {"artifact_id": {"$eq": candidate_key}}
                )
            except CredentialError as exc:
                return idx, "credential_error", exc

            return idx, ("indexed" if indexed_vector_keys else "unindexed"), None

    check_results = await asyncio.gather(
        *[_check_candidate(idx, key) for idx, key in candidate_keys.items()]
    )

    # asyncio.gather preserves input order, and candidate_keys was populated in
    # ascending idx order above, so this walk is deterministic — the same
    # CredentialError a sequential scan would hit first is the one surfaced.
    for idx, outcome, payload in check_results:
        if outcome == "credential_error":
            return _with_warning(credential_error_response(payload))

    for idx, outcome, _payload in check_results:
        descriptor = enriched[idx]
        candidate_key = candidate_keys[idx]
        if outcome == "new":
            to_write_indices.append(idx)
        elif outcome == "indexed":
            combined_results[idx] = {
                "written": False,
                "skipped": True,
                "artifact_id": candidate_key,
            }
            skipped_existing.append(
                {
                    "index": idx,
                    "artifact_id": candidate_key,
                    "title": descriptor.get("title", ""),
                }
            )
        else:  # "unindexed"
            message = (
                f"Artifact '{candidate_key}' exists in S3 but has no indexed vectors "
                "(a partial write). Run reconcile_index to re-index it."
            )
            combined_results[idx] = {
                "written": False,
                "skipped": True,
                "artifact_id": candidate_key,
                "reason": "unindexed",
                "message": message,
            }
            skipped_unindexed.append(
                {
                    "index": idx,
                    "artifact_id": candidate_key,
                    "title": descriptor.get("title", ""),
                    "message": message,
                }
            )

    # Restore ascending idx order: malformed-descriptor indices (added in the first,
    # synchronous pass) and freshly-discovered "new" indices (added in the second,
    # concurrent pass) can otherwise interleave in a way a single sequential loop
    # never would. write_artifacts' response is matched back to combined_results
    # positionally below, so this keeps that mapping identical to the original
    # strictly-sequential loop's.
    to_write_indices.sort()

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
    if skipped_unindexed:
        response["skipped_unindexed"] = skipped_unindexed
    if generation_failures:
        response["generation_failed"] = _generation_failed_report(descriptors, generation_failures)
    return _with_warning(response)
