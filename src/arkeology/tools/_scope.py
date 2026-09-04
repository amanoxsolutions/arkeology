"""arkeology.tools._scope — the cross-scope access gate, and nothing else.

Sole home of the gate, in both of the forms it takes. Keeping them in one small
module is deliberate and load-bearing: it is what allows the mutation-testing
`only_mutate` list to cover AGENTS.md's whole declared Scope with two entries.
`only_mutate` accepts file globs, not function names, so a gate implementation
added to a larger module drops out of mutation coverage without anything failing.
Add gate logic here, and have call sites delegate.

- ``is_own_scope``: the mandatory own-scope membership test
  (``artifact_id.startswith(scope + "/")``) — AGENTS.md's own highest-friction
  correctness rule, previously re-typed at 10+ call sites with no structural guard
  against a future dropped ``"/"``.
- ``is_cross_scope_readable``: the gate as an in-process predicate, applied to a
  candidate already fetched (own-scope always readable; foreign-scope readable iff
  ``tier == 3`` and ``visibility == "shared"``). Used by the read and delete paths.
  Previously hand-rolled in ``list.py``, ``freshness.py``, ``read.py``, and
  ``_reference_filter.py``.
- ``build_scope_filter``: the same rule as a server-side S3 Vectors filter, so
  foreign candidates failing the gate are never fetched. Used by the search,
  synthesise, and list paths.

The two gate forms must agree on every candidate; the agreement is pinned by a
test in ``tests/unit/test_tools__scope.py`` rather than left to review.
"""

from typing import Any


def is_own_scope(artifact_id: str, scope: str) -> bool:
    """Return True if artifact_id belongs to scope.

    Always uses ``scope + "/"`` as the prefix — never a bare ``startswith(scope)`` —
    so a scope of ``"team-a"`` never incorrectly matches an artifact_id under
    ``"team-abc/"`` (AGENTS.md's highest-friction correctness rule).

    Args:
        artifact_id: Full S3 key (or vector ``artifact_id``) to test.
        scope: The scope prefix to test membership against (a write_prefix or a
            single entry from read_prefixes_list — no trailing slash).

    Returns:
        True if artifact_id starts with ``scope + "/"``.
    """
    return artifact_id.startswith(scope + "/")


def is_cross_scope_readable(
    meta: dict[str, Any],
    artifact_id: str,
    own_scope: str,
    read_prefixes: list[str],
) -> bool:
    """Return True if artifact_id/meta is readable under the standard cross-scope gate.

    A candidate is readable when:
    - It is in the caller's own scope (``is_own_scope(artifact_id, own_scope)``) —
      always readable, regardless of tier/visibility.
    - It is in a foreign scope (matches one of ``read_prefixes``) **and** its
      stored ``tier == 3`` **and** ``visibility == "shared"``.

    Any other artifact_id (own-scope mismatch and no matching foreign prefix) is
    not readable.

    Args:
        meta: The candidate's metadata dict (vector or S3 object metadata) —
            only consulted when artifact_id is not in own scope.
        artifact_id: The candidate's full S3 key / vector ``artifact_id``.
        own_scope: The caller's own write_prefix.
        read_prefixes: The caller's configured foreign read prefixes.

    Returns:
        True if the candidate is readable under the cross-scope gate.
    """
    if is_own_scope(artifact_id, own_scope):
        return True
    is_foreign = any(is_own_scope(artifact_id, prefix) for prefix in read_prefixes)
    tier = int(meta.get("tier", 0))
    visibility = str(meta.get("visibility", ""))
    return is_foreign and tier == 3 and visibility == "shared"


def build_scope_filter(own_scope: str, read_prefixes: list[str]) -> dict[str, Any]:
    """Return the same gate as ``is_cross_scope_readable``, as an S3 Vectors filter.

    ``is_cross_scope_readable`` gates one candidate already in hand; this gates the
    query itself, so foreign artifacts that fail the gate are never fetched. The search,
    synthesise, and list paths all filter server-side with this. Both forms must reach
    the same verdict on the same candidate — see the agreement test in
    ``tests/unit/test_tools__scope.py``.

    Own-scope artifacts are always included. Foreign-scope artifacts are included only
    when ``tier == 3`` **and** ``visibility == "shared"``. Dropping either clause fails
    **open** — foreign tier-2 or ``hidden`` artifacts become reachable from another
    scope — which is why both are pinned by direct tests rather than only exercised
    through the tool suites.

    Args:
        own_scope: The caller's own write_prefix (no trailing slash).
        read_prefixes: The caller's configured foreign read prefixes. Empty means no
            foreign artifact is admissible at all.

    Returns:
        A metadata filter dict suitable for passing to ``query_vectors``.
    """
    if read_prefixes:
        return {
            "$or": [
                {"scope": {"$eq": own_scope}},
                {
                    "$and": [
                        {"scope": {"$in": read_prefixes}},
                        {"tier": {"$eq": 3}},
                        {"visibility": {"$eq": "shared"}},
                    ]
                },
            ]
        }
    return {"scope": {"$eq": own_scope}}
