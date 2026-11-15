---
type: Spec
id: p12-t51-migration-reference-rewrite
title: T51 — Migration Frontmatter Reference Rewriting + arkeology:// Content Rewrite
description: "Build a single authoritative path→artifact_id map from the full migration manifest before any writes (forward-reference safe via pure generate_artifact_id), resolve frontmatter references: path entries to identifiers to populate the references field, apply bounded path normalization, and leave http(s):// URLs and unresolved/excluded targets untouched and reported once, a reference left unresolved being added later by hand with link_metadata. A path that appears only in the body is never discovered; the server-side content rewrite of resolved paths is T56's."
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
    title: Artifact Cross-Referencing — First-Class references Field, Migration Rewrite, and referenced_by Warning
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-05-29-deterministic-artifact-ids.md
    title: Deterministic Slug-Based Artifact Identifiers
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/specs/p12-t46-references-field.md
    title: T46 — references First-Class Field on Artifact + write/read/list Surfacing + Filter
    last_modified: 2026-08-17T00:00:00Z
  - resource: plugins/arkeology/skills/migrating-to-arkeology/SKILL.md
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/specs/p12-t56-deterministic-content-reference-rewrite.md
    title: T56 — Deterministic Server-Side Content Reference Rewrite (Frontmatter + Body)
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/specs/p9-t30-write-artifacts.md
    title: Write Performance Z1 — write_artifacts + migrate_artifacts + P4 Section Truncation
  - resource: docs/contracts/modules/arkeology.tools.link_metadata.md
    title: arkeology.tools.link_metadata
  - resource: docs/contracts/modules/arkeology.tools.migrate_artifacts.md
    title: arkeology.tools.migrate_artifacts
  - resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
generated:
  by: "axians-architect/claude-opus-4.8"
  at: 2026-07-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:28:28Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T51 — Migration Frontmatter Reference Rewriting + `arkeology://` Content Rewrite

## TL;DR

Give migration a deterministic, forward-safe way to carry cross-references across the file-path →
`artifact_id` boundary: pure, testable resolution helpers in the server package (path normalization
+ a full-manifest path→id map built via the pure `generate_artifact_id`), and a
`migrating-to-arkeology` skill flow that builds the map from the **full** manifest before any writes,
resolves frontmatter `references:` path entries into the `references` field (T46), applies
**bounded** path normalization, and leaves `http(s)://` URLs and any unresolved/excluded target
**untouched** and reported. Only paths a file declares in its frontmatter `references:` list are
resolved — a link that appears only in the body is never discovered. Rewriting the resolved paths in
the stored content to `arkeology://artifact/{id}` is the server-side rewrite T56 specifies. A
reference left unresolved is added later by hand with `link_metadata`. The skills' offline copies of
the identifier and reference-extraction algorithms are held to the server's by a drift test.
(FR-52, AC-58.)

## 1. Problem Statement

Existing docs reference sibling files by repo-relative path, but a path and an `artifact_id` are
different addressing schemes and nothing carried those links across migration. Because
`generate_artifact_id` is a pure function of type + title (+ date for tier 2), a target's future
identifier is computable before it is written — so a single authoritative path→id map built from the
full manifest turns same-batch and multi-session forward references into non-problems
(adr-2026-07-03-artifact-cross-referencing D4). Resolution must be deliberately narrow (declared
frontmatter entries only, bounded normalization, transparent fall-through) because the inversion
analysis flagged
**migration fragility**, not broken links, as the primary risk
(adr-2026-07-03-artifact-cross-referencing D1/D5/D6).

A target that is not in the manifest at all — never discovered, excluded, or added only later —
cannot be resolved at first write: the migration reports it once, and the operator adds it later by
hand (R6). The manifest's shape and the result-to-status mapping are `p9-t30-write-artifacts`'s; the
post-migration commit backfill is `p10-t40-migration-skill-commit-refs-backfill`'s; the content
rewrite is `p12-t56-deterministic-content-reference-rewrite`'s.

All six stories are P1: same-batch forward reference resolves (P1); URLs and unresolved/excluded
targets left untouched (P1); bounded normalization ceiling (P1); first-write only, no retroactive
content patch (P1); the skills' offline ID algorithm cannot drift from the server's (P1); the skills'
offline reference-extraction algorithm cannot drift from the server's (P1).

## 2. Rules — The path→identifier map

### R1 — One path→`artifact_id` map from the full manifest, built before any writes

When migration begins, the skill flow builds a single path→`artifact_id` map from the FULL
`ARKEOLOGY_IMPORT.yaml` manifest — every entry, any status, across sessions, not the retry subset —
before any writes, computing each identifier via the pure `generate_artifact_id` rules (type slug,
date for tier 2, title slug, deterministic hash suffix). A reference to a target that is in the
manifest but scheduled for import later therefore still resolves.

**Example**

- Given file `A.md` whose frontmatter `references:` lists `../decisions/B.md`, and `B.md` is in the
  same manifest but scheduled for import later, when migration runs, then `A`'s `references` field
  contains `B`'s Arkeology identifier and the path is rewritten to `arkeology://artifact/{B-id}` in
  `A`'s stored content — even though `B` is written after `A`.

Source: AC-58 — the forward-reference part; adr-2026-07-03-artifact-cross-referencing D4 — the full-manifest (multi-session safety) part

## 3. Rules — Resolving a `references:` entry

### R2 — A well-formed relative path is first joined against the referencing file's directory

When a `references:` path is well-formed relative — it starts with `./` or `../`, after backslash
normalization — the system first joins it against the referencing file's own directory
(`join_reference_path`, POSIX join + normpath) before attempting the map lookup, and the joined
result is then passed through the bounded normalization ceiling before the lookup. A path that does
not start with `./` or `../`, or that is a URL, passes through this step unchanged.

This is resolution of a well-formed relative path, not the "repair" of a genuinely broken reference
that adr-2026-07-03-artifact-cross-referencing D6 deliberately excludes: a `../` that, once joined,
escapes above the repo root normalizes to a path absent from the map and falls through to the
unresolved handling exactly like any other non-matching path — no error, no special-casing.

**Example**

- Given `../decisions/B.md` written inside `notes/A.md`, when resolving, then it resolves against
  `decisions/B.md` in the map.

### R3 — Bounded normalization ceiling

When normalizing a `references:` path (after the join step, when applicable), the system converts
backslashes to forward slashes and attempts the lookup against the map under a small set of
leading-prefix variants — stripping only `./`, a single leading `/`, or none — and no further
transformation. A path that does not match after the join (if applicable) and bounded
normalization is left completely untouched and falls through to the general (unresolved) handling:
no further repair is attempted — genuinely broken/inconsistent source references are surfaced in
the report instead.

**Example**

- Given a backslash Windows-style path in `references:`, when resolving, then backslashes are
  converted to forward slashes and the lookup is attempted stripping only `./`, a single leading
  `/`, or none.

Source: adr-2026-07-03-artifact-cross-referencing D6

### R4 — `http(s)://` URLs are left untouched

When a `references:` entry is an `http://` / `https://` URL, the system leaves it verbatim, never
treats it as a path candidate, and never adds it to `references`.

**Example**

- Given a `references:` entry `https://example.com/x`, when migration runs, then it is left
  verbatim and is not in `references`.

Source: AC-58

### R5 — A resolved path populates `references` and is rewritten to `arkeology://artifact/{id}`

When a `references:` path resolves, the system adds the resolved full S3 key (the operative
`artifact_id`) to the migrated artifact's `references` field — threaded into the
`migrate_artifacts` descriptor (T46) — and the server rewrites that path in the stored content to
`arkeology://artifact/{id}`, where `{id}` is that same full key (`p12-t56-deterministic-content-reference-rewrite`
R1). Mixed addressing (`arkeology://…` next to raw `/docs/…`) is the correct permanent steady
state.

Source: AC-58; adr-2026-07-03-artifact-cross-referencing D2/D3 — the `arkeology://artifact/{id}` link part; adr-2026-07-03-artifact-cross-referencing D3 — the mixed-addressing part; p12-t56-deterministic-content-reference-rewrite R1

### R6 — An unresolved, excluded or never-migrated target is left untouched and reported once

When a `references:` path does not resolve — unresolved, mapped to an excluded (e.g. git-only ADR)
target, or never migrated — the system leaves the original path text untouched in content, omits
it from `references`, and surfaces it once, in the migration report — never drops it silently. A
reference left unresolved is added later by hand with `link_metadata`, which merges it into the
artifact's `references` without rewriting stored content.

**Example**

- Given `notes/A.md` whose `references:` lists `../decisions/B.md`, and `decisions/B.md` is not in
  the manifest, when `A.md` is written, then `A`'s stored content keeps `../decisions/B.md`, `A`'s
  `references` does not hold it, and the migration report names it once for `A.md`.

Source: AC-58, cluster E

## 4. Rules — Rewrite scope

### R7 — Which occurrences of a resolved path are rewritten is T56's

Which occurrences of a resolved path the stored content has rewritten — the frontmatter
`references:` list and markdown link targets in the body — and that a path never declared in the
file's own frontmatter is never discovered, are specified in
`p12-t56-deterministic-content-reference-rewrite`.

Source: adr-2026-07-03-artifact-cross-referencing D1, D16; p12-t56-deterministic-content-reference-rewrite R1, R3, R8

### R8 — Content is rewritten only at first-write time

When content is rewritten, the system does so only at first-write time (migration); it never
retroactively patches already-written content — already-written tier 2 content included.

Source: FR-52; adr-2026-07-03-artifact-cross-referencing D8 — the tier 2 part

### R9 — The skill orchestrates; the resolution logic lives in pure, unit-testable server helpers

The pure resolution/normalization helpers live in the server package (`src/arkeology/references.py`)
for testability, while the skill orchestrates migration: it builds the map, resolves each file's
`references:` entries with the documented algorithm and threads the results into the
`migrate_artifacts` descriptors. The helpers are the authoritative, unit-tested reference
implementation of the adr-2026-07-03-artifact-cross-referencing D4/D6 algorithm, and the system
makes them unit-testable (no AWS, no I/O) so the algorithm is verifiable independently of the
skill prose. The content rewrite itself runs server-side inside `migrate_artifacts` (R7).

**Why:** discovery, classification and resolution are an evolving operational workflow kept out of
the server core, while the content rewrite needs a byte-exact, idempotent guarantee only tested
code can give; the operator confirmed the server-side-helper-plus-skill placement.

Source: OQ-T51-a (Operator, 2026-07-03); ADR-012; adr-2026-07-03-artifact-cross-referencing D16

## 5. Rules — The skills' offline algorithms

### R10 — The skills' offline identifier computation matches `generate_artifact_id`

When a skill documents the offline identifier computation, the system keeps that documented
algorithm behaviourally identical to `src/arkeology/artifact.py::generate_artifact_id` composed into
the full key form `{write_prefix}/{bare_id}{extension}`. A migration run computes identifiers
before any artifact exists, from a `python3` snippet documented in the skill; if
`generate_artifact_id` changes and the snippets do not, every reference resolves to an identifier no
artifact will ever have — the whole rewrite silently produces dead links, and nothing fails.

- Executed over a shared table of representative inputs, the ID-computation snippet documented in
  `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` ("Building the path→full-key map")
  produces, for every input, exactly the full key
  `f"{write_prefix}/{generate_artifact_id(tier=…, type=…, date=…, title=…)}{extension}"`.
- A change to `generate_artifact_id`'s slug rules, hash length, hash input, or tier-2 / tier-3
  component order that is not mirrored in a skill snippet makes the drift test fail, naming the
  diverging input.
- The input table exercises at minimum: tier 2 and tier 3; a type containing an underscore; a
  non-ASCII title; a title whose punctuation collapses to the same slug as another; a title longer
  than the 60-character slug truncation; a title that slugifies to empty (the `artifact` fallback);
  and a path with and without a file extension.

### R11 — The skills' offline reference extraction matches `extract_references_list`

When a skill documents the offline reference-extraction algorithm, the system keeps that documented
algorithm behaviourally identical to the pure `src/arkeology/references.py::extract_references_list` helper
(`yaml.safe_load` primary path, stdlib-only manual-scan fallback for outright-malformed
frontmatter), documented as a canonical snippet in the migration skill in the same style/location
as the existing ID-computation snippet, and guarded by a second parameterised drift test in the
same drift test module, `tests/unit/test_skill_artifact_id_drift.py`, rather than a new one. A
migration run must extract a file's
frontmatter `references:` list before resolving any entry against the path→id map, from a `python3`
snippet documented in the skill; if `extract_references_list` changes and the snippets do not, or if
an agent hand-rolls the extraction instead of using the documented snippet, the extracted path text
can be silently corrupted (a YAML inline comment folded into the path text) and every reference
downstream fails to resolve without anything failing loudly.

- Executed over a shared table of representative frontmatter texts, the reference-extraction
  snippet documented in `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` produces, for
  every input, exactly the same ordered list of entries as `extract_references_list`.
- A change to `extract_references_list`'s YAML-primary parsing or its stdlib-only manual-scan
  fallback that is not mirrored in a skill snippet makes the drift test fail, naming the diverging
  case.
- The input table exercises at minimum: a block-style list; a flow-style list, including the empty
  `references: []` form; a `references:` key absent from the frontmatter; an inline `# comment`
  trailing an unquoted item; a quoted item containing a literal `#`; and frontmatter that fails to
  parse as YAML outright, exercising the manual-scan fallback.

**Why:** The reference-extraction step had the same unguarded-duplication shape as the ID step —
no canonical algorithm was documented for it, unlike the adjacent path→id-map step, and a real
migration run hand-rolled a naive regex line-scanner instead that silently corrupted resolution by
capturing a YAML inline comment as part of an extracted path. The same decision as for the ID
algorithm applies without re-litigation (decided/shipped 2026-08-13, architect).

Source: OQ-T51-b (Operator, 2026-08-12) and its addendum (architect, 2026-08-13)

### R12 — Both offline algorithms are held to the server by one drift-test module, never by import

The skills keep their own offline copy of the ID algorithm and of the reference-extraction
algorithm — they must compute both before the server is reachable — and both copies are held to
the server's behaviour by a drift test, not by import.

- When the unit suite runs, the system executes each skill's documented snippet — extracted from
  the SKILL.md file itself, never retyped into the test — over a shared input table (for reference
  extraction, a shared frontmatter-text input table) and fails if any produced identifier, or any
  produced entry list, differs from the server's for the same input.
- Every skill that documents either snippet is covered — today the migration skill alone — none by
  transitive assumption from another.
- When the drift test cannot locate a skill's documented snippet (block moved, renamed, or
  deleted), it fails rather than skips — an unlocatable algorithm is itself drift, not a reason to
  skip.
- The drift test asserts on computed output only and never on the skill's source text — no
  substring match, no `inspect.getsource` comparison. A source-text assertion passes as long as the
  text is present and says nothing about what the algorithm computes.
- When a SKILL.md documents more than one offline snippet (identifier computation and reference
  extraction, side by side), the test disambiguates which snippet (heredoc) it is extracting and
  executing rather than assuming a single offline snippet per file.
- When a new skill introduces its own offline identifier computation or offline
  reference-extraction computation, it is added to the same parameterised drift test rather than
  left unguarded.
- The extraction mechanism (regex on the fenced block vs. an explicit marker added to the skill)
  and the execution mechanism (subprocess vs. `exec`) are implementation choices left to the
  developer, provided the test never asserts on source text and never silently skips.

**Why:** Single-sourcing (the skill imports or calls the server) is not available: a migration run
computes identifiers offline, before the server is necessarily installed, configured,
or reachable — that is the whole reason the algorithm is pure and documented in prose — so
importing `references.py` is not available to the skills. The duplication is therefore accepted and
guarded, not removed: drift test chosen over single-sourcing.

Source: OQ-T51-b (Operator, 2026-08-12)

## 6. Boundaries

**Always:**
- Only paths declared in a file's own frontmatter `references:` list are resolved
  (adr-2026-07-03-artifact-cross-referencing D1); which of their occurrences in the content are
  rewritten is T56's (R7).
- `references` holds resolved full S3 keys (the operative `artifact_id`);
  content links use `arkeology://artifact/{id}` (adr-2026-07-03-artifact-cross-referencing D2/D3),
  where `{id}` is that same full key.
- The map is built from the FULL manifest, not the retry subset
  (adr-2026-07-03-artifact-cross-referencing D4 — multi-session safety).
- A well-formed relative path (`./`/`../`) is joined against the referencing file's directory before
  the adr-2026-07-03-artifact-cross-referencing D6 normalization ceiling — this is resolution, not
  repair: an escaping `../` still falls through to unresolved, it does not raise or get
  special-cased.
- Mixed addressing (`arkeology://…` next to raw `/docs/…`) is the correct permanent steady state
  (adr-2026-07-03-artifact-cross-referencing D3).
- The skills keep their own offline copy of the ID algorithm and of the reference-extraction
  algorithm — they must compute both before the server is reachable — and both copies are held
  to the server's behaviour by a drift test, not by import.

**Ask First:**
- None. Resolution scope and the normalization ceiling are fixed by ADR-012.

**Never:**
- Do not complete unresolved references automatically: no later migration run re-resolves them,
  nothing records them for one, and no separate backfill skill ships; a reference left unresolved
  is added by hand with `link_metadata` (R6) — revisit if operators repeatedly need to complete
  references after the migration.
- Do not discover or resolve a path that appears only in the body
  (adr-2026-07-03-artifact-cross-referencing D1).
- Do not attempt to repair genuinely broken/inconsistent source references beyond the bounded
  normalization (adr-2026-07-03-artifact-cross-referencing D6) — surface them in the report instead.
- Do not retroactively rewrite already-written tier 2 content
  (adr-2026-07-03-artifact-cross-referencing D8).
- Do not try to single-source the skills' ID computation by importing `references.py` /
  `artifact.py` from the skill, shelling out to the installed package, or calling an MCP tool —
  the skills run before the server is necessarily installed or reachable (decided 2026-08-12).
- Do not assert on skill source text in the drift test — behavioural equivalence only.

## 7. For the developer agent

### Files to Touch

Skills live only at `plugins/arkeology/skills/<name>/`.

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_references_resolution.py` | Create | Pure-helper tests: map build, normalization ceiling, URL passthrough, forward reference, unresolved fall-through — Red first |
| `src/arkeology/references.py` | Create | Pure helpers: `normalize_reference_path(path)`, `build_path_to_id_map(manifest_entries)` (uses `generate_artifact_id`), `join_reference_path(referencing_file_path, reference_path)` (relative-path join), `resolve_reference(path, path_to_id_map, referencing_file_path=None)` → id or `None` |
| `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` | Modify | Add the build-map → resolve-frontmatter → populate `references` → report-unresolved flow to Steps 3.A/3.B; document the normalization ceiling and URL/unresolved passthrough; no hand-rewrite of content — the server rewrites it (T56). The report names each unresolved path once (R6); the skill records no unresolved path in the manifest and has no completing last step |
| `plugins/arkeology/skills/backfilling-references/` | Delete | The separate backfill skill, retired with no replacement (R6, Never) |
| `README.md` | Modify | Remove the `backfilling-references` row from the skills table; say that a reference the migration leaves unresolved is added by hand with `link_metadata` |
| `.opencode/plugins/arkeology.js`, `plugins/arkeology/.claude-plugin/plugin.json`, `install.sh` | Verify (flag) | No change expected — each discovers skill directories under `plugins/arkeology/skills/`, so a deleted directory is no longer offered. Uncertain: a copy already installed on an engineer's machine (for example by `gh skill install`) is not removed by a re-install; confirm whether the sync skill removes it or the release notes must say so |

**ID drift test (R10, R12):**

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_skill_artifact_id_drift.py` | Create | The drift test. Parameterised over the skill files that document a snippet — today the migration skill alone; extracts each one's documented `python3` ID snippet from its SKILL.md, executes it, compares the produced full key against `generate_artifact_id` + `{write_prefix}/{bare_id}{extension}` for every row of a shared input table; fails if a snippet cannot be located. Pure — no AWS, no moto, no Bedrock |
| `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` | Verify (flag) | Snippet in the "Building the path→full-key map" section (`python3 - "$TYPE" "$TIER" "$DATE" "$TITLE" "$EXTENSION" "$WRITE_PREFIX"` with a `<<'PY'` heredoc). Change only if the test proves it already diverges, or if it needs a stable delimiter for extraction |
| `src/arkeology/references.py` | Modify | Module docstring's "do not reimplement the algorithm elsewhere" is contradicted by the skill copy: state that the migration skill keeps a deliberate offline copy and that `tests/unit/test_skill_artifact_id_drift.py` is what holds it to this module |

### Contracts

- `docs/contracts/modules/arkeology.tools.migrate_artifacts.md` § migrate_artifacts — the `references` and `resolved_references_map` descriptor keys a resolved path is threaded into, and the server-side content rewrite (R5, R9).
- `docs/contracts/modules/arkeology.tools.link_metadata.md` § link_metadata — the tool R6 names for adding, by hand, a reference the migration left unresolved (R6).
- `docs/contracts/data/s3.artifact.md` § generate_artifact_id — the identifier the map and the skills' offline snippet compute before any artifact exists (R1, R10).
- `docs/contracts/data/s3-annotations.artifact.md` § Storage Shape — the full-key form a resolved `references` element takes (R5).

### Testing Approach

**Project uses TDD.** Write `tests/unit/test_references_resolution.py` first (Red), then implement
`src/arkeology/references.py` (Green). The skill prose is authored to match the tested helper
semantics.

Pure-helper unit tests (no AWS, no moto):
- `build_path_to_id_map` — given manifest entries with `path`, `type`, `title`, `tier`, `date`,
  produces `{path: artifact_id}` using `generate_artifact_id`; identifiers match the deterministic
  scheme; forward references present in the map regardless of entry order.
- `normalize_reference_path` — backslash→forward-slash; strips `./`, single leading `/`, none; no
  other transformation.
- `resolve_reference` — resolves a normalized path against the map; returns `None` for URLs, for
  paths absent from the map, and for paths that only match beyond the normalization ceiling.
- `join_reference_path` — joins a well-formed `./`/`../` path against the referencing file's
  directory (POSIX semantics); passes URLs and non-relative paths through unchanged; an escaping
  `../` normalizes to a path that is simply absent from the map.
- URL passthrough — `http(s)://` entries return `None` (never treated as paths).
- Forward-reference resolution — a path whose target is later in the manifest still resolves.
- Unresolved fall-through — a path with no match returns `None` (caller leaves it untouched + reports).

Skill-level behaviour (AC-58) is validated by the migration integration/manual flow, not unit tests,
since the resolution orchestration is skill prose driving `migrate_artifacts`; the content
rewrite's tests are T56's.

**Skill ID drift test (R10, R12).** Written before any change to `references.py`'s docstring or to
either skill snippet, and expected to pass on first run against today's tree (the snippets are
believed correct; the test exists to keep them that way — a Red first run would mean the snippets
have already drifted, which is a defect in them, not in the test).

- One test module, `tests/unit/test_skill_artifact_id_drift.py`, parameterised over the skill files
  that document a snippet — today the migration skill alone — so another skill is one list entry
  away from being covered.
- Per skill: locate the documented ID snippet in the SKILL.md, dedent it, execute it (subprocess
  or `exec` with the documented arguments — the developer picks; the snippet already takes its six
  values as `sys.argv[1:7]`), and compare its printed full key against
  `f"{write_prefix}/{generate_artifact_id(tier=…, type=…, date=…, title=…)}{extension}"`.
- Shared input table covering the cases listed in R10 (tier 2/3, underscore type, non-ASCII
  title, punctuation-collapse pair, over-60-char title, empty-slug title, with/without extension).
  One table serves every covered skill.
- Failure output must name the input that diverged and both identifiers, so the next reader knows
  which side moved.
- Snippet not found → fail with a message pointing at the skill file and the expected block.
- No assertion on the skill's source text; extraction is a means of *executing* the documented
  algorithm, never a means of comparing it as a string.
