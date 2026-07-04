"""cairn_mcp.references — pure migration reference resolution helpers.

This module is AWS-free and I/O-free, matching ``artifact.py``'s posture. It implements
the ADR-012 (D4/D6) algorithm the ``migrating-to-cairn`` skill uses to carry
frontmatter ``references:`` path entries across the file-path -> ``artifact_id``
addressing boundary.

The canonical, operative ``artifact_id`` form used everywhere else in cairn-mcp
(``write_artifact``'s vector metadata, ``read_artifact``'s scope gate, the
``referenced_by`` reverse lookup) is the **full S3 key** —
``f"{write_prefix}/{bare_id}{extension}"`` — never the bare
:func:`cairn_mcp.artifact.generate_artifact_id` output on its own (review finding C1).
Every helper in this module that produces or consumes an identifier uses that same
full-key form:

1. Build a single authoritative path -> full-key map from the FULL migration
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

4. Join a well-formed relative reference (``./`` or ``../``) against the referencing
   file's own directory (:func:`join_reference_path`) before the D6 normalization and
   map lookup above, so that ``../decisions/B.md`` written in ``notes/A.md`` resolves
   against ``decisions/B.md`` in the map. This is resolution of a well-formed relative
   path, not the "repair" of a genuinely broken/inconsistent reference that D6
   deliberately excludes — those still fall through to unresolved. :func:`resolve_reference`
   accepts an optional ``referencing_file_path`` to apply this join automatically; when
   omitted, behaviour is unchanged (no join is attempted, matching the original D6-only
   ceiling).

The ``migrating-to-cairn`` and ``backfilling-references`` skills document and drive this
exact algorithm (OQ-T51-a) — this module is the authoritative, unit-tested reference
implementation; do not reimplement the algorithm elsewhere.
"""

import posixpath
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


def build_path_to_id_map(
    manifest_entries: list[ManifestEntry], write_prefix: str
) -> dict[str, str]:
    """Build a path -> full-key map from the FULL migration manifest (ADR-012 D4).

    Must be called with every manifest entry, of any status, across sessions — not just
    the subset currently being written or retried — so that forward references (a file
    referencing a sibling scheduled later in the same batch, or in an earlier/later
    session) always resolve regardless of write order. Each bare identifier is computed
    via the pure :func:`cairn_mcp.artifact.generate_artifact_id`, so it is deterministic;
    it is then composed into the full S3 key using the exact same form
    ``write_artifact`` uses (``f"{write_prefix}/{bare_id}{extension}"``, see
    ``cairn_mcp.tools.write``) — this is the operative ``artifact_id`` every other
    cairn-mcp surface (vector metadata, ``read_artifact``'s scope gate, the
    ``referenced_by`` reverse lookup) matches on (review finding C1). A map keyed to
    the bare id alone is dead on every one of those surfaces.

    Args:
        manifest_entries: Every entry from the migration manifest, each already carrying
            a resolved ``title`` and ``date`` (fallback extraction — frontmatter, H1,
            filename, git log, today — happens upstream in the skill, not here).
        write_prefix: This deployment's configured S3 write prefix (``Settings.write_prefix``
            / ``WRITE_PREFIX``) — the same value ``write_artifact`` prepends to every key.
            Callers outside the server process (the migration/backfill skills) must obtain
            this from the operator or by deriving it from an already-known full artifact_id;
            it is never guessed here.

    Returns:
        A ``dict`` mapping each entry's manifest ``path`` to its full S3 key
        (``{write_prefix}/{bare_id}{extension}``), where ``extension`` is derived from the
        entry's ``path`` via :func:`posixpath.splitext`, defaulting to ``.md`` when the
        path carries no extension — mirroring ``write_artifact``'s own ``file_extension``
        default. Empty when ``manifest_entries`` is empty.
    """
    path_to_id: dict[str, str] = {}
    for entry in manifest_entries:
        bare_id = generate_artifact_id(
            tier=entry["tier"],
            type=entry["type"],
            date=entry["date"],
            title=entry["title"],
        )
        extension = posixpath.splitext(entry["path"])[1] or ".md"
        path_to_id[entry["path"]] = f"{write_prefix}/{bare_id}{extension}"
    return path_to_id


def join_reference_path(referencing_file_path: str, reference_path: str) -> str:
    """Join a well-formed relative reference path against the referencing file's own
    directory, producing a repo-relative path suitable for a
    :func:`build_path_to_id_map` lookup (C6 fix — relative-path resolution).

    ``http://`` / ``https://`` URLs pass through unchanged (ADR-012 D5). A path that
    does not start with ``./`` or ``../`` (after backslash normalization) is already
    absolute or repo-relative and also passes through unchanged — only well-formed
    dotted-relative paths are joined. Joining uses POSIX semantics
    (:func:`posixpath.join` + :func:`posixpath.normpath`) against
    ``referencing_file_path``'s directory, not the repo root. A ``../`` that escapes
    above the repo root simply normalizes to a path carrying a leading ``../`` — it
    is not present in any map and stays unresolved downstream, rather than raising.

    Args:
        referencing_file_path: Repo-relative path of the file the reference was
            written in (e.g. ``"notes/A.md"``).
        reference_path: The raw reference path (or URL) text from a ``references:``
            entry, as it appears in source frontmatter.

    Returns:
        The joined, POSIX-normalized repo-relative path when ``reference_path`` is a
        well-formed relative (``./`` or ``../``) path; ``reference_path`` unchanged
        otherwise (URLs and already-absolute/repo-relative paths).
    """
    if reference_path.startswith(_URL_PREFIXES):
        return reference_path
    slashed = reference_path.replace("\\", "/")
    if not (slashed.startswith("./") or slashed.startswith("../")):
        return reference_path
    referencing_dir = posixpath.dirname(referencing_file_path.replace("\\", "/"))
    return posixpath.normpath(posixpath.join(referencing_dir, slashed))


def resolve_reference(
    path: str,
    path_to_id_map: dict[str, str],
    referencing_file_path: str | None = None,
) -> str | None:
    """Resolve a single ``references:`` path entry against the manifest-wide map.

    ``http://`` / ``https://`` entries are never treated as path candidates (ADR-012
    D5) and always resolve to ``None``, regardless of ``referencing_file_path``. When
    ``referencing_file_path`` is supplied, a well-formed relative (``./`` or ``../``)
    path is first joined against its directory via :func:`join_reference_path` (C6
    fix) — this is what makes ``../decisions/B.md`` written in ``notes/A.md`` resolve
    to B's id. When ``referencing_file_path`` is omitted, no join is attempted and
    behaviour matches the original bounded (D6) ceiling exactly. Either way, the
    (possibly joined) path is then normalized via :func:`normalize_reference_path` and
    looked up directly; a path absent from the map — including a ``../`` that escapes
    above the repo root — resolves to ``None``. The caller (the migration or backfill
    skill) is responsible for leaving an unresolved path's original text untouched in
    content and surfacing it in the migration report (cluster E) — this function never
    repairs or guesses beyond the documented join + D6 normalization.

    Args:
        path: The raw reference path (or URL) text from a ``references:`` entry.
        path_to_id_map: The full-manifest map built by :func:`build_path_to_id_map`.
        referencing_file_path: Repo-relative path of the file ``path`` was written in.
            When provided, enables relative (``./``/``../``) join resolution.

    Returns:
        The resolved full S3 key (the operative ``artifact_id``) if the (joined and
        normalized) path is present in the map, otherwise ``None``.
    """
    if path.startswith(_URL_PREFIXES):
        return None
    candidate = path
    if referencing_file_path is not None:
        candidate = join_reference_path(referencing_file_path, path)
    return path_to_id_map.get(normalize_reference_path(candidate))
