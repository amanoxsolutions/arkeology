"""arkeology.tools._search_helper — shared vector re-fetch loop for search and synthesise.

This private module contains the deduplicating re-fetch loop shared between
search_artifacts and synthesise_artifacts. Both tools call run_search_loop with
their respective parameters; tool-specific logic (content fetching, response
shape) is handled by each tool independently.

The cross-scope scope filter is *not* built here — ``run_search_loop`` delegates
to ``_scope.build_scope_filter``, so every implementation of the access gate stays
in ``_scope.py`` and inside the declared mutation-testing Scope.
"""

import asyncio
import json
import logging
from collections.abc import Collection
from typing import Any

from ulid import ULID

from arkeology.artifact import (
    ARTIFACT_TYPES,
    NON_FILTERABLE_METADATA_KEYS,
    REFERENCE_FIELDS,
    VALID_TIERS,
)
from arkeology.clients.interfaces import VectorsClientInterface
from arkeology.config import Settings
from arkeology.constants import ArtifactStatus, ErrorCode
from arkeology.errors import (
    CredentialError,
    InvalidFilterValueError,
    VectorDistanceMissingError,
)
from arkeology.tools._scope import build_scope_filter

logger = logging.getLogger(__name__)

# S3 Vectors query_vectors topK request ceiling — a requested top_k above this is
# clamped down rather than rejected outright.
_TOP_K_CEILING = 100

# Conservative half of the ~2 KB S3 Vectors metadata-filter expression size limit
# (mirrors the order of magnitude of VECTOR_FILTERABLE_METADATA_MAX_BYTES in
# artifact.py), leaving headroom in the same $and for the user/status/scope filter
# clauses. Once the $nin exclusion list would grow past this budget, the re-fetch
# loop stops issuing further queries and returns whatever has
# already been collected rather than risking a ValidationException from an oversized
# filter expression.
_NIN_EXCLUSION_BYTE_BUDGET = 1024


def _id_list_byte_size(artifact_ids: Collection[str]) -> int:
    """Return the UTF-8 byte size of ``artifact_ids`` as it appears in a $nin/$in clause."""
    return len(json.dumps(list(artifact_ids)).encode("utf-8"))


def fetch_vectors_by_metadata(
    vectors: VectorsClientInterface,
    filter_expr: dict[str, Any],
    *,
    include_data: bool = False,
) -> list[dict[str, Any]]:
    """Fetch vector entries matching a metadata filter: the ``list_vectors_by_metadata``
    → ``get_vectors`` two-step idiom, consolidated so every call site short-circuits
    identically on an empty key list rather than issuing a pointless ``get_vectors([])``
    call.

    Args:
        vectors: S3 Vectors client.
        filter_expr: Metadata filter expression passed to ``list_vectors_by_metadata``.
        include_data: Whether to include each vector's float32 embedding in the result
            (passed through to ``get_vectors``). Defaults to False.

    Returns:
        The list of matching vector entries (``{"key", "metadata", ...}``, plus
        ``"data"`` when ``include_data=True``). Empty when no keys match.

    Raises:
        CredentialError: Propagated unchanged from either underlying call.
    """
    keys = vectors.list_vectors_by_metadata(filter_expr)
    if not keys:
        return []
    return vectors.get_vectors(keys, include_data=include_data)


def fetch_vectors_by_artifact_ids(
    vectors: VectorsClientInterface,
    artifact_ids: Collection[str],
    *,
    include_data: bool = False,
) -> list[dict[str, Any]]:
    """Fetch every vector entry whose ``artifact_id`` is one of ``artifact_ids``, split
    across as many ``$in`` queries as the filter-expression byte budget requires.

    S3 Vectors rejects an oversized metadata-filter expression, so an ``$in`` list built
    from a caller-supplied set with no natural bound — a page's ``references``, every
    synthesis's ``source_artifacts`` — has to be chunked exactly as ``run_search_loop``
    bounds its ``$nin`` list, and against the same ``_NIN_EXCLUSION_BYTE_BUDGET``. A
    single id longer than the whole budget still gets its own query rather than
    producing an empty chunk forever.

    Args:
        vectors: S3 Vectors client.
        artifact_ids: The artifact IDs to resolve. Order is normalised (sorted) so the
            chunk boundaries are deterministic.
        include_data: Whether to include each vector's float32 embedding in the result.

    Returns:
        The concatenated matches across every chunk. Empty when ``artifact_ids`` is.

    Raises:
        CredentialError: Propagated unchanged from any underlying call.
    """
    items: list[dict[str, Any]] = []
    chunk: list[str] = []

    def _flush() -> None:
        if chunk:
            items.extend(
                fetch_vectors_by_metadata(
                    vectors, {"artifact_id": {"$in": chunk}}, include_data=include_data
                )
            )

    for artifact_id in sorted(artifact_ids):
        if chunk and _id_list_byte_size([*chunk, artifact_id]) > _NIN_EXCLUSION_BYTE_BUDGET:
            _flush()
            chunk = []
        chunk.append(artifact_id)
    _flush()
    return items


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


def derive_last_edited_at(last_edited_ulid: str | None) -> str | None:
    """Derive an ISO 8601 timestamp from a ``last_edited_ulid``.

    A ULID encodes its creation timestamp in its first 48 bits — this decodes it.
    Returns ``None`` for a falsy input (no ULID recorded) or a malformed ULID that
    fails to parse (logged as a warning; the caller degrades to a null timestamp
    rather than failing the whole call over a transparency-only field).

    Args:
        last_edited_ulid: The raw ULID string, or ``None``/empty.

    Returns:
        An ISO 8601 timestamp string, or ``None``.
    """
    if not last_edited_ulid:
        return None
    try:
        return ULID.from_str(last_edited_ulid).datetime.isoformat()
    except Exception:
        logger.warning("Malformed last_edited_ulid %r — timestamp will be null", last_edited_ulid)
        return None


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
            ``tier`` is not 2 or 3 — a typo'd/out-of-range filter
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


def build_artifact_summary(
    meta: dict[str, Any],
    artifact_id: str,
    tags_val: list[str],
    source_artifacts_val: list[str],
) -> dict[str, Any]:
    """Build the ~14-key artifact summary dict shared by ``list_artifacts`` and
    ``search_artifacts``.

    Both tools construct this same set of fields from vector metadata; each layers
    its own extra keys on top (``list_artifacts`` adds ``commit_refs``/``references``;
    ``search_artifacts`` adds ``score``/``last_edited_at``).

    Args:
        meta: Raw vector metadata for the artifact.
        artifact_id: The artifact's id.
        tags_val: Already-coerced ``tags`` list (see ``coerce_list_field``).
        source_artifacts_val: Already-coerced ``source_artifacts`` list.

    Returns:
        A dict with the 14 shared summary keys.
    """
    return {
        "artifact_id": artifact_id,
        "type": meta.get("type"),
        "team": meta.get("team"),
        "project": meta.get("project"),
        "tier": int(meta.get("tier", 0)),
        "date": meta.get("date"),
        "status": meta.get("status"),
        "title": meta.get("title"),
        "visibility": meta.get("visibility"),
        "tags": tags_val,
        "author_role": meta.get("author_role") or None,
        "description": meta.get("description"),
        "source_artifacts": source_artifacts_val,
        "last_edited_ulid": meta.get("last_edited_ulid") or None,
    }


def clamp_top_k(top_k: int) -> tuple[int, bool] | dict[str, Any]:
    """Validate and clamp a caller-supplied ``top_k``.

    Mirrors the identical rejection-and-clamp logic previously duplicated in
    ``search.py`` and ``synthesise.py``: a non-positive ``top_k`` is rejected; any
    other value is capped at the S3 Vectors ``query_vectors`` topK ceiling.

    Args:
        top_k: The caller-requested top_k (already defaulted by the caller).

    Returns:
        On success: ``(effective_top_k, clamped)`` where ``clamped`` is True when
        the requested value exceeded the ceiling. On rejection (``top_k <= 0``):
        the same ``{"error": ErrorCode.VALIDATION_ERROR, "message": str}`` dict
        shape callers already return directly to the MCP caller.
    """
    if top_k <= 0:
        return {
            "error": ErrorCode.VALIDATION_ERROR,
            "message": f"top_k must be a positive integer, got {top_k}",
        }
    effective_top_k = min(top_k, _TOP_K_CEILING)
    clamped = effective_top_k < top_k
    return effective_top_k, clamped


async def run_search_loop(
    *,
    settings: Settings,
    vectors: VectorsClientInterface,
    query_vector: list[float],
    user_filters: list[dict[str, Any]],
    status_filter: dict[str, Any] | None,
    effective_top_k: int,
) -> tuple[list[dict[str, Any]], bool, bool] | dict[str, Any]:
    """Execute the deduplicating re-fetch loop over the vector index.

    Iterates up to ``settings.search_max_iterations`` times, accumulating
    distinct artifacts until ``effective_top_k`` is reached or the index
    is exhausted. Already-seen artifact IDs are excluded via ``$nin`` filter.

    The ``$nin`` exclusion list is bounded by ``_NIN_EXCLUSION_BYTE_BUDGET`` — once it
    would grow past that budget the loop stops gracefully and returns whatever has been
    collected, rather than risking a filter-size error from S3 Vectors. Similarly, a
    **non-credential** failure from ``query_vectors`` mid-loop stops the loop and returns
    the partial result set rather than discarding already-collected results. A credential
    error is the one exception: it returns the structured ``credential_error`` response
    immediately, even if some results were already collected, because every subsequent
    iteration would fail the same way.

    ``VectorDistanceMissingError`` (raised by the vectors client when a
    ``query_vectors`` result is missing its ``distance`` field — a signal of possible
    S3 Vectors index corruption, per the exception's own docstring) is a **soft**
    signal, not a hard abort: it is logged distinctly from an ordinary non-credential
    failure (a different message, at ``ERROR`` not ``WARNING``, so it is
    grep/alertable and doesn't blend into transient-error noise) and otherwise handled
    exactly like a non-credential failure — the loop stops and whatever partial results
    were already collected are returned. The returned ``index_corruption_detected`` flag
    tells the caller this happened, without ever aborting the call.

    ``query_vectors`` is a blocking boto3 call, so each iteration routes it through
    ``asyncio.to_thread`` — this coroutine must be awaited by every caller.

    The fetch budget (``search_fetch_top_k × search_max_iterations``)
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
        status_filter: Status gate filter (e.g. ``{"status": {"$eq": "active"}}``), or
            ``None`` to omit the status clause entirely (the caller's ``status="all"``
            sentinel).
        effective_top_k: Maximum number of distinct artifacts to collect.

    Returns:
        On success (including a partial, non-credential-failure-truncated result):
            ``(list[dict], bool, bool)`` — the result list (each dict has keys
            ``artifact_id``, ``score``, and ``meta``, the raw vector metadata
            dict), a ``fetch_exhausted`` flag: ``True`` when the loop
            stopped due to its own iteration/``$nin`` budget while still
            finding new, unseen matches (more may exist beyond what was
            fetched); ``False`` when it stopped because ``effective_top_k``
            was reached or the index was naturally exhausted; and an
            ``index_corruption_detected`` flag: ``True`` when the loop stopped
            because ``query_vectors`` raised ``VectorDistanceMissingError``
            mid-loop, ``False`` otherwise.
        On credential error: ``{"error": "credential_error", "message": str}``
    """
    scope_filter = build_scope_filter(settings.write_prefix, settings.read_prefixes_list)
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    fetch_exhausted = False
    index_corruption_detected = False

    for _ in range(settings.search_max_iterations):
        and_clauses: list[dict[str, Any]] = [*user_filters, scope_filter]
        if status_filter is not None:
            and_clauses.append(status_filter)

        if seen_ids:
            nin_bytes = _id_list_byte_size(seen_ids)
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
        except VectorDistanceMissingError:
            # Distinct from the generic non-credential branch below: this signals
            # possible S3 Vectors index corruption (see the exception's own
            # docstring), so it is logged at ERROR with its own grep/alertable
            # message rather than blending into ordinary transient-error WARNING
            # noise. Still a soft signal — the loop stops and whatever partial
            # results were already collected are returned, exactly like a
            # non-credential failure; the call is never aborted for this reason.
            logger.error(
                "Vector distance missing in search re-fetch loop after collecting %d "
                "result(s) — possible S3 Vectors index corruption; returning partial "
                "results",
                len(results),
                exc_info=True,
            )
            index_corruption_detected = True
            fetch_exhausted = len(results) < effective_top_k
            break
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
    return results[:effective_top_k], fetch_exhausted, index_corruption_detected


def find_referrers(
    *,
    vectors: VectorsClientInterface,
    settings: Settings,
    artifact_id: str,
) -> list[str]:
    """Reverse-look-up own-scope, active artifacts that reference ``artifact_id``.

    Generalizes ``delete_artifact``'s former synthesis-only check (ADR-012 D13, T50)
    into a single unified own-scope ``referenced_by`` lookup covering every field in
    :data:`arkeology.artifact.REFERENCE_FIELDS`, reused by both ``delete_artifact`` and
    ``archive_artifact``. Both filterable and non-filterable reference fields are
    resolved with a **single** ``list_vectors_by_metadata`` query — never two separate
    full-index scans: own-scope + active-status, ANDed with a
    top-level ``$or`` that combines one server-side ``{field: {"$eq": artifact_id}}``
    clause per filterable field (driven by
    :data:`arkeology.artifact.NON_FILTERABLE_METADATA_KEYS` — never hardcoded per tool)
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
    referrers: set[str] = set()
    for item in fetch_vectors_by_metadata(vectors, filter_expr, include_data=False):
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
