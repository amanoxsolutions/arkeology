---
type: Spec
id: p10-t40-migration-skill-commit-refs-backfill
title: T40 — Migration Skill commit_refs Backfill Options
description: Spec for a new Step 5 in the migrating-to-arkeology skill offering three commit-refs backfill choices after migration — skip, bulk HEAD link, or per-file git history backfill.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md
    title: Artifact Commit References
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-06-16-artifact-commit-traceability.md
    title: Artifact Commit Traceability — ULID Timestamps, Vector-Only Commit Links, and Agent-Driven Protocol
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
generated:
  by: "axians-architect/claude-sonnet-4.6"
  at: 2026-06-16T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T17:23:42Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T40 — Migration Skill `commit_refs` Backfill Options

## TL;DR

Skill-only update to `skills/migrating-to-arkeology/SKILL.md`. A new Step 5 is inserted after
verification offering the operator three commit-refs backfill choices: do not backfill
(default), link all to the current HEAD with one git call (fast, imprecise), or backfill
per-file from git history (accurate, O(n) git calls). No server code changes — `link_commit`
(T38) is already implemented.

## 1. Problem Statement

> **Alignment note (2026-07-03, ADR-011).** Everywhere this spec says `link_commit`, read
> **`link_metadata`** — `link_commit` is generalized and superseded by `link_metadata`
> (`p12-t49-link-metadata`). All three backfill options (skip / bulk HEAD link / per-file git
> history) stand unchanged; only the tool name changes. Backfilled `commit_refs` now land in the
> **durable S3 object annotation** (dual-written with vector metadata), so they **survive
> `reconcile_index`** — the earlier "vector-metadata-only, reconcile drops `commit_refs`" caveat no
> longer applies. This remains a skill-only change with no server code impact.

After migration, all written artifacts have empty `commit_refs`. Future `propose_commit_links`
calls without a `since_ulid` bound will surface every unlinked artifact — including all the
ones just migrated — creating noise. The three options let the operator choose the right
trade-off: do nothing and accept the noise, quickly mark all artifacts with the migration-time
HEAD SHA, or invest O(n) git calls to attach historically accurate per-file SHAs.

All three user stories this spec covers — the operator skips backfill and finishes immediately,
links all artifacts to the current HEAD, or backfills from git history — are P1.

## 2. Rules — Step 5 and its options

### R1 — A new Step 5 sits between Verification and Post-migration cleanup

Step 5 is inserted between the current Step 4 (Verification) and Step 5 (Post-migration
cleanup); the current Step 5 is renumbered to Step 6.

### R2 — Step 5 presents three backfill options, with option 1 as the default

When migration is verified, the skill presents the three backfill options to the operator with
option 1 (do not backfill) marked as the default: do not backfill (default), link all to the
current HEAD with one git call (fast, imprecise), or backfill per-file from git history
(accurate, O(n) git calls). The step is always optional with a clearly marked default.

### R3 — Only successfully written artifact_ids, from the migration response, are backfilled

Artifact_ids passed to `link_commit` are the full S3 keys returned in the `migrate_artifacts`
(or `write_artifacts`) response — never re-queried from Arkeology. Only artifact_ids that were
written successfully (response entry has `written: true`) are included — failed entries are
excluded from all backfill options.

## 3. Rules — Option 1: do not backfill

### R4 — Option 1 makes no tool call, notes the `propose_commit_links` noise, and proceeds to Step 6

When the operator selects option 1, the skill notes the `propose_commit_links` noise edge case
and proceeds to Step 6 (post-migration cleanup) with no tool calls: no Arkeology tool call is
made in Step 5.

**Example**

- **Given** migration has been verified, **when** the operator selects option 1 (default),
  **then** the skill proceeds to Step 6 (post-migration cleanup) without making any tool calls.
- The skill notes that unlinked migrated artifacts will surface in future
  `propose_commit_links` calls when `since_ulid` is absent or pre-dates the migration.

## 4. Rules — Option 2: link all to the current HEAD

### R5 — Option 2 runs `git rev-parse HEAD` once and calls `link_commit` once with every written artifact_id

When the operator selects option 2, the skill runs `git rev-parse HEAD` exactly once; if the
command succeeds, it calls `link_commit(artifact_ids=[all_written_ids], commit_sha=<HEAD>)`
once, with all successfully written artifact_ids and that SHA, so every migrated artifact
carries the HEAD SHA in its `commit_refs` after the call. The skill notes that the HEAD SHA is
the migration-time snapshot of the repo, not historically accurate per-file provenance — the
"imprecise but fast" trade-off.

**Example**

- **Given** migration has been verified, **when** the operator selects option 2, **then** the
  skill runs `git rev-parse HEAD` once, then calls `link_commit` once with all successfully
  written artifact_ids and that SHA.

### R6 — When `git rev-parse HEAD` fails, option 2 offers option 1 or option 3 before any action

When `git rev-parse HEAD` fails (repository has no commits yet), the skill explains the cause
and offers option 1 or option 3 as alternatives before taking any action — no `link_commit`
call is made.

## 5. Rules — Option 3: backfill from git history

### R7 — Option 3 shows a slow-operation warning and waits for acknowledgment before any git call

When the operator selects option 3, the skill displays an upfront slow-operation warning (about
O(n) git calls) and waits for explicit operator acknowledgment before any `git log` calls begin.
The slow-operation warning IS the confirmation gate.

### R8 — Option 3 resolves each migrated file's last-touching commit SHA

When option 3 is running, the skill runs `git log -1 --format=%H -- <filepath>` once per
migrated file, and correlates each file path with its artifact_id from the `migrate_artifacts`
response (matched by position in the input descriptor list). A file with git history has its
artifact_id grouped under its last-touching commit SHA.

### R9 — A file with no git history is skipped, never halting the step

When `git log -1 --format=%H -- <filepath>` returns no output for a file (never committed), the
skill skips that artifact_id — never halt, no error — and includes it in the skipped count
reported in the final summary.

### R10 — Option 3 calls `link_commit` once per unique SHA, reporting progress after each call

When option 3 is running, the skill groups artifact_ids by their resolved SHA and calls
`link_commit(artifact_ids=[...], commit_sha=<sha>)` once per unique SHA — never one call per
file. It reports progress after each `link_commit` call (e.g. "Linked 12 of 45 files").

**Example**

- Given multiple files sharing the same last-touching SHA, then `link_commit` is called
  once for that SHA with all their artifact_ids — never one call per file.

### R11 — Option 3 ends with a count of linked and skipped artifacts

When option 3 completes, the skill reports the count of linked artifacts and the count skipped
(no git history found).

## 6. Boundaries

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

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/migrating-to-arkeology/SKILL.md` | Modify | Insert new Step 5; renumber current Step 5 → Step 6 |

### Contracts

None.

### Testing Approach

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
