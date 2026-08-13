"""arkeology.references — pure migration reference resolution helpers.

This module is AWS-free and I/O-free, matching ``artifact.py``'s posture. It implements
the ADR-012 (D4/D6) algorithm the ``migrating-to-arkeology`` skill uses to carry
frontmatter ``references:`` path entries across the file-path -> ``artifact_id``
addressing boundary.

The canonical, operative ``artifact_id`` form used everywhere else in arkeology
(``write_artifact``'s vector metadata, ``read_artifact``'s scope gate, the
``referenced_by`` reverse lookup) is the **full S3 key** —
``f"{write_prefix}/{bare_id}{extension}"`` — never the bare
:func:`arkeology.artifact.generate_artifact_id` output on its own, which matches none of
those surfaces.
Every helper in this module that produces or consumes an identifier uses that same
full-key form:

0. Extract the raw ``references:`` entries from a file's frontmatter text
   (:func:`extract_references_list`), before any normalization, joining, or map
   lookup — this is the parsing step every later step in this list assumes has
   already happened.
1. Build a single authoritative path -> full-key map from the FULL migration
   manifest, before any writes, using the pure :func:`arkeology.artifact.generate_artifact_id`
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
5. Rewrite every already-resolved path literally in stored content — both the
   frontmatter ``references:`` list item AND any markdown body link target pointing at
   the identical path — to ``arkeology://artifact/{id}`` (:func:`rewrite_content_references`,
   T56/FR-52 extension, ADR-012 Revision 2026-07-06). This is a deterministic, pure,
   markdown-aware text rewrite driven entirely by a caller-supplied
   ``{original_reference_text: artifact_id}`` map — it never discovers a path that was
   not already a key in that map (ADR-012 D1 is unaffected: no new in-body link
   *discovery* is added, only a by-product rewrite of an already-known string wherever
   it occurs).

The ``migrating-to-arkeology`` and ``backfilling-references`` skills document and drive this
exact algorithm — this module is the authoritative, unit-tested reference implementation;
do not reimplement it in server code.

Those two skills are the deliberate exception: each documents standalone ``python3``
snippets that recompute the identifier, and extract the ``references:`` list, offline,
because a migration or backfill run does this before the server is necessarily
installed, configured, or reachable (and before PyYAML is guaranteed to be installed
in an arbitrary target repo's environment), so importing this module is not available
to them. That duplication is accepted and guarded, not removed —
``tests/unit/test_skill_artifact_id_drift.py`` executes each skill's documented
snippets over shared input tables and fails if either diverges from
:func:`arkeology.artifact.generate_artifact_id` or :func:`extract_references_list`
(via its stdlib-only :func:`_extract_references_list_manual` fallback, which the
skill snippet mirrors exactly). A new skill that computes identifiers or extracts
references offline belongs in that test's skill list.
"""

import posixpath
import re
from typing import TypedDict

import yaml

from arkeology.artifact import generate_artifact_id
from arkeology.errors import DuplicateManifestPathError

# URL schemes that are always left untouched and never treated as a path candidate
# (ADR-012 D5).
_URL_PREFIXES: tuple[str, ...] = ("http://", "https://")


class ManifestEntry(TypedDict):
    """One resolved migration manifest entry, as consumed by :func:`build_path_to_id_map`.

    Attributes:
        path: Repo-relative file path, exactly as it appears in the manifest / a
            ``references:`` entry once normalized.
        type: Artifact type (see :data:`arkeology.artifact.ARTIFACT_TYPES`).
        tier: 2 or 3.
        title: The artifact's resolved title (already extracted from frontmatter,
            an H1 heading, or the filename by the time the map is built).
        date: ISO-8601 date string. Required even for tier 3 entries because
            :func:`arkeology.artifact.generate_artifact_id` always validates it,
            even though tier 3 ids do not encode it.
    """

    path: str
    type: str
    tier: int
    title: str
    date: str


def extract_references_list(frontmatter_text: str) -> list[str]:
    """Extract the frontmatter ``references:`` list from raw frontmatter YAML text.

    Primary path parses ``frontmatter_text`` with :func:`yaml.safe_load` and reads the
    top-level ``references`` key: absent, or present but not a list, resolves to
    ``[]``; otherwise every entry is returned as a string. Block style (``references:``
    followed by indented ``- item`` lines), flow style (``references: [a.md, b.md]``,
    including the empty ``references: []`` form), quoted and unquoted items, and
    inline ``# comment`` text are all handled correctly and natively by the YAML
    parser — including a literal ``#`` inside a quoted item, which YAML syntax never
    treats as a comment start.

    Fallback path — :func:`_extract_references_list_manual` — runs only when
    ``frontmatter_text`` fails to parse as YAML *outright* (a ``yaml.YAMLError``, e.g.
    a syntax error elsewhere in the frontmatter block). This is a manual, stdlib-only
    scan for a block- or flow-style ``references:`` list that strips a trailing
    ``# comment`` (only when it appears outside quotes) and surrounding quote
    characters from each item — the exact algorithm the ``migrating-to-arkeology`` and
    ``backfilling-references`` skills document as a dependency-free ``python3``
    snippet, because PyYAML is not guaranteed to be installed in an arbitrary target
    repo's environment (see this module's docstring on the skills' one deliberate
    duplication exception).

    Args:
        frontmatter_text: The YAML body of the frontmatter block — the text between
            the opening and closing ``---`` fence lines, fences excluded.

    Returns:
        The ``references:`` entries in source order, as raw (still-unresolved,
        still-unnormalized) path or URL text. Empty when the key is absent, not a
        list, or the list itself is empty.
    """
    try:
        data = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError:
        return _extract_references_list_manual(frontmatter_text)
    if not isinstance(data, dict):
        return []
    references = data.get("references")
    if not isinstance(references, list):
        return []
    return [str(item) for item in references]


def _strip_quotes(value: str) -> str:
    """Strip a single matching pair of surrounding quote characters from ``value``,
    if present; otherwise return it unchanged."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _strip_inline_comment(value: str) -> str:
    """Strip a trailing ``# comment`` from a manually-scanned list-item value.

    A value opening with a quote character is returned verbatim through its closing
    quote (including the quote characters) — a ``#`` inside quotes is data, never a
    comment start, matching YAML's own rule. An unquoted value is truncated at the
    first `` #`` (space then hash), which is also never present as a data character in
    a well-formed reference path.
    """
    stripped = value.strip()
    if stripped[:1] in ('"', "'"):
        quote = stripped[0]
        end = stripped.find(quote, 1)
        return stripped if end == -1 else stripped[: end + 1]
    hash_index = stripped.find(" #")
    return stripped if hash_index == -1 else stripped[:hash_index].rstrip()


def _split_inline_list(items_text: str) -> list[str]:
    """Split a flow-style YAML list body (the text between ``[`` and ``]``) on
    top-level commas, stripping whitespace and surrounding quotes from each item. A
    blank (whitespace-only) body — the ``references: []`` empty-list form — is ``[]``.
    """
    if not items_text.strip():
        return []
    return [_strip_quotes(part.strip()) for part in items_text.split(",")]


# A flow-style `references:` key with its value on the same line, e.g.
# `references: [a.md, "b.md"]` or the empty-list form `references: []`.
_REFERENCES_INLINE_LIST_RE = re.compile(r"^references:\s*\[(?P<items>.*)\]\s*(?:#.*)?$")


def _extract_references_list_manual(frontmatter_text: str) -> list[str]:
    """Stdlib-only fallback for :func:`extract_references_list`, used only when
    ``frontmatter_text`` fails to parse as YAML outright. Scans for a block-style
    ``references:`` key opener (:data:`_REFERENCES_BLOCK_KEY_RE`) followed by indented
    list items (:data:`_LIST_ITEM_RE`), or a flow-style same-line list
    (:data:`_REFERENCES_INLINE_LIST_RE`), stripping inline comments and quotes from
    each item. This mirrors the exact snippet the ``migrating-to-arkeology`` and
    ``backfilling-references`` skills document — see :func:`extract_references_list`.
    """
    items: list[str] = []
    in_block_list = False
    for line in frontmatter_text.split("\n"):
        inline_match = _REFERENCES_INLINE_LIST_RE.match(line.strip())
        if inline_match:
            return _split_inline_list(inline_match.group("items"))
        if _REFERENCES_BLOCK_KEY_RE.match(line.rstrip()):
            in_block_list = True
            continue
        if in_block_list:
            item_match = _LIST_ITEM_RE.match(line)
            if item_match:
                items.append(_strip_quotes(_strip_inline_comment(item_match.group("value"))))
                continue
            in_block_list = False
    return items


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
    via the pure :func:`arkeology.artifact.generate_artifact_id`, so it is deterministic;
    it is then composed into the full S3 key using the exact same form
    ``write_artifact`` uses (``f"{write_prefix}/{bare_id}{extension}"``, see
    ``arkeology.tools.write``) — this is the operative ``artifact_id`` every other
    arkeology surface (vector metadata, ``read_artifact``'s scope gate, the
    ``referenced_by`` reverse lookup) matches on. A map keyed to the bare id alone is dead
    on every one of those surfaces.

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

    Raises:
        DuplicateManifestPathError: Two entries normalize to the same path.
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
        # M13: key on the normalized path, not the raw manifest path — a manifest
        # entry spelled with a leading "./" or a backslash must still be found by
        # resolve_reference's normalize_reference_path(candidate) lookup, otherwise
        # the reference silently never resolves.
        normalized_path = normalize_reference_path(entry["path"])
        # Two entries normalizing to the same key must never silently
        # last-write-win — that discards one entry's mapping with zero signal.
        if normalized_path in path_to_id:
            raise DuplicateManifestPathError(normalized_path)
        path_to_id[normalized_path] = f"{write_prefix}/{bare_id}{extension}"
    return path_to_id


def join_reference_path(referencing_file_path: str, reference_path: str) -> str:
    """Join a well-formed relative reference path against the referencing file's own
    directory, producing a repo-relative path suitable for a
    :func:`build_path_to_id_map` lookup.

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
    path is first joined against its directory via :func:`join_reference_path` —
    this is what makes ``../decisions/B.md`` written in ``notes/A.md`` resolve
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


# ---------------------------------------------------------------------------
# rewrite_content_references — T56 / FR-52 extension (ADR-012 Revision 2026-07-06)
# ---------------------------------------------------------------------------

# A markdown inline link: [text](target). The target group stops at the first ')' —
# a pragmatic, non-balanced-parens extraction (OQ-T56-f); a target containing an
# unescaped ')' before its own closing paren is a documented, out-of-scope limitation.
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")

# A backtick-fenced code block delimiter, optionally followed by a language tag
# (e.g. "```", "```python"). Only backtick fences are recognised (OQ-T56-c).
_FENCE_RE = re.compile(r"^```")

# A block-style frontmatter `references:` key opener — deliberately excludes flow-style
# (`references: [...]`) and non-empty same-line values, which are left as a safe no-op
# (OQ-T56-d).
_REFERENCES_BLOCK_KEY_RE = re.compile(r"^references:\s*$")

# A block-style YAML list item: "<indent>- <value>". Matches any indentation level;
# scoping to the references: block is enforced by the caller's state machine, not by
# this pattern alone.
_LIST_ITEM_RE = re.compile(r"^(?P<indent>[ \t]*-[ \t]+)(?P<value>.*)$")

_ARKEOLOGY_ARTIFACT_URI_PREFIX = "arkeology://artifact/"


def _quote_style(value: str) -> tuple[str, str]:
    """Split a frontmatter list-item value into its unquoted text and quote character.

    Returns ``(unquoted_text, quote_char)`` where ``quote_char`` is ``'"'``, ``"'"``, or
    ``""`` (unquoted). No escape-sequence handling is attempted — matches the "simple,
    exact, byte-for-byte" matching contract; a value that is not a simple `"..."` or
    `'...'` wrapped string is treated as unquoted verbatim.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1], value[0]
    return value, ""


def _compute_fence_flags(lines: list[str]) -> list[bool]:
    """Mark every line that is part of a fenced code block (opening/closing delimiter
    line included) as ``True``, so callers can leave that entire span byte-for-byte
    untouched. An unterminated (odd count) fence marks everything from the unmatched
    opening delimiter through end-of-content as fenced — safer to under-rewrite than to
    rewrite inside a probably-still-code region (Story 4)."""
    flags = [False] * len(lines)
    in_fence = False
    for i, line in enumerate(lines):
        is_delim = bool(_FENCE_RE.match(line.strip()))
        if in_fence:
            flags[i] = True
            if is_delim:
                in_fence = False
            continue
        if is_delim:
            flags[i] = True
            in_fence = True
    return flags


def _frontmatter_end_index(lines: list[str]) -> int | None:
    """Return the line index of the closing ``---`` frontmatter delimiter, or ``None``
    when ``lines`` does not open with a ``---`` frontmatter block."""
    if not lines or lines[0].rstrip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return i
    return None


def _rewrite_frontmatter_item(line: str, resolved_map: dict[str, str]) -> str:
    """Rewrite a single frontmatter ``references:`` list-item line if its unquoted value
    exactly matches a ``resolved_map`` key; otherwise return the line unchanged."""
    match = _LIST_ITEM_RE.match(line)
    if not match:
        return line
    indent = match.group("indent")
    value = match.group("value")
    unquoted, quote = _quote_style(value)
    artifact_id = resolved_map.get(unquoted)
    if artifact_id is None:
        return line
    new_value = f"{_ARKEOLOGY_ARTIFACT_URI_PREFIX}{artifact_id}"
    return f"{indent}{quote}{new_value}{quote}"


def _rewrite_body_line(line: str, normalized_map: dict[str, str]) -> str:
    """Rewrite every markdown inline link target on ``line`` whose path portion matches
    a ``normalized_map`` key (after :func:`normalize_reference_path`), dropping any
    ``#anchor`` from the rewritten URI and appending it as a verbatim trailing note."""

    def _replace(match: re.Match[str]) -> str:
        text = match.group(1)
        target = match.group(2)
        if target.startswith(_URL_PREFIXES):
            return match.group(0)
        path_portion, _, anchor = target.partition("#")
        artifact_id = normalized_map.get(normalize_reference_path(path_portion))
        if artifact_id is None:
            return match.group(0)
        rewritten = f"[{text}]({_ARKEOLOGY_ARTIFACT_URI_PREFIX}{artifact_id})"
        if anchor:
            rewritten += f' ("{anchor}" section)'
        return rewritten

    return _LINK_RE.sub(_replace, line)


def rewrite_content_references(content: str, resolved_map: dict[str, str] | None) -> str:
    """Rewrite every literal occurrence of an already-resolved reference path in
    ``content`` to ``arkeology://artifact/{id}`` — both the frontmatter ``references:``
    list item AND any markdown body link target pointing at the identical path
    (T56/FR-52 extension, ADR-012 Revision 2026-07-06).

    ``resolved_map`` is ``{original_reference_text: artifact_id}`` — the exact literal
    text of each frontmatter ``references:`` entry that already resolved for this file,
    built by the caller using the unchanged T51 resolution algorithm
    (:func:`resolve_reference`). This function never discovers a path that is not
    already a key in ``resolved_map`` — ADR-012 D1's discovery boundary is untouched;
    the body rewrite is a by-product of rewriting a known string everywhere it occurs,
    not a new discovery capability.

    Matching rules:
        - Frontmatter ``references:`` list items (block-style only, OQ-T56-d) are
          matched EXACTLY against the item's unquoted value — never normalized — and
          rewritten preserving the item's original quote style (unquoted / single /
          double) and list position.
        - Markdown body link targets (``[text](target)``, optionally carrying a
          ``#anchor``) are matched by applying :func:`normalize_reference_path` — never
          :func:`join_reference_path`, which needs per-occurrence file context this pure
          helper does not have (see Boundaries/Never, OQ-T56-e) — to both the target's
          path portion and each ``resolved_map`` key, then comparing for exact equality.
          A matched anchor is dropped from the rewritten URI and preserved verbatim as
          a trailing ``("<anchor>" section)`` note immediately after the link. Text
          inside a fenced (backtick) code block, and bare prose mentions with no
          markdown link syntax, are never matched.
        - ``http://`` / ``https://`` targets are never rewrite candidates (ADR-012 D5),
          checked before any normalization or comparison.

    Determinism and idempotency: this is a pure function of its two arguments — the
    same inputs always produce byte-identical output, and re-running on
    already-rewritten content (or with an empty/absent ``resolved_map``) is a no-op,
    because a rewritten target (``arkeology://artifact/{id}``, no ``#``) is never itself a
    ``resolved_map`` key.

    Args:
        content: The full artifact content, frontmatter block included.
        resolved_map: ``{original_reference_text: artifact_id}`` for this file's
            already-resolved frontmatter ``references:`` entries. ``None`` or empty is a
            safe no-op — ``content`` is returned completely unchanged.

    Returns:
        The rewritten content, or ``content`` unchanged when ``resolved_map`` is
        empty/absent or nothing in it occurs in ``content``.
    """
    if not resolved_map:
        return content

    lines = content.split("\n")
    fence_flags = _compute_fence_flags(lines)
    frontmatter_end = _frontmatter_end_index(lines)
    normalized_map = {normalize_reference_path(k): v for k, v in resolved_map.items()}

    in_references_list = False
    out_lines: list[str] = []
    for i, line in enumerate(lines):
        if fence_flags[i]:
            out_lines.append(line)
            in_references_list = False
            continue

        if frontmatter_end is not None and i <= frontmatter_end:
            if _REFERENCES_BLOCK_KEY_RE.match(line.rstrip()):
                in_references_list = True
                out_lines.append(line)
                continue
            if in_references_list and _LIST_ITEM_RE.match(line):
                out_lines.append(_rewrite_frontmatter_item(line, resolved_map))
                continue
            in_references_list = False
            out_lines.append(line)
            continue

        out_lines.append(_rewrite_body_line(line, normalized_map))

    return "\n".join(out_lines)
