"""cairn_mcp.tools._search_helper — shared vector re-fetch loop for search and synthesise.

This private module contains the scope-filter construction and deduplicating
re-fetch loop shared between search_artifacts and synthesise_artifacts. Both
tools call _run_search_loop with their respective parameters; tool-specific
logic (content fetching, response shape) is handled by each tool independently.
"""

import asyncio
import json
import logging
from typing import Any

from cairn_mcp.artifact import (
    ARTIFACT_TYPES,
    NON_FILTERABLE_METADATA_KEYS,
    REFERENCE_FIELDS,
    VALID_TIERS,
)
from cairn_mcp.clients.interfaces import VectorsClientInterface
from cairn_mcp.config import Settings
from cairn_mcp.constants import ArtifactStatus, ErrorCode
from cairn_mcp.errors import CredentialError, InvalidFilterValueError

logger = logging.getLogger(__name__)

# Conservative half of the ~2 KB S3 Vectors metadata-filter expression size limit
# (mirrors the order of magnitude of VECTOR_FILTERABLE_METADATA_MAX_BYTES in
# artifact.py), leaving headroom in the same $and for the user/status/scope filter
# clauses. Once the $nin exclusion list would grow past this budget, the re-fetch
# loop (M-6, Phase 12 review) stops issuing further queries and returns whatever has
# already been collected rather than risking a ValidationException from an oversized
# filter expression.
_NIN_EXCLUSION_BYTE_BUDGET = 1024


def _nin_list_byte_size(seen_ids: set[str]) -> int:
    """Return the UTF-8 byte size of ``seen_ids`` as it would appear in a $nin clause."""
    return len(json.dumps(list(seen_ids)).encode("utf-8"))


def build_scope_filter(settings: Settings) -> dict[str, Any]:
    """Build the S3 Vectors scope filter for the current deployment.

    Own-scope artifacts are always visible. Foreign-scope artifacts are
    included only when tier=3 and visibility="shared".

    Args:
        settings: Server configuration with write_prefix and read_prefixes.

    Returns:
        A metadata filter dict suitable for passing to query_vectors.
    """
    read_prefixes = settings.read_prefixes_list
    write_prefix = settings.write_prefix

    if read_prefixes:
        return {
            "$or": [
                {"scope": {"$eq": write_prefix}},
                {
                    "$and": [
                        {"scope": {"$in": read_prefixes}},
                        {"tier": {"$eq": 3}},
                        {"visibility": {"$eq": "shared"}},
                    ]
                },
            ]
        }
    return {"scope": {"$eq": write_prefix}}


def coerce_list_field(meta: dict[str, Any], key: str) -> list[str]:
    """Coerce a metadata list field to ``list[str]``, accepting both encodings.

    Vector metadata stores list fields (``tags``, ``source_artifacts``,
    ``commit_refs``) as ``list[str]``; S3 object metadata stores them as a
    comma-joined string. This helper handles both: a list value is returned
    as-is, anything else is split on commas with empty segments dropped.

    Args:
        meta: A metadata dict (vector or S3 object metadata).
        key: The field name to read.

    Returns:
        The field value as a list of non-empty strings.
    """
    value = meta.get(key)
    if isinstance(value, list):
        return value
    return [item for item in str(value if value is not None else "").split(",") if item]


def build_user_filters(
    *,
    type: str | None = None,  # noqa: A002
    team: str | None = None,
    project: str | None = None,
    tier: int | None = None,
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build the caller-supplied metadata filter clauses shared by the read path.

    Produces the ``type/team/project/tier/tags`` ``$eq`` clauses used by
    search, synthesise, and list. ``tags`` expands to one ``$eq`` clause per
    tag (AND semantics, element-in-list matching on the vector ``tags`` field).
    Each argument is omitted from the result when ``None`` (or empty for tags).

    Args:
        type: Optional artifact type filter. Must be one of ``ARTIFACT_TYPES``.
        team: Optional team filter.
        project: Optional project filter.
        tier: Optional tier filter. Must be one of ``VALID_TIERS`` (2 or 3).
        tags: Optional list of tags; all must match (AND semantics).

    Returns:
        A list of metadata filter clause dicts.

    Raises:
        InvalidFilterValueError: ``type`` is not a recognised artifact type, or
            ``tier`` is not 2 or 3 (07-02 #5) — a typo'd/out-of-range filter
            value must never silently fall through to a filter clause that
            legitimately matches nothing, which is indistinguishable from a
            real zero-result query. Callers translate this to
            ``ErrorCode.VALIDATION_ERROR``.
    """
    clauses: list[dict[str, Any]] = []
    if type is not None:
        if type not in ARTIFACT_TYPES:
            raise InvalidFilterValueError("type", type)
        clauses.append({"type": {"$eq": type}})
    if team is not None:
        clauses.append({"team": {"$eq": team}})
    if project is not None:
        clauses.append({"project": {"$eq": project}})
    if tier is not None:
        if tier not in VALID_TIERS:
            raise InvalidFilterValueError("tier", tier)
        clauses.append({"tier": {"$eq": tier}})
    if tags:
        for tag in tags:
            clauses.append({"tags": {"$eq": tag}})
    return clauses


async def run_search_loop(
    *,
    settings: Settings,
    vectors: VectorsClientInterface,
    query_vector: list[float],
    user_filters: list[dict[str, Any]],
    status_filter: dict[str, Any],
    effective_top_k: int,
) -> tuple[list[dict[str, Any]], bool] | dict[str, Any]:
    """Execute the deduplicating re-fetch loop over the vector index.

    Iterates up to ``settings.search_max_iterations`` times, accumulating
    distinct artifacts until ``effective_top_k`` is reached or the index
    is exhausted. Already-seen artifact IDs are excluded via ``$nin`` filter.

    M-6 (Phase 12 review): the ``$nin`` exclusion list is bounded by
    ``_NIN_EXCLUSION_BYTE_BUDGET`` — once it would grow past that budget the loop
    stops gracefully and returns whatever has been collected, rather than risking a
    filter-size error from S3 Vectors. Similarly, a **non-credential** failure from
    ``query_vectors`` mid-loop no longer discards already-collected results: it stops
    the loop and returns the partial result set. Credential-error handling is
    unchanged — it still returns the structured ``credential_error`` response
    immediately, even if some results were already collected.

    M-8 (Phase 12 review): ``query_vectors`` is a blocking boto3 call, so each
    iteration routes it through ``asyncio.to_thread`` — this coroutine must be
    awaited by every caller.

    07-02 #7: the fetch budget (``search_fetch_top_k × search_max_iterations``)
    can be smaller than the true number of distinct matching artifacts, so the
    loop may stop with fewer than ``effective_top_k`` results collected purely
    because it ran out of iterations or ``$nin`` budget — not because the index
    is actually exhausted. ``fetch_exhausted`` distinguishes that case (more
    matches may exist beyond what was fetched) from a genuine, natural
    exhaustion (a ``query_vectors`` call returned no new, not-yet-seen
    artifacts — i.e. there is nothing left to find).

    Args:
        settings: Server configuration.
        vectors: S3 Vectors client.
        query_vector: Embedded query vector.
        user_filters: Caller-supplied metadata filter clauses (type, team, tier, etc.).
        status_filter: Status gate filter (e.g. ``{"status": {"$eq": "active"}}``).
        effective_top_k: Maximum number of distinct artifacts to collect.

    Returns:
        On success (including a partial, non-credential-failure-truncated result):
            ``(list[dict], bool)`` — the result list (each dict has keys
            ``artifact_id``, ``score``, and ``meta``, the raw vector metadata
            dict) and a ``fetch_exhausted`` flag: ``True`` when the loop
            stopped due to its own iteration/``$nin`` budget while still
            finding new, unseen matches (more may exist beyond what was
            fetched); ``False`` when it stopped because ``effective_top_k``
            was reached or the index was naturally exhausted.
        On credential error: ``{"error": "credential_error", "message": str}``
    """
    scope_filter = build_scope_filter(settings)
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    fetch_exhausted = False

    for _ in range(settings.search_max_iterations):
        and_clauses: list[dict[str, Any]] = [*user_filters, status_filter, scope_filter]

        if seen_ids:
            nin_bytes = _nin_list_byte_size(seen_ids)
            if nin_bytes > _NIN_EXCLUSION_BYTE_BUDGET:
                logger.debug(
                    "Search re-fetch loop stopping: $nin exclusion list reached %d bytes "
                    "(budget %d) with %d result(s) already collected",
                    nin_bytes,
                    _NIN_EXCLUSION_BYTE_BUDGET,
                    len(results),
                )
                fetch_exhausted = len(results) < effective_top_k
                break
            and_clauses.append({"artifact_id": {"$nin": list(seen_ids)}})

        combined_filter: dict[str, Any] = (
            {"$and": and_clauses} if len(and_clauses) > 1 else and_clauses[0]
        )

        try:
            raw = await asyncio.to_thread(
                vectors.query_vectors, query_vector, settings.search_fetch_top_k, combined_filter
            )
        except CredentialError as exc:
            return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}
        except Exception:
            logger.warning(
                "Non-credential error in search re-fetch loop after collecting %d "
                "result(s); returning partial results",
                len(results),
                exc_info=True,
            )
            fetch_exhausted = len(results) < effective_top_k
            break

        # Keep highest-scoring section per artifact
        best_by_id: dict[str, tuple[float, dict[str, Any]]] = {}
        for item in raw:
            item_meta: dict[str, Any] = item["metadata"]
            aid: str = str(item_meta["artifact_id"])
            score: float = float(item["score"])
            if aid not in best_by_id or score > best_by_id[aid][0]:
                best_by_id[aid] = (score, item_meta)

        new_entries = [(aid, data) for aid, data in best_by_id.items() if aid not in seen_ids]

        if not new_entries:
            # Natural exhaustion: the index genuinely has nothing left to offer —
            # not a budget-truncation case.
            break

        for aid, (score, meta) in new_entries:
            results.append({"artifact_id": aid, "score": score, "meta": meta})
            seen_ids.add(aid)

        if len(results) >= effective_top_k:
            break
    else:
        # The for loop ran to completion (search_max_iterations reached) without
        # ever hitting one of the natural-stop breaks above, and each iteration up
        # to the last kept finding new, unseen matches — the iteration budget, not
        # the true match count, is what ended the loop.
        fetch_exhausted = len(results) < effective_top_k

    results.sort(key=lambda r: float(r["score"]), reverse=True)
    return results[:effective_top_k], fetch_exhausted


def find_referrers(
    *,
    vectors: VectorsClientInterface,
    settings: Settings,
    artifact_id: str,
) -> list[str]:
    """Reverse-look-up own-scope, active artifacts that reference ``artifact_id``.

    Generalizes ``delete_artifact``'s former synthesis-only check (ADR-012 D13, T50)
    into a single unified own-scope ``referenced_by`` lookup covering every field in
    :data:`cairn_mcp.artifact.REFERENCE_FIELDS`, reused by both ``delete_artifact`` and
    ``archive_artifact``. Both filterable and non-filterable reference fields are
    resolved with a **single** ``list_vectors_by_metadata`` query (Phase-12 #27 — this
    used to be two separate full-index scans): own-scope + active-status, ANDed with a
    top-level ``$or`` that combines one server-side ``{field: {"$eq": artifact_id}}``
    clause per filterable field (driven by
    :data:`cairn_mcp.artifact.NON_FILTERABLE_METADATA_KEYS` — never hardcoded per tool)
    with a bounded ``type = synthesis`` prefilter standing in for the non-filterable
    ``source_artifacts`` field, which S3 Vectors rejects a server-side ``$eq`` on. Each
    candidate returned by that one query is then checked in-process against every
    reference field it could plausibly match: filterable fields directly (the
    server-side ``$eq`` already guarantees a match for those, so this re-check is
    cheap confirmation, not new filtering), and ``source_artifacts`` only when
    ``type == "synthesis"``. A server-side ``$eq`` is never issued on
    ``source_artifacts``.

    Results are deduplicated by ``artifact_id``; the target itself is always excluded.

    Args:
        vectors: S3 Vectors client.
        settings: Server configuration (supplies the own-scope filter clause).
        artifact_id: The artifact about to be deleted or archived.

    Returns:
        Sorted list of distinct own-scope referrer ``artifact_id`` strings. Empty if
        no referrers are found.

    Raises:
        CredentialError: Propagated from the underlying vector client calls; callers
            are expected to catch it and return a structured credential error.
    """
    filterable_fields = [f for f in REFERENCE_FIELDS if f not in NON_FILTERABLE_METADATA_KEYS]
    non_filterable_fields = [f for f in REFERENCE_FIELDS if f in NON_FILTERABLE_METADATA_KEYS]
    # source_artifacts only ever appears on synthesis artifacts (bounded prefilter, not
    # an unbounded fetch-all-then-filter). No other non-filterable reference field is
    # currently defined; a future one requires its own field-appropriate prefilter.
    check_source_artifacts = "source_artifacts" in non_filterable_fields

    or_clauses: list[dict[str, Any]] = [
        {field: {"$eq": artifact_id}} for field in filterable_fields
    ]
    if check_source_artifacts:
        or_clauses.append({"type": {"$eq": "synthesis"}})

    if not or_clauses:
        return []

    filter_expr: dict[str, Any] = {
        "$and": [
            {"scope": {"$eq": settings.write_prefix}},
            {"status": {"$eq": ArtifactStatus.ACTIVE}},
            {"$or": or_clauses},
        ]
    }
    keys = vectors.list_vectors_by_metadata(filter_expr)
    referrers: set[str] = set()
    if keys:
        for item in vectors.get_vectors(keys, include_data=False):
            meta = item["metadata"]
            referrer_id = str(meta.get("artifact_id", ""))
            if not referrer_id or referrer_id == artifact_id:
                continue
            if any(artifact_id in coerce_list_field(meta, field) for field in filterable_fields):
                referrers.add(referrer_id)
            elif check_source_artifacts and meta.get("type") == "synthesis":
                if artifact_id in coerce_list_field(meta, "source_artifacts"):
                    referrers.add(referrer_id)

    return sorted(referrers)
