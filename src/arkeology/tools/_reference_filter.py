"""arkeology.tools._reference_filter — cross-scope references-field access control.

Shared predicate for filtering the ``references`` field on cross-scope reads
(ADR-012, "Cross-scope reference filtering"). Both read_artifact and
list_artifacts delegate to resolve_readable_targets() so the readability rule
is defined in exactly one place.
"""

import asyncio
from typing import Any

from arkeology.clients.interfaces import VectorsClientInterface
from arkeology.config import Settings
from arkeology.tools._scope import is_cross_scope_readable, is_own_scope
from arkeology.tools._search_helper import fetch_vectors_by_artifact_ids


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

    A **foreign-scope** candidate with no matching vector entry (deleted, never
    existed, or not yet indexed) is excluded from the returned set — not
    readable, fail safe.

    This does **not** hold for own-scope candidates, and deliberately so. They
    are admitted on prefix match alone, without any existence check, so a
    reference naming an own-scope artifact that has since been deleted is
    returned as readable and presented as a live link. That is a dangling-link
    accuracy limitation, not a confidentiality one — the target is in the
    caller's own scope either way — and it is the price of the own-scope
    short-circuit below, which is what keeps an all-own-scope candidate set at
    zero vector-client calls.

    Own-scope candidates are resolved by prefix alone (no vector-client call
    needed, mirroring read_artifact's Step 1 scope gate). The remaining
    candidates are resolved by batched ``$in`` lookups on ``artifact_id``, so the
    whole candidate set costs one round trip per chunk rather than one per
    candidate. The candidate set is caller-supplied and unbounded, so the
    ``$in`` list is chunked to the filter-expression byte budget S3 Vectors
    enforces — see ``fetch_vectors_by_artifact_ids``.

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
        if is_own_scope(candidate_id, own_scope):
            readable.add(candidate_id)
        else:
            unresolved.add(candidate_id)

    if not unresolved:
        return readable

    # Off the event loop — blocking boto3 calls.
    items = await asyncio.to_thread(fetch_vectors_by_artifact_ids, vectors, unresolved)
    for item in items:
        meta: dict[str, Any] = item.get("metadata", {})
        candidate_id = str(meta.get("artifact_id", ""))
        if candidate_id not in unresolved:
            continue

        if is_cross_scope_readable(meta, candidate_id, own_scope, read_prefixes):
            readable.add(candidate_id)

    return readable
