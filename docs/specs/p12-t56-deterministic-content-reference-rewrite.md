---
type: spec
title: T56 — Deterministic Server-Side Content Reference Rewrite (Frontmatter + Body)
description: Extend the migration content rewrite so a path already resolved from a file's frontmatter references: list is rewritten to cairn://artifact/{id} everywhere it occurs in stored content — the frontmatter block AND markdown link targets in the body — executed as a deterministic, server-side pure helper inside migrate_artifacts instead of the current agent-in-context frontmatter-only rewrite. Does not reopen in-body link discovery.
tags: []
timestamp: 2026-07-06T00:00:00Z
okf_version: "0.1"
feature: p12-t56-deterministic-content-reference-rewrite
status: ready
phase: 12
task: 56
references:
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/specs/p12-t51-migration-reference-rewrite.md
  - docs/brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md
  - docs/specs/p9-t30-write-artifacts.md
  - src/cairn_mcp/references.py
  - plugins/cairn-mcp/skills/migrating-to-cairn/SKILL.md
authored:
  by: "architect"
  date: "2026-07-06"
---

# T56 — Deterministic Server-Side Content Reference Rewrite (Frontmatter + Body)

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Give migration's content rewrite (T51/FR-52) a deterministic, server-side implementation, and
extend it to also rewrite the body: for any path already resolved from a file's frontmatter
`references:` list, replace every literal occurrence of that path — in the frontmatter block AND
in markdown link targets in the body — with `cairn://artifact/{id}`. Add one new pure,
unit-testable helper (`rewrite_content_references`) to `src/cairn_mcp/references.py`; apply it
inside `migrate_artifacts`, driven by a new transient descriptor key
(`resolved_references_map`) the agent threads per file; remove the current agent-in-context
hand-rewrite instructions from the `migrating-to-cairn` skill. In-body link **discovery** —
resolving a path that was never declared in a file's own frontmatter `references:` list — remains
explicitly out of scope (ADR-012 D1, reaffirmed in the ADR-012 Revision, 2026-07-06).

## Problem Statement

T51 gave migration a deterministic *resolution* algorithm (the path→id map, `references.py`) but
left the *content rewrite* itself as agent-in-context text editing: the skill instructs the agent
to "rewrite that entry, in the stored content's frontmatter `references:` list only, to
`cairn://artifact/{id}`" by hand. Two gaps follow from this. First, an LLM performing find/replace
over arbitrary markdown text has no byte-exact, idempotent guarantee — "deterministic" is not a
property the current mechanism can claim, and the skill runs no local scripts to make it one.
Second, this project's own house documentation style frequently echoes a frontmatter reference as
an in-body markdown link pointing at the identical target (e.g. a `references:` entry
`../decisions/B.md` reappearing as `[the decision](../decisions/B.md)` in prose) — and today that
body occurrence is left as a dead raw path even though the target is already fully resolved and
known. This spec closes both gaps with one change: move the rewrite into a tested, deterministic
server-side helper, and extend its reach to cover the identical already-resolved path wherever it
occurs in the file — without adding any capability to discover a path that was never declared in
that file's own frontmatter.

## User Stories

### Story 1 — Resolved frontmatter reference rewritten, quote style preserved (P1)

**Acceptance criteria:**
- Given a file whose frontmatter `references:` list contains `- "../decisions/B.md"` and this
  entry already resolved (per T51/D4) to B's artifact_id, when `migrate_artifacts` writes the
  file, then the stored content's frontmatter entry reads `- "cairn://artifact/{B-id}"` — double
  quotes preserved, list position unchanged. (FR-52 extension)
- Given the same entry written unquoted (`- ../decisions/B.md`), then the rewritten entry is
  unquoted (`- cairn://artifact/{B-id}`). (FR-52 extension)
- Given a `references:` list with three entries where only the second resolves, when the file is
  written, then only the second entry is rewritten; the first and third are left completely
  untouched and the list still has three entries in the same order. (FR-52 extension)

### Story 2 — The same resolved path is rewritten wherever it occurs in the body (P1)

**Acceptance criteria:**
- Given a file whose body contains an inline markdown link `[the decision](../decisions/B.md)`
  using the exact path text already resolved from frontmatter, when `migrate_artifacts` writes the
  file, then the body link target is rewritten to `cairn://artifact/{B-id}` and the link *text*
  (`the decision`) is left unchanged. (FR-52 extension)
- Given the body link is `[the decision](../decisions/B.md#outcome)` (carrying an anchor), then
  the rewritten target drops the anchor from the URI AND a human-readable note is appended
  immediately after the link's closing `)`: `[the decision](cairn://artifact/{B-id}) ("outcome"
  section)`. The note text is the raw fragment after `#`, verbatim. (anchor decision — FROZEN)
- Given a hyphenated / multi-word anchor `[x](../decisions/B.md#my-decision)`, then the note is
  `("my-decision" section)` — the fragment is preserved verbatim, never de-slugified to
  `"my decision"`.
- Given the already-rewritten anchored link `[the decision](cairn://artifact/{B-id}) ("outcome"
  section)` is passed through the helper a second time, then the output is identical — the note is
  not re-appended (the rewritten target is `cairn://artifact/{B-id}` with no `#`, and
  `cairn://…` is not a key in `resolved_map`, so the second pass matches nothing).
- Given the same resolved path appears as two separate body links in the same file, when the file
  is written, then both occurrences are rewritten, not just the first.
- Given a body link `[other](../decisions/B.md.bak)` — NOT an exact match to the resolved path
  after normalization — then it is left completely untouched (collision safety).
- Given a body link written with a different but D6-normalization-equivalent spelling of the same
  resolved path (e.g. body has `./decisions/B.md`, the frontmatter entry that resolved was
  `../decisions/B.md` and the map key, once joined, is `decisions/B.md`), when both sides are
  passed through the existing bounded `normalize_reference_path`, then the body link is rewritten.
  A spelling that would only match via the *join* step (not available inside the pure content
  helper, which has no per-occurrence file context) is left untouched — see Open Questions.

### Story 3 — Undeclared body-only links are never discovered or rewritten (P1)

**Acceptance criteria:**
- Given a body link `[unrelated](../decisions/C.md)` where `C.md` was never listed in *this*
  file's frontmatter `references:` — even if `C.md` is itself a real, resolvable migrated artifact
  elsewhere in the manifest — when `migrate_artifacts` writes the file, then the link is left
  completely untouched: it is never discovered, resolved, or rewritten. (ADR-012 D1 preserved)
- Given a bare prose mention `"see ../decisions/B.md for details"` with no markdown link syntax,
  even though `B.md` did resolve from this file's frontmatter, then the prose mention is left
  untouched — only frontmatter list items and markdown link-target syntax are ever rewritten.
  (markdown-awareness scoping)

### Story 4 — Fenced code blocks are never touched (P1)

**Acceptance criteria:**
- Given a fenced code block (```` ``` ````-delimited) containing the literal text
  `[link](../decisions/B.md)` — e.g. inside a documented example — when `migrate_artifacts`
  writes the file, then the text inside the fence is left byte-for-byte untouched, even though it
  would otherwise match.
- Given an unterminated (odd count) code fence, when the helper runs, then it does not raise —
  everything from the unmatched opening fence to end-of-content is treated as still-inside-code
  and left untouched (safer to under-rewrite than to rewrite inside a probably-still-code region).

### Story 5 — Deterministic and idempotent (P1)

**Acceptance criteria:**
- Given the same `content` and `resolved_map`, when `rewrite_content_references` is called twice,
  then both calls return byte-identical output.
- Given content that has already been rewritten once, when the helper is called again with the
  same map, then the output is unchanged — no double-wrapping, no
  `cairn://artifact/cairn://artifact/...` nesting.
- Given an empty or absent `resolved_map`, when the helper runs, then `content` is returned
  completely unchanged, including whitespace and formatting in the frontmatter block.

### Story 6 — No re-embed, no metadata leakage, migration-only (P1)

**Acceptance criteria:**
- Given a descriptor with a non-empty `resolved_references_map`, when
  `migrate_artifacts(dry_run=False)` writes the artifact, then the content stored in S3, the
  content parsed into sections and embedded, and the content later returned by `read_artifact` are
  all identical (the rewritten version) — embedding happens exactly once, on the final content.
  (no re-embed)
- Given the same call, when the response, the S3 object metadata, and the vector metadata are
  inspected, then no `resolved_references_map` key appears anywhere. (no leakage)
- Given `dry_run=True` with the same descriptor, when the enriched descriptor is returned, then
  its `content` field already reflects the rewrite (the preview shows the true final content), and
  `resolved_references_map` is absent from the returned descriptor.
- Given a direct call to `write_artifact` or `write_artifacts` (outside `migrate_artifacts`), when
  a caller supplies an unrecognised `resolved_references_map`-shaped key, then it has no effect —
  this capability is `migrate_artifacts`-only and is never wired into the general write path.

## Requirements

- WHEN a `migrate_artifacts` descriptor carries a non-empty `resolved_references_map` THE SYSTEM
  SHALL rewrite every literal occurrence of each map key in the descriptor's `content` — both
  within the frontmatter `references:` YAML list and within markdown link targets in the body —
  to `cairn://artifact/{id}`, before any write, applied identically in both `dry_run` modes.
- WHEN a frontmatter `references:` list item's unquoted value exactly equals a
  `resolved_references_map` key THE SYSTEM SHALL replace it with `cairn://artifact/{id}`,
  preserving the item's original quote style (unquoted, single-, or double-quoted) and its
  position in the list.
- WHEN a markdown inline link target (`[text](target)`) — split on the first `#` into a path
  portion and an optional anchor — has a path portion that equals a `resolved_references_map` key
  after applying `normalize_reference_path` (`references.py`) to both sides THE SYSTEM SHALL
  replace the target with `cairn://artifact/{id}` (dropping the anchor from the URI).
- WHEN such a matched link carried a non-empty anchor (text after the first `#`) THE SYSTEM SHALL
  append a human-readable note immediately after the rewritten link's closing `)`, in the exact
  form `<space>("<anchor>" section)`, where `<anchor>` is the raw fragment text after `#`,
  verbatim and un-de-slugified (e.g. `my-decision` stays `my-decision`) — so
  `[text](../adr.md#my-decision)` becomes `[text](cairn://artifact/{id}) ("my-decision" section)`.
- WHEN such a matched link carried no anchor THE SYSTEM SHALL rewrite the target with no appended
  note.
- WHEN already-rewritten content is passed through `rewrite_content_references` again THE SYSTEM
  SHALL NOT re-append or duplicate the anchor note: the rewritten target is `cairn://artifact/{id}`
  with no `#`, and `cairn://…` is never a key in `resolved_references_map`, so a second pass finds
  no match and appends nothing.
- WHEN a candidate path portion or frontmatter list value does not match any
  `resolved_references_map` key — exactly for frontmatter, or via `normalize_reference_path` for
  body links — THE SYSTEM SHALL leave it completely untouched; no partial, fuzzy, or
  substring-containment rewrite is ever performed.
- WHEN a target begins with `http://` or `https://` THE SYSTEM SHALL never treat it as a rewrite
  candidate, matching ADR-012 D5, checked before any normalization or comparison.
- WHEN text falls inside a fenced code block (opened by a ``` or ```lang line and not yet closed
  by a matching ``` line) THE SYSTEM SHALL leave it completely untouched, including any text that
  would otherwise match a frontmatter-list or link-target pattern.
- WHEN `rewrite_content_references` is called twice with the same `(content, resolved_map)` THE
  SYSTEM SHALL return byte-identical output on both calls.
- WHEN `resolved_references_map` is absent or empty on a descriptor THE SYSTEM SHALL leave that
  descriptor's `content` completely unchanged.
- WHEN the content rewrite runs inside `migrate_artifacts` THE SYSTEM SHALL apply it after
  description generation/clipping and before the skip-existing check and the delegation to
  `write_artifacts`, so the content that is stored, parsed into sections, and embedded is the same
  final (rewritten) text in every case — no separate re-embed step is introduced.
- WHEN `migrate_artifacts` returns a response THE SYSTEM SHALL never surface the transient
  `resolved_references_map` key — in a dry-run descriptor echo, a write result, or an error — it
  is consumed and discarded before the descriptor is returned or handed to `write_artifacts`.
- WHEN `write_artifact` or `write_artifacts` is called directly (outside `migrate_artifacts`) THE
  SYSTEM SHALL NOT apply any content rewrite of this kind — the capability is
  `migrate_artifacts`-only.

## Boundaries

**Always:**
- Only paths already present as keys in the per-descriptor `resolved_references_map` — built
  exactly as T51 already builds frontmatter `references:` resolution — are ever rewritten; no new
  discovery of undeclared body-only links is performed (ADR-012 D1 preserved).
- The rewrite is applied once, server-side, before the artifact is embedded or stored, so S3
  content and the embedded section text are always byte-consistent (no re-embed).
- `resolved_references_map` is transient: built in-context by the agent (reusing `references.py`'s
  existing resolution algorithm, T51-unchanged), threaded through the `migrate_artifacts`
  descriptor, consumed by the server, and never stored in S3 metadata, vector metadata, or the
  `Artifact` model.
- Migration never overwrites an existing key (A-1 skip-existing), so this rewrite is inherently
  first-write-only — matches T51/D8's "content rewritten once, never retroactively patched."
- Every id in `resolved_references_map` values is resolved from this deployment's own migration
  manifest / `write_prefix` (T51/D4) — inherently own-scope; no new cross-scope validation is
  introduced.
- `rewrite_content_references` reuses `normalize_reference_path` from `references.py` for body-link
  comparison — do not duplicate that normalization logic.
- TDD: the pure helper's test file is written and failing (Red) before `rewrite_content_references`
  is implemented (Green).

**Ask First:**
- Nothing — all operator decisions are frozen (see Open Questions). Reference-style `[text][ref]`
  links, tilde (`~~~`) fences, and flow-style YAML `references:` lists are confirmed out of scope
  for v1; anchor handling is confirmed drop-from-URI-preserve-as-note.

**Never:**
- Do not perform a full YAML parse-and-re-dump of the frontmatter block to apply the rewrite — this
  would reformat or reorder unrelated frontmatter content (key order, comments, quoting elsewhere)
  and break the "content rewritten once, deterministically" contract. Use targeted, line-scoped
  text replacement of the matching list item only.
- Do not rewrite bare prose mentions of a path with no markdown link syntax — only frontmatter list
  items and inline markdown link targets are in scope.
- Do not apply `join_reference_path`'s directory-join step inside `rewrite_content_references` — a
  body-found candidate cannot safely be assumed to share the frontmatter entry's referencing
  directory; only the non-join, bounded `normalize_reference_path` step is reused.
- Do not add `resolved_references_map` handling to `write_artifact` or `write_artifacts` — this
  capability is `migrate_artifacts`-only.
- Do not let `resolved_references_map` leak into any stored metadata, response field, or the
  `Artifact` model.
- Do not discover or resolve a path that was never declared in a file's own frontmatter
  `references:` list, regardless of whether it would otherwise be resolvable against the manifest
  (ADR-012 D1).

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_references_content_rewrite.py` | Create | Pure-helper tests for `rewrite_content_references` — frontmatter quote-style variants, body markdown-link rewrite, anchor drop-from-URI + note appended (incl. anchored idempotency), substring-collision safety, fenced-code-block skip, URL passthrough, unresolved-entry passthrough, idempotency, empty/absent-map no-op — Red first |
| `src/cairn_mcp/references.py` | Modify | Add `rewrite_content_references(content: str, resolved_map: dict[str, str]) -> str` pure helper alongside the existing T51 helpers; reuse `normalize_reference_path`; no new module-level state |
| `tests/unit/test_tools_migrate_artifacts.py` | Modify | Add tests: a descriptor's `resolved_references_map` rewrites `content` before the skip-existing check and before delegation to `write_artifacts`; the key never appears in the `dry_run=True` descriptor echo or the `dry_run=False` result; absent/empty map is a no-op; content stored in S3 matches content embedded (assert via the existing write-path spies) |
| `src/cairn_mcp/tools/migrate_artifacts.py` | Modify | New step between description clipping (current Step 3) and the `dry_run` branch (current Step 4): for each `enriched` descriptor carrying `resolved_references_map`, call `rewrite_content_references` on its `content` and pop the key before the descriptor is returned or written |
| `plugins/cairn-mcp/skills/migrating-to-cairn/SKILL.md` | Modify | Replace the hand-rewrite instruction in "Resolving a `references:` entry against the map" (Step 3, "Match found" bullet) with: populate the descriptor's `references` field AND `resolved_references_map` ({original text: id}); remove the "rewrite that entry... to `cairn://artifact/{id}`" instruction. Update 3.A1b and 3.B5 ("rewrite resolved entries in that file's content... to `cairn://artifact/{id}`") to say the map is passed in the descriptor and the server performs the frontmatter+body rewrite. Update the "Only the frontmatter `references:` YAML list is touched" paragraph (end of Step 3) to state the server now also rewrites matching markdown link targets in the body, while in-body link *discovery* remains out of scope (ADR-012 D1) |
| `docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md` | Already modified (architect) | Revision section (2026-07-06) reversing the no-server-side-rewrite call for this bounded case |
| `docs/brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md` | Already modified (architect) | D16 addendum (Session 2026-07-06) recording the decision |

## Testing Approach

**Project uses TDD.** Write `tests/unit/test_references_content_rewrite.py` first (Red), then
implement `rewrite_content_references` in `src/cairn_mcp/references.py` (Green). Then add the
`migrate_artifacts` integration-level unit tests (Red → Green) for the descriptor-threading and
placement contract.

**Cycle A — pure helper (`rewrite_content_references`):**
- Frontmatter: unquoted match rewritten; double-quoted match rewritten with quotes preserved;
  single-quoted match rewritten with quotes preserved; mixed list (some resolve, some don't) only
  rewrites the matching entries, preserving order and count; empty `references: []` is a no-op;
  no `references:` key at all is a no-op for that section.
- Body links: exact match rewritten; non-matching longer token (`docs/a.md.bak` vs map key
  `docs/a.md`) left untouched; two occurrences of the same resolved link in one file both
  rewritten; a body link spelled with a leading `./` or backslash that normalizes (via
  `normalize_reference_path`) to a map key is rewritten; link *text* (inside `[...]`) is never
  altered even if it textually matches a map key; an `http(s)://` link target is never a candidate
  even if part of its text matches a map key.
- Body-link anchors: a match with `#anchor` is rewritten with the anchor dropped from the URI and
  the note ` ("anchor" section)` appended after the closing `)`; a hyphenated/multi-word anchor
  (`#my-decision`) is kept verbatim in the note (`("my-decision" section)`), never de-slugified; a
  matched link with no anchor gets no note; anchored idempotency — running twice on
  `[x](cairn://artifact/{id}) ("outcome" section)` yields identical output (no double note); a `#`
  appearing inside a fenced code block is still skipped (the whole fenced region is untouched,
  anchor logic never runs on it).
- Non-goals (explicit negative tests): a body link to a path never declared in this file's
  frontmatter is untouched even if resolvable; a bare prose mention with no link syntax is
  untouched; text inside a fenced code block is untouched byte-for-byte, including an unterminated
  fence (treated as code through end-of-content).
- Purity/determinism: same inputs called twice produce identical output; already-rewritten content
  passed through again is unchanged (no double-wrap); an empty or absent map returns content
  unchanged, including exact whitespace; a map key with no occurrence anywhere in content is a safe
  no-op (does not raise).

**Cycle B — `migrate_artifacts` integration:**
- A descriptor with `resolved_references_map` set has its `content` rewritten before
  `s3.head_object`/`s3.put_object` are called (assert via spy) — i.e. before the skip-existing
  check and the `write_artifacts` delegation.
- The rewritten content is what `bedrock.embed` receives for section embedding (spy assertion) —
  proving no re-embed step and no S3/embedding divergence.
- `resolved_references_map` never appears in the `dry_run=True` response's `descriptors` list nor
  in the `dry_run=False` response's `results` list.
- A descriptor without `resolved_references_map` (the common case for ordinary, non-reference-
  bearing files) is unaffected — behaviourally identical to pre-T56 `migrate_artifacts`.

**Integration test** (`tests/integration/`, `@pytest.mark.integration`): a two-file migration where
file A's frontmatter references file B (with a matching body link) round-trips through
`migrate_artifacts(dry_run=False)` against real AWS; `read_artifact` on A returns content with both
the frontmatter and body occurrences rewritten to `cairn://artifact/{B-id}`.

## Open Questions

All operator decisions are FROZEN — this spec is dispatch-ready with no open operator questions.
The resolved decisions and their (implementation-note) limitations are recorded below.

- **OQ-T56-a — Anchor handling (FROZEN 2026-07-06).** A body link `[text](path#anchor)` is
  rewritten with the anchor dropped from the URI, and the anchor is preserved as a human-readable
  note appended immediately after the rewritten link: `[text](cairn://artifact/{id}) ("anchor"
  section)`. `<anchor>` is the raw fragment text after `#`, verbatim (never de-slugified). A link
  with no anchor gets no note. Rationale: the `cairn://artifact/{id*}` template matches the id
  verbatim with no fragment-aware resolution today (and URI fragments are commonly stripped
  client-side before a resource read), so keeping `#anchor` in the URI risks breaking id resolution
  on hosts that pass the fragment through — while the appended note retains the human pointing
  precision the anchor conveyed. Idempotency holds because the rewritten target has no `#` and
  `cairn://…` is never a `resolved_references_map` key, so a second pass appends nothing (explicit
  test required — see Testing Approach).
- **OQ-T56-b — Reference-style markdown links: OUT OF SCOPE for v1 (FROZEN 2026-07-06).**
  `[text][ref]` + a separate `[ref]: path "title"` definition is a different Markdown construct
  from inline `](path)` links and is not rewritten by this spec. Not a limitation the developer
  needs to guard against beyond simply not matching it.
- **OQ-T56-c — Tilde-fenced code blocks: OUT OF SCOPE for v1 (FROZEN 2026-07-06).** Only backtick
  fences (```` ``` ````) are skip-protected; `~~~`-fenced blocks are not specially detected. This
  project's documentation uses backtick fences exclusively, so practical exposure is nil.
- **OQ-T56-d — Flow-style YAML `references:` lists: OUT OF SCOPE for v1 (FROZEN 2026-07-06).** Only
  block-style (`- item` per line) `references:` lists are matched; a single-line flow-style list
  (`references: ["a.md", "b.md"]`) is left untouched (safe no-op, never mis-parsed). The skill's
  examples and the existing migrated corpus use block style exclusively.
- **OQ-T56-e — Body-link matching is normalization-equivalent, not join-equivalent, and misses are
  SILENT (FROZEN 2026-07-06).** A body link that would only resolve to the same target via
  `join_reference_path`'s directory-join (a different implicit base directory than the frontmatter
  entry's) is not rewritten — only the non-join bounded `normalize_reference_path` is applied during
  content matching, for the safety reason in Boundaries/Never. **No report is produced for body
  occurrences left unrewritten** — this is correctly out of scope, not a failure, and Step 4
  verification's reference-resolution report (inherited from T51) continues to cover only
  unresolved *frontmatter* `references:` entries, exactly as before. The developer must NOT add any
  "body occurrence left unrewritten" reporting.
- **OQ-T56-f — Nested/balanced parentheses inside a link target (implementation note, no operator
  decision needed).** A link target containing an unescaped `)` before its own closing paren can
  defeat a naive `\]\(([^)]+)\)`-style extraction. Full CommonMark-correct balanced-paren parsing
  is not required — choose a pragmatic extraction and document the known limitation in the helper's
  docstring; migrated repo-relative paths are not expected to contain parentheses in practice.
