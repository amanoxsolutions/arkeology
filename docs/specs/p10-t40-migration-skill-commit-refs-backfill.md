---
type: spec
title: T40 — Migration Skill commit_refs Backfill Options
description: Spec for a new Step 5 in the migrating-to-arkeology skill offering three commit-refs backfill choices after migration — skip, bulk HEAD link, or per-file git history backfill.
tags: []
timestamp: 2026-06-16T00:00:00Z
okf_version: "0.1"
feature: p10-t40-migration-skill-commit-refs-backfill
status: ready
phase: 10
task: 40
references:
  - docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md
  - docs/architecture-decisions/adr-2026-06-16-artifact-commit-traceability.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/planning-artifacts/requirements.md
authored:
  by: architect
  date: "2026-06-16"
revised:
  by: architect
  date: "2026-07-03"
---

# T40 — Migration Skill `commit_refs` Backfill Options

> **Alignment note (2026-07-03, ADR-011).** Everywhere this spec says `link_commit`, read
> **`link_metadata`** — `link_commit` is generalized and superseded by `link_metadata`
> (`p12-t49-link-metadata`). All three backfill options (skip / bulk HEAD link / per-file git
> history) stand unchanged; only the tool name changes. Backfilled `commit_refs` now land in the
> **durable S3 object annotation** (dual-written with vector metadata), so they **survive
> `reconcile_index`** — the earlier "vector-metadata-only, reconcile drops `commit_refs`" caveat no
> longer applies. This remains a skill-only change with no server code impact.

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Skill-only update to `skills/migrating-to-arkeology/SKILL.md`. A new Step 5 is inserted after
verification offering the operator three commit-refs backfill choices: do not backfill
(default), link all to the current HEAD with one git call (fast, imprecise), or backfill
per-file from git history (accurate, O(n) git calls). No server code changes — `link_commit`
(T38) is already implemented.

## Problem Statement

After migration, all written artifacts have empty `commit_refs`. Future `propose_commit_links`
calls without a `since_ulid` bound will surface every unlinked artifact — including all the
ones just migrated — creating noise. The three options let the operator choose the right
trade-off: do nothing and accept the noise, quickly mark all artifacts with the migration-time
HEAD SHA, or invest O(n) git calls to attach historically accurate per-file SHAs.

## User Stories

### Story 1 — Operator skips backfill and finishes immediately (P1)

**Given** migration has been verified, **when** the operator selects option 1 (default),
**then** the skill proceeds to Step 6 (post-migration cleanup) without making any tool calls.

**Acceptance criteria:**
- Given the operator selects option 1, then no Arkeology tool call is made in Step 5.
- The skill notes that unlinked migrated artifacts will surface in future
  `propose_commit_links` calls when `since_ulid` is absent or pre-dates the migration.

### Story 2 — Operator links all artifacts to the current HEAD (P1)

**Given** migration has been verified, **when** the operator selects option 2, **then** the
skill runs `git rev-parse HEAD` once, then calls `link_commit` once with all successfully
written artifact_ids and that SHA.

**Acceptance criteria:**
- Given the operator selects option 2, then `git rev-parse HEAD` is called exactly once.
- Given the command returns a SHA, then `link_commit` is called once with all successfully
  written artifact_ids and that SHA; every migrated artifact carries the HEAD SHA in its
  `commit_refs` after the call.
- Given `git rev-parse HEAD` fails (repository has no commits yet), then the skill explains
  why and offers to proceed with option 1 or option 3 instead — no `link_commit` call is made.
- The skill notes that the HEAD SHA is the migration-time snapshot of the repo, not
  historically accurate per-file provenance.

### Story 3 — Operator backfills from git history (P1)

**Given** migration has been verified, **when** the operator selects option 3, **then** the
skill warns about O(n) git calls upfront, runs `git log -1 --format=%H -- <filepath>` per
migrated file, groups artifact_ids by SHA, and calls `link_commit` once per unique SHA.

**Acceptance criteria:**
- Given the operator selects option 3, then the slow-operation warning is displayed before
  any git calls begin and the operator must acknowledge before proceeding.
- Given a file with git history, then its artifact_id is grouped under its last-touching
  commit SHA.
- Given a file with no git history (never committed), then that artifact_id is skipped and
  reported in the final summary — no halt, no error.
- Given multiple files sharing the same last-touching SHA, then `link_commit` is called
  once for that SHA with all their artifact_ids — never one call per file.
- Given all calls complete, then the skill reports count of linked artifacts and count
  skipped (no git history found).

## Requirements

- WHEN migration is verified THE SKILL SHALL present the three backfill options to the
  operator with option 1 (do not backfill) marked as the default.
- WHEN the operator selects option 1 THE SKILL SHALL note the `propose_commit_links` noise
  edge case and proceed to Step 6 with no tool calls.
- WHEN the operator selects option 2 THE SKILL SHALL run `git rev-parse HEAD`; if the
  command succeeds, call `link_commit(artifact_ids=[all_written_ids], commit_sha=<HEAD>)`;
  if the command fails, explain the cause and offer option 1 or option 3 as alternatives.
- WHEN the operator selects option 3 THE SKILL SHALL display an upfront slow-operation
  warning and wait for explicit acknowledgment before any git calls begin.
- WHEN option 3 is running THE SKILL SHALL correlate each file path with its artifact_id
  from the `migrate_artifacts` response (matched by position in the input descriptor list).
- WHEN `git log -1 --format=%H -- <filepath>` returns no output for a file THE SKILL SHALL
  skip that artifact_id — never halt; include it in the skipped count.
- WHEN option 3 is running THE SKILL SHALL group artifact_ids by their resolved SHA and call
  `link_commit(artifact_ids=[...], commit_sha=<sha>)` once per unique SHA.
- WHEN option 3 completes THE SKILL SHALL report the count of linked artifacts and the count
  skipped (no git history found).

## Boundaries

**Always:**
- Artifact_ids passed to `link_commit` are the full S3 keys returned in the
  `migrate_artifacts` (or `write_artifacts`) response — never re-queried from Arkeology.
- Only artifact_ids that were written successfully (response entry has `written: true`) are
  included — failed entries are excluded from all backfill options.
- For option 2: one `git rev-parse HEAD` call; one `link_commit` call with all artifact_ids.
- For option 3: one `git log -1` call per file; one `link_commit` call per unique SHA.
- Report progress after each `link_commit` call for option 3 (e.g. "Linked 12 of 45 files").
- Step 5 is inserted between the current Step 4 (Verification) and Step 5 (Post-migration
  cleanup); the current Step 5 is renumbered to Step 6.
- SKILL.md line count must remain ≤ 500 lines after the change (current: 451 lines).

**Ask First:**
- For option 3: the slow-operation warning IS the confirmation gate — wait for explicit
  operator acknowledgment before running any `git log` calls.
- For option 2: if `git rev-parse HEAD` fails, offer alternatives before taking any action.

**Never:**
- Do not call `write_artifact` or `migrate_artifacts` in Step 5 — content writes are done.
- Do not call `propose_commit_links` in Step 5 — that is a session-protocol tool, not a
  migration tool.
- Do not include artifact_ids from failed write entries in any `link_commit` call.
- Do not make this step mandatory — it is always optional with a clearly marked default.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/migrating-to-arkeology/SKILL.md` | Modify | Insert new Step 5; renumber current Step 5 → Step 6 |

## Testing Approach

Skill-only change — no server code, no Python source changes, no unit tests.

**Validation gate:** `python scripts/validate.py` must pass. The validator enforces ≤ 500
lines and valid frontmatter on all `skills/*/SKILL.md` files.

**Manual acceptance checklist:**

- [ ] New Step 5 is positioned after Step 4 (Verification) and before the renamed Step 6.
- [ ] All three options are presented with option 1 clearly marked as the default.
- [ ] Option 1 includes the `propose_commit_links` noise edge case note.
- [ ] Option 2 runs `git rev-parse HEAD` once and calls `link_commit` with all written
  artifact_ids; the "imprecise but fast" trade-off is noted.
- [ ] Option 2 handles the empty-repo edge case (`git rev-parse HEAD` fails) gracefully.
- [ ] Option 3 has the upfront slow-operation warning with explicit acknowledgment gate.
- [ ] Option 3 groups by SHA — not one `link_commit` per file.
- [ ] No-git-history files are skipped with a note in the final summary.
- [ ] Progress reporting is present for option 3.
- [ ] `python scripts/validate.py` exits 0.

## Open Questions

*(none — all constraints resolved)*
