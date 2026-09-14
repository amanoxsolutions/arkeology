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
  most foreign candidates failing the gate are never fetched. Used by the search,
  synthesise, and list paths.

The two forms are **not peers**. ``is_cross_scope_readable`` is the authority and every
read path runs it; ``build_scope_filter`` is a prefetch optimisation. The filter may
admit more than the predicate does — ``$eq`` is value-in-list for a list-valued field,
so a non-scalar ``tier`` matches its clause — and that is harmless, because the
predicate then denies it. A filter that admitted *less* would be the bug, since the
candidate would never be fetched for the predicate to see. That one direction is pinned
by a test in ``tests/unit/test_tools__scope.py`` rather than left to review.
"""

from typing import Any


def coerce_tier(value: Any) -> int | None:
    """Coerce a stored ``tier`` value to an int, or ``None`` when it will not coerce.

    The coercion is required, not defensive: ``read_artifact`` hands the gate S3 object
    metadata, where ``tier`` is a stringified integer, while the listing, search, and
    freshness paths hand it vector metadata, where ``tier`` is an ``int``. The two
    encodings are deliberate and must not be unified, so this is what reconciles them.

    Returning ``None`` rather than raising is what makes the gate *total*. This runs over
    data this deployment did not write, per candidate inside a loop, so an absent,
    non-numeric, non-scalar, or infinite value used to raise and take down the whole call
    rather than answer for one candidate. An exception is neither an allow nor a deny.

    It lives here, beside the gate it feeds, because the same three-way coercion is also
    what ``build_artifact_summary`` and ``read_artifact`` need — and the identical guard
    was independently wrong in all three before it was shared.
    """
    try:
        return int(value)
    except TypeError, ValueError, OverflowError:
        # OverflowError is the infinite case: int(float("inf")) raises it rather than
        # ValueError, which int(float("nan")) does.
        return None


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

    Never raises for any value in ``meta``. An absent, non-numeric, or non-scalar
    ``tier``, and an absent or non-string ``visibility``, are not an affirmative
    reading of the rule and deny the candidate. Denial is silent and uncounted: naming
    a denied foreign candidate would disclose the existence the gate exists to
    withhold.

    Returns:
        True if the candidate is readable under the cross-scope gate.
    """
    if is_own_scope(artifact_id, own_scope):
        return True
    is_foreign = any(is_own_scope(artifact_id, prefix) for prefix in read_prefixes)
    # ``visibility`` is compared as stored rather than through ``str()``: coercing would
    # admit any object whose text happens to read "shared", a value no writer ever
    # stored and one the server-side filter form would never match.
    return is_foreign and coerce_tier(meta.get("tier")) == 3 and meta.get("visibility") == "shared"


def build_scope_filter(own_scope: str, read_prefixes: list[str]) -> dict[str, Any]:
    """Return the same gate as ``is_cross_scope_readable``, as an S3 Vectors filter.

    ``is_cross_scope_readable`` decides one candidate already in hand and is the
    authority; this narrows the query itself so most foreign artifacts that fail the gate
    are never fetched. The search, synthesise, and list paths all filter server-side with
    this *and* run the predicate over what comes back. This filter may admit more than
    the predicate does (``$eq`` is value-in-list for a list-valued field, which ``tags``
    requires, so a non-scalar ``tier`` matches its clause); it must never admit less —
    see ``test_never_rejects_a_candidate_the_predicate_would_admit``.

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
