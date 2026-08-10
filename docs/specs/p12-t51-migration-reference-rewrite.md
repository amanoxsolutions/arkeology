---
type: spec
title: T51 — Migration Frontmatter Reference Rewriting + cairn:// Content Rewrite
description: Build a single authoritative path→artifact_id map from the full migration manifest before any writes (forward-reference safe via pure generate_artifact_id), resolve frontmatter references: path entries to identifiers to populate the references field, rewrite resolved references in stored content to cairn://artifact/{id}, apply bounded path normalization, and leave http(s):// URLs and unresolved/excluded targets untouched. In-body markdown links out of scope.
tags: []
timestamp: 2026-07-03T00:00:00Z
okf_version: "0.1"
feature: p12-t51-migration-reference-rewrite
status: ready
phase: 12
task: 51
references:
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/architecture-decisions/adr-2026-05-29-deterministic-artifact-ids.md
  - docs/specs/p12-t46-references-field.md
  - skills/migrating-to-cairn/SKILL.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-07-03"
revised:
  by: "tech-writer"
  date: "2026-07-04"
---

# T51 — Migration Frontmatter Reference Rewriting + `cairn://` Content Rewrite

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Give migration a deterministic, forward-safe way to carry cross-references across the file-path →
`artifact_id` boundary. Add pure, testable resolution helpers (path normalization + a full-manifest
path→id map built via the pure `generate_artifact_id`) to the server package, and update the
`migrating-to-cairn` skill to: build the map from the **full** manifest before any writes, resolve
frontmatter `references:` path entries into the `references` field (T46), rewrite resolved
references in stored content to `cairn://artifact/{id}`, apply **bounded** path normalization, and
leave `http(s)://` URLs and any unresolved/excluded target **untouched** and reported. In-body
markdown links are out of scope. (FR-52, AC-58.)

> **Revised 2026-07-04 (tech-writer).** A well-formed relative reference
> (`./` or `../`) is **first joined against the referencing file's own directory**
> (`join_reference_path`, POSIX semantics) *before* the D6 bounded-normalization lookup below — this
> is what makes `../decisions/B.md` written inside `notes/A.md` resolve against `decisions/B.md` in
> the map (see Story 1's example). This is resolution of a well-formed relative path, not the
> "repair" of a genuinely broken reference that D6 deliberately excludes; a `../` that escapes above
> the repo root still normalizes to a path absent from the map and falls through to unresolved. See
> the Requirements/Boundaries additions below.

## Problem Statement

Existing docs reference sibling files by repo-relative path, but a path and an `artifact_id` are
different addressing schemes and nothing carried those links across migration. Because
`generate_artifact_id` is a pure function of type + title (+ date for tier 2), a target's future
identifier is computable before it is written — so a single authoritative path→id map built from the
full manifest turns same-batch and multi-session forward references into non-problems (ADR-012 D4).
The rewrite must be deliberately narrow (frontmatter only, bounded normalization, transparent
fall-through) because the inversion analysis flagged **migration fragility**, not broken links, as
the primary risk (ADR-012 D1/D5/D6).

## User Stories

### Story 1 — Same-batch forward reference resolves (P1)

**Acceptance criteria:**
- Given file `A.md` whose frontmatter `references:` lists `../decisions/B.md`, and `B.md` is in the
  same manifest but scheduled for import later, when migration runs then `A`'s `references` field
  contains `B`'s cairn identifier and the path is rewritten to `cairn://artifact/{B-id}` in `A`'s
  stored content — even though `B` is written after `A`. (AC-58)

### Story 2 — URLs and unresolved/excluded targets left untouched (P1)

**Acceptance criteria:**
- Given a `references:` entry `https://example.com/x`, when migration runs then it is left verbatim,
  never treated as a path candidate, and never added to `references`. (AC-58)
- Given a `references:` path that maps to an excluded (e.g. git-only ADR) or never-migrated target,
  then the original path text is left untouched in content, the entry is NOT added to `references`,
  and the case is surfaced in the migration report. (AC-58, cluster E)

### Story 3 — Bounded normalization ceiling (P1)

**Acceptance criteria:**
- Given a backslash Windows-style path in `references:`, when resolving then backslashes are
  converted to forward slashes and the lookup is attempted stripping only `./`, a single leading
  `/`, or none.
- Given a well-formed relative path (`./` or `../`) in `references:`, when resolving then it is
  first joined against the referencing file's own directory (POSIX semantics), and the joined
  result is then passed through the bounded normalization above before the map lookup — this is
  what makes Story 1's `../decisions/B.md` example resolve.
- Given a `../` that, once joined, escapes above the repo root, then the joined path is absent from
  the map and falls through to the unresolved handling exactly like any other non-matching path — no
  error, no special-casing.
- Given a path that does not match after the join (if applicable) and bounded normalization, then it
  is left completely untouched and falls through to the general (unresolved) handling — no further
  repair is attempted.

### Story 4 — First-write only; no retroactive content patch (P1)

**Acceptance criteria:**
- Given content rewriting, then it happens only at first-write time (migration) — already-written
  tier 2 content is never retroactively patched. (FR-52)
- Given in-body markdown links, then they are NOT rewritten (out of scope). (ADR-012 D1)

## Requirements

- WHEN migration begins THE SYSTEM (skill flow) SHALL build a single path→`artifact_id` map from the
  FULL `CAIRN_IMPORT.yaml` manifest (every entry, any status, across sessions) before any writes,
  computing each identifier via the pure `generate_artifact_id` rules (type slug, date for tier 2,
  title slug, deterministic hash suffix).
- WHEN a `references:` path is well-formed relative (starts with `./` or `../`, after backslash
  normalization) THE SYSTEM SHALL first join it against the referencing file's own directory
  (`join_reference_path`, POSIX join + normpath) before attempting the map lookup — a path that
  does not start with `./` or `../`, or that is a URL, passes through this step
  unchanged.
- WHEN normalizing a `references:` path (after the join step above, when applicable) THE SYSTEM
  SHALL convert backslashes to forward slashes and attempt lookup against the map under a small set
  of leading-prefix variants (`./`, single leading `/`, none) — and no further transformation.
- WHEN a `references:` entry is an `http://` / `https://` URL THE SYSTEM SHALL leave it untouched and
  never treat it as a path.
- WHEN a `references:` path resolves THE SYSTEM SHALL add the resolved full S3 key (the operative
  `artifact_id`) to the migrated artifact's `references` field (threaded into
  the `migrate_artifacts` descriptor, T46) and rewrite that path in the stored content to
  `cairn://artifact/{id}`.
- WHEN a `references:` path does not resolve (unresolved / excluded / never-migrated) THE SYSTEM
  SHALL leave the original path text untouched in content, omit it from `references`, and surface it
  in the migration report — never drop it silently.
- WHEN content is rewritten THE SYSTEM SHALL do so only at first-write time; it SHALL NOT
  retroactively patch already-written content.
- WHEN the resolution / normalization logic is implemented as pure helpers THE SYSTEM SHALL make them
  unit-testable (no AWS, no I/O) so the algorithm is verifiable independently of the skill prose.

## Boundaries

**Always:**
- Only the frontmatter `references:` YAML list is mechanically rewritten (ADR-012 D1).
- `references` holds resolved full S3 keys (the operative `artifact_id`);
  content links use `cairn://artifact/{id}` (D2/D3), where `{id}` is that same full key.
- The map is built from the FULL manifest, not the retry subset (D4 — multi-session safety).
- A well-formed relative path (`./`/`../`) is joined against the referencing file's directory before
  the D6 normalization ceiling — this is resolution, not repair: an escaping
  `../` still falls through to unresolved, it does not raise or get special-cased.
- Mixed addressing (`cairn://…` next to raw `/docs/…`) is the correct permanent steady state (D3).

**Ask First:**
- Nothing — scope and ceiling fixed by ADR-012.

**Never:**
- Do not rewrite in-body markdown links (D1).
- Do not attempt to repair genuinely broken/inconsistent source references beyond the bounded
  normalization (D6) — surface them in the report instead.
- Do not retroactively rewrite already-written tier 2 content (D8).
- Do not add server-side rewrite logic inside `migrate_artifacts` beyond threading the `references`
  descriptor key (ADR-012 rejected server-side rewrite; the skill orchestrates).

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_references_resolution.py` | Create | Pure-helper tests: map build, normalization ceiling, URL passthrough, forward reference, unresolved fall-through — Red first |
| `src/cairn_mcp/references.py` | Create | Pure helpers: `normalize_reference_path(path)`, `build_path_to_id_map(manifest_entries)` (uses `generate_artifact_id`), `join_reference_path(referencing_file_path, reference_path)` (relative-path join), `resolve_reference(path, path_to_id_map, referencing_file_path=None)` → id or `None` |
| `skills/migrating-to-cairn/SKILL.md` | Modify | Add the build-map → resolve-frontmatter → populate `references` → rewrite content to `cairn://artifact/{id}` → report-unresolved flow to Steps 3.A/3.B; document the normalization ceiling and URL/unresolved passthrough; in-body links explicitly out of scope |

## Testing Approach

**Project uses TDD.** Write `tests/unit/test_references_resolution.py` first (Red), then implement
`src/cairn_mcp/references.py` (Green). The skill prose is authored to match the tested helper
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
since the rewrite orchestration is skill prose driving `migrate_artifacts`.

> **Consistency note (2026-07-06, shipped in `7a697dd`).** An ordinary overwriting write now
> **replaces** `references` outright rather than merging it with any prior stored value (see
> `docs/specs/p12-t46-references-field.md`'s forward-pointer note). This task is already consistent
> with that decision and needs no behavioural change: it only ever
> populates `references` on a **first write** (migration never overwrites an existing key), where
> there is no prior stored value to merge against in the first place — the resolved frontmatter
> list this task produces simply *becomes* the field's initial value, which is what "replace" means
> for a first write by definition.

## Open Questions

- **OQ-T51-a (CONFIRMED by operator, 2026-07-03):** The pure resolution/normalization helpers live in
  the server package (`src/cairn_mcp/references.py`) for testability even though ADR-012 assigns the
  rewrite orchestration to the skill. Decision: keep the helpers as the authoritative, unit-tested
  reference implementation of the D4/D6 algorithm; the skill documents the same algorithm for the
  agent to apply in-context. This satisfies both the ADR (skill orchestrates, no server-side rewrite)
  and the plan (testable Red/Green logic). Operator confirmed the server-side-helper-plus-skill
  placement.
