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
  - resource: docs/specs/p12-t49-link-metadata.md
    title: T49 — link_metadata Tool (generalizes and supersedes link_commit)
  - resource: docs/contracts/modules/arkeology.tools.link_metadata.md
    title: arkeology.tools.link_metadata
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/specs/p9-t30-write-artifacts.md
    title: Write Performance Z1 — write_artifacts + migrate_artifacts + P4 Section Truncation
  - resource: docs/contracts/modules/arkeology.tools.migrate_artifacts.md
    title: arkeology.tools.migrate_artifacts
generated:
  by: "axians-architect/claude-sonnet-4.6"
  at: 2026-06-16T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:19:59Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T40 — Migration Skill `commit_refs` Backfill Options

## TL;DR

Skill-only update to `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md`. A new Step 5 is inserted after
verification offering the operator three commit-refs backfill choices: do not backfill
(default), link all to the current HEAD with one git call (fast, imprecise), or backfill
per-file from git history (accurate, one git command over every migrated file). No server code
changes — `link_metadata` (`p12-t49-link-metadata`) is already implemented.

## 1. Problem Statement

After migration, all written artifacts have empty `commit_refs`. Future `propose_commit_links`
calls without a `since_ulid` bound will surface every unlinked artifact — including all the
ones just migrated — creating noise. The three options let the operator choose the right
trade-off: do nothing and accept the noise, quickly mark all artifacts with the migration-time
HEAD SHA, or look up each file's history to attach historically accurate per-file SHAs. Both linking
options call `link_metadata`, which stores `commit_refs` in the artifact's S3 object annotation, so
a backfilled link survives `reconcile_index`.

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
(accurate, one git command over every migrated file). The step is always optional with a clearly
marked default. Selecting a linking option — 2 or 3 — is the operator's confirmation: the skill
starts it with no further prompt.

**Example**

- Given migration has been verified, when the operator selects option 3, then the skill runs the
  history lookup (R8) at once, without asking the operator to acknowledge anything first.

### R3 — Only migrated artifact_ids, read from the manifest, are backfilled

Artifact_ids passed to `link_metadata` are the full S3 keys the server returned for the migrated
files, never re-queried from Arkeology. For a migration tracked in `ARKEOLOGY_IMPORT.yaml`, they are
the `artifact_id` recorded on every manifest entry with `status: written`
(`p9-t30-write-artifacts` R16) — so artifacts written in an earlier session are included. For a
migration small enough to run without a manifest, they are the `artifact_id`s of the response
entries with `written: true`. Failed entries are excluded from all backfill options.

**Example**

- Given a 95-file migration whose first session wrote 60 files and whose second session wrote the
  remaining 35, when the operator selects option 2 at the end of the second session, then
  `link_metadata` receives all 95 artifact_ids, read from the manifest.

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

### R5 — Option 2 runs `git rev-parse HEAD` once and calls `link_metadata` once with every written artifact_id

When the operator selects option 2, the skill runs `git rev-parse HEAD` exactly once; if the
command succeeds, it calls `link_metadata(artifact_ids=[all_written_ids], commit_refs=[<HEAD>])`
once, with all successfully written artifact_ids and that SHA, so every migrated artifact
carries the HEAD SHA in its `commit_refs` after the call. The skill notes that the HEAD SHA is
the migration-time snapshot of the repo, not historically accurate per-file provenance — the
"imprecise but fast" trade-off.

**Example**

- **Given** migration has been verified, **when** the operator selects option 2, **then** the
  skill runs `git rev-parse HEAD` once, then calls `link_metadata` once with all successfully
  written artifact_ids and `commit_refs=[<that SHA>]`.

### R6 — When `git rev-parse HEAD` fails, option 2 offers option 1 or option 3 before any action

When `git rev-parse HEAD` fails (repository has no commits yet), the skill explains the cause
and offers option 1 or option 3 as alternatives before taking any action — no `link_metadata`
call is made.

## 5. Rules — Option 3: backfill from git history

### R8 — Option 3 resolves every migrated file's last-touching commit SHA in one command

When option 3 is running, the skill resolves the last-touching commit SHA of every migrated file
with one shell command over all their paths — never one agent tool call per file. The command's
output pairs each path with its SHA; its form (a loop running `git log -1 --format=%H -- <filepath>`
per path, or a single `git log --name-only` pass) is the developer's choice. The skill correlates
each file path with its artifact_id from the same source as R3 — the manifest entry holding both,
or, without a manifest, the `migrate_artifacts` response entry matched by position in the input
descriptor list. A file with git history has its artifact_id grouped under its last-touching
commit SHA.

**Example**

- Given 95 migrated files, when option 3 runs, then one shell command yields the SHAs of all 95,
  and the skill groups their artifact_ids by SHA from that output.

**Why:** the lookup is deterministic and needs no judgement between files, while each agent tool
call is a model turn that carries the whole conversation.

### R9 — A file with no git history is skipped, never halting the step

When the command yields no SHA for a file (never committed), the skill skips that artifact_id —
never halt, no error — and includes it in the skipped count reported in the final summary.

### R10 — Option 3 calls `link_metadata` once per unique SHA, reporting progress after each call

When option 3 is running, the skill groups artifact_ids by their resolved SHA and calls
`link_metadata(artifact_ids=[...], commit_refs=[<sha>])` once per unique SHA — never one call per
file. It reports progress after each `link_metadata` call (e.g. "Linked 12 of 45 files").

**Example**

- Given multiple files sharing the same last-touching SHA, then `link_metadata` is called
  once for that SHA with all their artifact_ids — never one call per file.

### R11 — Option 3 ends with a count of linked and skipped artifacts

When option 3 completes, the skill reports the count of linked artifacts and the count skipped
(no git history found).

## 6. Boundaries

**Always:**
- Artifact_ids passed to `link_metadata` come from the manifest's `status: written` entries, or,
  without a manifest, from the response entries with `written: true` (R3) — never re-queried from
  Arkeology; failed entries are excluded from all backfill options.
- For option 2: one `git rev-parse HEAD` call; one `link_metadata` call with all artifact_ids.
- For option 3: one shell command resolves every file's SHA (R8); one `link_metadata` call per
  unique SHA.
- Report progress after each `link_metadata` call for option 3 (e.g. "Linked 12 of 45 files").
- Step 5 is inserted between the current Step 4 (Verification) and Step 5 (Post-migration
  cleanup); the current Step 5 is renumbered to Step 6.
- SKILL.md line count must remain ≤ 500 lines after the change.

**Ask First:**
- For option 2: if `git rev-parse HEAD` fails, offer alternatives before taking any action.

**Never:**
- Do not call `write_artifact` or `migrate_artifacts` in Step 5 — content writes are done.
- Do not call `propose_commit_links` in Step 5 — the manifest, or the migration response without
  one, already names every artifact Step 5 links (R3).
- Do not include artifact_ids from failed write entries in any `link_metadata` call.
- Do not make this step mandatory — it is always optional with a clearly marked default.
- Do not ask for a further acknowledgment once option 3 is selected (R2) — revisit if the history
  lookup ever needs more than the one command R8 runs.

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` | Modify | Insert new Step 5; renumber current Step 5 → Step 6; option 3 starts on selection with no slow-operation warning or acknowledgment prompt (R2) and resolves every SHA in one shell command (R8) |

### Contracts

- `docs/contracts/modules/arkeology.tools.link_metadata.md` § link_metadata — the backfill call, its `linked` and `skipped` counts and its error response (R5, R10, R11).
- `docs/contracts/modules/arkeology.tools.migrate_artifacts.md` § migrate_artifacts — the positionally aligned `results` entries (`written`, `artifact_id`) read when the migration has no manifest (R3, R8).

### Testing Approach

Skill-only change — no server code, no Python source changes, no unit tests.

**Validation gate:** `python scripts/validate.py` must pass. The validator checks the frontmatter
of every `SKILL.md` under `plugins/arkeology/skills/`; it does not count lines, so the ≤ 500-line
boundary is checked by hand.

**Manual acceptance checklist:**

- [ ] New Step 5 is positioned after Step 4 (Verification) and before the renamed Step 6.
- [ ] All three options are presented with option 1 clearly marked as the default.
- [ ] Option 1 includes the `propose_commit_links` noise edge case note.
- [ ] Option 2 runs `git rev-parse HEAD` once and calls
  `link_metadata(artifact_ids=[...], commit_refs=[<HEAD>])` with all written artifact_ids; the
  "imprecise but fast" trade-off is noted.
- [ ] Option 2 handles the empty-repo edge case (`git rev-parse HEAD` fails) gracefully.
- [ ] Option 3 starts as soon as it is selected, with no slow-operation warning or acknowledgment
  prompt.
- [ ] Option 3 resolves every migrated file's SHA in one shell command, never one tool call per
  file.
- [ ] Option 3 groups by SHA and calls `link_metadata(..., commit_refs=[<sha>])` once per SHA — not
  one call per file.
- [ ] No-git-history files are skipped with a note in the final summary.
- [ ] Progress reporting is present for option 3.
- [ ] `python scripts/validate.py` exits 0.
