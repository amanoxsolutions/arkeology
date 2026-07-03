"""cairn_mcp.references — pure migration reference resolution helpers.

This module is AWS-free and I/O-free, matching ``artifact.py``'s posture. It implements
the ADR-012 (D4/D6) algorithm the ``migrating-to-cairn`` skill uses to carry
frontmatter ``references:`` path entries across the file-path -> ``artifact_id``
addressing boundary:

1. Build a single authoritative path -> ``artifact_id`` map from the FULL migration
   manifest, before any writes, using the pure :func:`cairn_mcp.artifact.generate_artifact_id`
   (:func:`build_path_to_id_map`). Because id generation is a pure function of
   type + title (+ date for tier 2), a target's future identifier is computable
   as soon as its manifest entry is known — this makes same-batch and multi-session
   forward references resolve regardless of write order.
2. Normalize a candidate reference path against a small, deliberately BOUNDED ceiling
   (:func:`normalize_reference_path`): backslash -> forward slash, then strip only a
   leading ``./``, a single leading ``/``, or neither. No further repair is attempted —
   genuinely broken/inconsistent source references are surfaced to the operator, not
   fixed (ADR-012 D6).
3. Resolve a reference against the map (:func:`resolve_reference`), treating
   ``http://`` / ``https://`` entries as never-path candidates and returning ``None``
   for anything absent from the map after the bounded normalization above.

Relative (``../``) path navigation is deliberately out of this bounded ceiling: joining
a reference against the referencing file's own directory (if needed) is the skill's
responsibility, performed in-context before calling these helpers, not something this
module infers.

The ``migrating-to-cairn`` skill documents and drives this exact algorithm (OQ-T51-a) —
this module is the authoritative, unit-tested reference implementation; do not
reimplement the algorithm elsewhere.
"""

from typing import TypedDict

from cairn_mcp.artifact import generate_artifact_id

# URL schemes that are always left untouched and never treated as a path candidate
# (ADR-012 D5).
_URL_PREFIXES: tuple[str, ...] = ("http://", "https://")


class ManifestEntry(TypedDict):
    """One resolved migration manifest entry, as consumed by :func:`build_path_to_id_map`.

    Attributes:
        path: Repo-relative file path, exactly as it appears in the manifest / a
            ``references:`` entry once normalized.
        type: Artifact type (see :data:`cairn_mcp.artifact.ARTIFACT_TYPES`).
        tier: 2 or 3.
        title: The artifact's resolved title (already extracted from frontmatter,
            an H1 heading, or the filename by the time the map is built).
        date: ISO-8601 date string. Required even for tier 3 entries because
            :func:`cairn_mcp.artifact.generate_artifact_id` always validates it,
            even though tier 3 ids do not encode it.
    """

    path: str
    type: str
    tier: int
    title: str
    date: str


def normalize_reference_path(path: str) -> str:
    """Apply the bounded (D6) normalization ceiling to a candidate reference path.

    Converts backslashes to forward slashes, then strips exactly one of: a leading
    ``./``, a single leading ``/``, or neither — whichever applies. No other
    transformation is attempted; a path that would only match after further repair
    (e.g. ``../`` relative navigation) is returned unchanged and falls through to the
    caller's unresolved handling.

    Args:
        path: The raw reference path text (as written in source frontmatter).

    Returns:
        The normalized path, suitable for a direct lookup in a path -> ``artifact_id``
        map built by :func:`build_path_to_id_map`.
    """
    slashed = path.replace("\\", "/")
    if slashed.startswith("./"):
        return slashed[2:]
    if slashed.startswith("/"):
        return slashed[1:]
    return slashed


def build_path_to_id_map(manifest_entries: list[ManifestEntry]) -> dict[str, str]:
    """Build a path -> ``artifact_id`` map from the FULL migration manifest (ADR-012 D4).

    Must be called with every manifest entry, of any status, across sessions — not just
    the subset currently being written or retried — so that forward references (a file
    referencing a sibling scheduled later in the same batch, or in an earlier/later
    session) always resolve regardless of write order. Each identifier is computed via
    the pure :func:`cairn_mcp.artifact.generate_artifact_id`, so it is deterministic and
    matches exactly what the artifact will be keyed as once actually written.

    Args:
        manifest_entries: Every entry from the migration manifest, each already carrying
            a resolved ``title`` and ``date`` (fallback extraction — frontmatter, H1,
            filename, git log, today — happens upstream in the skill, not here).

    Returns:
        A ``dict`` mapping each entry's manifest ``path`` to its deterministic
        ``artifact_id``. Empty when ``manifest_entries`` is empty.
    """
    path_to_id: dict[str, str] = {}
    for entry in manifest_entries:
        path_to_id[entry["path"]] = generate_artifact_id(
            tier=entry["tier"],
            type=entry["type"],
            date=entry["date"],
            title=entry["title"],
        )
    return path_to_id


def resolve_reference(path: str, path_to_id_map: dict[str, str]) -> str | None:
    """Resolve a single ``references:`` path entry against the manifest-wide map.

    ``http://`` / ``https://`` entries are never treated as path candidates (ADR-012
    D5) and always resolve to ``None``. Any other path is normalized via the bounded
    ceiling in :func:`normalize_reference_path` and looked up directly; a path absent
    from the map — including one that would only match after normalization beyond the
    ceiling, such as ``../`` relative navigation — also resolves to ``None``. The
    caller (the migration skill) is responsible for leaving an unresolved path's
    original text untouched in content and surfacing it in the migration report
    (cluster E) — this function never repairs or guesses.

    Args:
        path: The raw reference path (or URL) text from a ``references:`` entry.
        path_to_id_map: The full-manifest map built by :func:`build_path_to_id_map`.

    Returns:
        The resolved ``artifact_id`` if the (normalized) path is present in the map,
        otherwise ``None``.
    """
    if path.startswith(_URL_PREFIXES):
        return None
    return path_to_id_map.get(normalize_reference_path(path))
