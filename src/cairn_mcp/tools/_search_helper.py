"""cairn_mcp.tools._search_helper — shared vector re-fetch loop for search and synthesise.

This private module contains the scope-filter construction and deduplicating
re-fetch loop shared between search_artifacts and synthesise_artifacts. Both
tools call _run_search_loop with their respective parameters; tool-specific
logic (content fetching, response shape) is handled by each tool independently.
"""

from typing import Any

from cairn_mcp.clients.interfaces import VectorsClientInterface
from cairn_mcp.config import Settings
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
            return {"error": "credential_error", "message": str(exc)}

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
