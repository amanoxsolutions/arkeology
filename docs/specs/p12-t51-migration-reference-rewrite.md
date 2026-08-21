---
type: spec
title: T51 — Migration Frontmatter Reference Rewriting + arkeology:// Content Rewrite
description: Build a single authoritative path→artifact_id map from the full migration manifest before any writes (forward-reference safe via pure generate_artifact_id), resolve frontmatter references: path entries to identifiers to populate the references field, rewrite resolved references in stored content to arkeology://artifact/{id}, apply bounded path normalization, and leave http(s):// URLs and unresolved/excluded targets untouched. In-body markdown links out of scope.
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
  - plugins/arkeology/skills/migrating-to-arkeology/SKILL.md
  - docs/planning-artifacts/requirements.md
authored:
  by: "architect"
  date: "2026-07-03"
revised:
  by: "architect"
  date: "2026-08-13"
---

# T51 — Migration Frontmatter Reference Rewriting + `arkeology://` Content Rewrite

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Give migration a deterministic, forward-safe way to carry cross-references across the file-path →
`artifact_id` boundary. Add pure, testable resolution helpers (path normalization + a full-manifest
path→id map built via the pure `generate_artifact_id`) to the server package, and update the
`migrating-to-arkeology` skill to: build the map from the **full** manifest before any writes, resolve
frontmatter `references:` path entries into the `references` field (T46), rewrite resolved
references in stored content to `arkeology://artifact/{id}`, apply **bounded** path normalization, and
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

> **Revised 2026-08-12 (tech-writer).** OQ-T51-a's "helpers are authoritative, the skill
> documents the same algorithm" split shipped with nothing holding the two sides together.
> `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` ("Building the path→full-key
> map") and `plugins/arkeology/skills/backfilling-references/SKILL.md` (Workflow step
> "Build the path→full-key map") each carry a
> standalone `python3` snippet that recomputes the identifier, and `src/arkeology/references.py`'s
> module docstring tells the reader not to reimplement the algorithm — while two copies of it sit
> in the skills, unguarded: either can drift from `generate_artifact_id` without any test failing,
> and the result is a migration that resolves every reference to an identifier no artifact will
> ever have. **Decision (operator, 2026-08-12): add a drift test; do not attempt to
> single-source.** The skills must compute identifiers *offline*, during a migration or backfill
> run, before the server is necessarily reachable or even installed, so importing `references.py`
> is not available to them. Story 5 and the requirements below pin the two copies behaviourally.

> **Revised 2026-08-13 (architect).** The reference-extraction step this rewrite depends on —
> "parse the frontmatter `references:` list" — had the same unguarded-duplication problem as
> OQ-T51-b: no canonical algorithm was documented for it, unlike the adjacent path→id-map step,
> and a real migration run hand-rolled a naive regex line-scanner instead that silently corrupted
> resolution by capturing a YAML inline comment as part of an extracted path. Shipped fix: a pure
> `extract_references_list` helper added to `src/arkeology/references.py` (`yaml.safe_load`
> primary path, stdlib-only manual-scan fallback for outright-malformed frontmatter), the matching
> canonical snippet documented in both skill files in the same style/location as the existing
> ID-computation snippet, and `tests/unit/test_skill_artifact_id_drift.py` extended with a second
> parameterised drift test guarding it. Same decision as OQ-T51-b applies: guard by drift test,
> do not attempt to single-source. See Story 6, the "Skill-side reference extraction"
> requirements below, and the OQ-T51-b addendum.

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
  contains `B`'s Arkeology identifier and the path is rewritten to `arkeology://artifact/{B-id}` in `A`'s
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

### Story 5 — The skills' offline ID algorithm cannot drift from the server's (P1)

A migration or backfill run computes identifiers before any artifact exists, from a
`python3` snippet documented in the skill. If `generate_artifact_id` changes and the snippets
do not, every reference resolves to an identifier no artifact will ever have — the whole
rewrite silently produces dead links, and nothing fails.

**Acceptance criteria:**
- Given the ID-computation snippet documented in
  `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md`, when it is executed over a shared
  table of representative inputs, then for every input it produces exactly the full key
  `f"{write_prefix}/{generate_artifact_id(tier=…, type=…, date=…, title=…)}{extension}"`.
- Given the same for `plugins/arkeology/skills/backfilling-references/SKILL.md`, then the same
  equality holds — both skills are covered, neither by transitive assumption from the other.
- Given a change to `generate_artifact_id`'s slug rules, hash length, hash input, or tier-2 /
  tier-3 component order that is not mirrored in a skill snippet, when the suite runs, then the
  drift test fails and names the diverging input.
- Given the input table, then it exercises at minimum: tier 2 and tier 3; a type containing an
  underscore; a non-ASCII title; a title whose punctuation collapses to the same slug as another;
  a title longer than the 60-character slug truncation; a title that slugifies to empty (the
  `artifact` fallback); and a path with and without a file extension.
- Given the test, then it makes **no assertion about the skill's source text** — no substring
  match, no `inspect.getsource` comparison. A source-text assertion passes as long as the text is
  present and says nothing about what the algorithm computes. It asserts only on computed outputs.
- Given a skill file whose documented snippet can no longer be located for execution (block
  moved, renamed, or deleted), when the test runs, then it fails — an unlocatable algorithm is
  itself drift, not a reason to skip.

### Story 6 — The skills' offline reference-extraction algorithm cannot drift from the server's (P1)

A migration or backfill run must extract an artifact's frontmatter `references:` list before
resolving any entry against the path→id map, from a `python3` snippet documented in the skill —
the same offline-computation shape as Story 5's ID snippet, and the same failure mode: if
`extract_references_list` changes and the snippets do not, or if an agent hand-rolls the
extraction instead of using the documented snippet, the extracted path text can be silently
corrupted (a YAML inline comment folded into the path text) and every reference downstream fails
to resolve without anything failing loudly.

**Acceptance criteria:**
- Given the reference-extraction snippet documented in
  `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md`, when it is executed over a shared
  table of representative frontmatter texts, then for every input it produces exactly the same
  ordered list of entries as `extract_references_list`.
- Given the same for `plugins/arkeology/skills/backfilling-references/SKILL.md`, then the same
  equality holds — both skills are covered, neither by transitive assumption from the other.
- Given a change to `extract_references_list`'s YAML-primary parsing or its stdlib-only
  manual-scan fallback that is not mirrored in a skill snippet, when the suite runs, then the
  drift test fails and names the diverging case.
- Given the input table, then it exercises at minimum: a block-style list; a flow-style list,
  including the empty `references: []` form; a `references:` key absent from the frontmatter; an
  inline `# comment` trailing an unquoted item; a quoted item containing a literal `#`; and
  frontmatter that fails to parse as YAML outright, exercising the manual-scan fallback.
- Given the test, then it makes **no assertion about the skill's source text** — no substring
  match, no `inspect.getsource` comparison. It asserts only on computed output.
- Given a skill file whose documented reference-extraction snippet can no longer be located for
  execution (block moved, renamed, or deleted), when the test runs, then it fails — an
  unlocatable algorithm is itself drift, not a reason to skip.
- Given a SKILL.md that documents both the ID-computation and reference-extraction snippets side
  by side, then the test disambiguates which heredoc it is executing rather than assuming a
  single offline snippet per file.

## Requirements

- WHEN migration begins THE SYSTEM (skill flow) SHALL build a single path→`artifact_id` map from the
  FULL `ARKEOLOGY_IMPORT.yaml` manifest (every entry, any status, across sessions) before any writes,
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
  `arkeology://artifact/{id}`.
- WHEN a `references:` path does not resolve (unresolved / excluded / never-migrated) THE SYSTEM
  SHALL leave the original path text untouched in content, omit it from `references`, and surface it
  in the migration report — never drop it silently.
- WHEN content is rewritten THE SYSTEM SHALL do so only at first-write time; it SHALL NOT
  retroactively patch already-written content.
- WHEN the resolution / normalization logic is implemented as pure helpers THE SYSTEM SHALL make them
  unit-testable (no AWS, no I/O) so the algorithm is verifiable independently of the skill prose.

**Skill-side identifier computation:**

- WHEN a skill documents the offline identifier computation THE SYSTEM SHALL keep that
  documented algorithm behaviourally identical to `src/arkeology/artifact.py::generate_artifact_id`
  composed into the full key form `{write_prefix}/{bare_id}{extension}`.
- WHEN the unit suite runs THE SYSTEM SHALL execute each skill's documented snippet — extracted
  from the SKILL.md file itself, never retyped into the test — over a shared input table and
  SHALL fail if any produced identifier differs from the server's for the same input.
- WHEN the drift test cannot locate a skill's documented snippet THE SYSTEM SHALL fail rather
  than skip.
- WHEN the drift test asserts THE SYSTEM SHALL assert on computed identifiers only and SHALL NOT
  assert on the skill's source text (no substring or `inspect.getsource` comparison).
- WHEN a new skill introduces its own offline identifier computation THE SYSTEM SHALL add it to
  the same parameterised drift test rather than leaving it unguarded.

**Skill-side reference extraction:**

- WHEN a skill documents the offline reference-extraction algorithm THE SYSTEM SHALL keep that
  documented algorithm behaviourally identical to
  `src/arkeology/references.py::extract_references_list` (`yaml.safe_load` primary path,
  stdlib-only manual-scan fallback for outright-malformed frontmatter).
- WHEN the unit suite runs THE SYSTEM SHALL execute each skill's documented reference-extraction
  snippet — extracted from the SKILL.md file itself, never retyped into the test — over a shared
  frontmatter-text input table and SHALL fail if any produced entry list differs from the
  server's for the same input.
- WHEN a SKILL.md documents more than one offline snippet (identifier computation and reference
  extraction) THE SYSTEM SHALL disambiguate which snippet it is extracting rather than assuming a
  single heredoc per file.
- WHEN the drift test cannot locate a skill's documented reference-extraction snippet THE SYSTEM
  SHALL fail rather than skip.
- WHEN the drift test asserts THE SYSTEM SHALL assert on computed output only and SHALL NOT
  assert on the skill's source text (no substring or `inspect.getsource` comparison).
- WHEN a new skill introduces its own offline reference-extraction computation THE SYSTEM SHALL
  add it to the same parameterised drift test rather than leaving it unguarded.

## Boundaries

**Always:**
- Only the frontmatter `references:` YAML list is mechanically rewritten (ADR-012 D1).
- `references` holds resolved full S3 keys (the operative `artifact_id`);
  content links use `arkeology://artifact/{id}` (D2/D3), where `{id}` is that same full key.
- The map is built from the FULL manifest, not the retry subset (D4 — multi-session safety).
- A well-formed relative path (`./`/`../`) is joined against the referencing file's directory before
  the D6 normalization ceiling — this is resolution, not repair: an escaping
  `../` still falls through to unresolved, it does not raise or get special-cased.
- Mixed addressing (`arkeology://…` next to raw `/docs/…`) is the correct permanent steady state (D3).
- The skills keep their own offline copy of the ID algorithm and of the reference-extraction
  algorithm — they must compute both before the server is reachable — and both copies are held
  to the server's behaviour by a drift test, not by import.

**Ask First:**
- Nothing — scope and ceiling fixed by ADR-012.

**Never:**
- Do not rewrite in-body markdown links (D1).
- Do not attempt to repair genuinely broken/inconsistent source references beyond the bounded
  normalization (D6) — surface them in the report instead.
- Do not retroactively rewrite already-written tier 2 content (D8).
- Do not add server-side rewrite logic inside `migrate_artifacts` beyond threading the `references`
  descriptor key (ADR-012 rejected server-side rewrite; the skill orchestrates).
- Do not try to single-source the skills' ID computation by importing `references.py` /
  `artifact.py` from the skill, shelling out to the installed package, or calling an MCP tool —
  the skills run before the server is necessarily installed or reachable (decided 2026-08-12).
- Do not assert on skill source text in the drift test — behavioural equivalence only.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_references_resolution.py` | Create | Pure-helper tests: map build, normalization ceiling, URL passthrough, forward reference, unresolved fall-through — Red first |
| `src/arkeology/references.py` | Create | Pure helpers: `normalize_reference_path(path)`, `build_path_to_id_map(manifest_entries)` (uses `generate_artifact_id`), `join_reference_path(referencing_file_path, reference_path)` (relative-path join), `resolve_reference(path, path_to_id_map, referencing_file_path=None)` → id or `None` |
| `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` | Modify | Add the build-map → resolve-frontmatter → populate `references` → rewrite content to `arkeology://artifact/{id}` → report-unresolved flow to Steps 3.A/3.B; document the normalization ceiling and URL/unresolved passthrough; in-body links explicitly out of scope |

*(Skill path corrected 2026-08-12: skills live only at `plugins/arkeology/skills/<name>/`; there is no
top-level `skills/` directory and no symlinks.)*

**ID drift test (Story 5):**

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_skill_artifact_id_drift.py` | Create | The drift test. Parameterised over both skill files; extracts each one's documented `python3` ID snippet from its SKILL.md, executes it, compares the produced full key against `generate_artifact_id` + `{write_prefix}/{bare_id}{extension}` for every row of a shared input table; fails if a snippet cannot be located. Pure — no AWS, no moto, no Bedrock |
| `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` | Verify (flag) | Snippet in the "Building the path→full-key map" section (`python3 - "$TYPE" "$TIER" "$DATE" "$TITLE" "$EXTENSION" "$WRITE_PREFIX"` with a `<<'PY'` heredoc). Change only if the test proves it already diverges, or if it needs a stable delimiter for extraction |
| `plugins/arkeology/skills/backfilling-references/SKILL.md` | Verify (flag) | Same snippet in Workflow step "Build the path→full-key map", indented inside a numbered list — the extraction must dedent. Same change rule as above |
| `src/arkeology/references.py` | Modify | Module docstring's "do not reimplement the algorithm elsewhere" is currently contradicted by the two skill copies it names one line earlier: state that the skills keep a deliberate offline copy and that `tests/unit/test_skill_artifact_id_drift.py` is what holds it to this module |

## Testing Approach

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
since the rewrite orchestration is skill prose driving `migrate_artifacts`.

**Skill ID drift test (Story 5).** Written before any change to `references.py`'s docstring or to
either skill snippet, and expected to pass on first run against today's tree (the snippets are
believed correct; the test exists to keep them that way — a Red first run would mean the snippets
have already drifted, which is a defect in them, not in the test).

- One test module, `tests/unit/test_skill_artifact_id_drift.py`, parameterised over the two skill
  files so a third skill is one list entry away from being covered.
- Per skill: locate the documented ID snippet in the SKILL.md, dedent it, execute it (subprocess
  or `exec` with the documented arguments — the developer picks; the snippet already takes its six
  values as `sys.argv[1:7]`), and compare its printed full key against
  `f"{write_prefix}/{generate_artifact_id(tier=…, type=…, date=…, title=…)}{extension}"`.
- Shared input table covering the cases listed in Story 5's acceptance criteria (tier 2/3,
  underscore type, non-ASCII title, punctuation-collapse pair, over-60-char title, empty-slug
  title, with/without extension). One table, both skills — divergence between the two snippets is
  caught by the same rows.
- Failure output must name the input that diverged and both identifiers, so the next reader knows
  which side moved.
- Snippet not found → fail with a message pointing at the skill file and the expected block.
- No assertion on the skill's source text; extraction is a means of *executing* the documented
  algorithm, never a means of comparing it as a string.

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
  the server package (`src/arkeology/references.py`) for testability even though ADR-012 assigns the
  rewrite orchestration to the skill. Decision: keep the helpers as the authoritative, unit-tested
  reference implementation of the D4/D6 algorithm; the skill documents the same algorithm for the
  agent to apply in-context. This satisfies both the ADR (skill orchestrates, no server-side rewrite)
  and the plan (testable Red/Green logic). Operator confirmed the server-side-helper-plus-skill
  placement.
- **OQ-T51-b (DECIDED by operator, 2026-08-12) — how to stop the skills' duplicated ID algorithm
  from drifting.** Options were single-sourcing (skill imports or calls the server)
  versus a drift test. **Chosen: drift test.** Single-sourcing is not available: a migration or
  backfill run computes identifiers offline, before the server is necessarily installed,
  configured, or reachable — that is the whole reason the algorithm is pure and documented in
  prose. The duplication is therefore accepted and guarded, not removed. See Story 5, the
  requirements, and the Testing Approach section above. Remaining latitude for the developer: the
  extraction mechanism (regex on the fenced block vs. an explicit marker added to the skill) and
  execution mechanism (subprocess vs. `exec`) — both are implementation choices, provided the test
  never asserts on source text and never silently skips.
  **Addendum (decided/shipped 2026-08-13, architect):** a second offline algorithm turned up
  with the identical unguarded-duplication shape — the skills' frontmatter `references:`
  extraction step had no canonical algorithm to follow at all (unlike the ID step, which already
  had one), and a real migration session hand-rolled a naive regex scanner for it that silently
  corrupted resolution by capturing a YAML inline comment as part of an extracted path. The same
  decision applies without re-litigation: single-sourcing remains unavailable (the skills still
  compute offline, before the server is necessarily reachable), so the fix is the same shape —
  a canonical `extract_references_list` reference implementation, a matching documented snippet
  in both skill files, and a second parameterised case in the same drift test module rather than
  a new one. See Story 6 and the "Skill-side reference extraction" requirements above.
