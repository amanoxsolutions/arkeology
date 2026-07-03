"""cairn_mcp.tools._search_helper — shared vector re-fetch loop for search and synthesise.

This private module contains the scope-filter construction and deduplicating
re-fetch loop shared between search_artifacts and synthesise_artifacts. Both
tools call _run_search_loop with their respective parameters; tool-specific
logic (content fetching, response shape) is handled by each tool independently.
"""

from typing import Any

from cairn_mcp.artifact import NON_FILTERABLE_METADATA_KEYS, REFERENCE_FIELDS
from cairn_mcp.clients.interfaces import VectorsClientInterface
from cairn_mcp.config import Settings
from cairn_mcp.constants import ArtifactStatus, ErrorCode
from cairn_mcp.errors import CredentialError


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
        type: Optional artifact type filter.
        team: Optional team filter.
        project: Optional project filter.
        tier: Optional tier filter.
        tags: Optional list of tags; all must match (AND semantics).

    Returns:
        A list of metadata filter clause dicts.
    """
    clauses: list[dict[str, Any]] = []
    if type is not None:
        clauses.append({"type": {"$eq": type}})
    if team is not None:
        clauses.append({"team": {"$eq": team}})
    if project is not None:
        clauses.append({"project": {"$eq": project}})
    if tier is not None:
        clauses.append({"tier": {"$eq": tier}})
    if tags:
        for tag in tags:
            clauses.append({"tags": {"$eq": tag}})
    return clauses


def run_search_loop(
    *,
    settings: Settings,
    vectors: VectorsClientInterface,
    query_vector: list[float],
    user_filters: list[dict[str, Any]],
    status_filter: dict[str, Any],
    effective_top_k: int,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Execute the deduplicating re-fetch loop over the vector index.

    Iterates up to ``settings.search_max_iterations`` times, accumulating
    distinct artifacts until ``effective_top_k`` is reached or the index
    is exhausted. Already-seen artifact IDs are excluded via ``$nin`` filter.

    Args:
        settings: Server configuration.
        vectors: S3 Vectors client.
        query_vector: Embedded query vector.
        user_filters: Caller-supplied metadata filter clauses (type, team, tier, etc.).
        status_filter: Status gate filter (e.g. ``{"status": {"$eq": "active"}}``).
        effective_top_k: Maximum number of distinct artifacts to collect.

    Returns:
        On success: ``list[dict]`` — each dict has keys ``artifact_id``, ``score``,
            and ``meta`` (the raw vector metadata dict).
        On credential error: ``{"error": "credential_error", "message": str}``
    """
    scope_filter = build_scope_filter(settings)
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []

    for _ in range(settings.search_max_iterations):
        and_clauses: list[dict[str, Any]] = [*user_filters, status_filter, scope_filter]

        if seen_ids:
            and_clauses.append({"artifact_id": {"$nin": list(seen_ids)}})

        combined_filter: dict[str, Any] = (
            {"$and": and_clauses} if len(and_clauses) > 1 else and_clauses[0]
        )

        try:
            raw = vectors.query_vectors(query_vector, settings.search_fetch_top_k, combined_filter)
        except CredentialError as exc:
            return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)}

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
            break

        for aid, (score, meta) in new_entries:
            results.append({"artifact_id": aid, "score": score, "meta": meta})
            seen_ids.add(aid)

        if len(results) >= effective_top_k:
            break

    results.sort(key=lambda r: float(r["score"]), reverse=True)
    return results[:effective_top_k]


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
    ``archive_artifact``. The lookup branches by each field's filterability, driven by
    :data:`cairn_mcp.artifact.NON_FILTERABLE_METADATA_KEYS` — never hardcoded per tool:

    - **Filterable** fields (currently ``references``) are resolved with a single
      ``list_vectors_by_metadata`` query ANDing the own-scope filter, the active-status
      filter, and an ``$or`` of one ``{field: {"$eq": artifact_id}}`` clause per
      filterable field.
    - **Non-filterable** ``source_artifacts`` — which S3 Vectors rejects a server-side
      ``$eq`` on — is resolved via a bounded, filterable ``type = synthesis`` prefilter
      (own-scope, active) fetched via ``list_vectors_by_metadata``, followed by an
      in-process membership check of ``artifact_id`` in each candidate's
      ``source_artifacts`` value. A server-side ``$eq`` is never issued on
      ``source_artifacts``.

    Results from both branches are unioned and deduplicated by ``artifact_id``; the
    target itself is always excluded.

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

    referrers: set[str] = set()

    # ── Filterable branch: single server-side $eq/$or query ──────────────────────
    if filterable_fields:
        filter_expr: dict[str, Any] = {
            "$and": [
                {"scope": {"$eq": settings.write_prefix}},
                {"status": {"$eq": ArtifactStatus.ACTIVE}},
                {"$or": [{field: {"$eq": artifact_id}} for field in filterable_fields]},
            ]
        }
        keys = vectors.list_vectors_by_metadata(filter_expr)
        if keys:
            for item in vectors.get_vectors(keys):
                referrer_id = str(item["metadata"].get("artifact_id", ""))
                if referrer_id and referrer_id != artifact_id:
                    referrers.add(referrer_id)

    # ── Non-filterable branch: type=synthesis prefilter + in-process check ───────
    # source_artifacts only ever appears on synthesis artifacts (bounded prefilter,
    # not an unbounded fetch-all-then-filter). No other non-filterable reference field
    # is currently defined; a future one requires its own field-appropriate prefilter.
    if "source_artifacts" in non_filterable_fields:
        prefilter: dict[str, Any] = {
            "$and": [
                {"type": {"$eq": "synthesis"}},
                {"status": {"$eq": ArtifactStatus.ACTIVE}},
                {"scope": {"$eq": settings.write_prefix}},
            ]
        }
        keys = vectors.list_vectors_by_metadata(prefilter)
        if keys:
            for item in vectors.get_vectors(keys):
                meta = item["metadata"]
                referrer_id = str(meta.get("artifact_id", ""))
                if referrer_id == artifact_id:
                    continue
                if artifact_id in coerce_list_field(meta, "source_artifacts"):
                    referrers.add(referrer_id)

    return sorted(referrers)
