---
status: closed
references: []
authored:
  by: "developer"
  date: "2026-06-02"
revised:
  by: ""
  date: ""
---

# Issue: Migration Ran Sequentially Despite Parallelism Improvements

**Date:** 2026-06-02
**Severity:** Medium
**Status:** Fixed 2026-06-02
**Source:** Operator report during live test — migration was "still very slow"

## Description

The Phase 8 write-performance work (T26–T28) added `SECTION_CONCURRENCY`, `EMBED_MAX_SECTIONS`,
and `EMBED_MIN_SECTION_LENGTH` to speed up bulk imports. The `migrating-to-cairn` skill was
also updated (T29) with a parallel sub-agent path (Path C, ≥ 10 files) and a concurrent script
path (Path B, 5–9 files via `MIGRATE_CONCURRENCY`). Despite these additions, the operator
reported that migration was still very slow during the live test.

The skill has no step that surfaces parallelism settings to the operator and asks them to
confirm or adjust before migration starts. An operator who does not read the execution details
in Step 5 carefully will use whatever defaults happen to be in their `.env` — or the script
defaults — without knowing they can be changed.

## Root Cause

Three missing confirmations in `migrating-to-cairn/SKILL.md`:

1. **`SECTION_CONCURRENCY` is never surfaced.** This controls how many Bedrock embed calls
   run concurrently per artifact write. It affects all three paths (A, B, C). The skill
   does not mention it at any point before migration starts, so an operator with the
   default value of 5 has no reason to increase it.

2. **`MIGRATE_CONCURRENCY` is only mentioned in Step 5d (execution command), after the
   dry run is already confirmed.** By the time the operator sees it, they have already
   committed to running the script. The skill does not prompt them to consider the value
   before the dry run.

3. **Path C sub-agent batch size is fixed at 4–5 in the skill text with no operator
   input.** For a very large migration the operator may want smaller or larger batches,
   but is not asked.

## Affected File

`/home/mlnrt/.config/opencode/skills/migrating-to-cairn/SKILL.md` — Step 5 section only.

## Options

### Option A — Add a "Parallelism settings" block at the start of Step 5, gated on ≥ 5 files (recommended)

Before the path branches, when the confirmed file count is 5 or more, show the operator
a table of relevant settings and ask them to confirm or adjust:

| Setting | Default | Suggested for bulk import | What it controls |
|---|---|---|---|
| `SECTION_CONCURRENCY` | 5 | 10–15 | Concurrent Bedrock embed calls per artifact write (all paths) |
| `MIGRATE_CONCURRENCY` | 3 | 5–10 | Concurrent artifact writes (Path B only) |

Path C note: sub-agent batch size is 4–5 by default; ask operator if they want to adjust.

Gate on ≥ 5 files because:
- Path A (1–4 files) is sequential by design; parallelism settings are irrelevant.
- Paths B and C both use concurrency and benefit from operator input.

- Directly addresses the observed slowness.
- Adds one pause to the workflow before writes begin — appropriate given the performance impact.
- No code change; skill markdown only.

### Option B — Add the confirmation to Step 4 (metadata enrichment)

At the end of Step 4, after the operator confirms the classification table, include the
parallelism check as a natural "before we write" checkpoint.

- Sits at the pivot between planning and execution.
- Mixes execution settings into a step focused on metadata — may confuse operators reading
  the skill for the first time.

### Option C — Embed per-path prompts in Step 5 rather than a shared block

Add a brief "before you run" prompt inside each path that uses concurrency (B and C) rather
than a single shared block.

- Path-specific guidance is always relevant.
- Duplicates the `SECTION_CONCURRENCY` prompt across paths B and C; harder to keep
  consistent.

## Recommendation

**Option A.** Single block, clear gate condition, minimal disruption to the skill's overall
flow. Insert it as a new sub-section at the top of Step 5, before the path descriptions.

## Tests Required

None — skill markdown only, no code change.

## Fix Applied

**File:** `/home/mlnrt/.config/opencode/skills/migrating-to-cairn/SKILL.md`

Added a `### Parallelism settings (≥ 5 files only)` sub-section at the top of Step 5,
before the path descriptions. The block:
- Is skipped for 1–4 files (Path A — sequential by design).
- For ≥ 5 files, surfaces `SECTION_CONCURRENCY` and `MIGRATE_CONCURRENCY` with defaults
  and bulk-import suggestions, and asks the operator to confirm or adjust before any
  writes begin.
- Includes a Path C note on sub-agent batch size.
- Explains how to apply changes (restart required for `SECTION_CONCURRENCY`).
