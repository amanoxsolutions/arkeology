"""arkeology.tools._scope — shared scope-check predicates.

Centralises the two scope-related checks previously re-implemented independently
at each call site across the tool modules (review findings I-3 and F-1):

- ``is_own_scope``: the mandatory own-scope membership test
  (``artifact_id.startswith(scope + "/")``) — AGENTS.md's own highest-friction
  correctness rule, manually re-typed at 10+ call sites with no structural guard
  against a future dropped ``"/"``.
- ``is_cross_scope_readable``: the cross-scope readability predicate (own-scope
  always readable; foreign-scope readable iff ``tier == 3`` and
  ``visibility == "shared"``), independently hand-rolled in ``list.py``,
  ``freshness.py``, ``read.py``, and ``_reference_filter.py``.
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
