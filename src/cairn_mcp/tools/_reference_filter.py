"""cairn_mcp.tools._reference_filter — cross-scope references-field access control.

Shared predicate for filtering the ``references`` field on cross-scope reads
(ADR-012, "Cross-scope reference filtering"). Both read_artifact and
list_artifacts delegate to resolve_readable_targets() so the readability rule
is defined in exactly one place.
"""

import asyncio
from typing import Any

from cairn_mcp.clients.interfaces import VectorsClientInterface
from cairn_mcp.config import Settings


async def resolve_readable_targets(
    vectors: VectorsClientInterface,
    settings: Settings,
    candidate_ids: set[str],
) -> set[str]:
    """Resolve which of candidate_ids are readable by the current scope.

    A candidate is readable when:
    - It is in the caller's own scope (``candidate_id`` starts with
      ``write_prefix/``) — always readable, regardless of tier/visibility.
    - It is in a foreign scope **and** its stored ``tier == 3`` **and**
      ``visibility == "shared"``.

    A candidate with no matching vector entry (deleted, never existed, or not
    yet indexed) is excluded from the returned set — not readable, fail safe.

    Own-scope candidates are resolved by prefix alone (no vector-client call
    needed, mirroring read_artifact's Step 1 scope gate). The remaining
    candidates are resolved via a single batched ``list_vectors_by_metadata``
    query (using an ``$in`` filter on ``artifact_id``) followed by one
    ``get_vectors`` call, so the whole candidate set costs at most one
    additional round trip regardless of size.

    Args:
        vectors: S3 Vectors client.
        settings: Server configuration (own/foreign scope prefixes).
        candidate_ids: Bare artifact IDs to resolve.

    Returns:
        The subset of candidate_ids that are readable by the current scope.
    """
    if not candidate_ids:
        return set()

    own_scope = settings.write_prefix
    read_prefixes = settings.read_prefixes_list

    readable: set[str] = set()
    unresolved: set[str] = set()
    for candidate_id in candidate_ids:
        if candidate_id.startswith(own_scope + "/"):
            readable.add(candidate_id)
        else:
            unresolved.add(candidate_id)

    if not unresolved:
        return readable

    # M-8: off the event loop — blocking boto3 calls.
    keys = await asyncio.to_thread(
        vectors.list_vectors_by_metadata, {"artifact_id": {"$in": sorted(unresolved)}}
    )
    if not keys:
        return readable

    items = await asyncio.to_thread(vectors.get_vectors, keys)
    for item in items:
        meta: dict[str, Any] = item.get("metadata", {})
        candidate_id = str(meta.get("artifact_id", ""))
        if candidate_id not in unresolved:
            continue

        is_foreign = any(candidate_id.startswith(p + "/") for p in read_prefixes)
        tier = int(meta.get("tier", 0))
        visibility = str(meta.get("visibility", ""))
        if is_foreign and tier == 3 and visibility == "shared":
            readable.add(candidate_id)

    return readable
