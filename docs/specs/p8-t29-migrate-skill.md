---
type: spec
title: Write Performance L1+L2 — Migration Skill Parallel Writes
description: Restructures the migrating-to-arkeology skill's Path A into two phases (enrich-all then parallel-write via sub-agents) and adds concurrent writes to migrate.py, together reducing a 10-document migration from ~10 minutes to ~1 minute.
tags: []
timestamp: 2026-06-02T00:00:00Z
okf_version: "0.1"
feature: p8-t29-migrate-skill
phase: 8
task: 29
status: superseded
references:
  - docs/contracts/modules/arkeology.tools.migrate_artifacts.md
authored:
  by: "architect"
  date: "2026-06-02"
revised:
  by: ""
  date: ""
---

# Write Performance L1+L2 — Migration Skill Parallel Writes

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

The `migrating-to-arkeology` skill's Path A processes files one-at-a-time (enrich → write → next),
stacking LLM inference time and `write_artifact` latency sequentially. This spec restructures
Path A into two phases (enrich all files first, then write in parallel batches via the `task`
tool) for migrations of 10+ files, and lowers the Path B threshold from 30 to 5 files while
adding concurrent writes to `migrate.py` — together eliminating the agent-inference overhead
from write latency and making bulk migration roughly 10–75× faster end-to-end.

## Problem Statement

The brainstorming session (2026-06-01, Sessions 2–3) identified two document-level parallelism
directions. L1 eliminates the LLM-inference tax between writes by splitting enrichment (all
files, main agent, sequential) from writing (batches, sub-agents, parallel). L2 enables
concurrent `write_artifact` calls from `migrate.py` via `asyncio.gather` so Python I/O
parallelism applies even when the agent-only path is used. These two changes are complementary:
L1 parallelises the expensive LLM work; L2 parallelises the API write calls. Combined with P1
(section-level concurrency), a 10-document migration drops from ~10 minutes to ~1 minute.

## User Stories

### Story 1 — Path A for ≥ 10 files uses two-phase parallel writes (P1)

A developer migrates 15 documents using Path A. The main agent enriches all 15 files in one
sequential pass (read, generate description, recover date), then splits them into three batches
of 5 and spawns sub-agents via the `task` tool. Each sub-agent writes its batch. The main agent
waits for all sub-agents and proceeds to verification.

**Acceptance criteria:**
- Given 15 files and the updated SKILL.md, when the main agent follows Step 5, then it
  completes all 15 enrichments before making any `write_artifact` call, then spawns sub-agents
  for writing.
- Given a sub-agent that does not have `write_artifact` access, when it processes its batch,
  then it returns structured metadata for each file so the main agent can write sequentially
  as a fallback.
- Given a sub-agent that returns a per-file error for one entry, when the main agent collects
  results, then it reports that error and proceeds with the successful entries.

### Story 2 — Path A for < 10 files is unchanged (P1)

Small migrations (1–9 files) use the existing sequential Path A. The spawn overhead (~30 s for
3 agents) is not justified at this scale.

**Acceptance criteria:**
- Given 7 files and the updated SKILL.md, when the main agent reaches Step 5 (Path A gate),
  then it enriches and writes each file sequentially without spawning sub-agents.

### Story 3 — Path B threshold is lowered to 5 files (P1)

A developer with 8 files previously had to use the less-efficient Path A. With the new
threshold, they use `migrate.py` from 5 files onwards.

**Acceptance criteria:**
- Given 6 files confirmed in Step 3, when the main agent reaches Step 5, then it follows
  Path B (produce ARKEOLOGY_IMPORT.yaml, dry-run, execute with migrate.py).
- Given 4 files, when the main agent reaches Step 5, then it follows Path A.

### Story 4 — migrate.py writes artifacts concurrently (P1)

An operator runs `migrate.py` with a 20-entry manifest. All 20 artifacts are written
concurrently (up to `MIGRATE_CONCURRENCY` at a time), reducing total write time from
`N × per_artifact_time` to `ceil(N / MIGRATE_CONCURRENCY) × per_artifact_time`.

**Acceptance criteria:**
- Given a 10-entry manifest and `MIGRATE_CONCURRENCY=3`, when `migrate.py` executes, then
  up to 3 `write_artifact` calls are in-flight simultaneously (each writing to S3 and S3
  Vectors independently via their own Bedrock + S3 + S3 Vectors calls).
- Given `MIGRATE_CONCURRENCY` absent from the environment, when `migrate.py` runs, then it
  defaults to 3.
- Given a partial failure (2 of 10 entries raise exceptions), when `migrate.py` completes,
  then the JSON output reports `written: true` for 8 entries and `error: "..."` for the 2
  failures — the script does not abort early.
- Given a `--dry-run` flag, when `migrate.py` runs, then no writes occur and the dry-run path
  is not affected by concurrency (descriptions may still be generated concurrently).

## Requirements

- WHEN the confirmed file count is ≥ 10 THE SKILL SHALL instruct the main agent to complete
  enrichment (Steps 1–4) for all files before making any `write_artifact` call.
- WHEN enrichment is complete and file count is ≥ 10 THE SKILL SHALL instruct the main agent
  to split descriptors into batches of at most 5 and spawn one sub-agent per batch via the
  `task` tool.
- WHEN a sub-agent batch prompt includes `write_artifact` instructions and the sub-agent lacks
  tool access THE SKILL SHALL instruct the sub-agent to return the enriched metadata as a
  structured list so the main agent can fall back to sequential writes.
- WHEN the confirmed file count is 1–9 THE SKILL SHALL instruct the main agent to use the
  existing sequential Path A (enrich + write per file, no sub-agents).
- WHEN the confirmed file count is ≥ 5 THE SKILL SHALL route to Path B (ARKEOLOGY_IMPORT.yaml +
  migrate.py) instead of the previous ≥ 30 threshold.
- WHEN the confirmed file count is 1–4 THE SKILL SHALL route to Path A.
- WHEN `migrate.py` executes writes THE SYSTEM SHALL process all entries concurrently using
  `asyncio.gather` limited by `asyncio.Semaphore(MIGRATE_CONCURRENCY)`.
- WHEN `MIGRATE_CONCURRENCY` is absent from the environment THE SYSTEM SHALL default to 3.
- WHEN `MIGRATE_CONCURRENCY` is set to a value less than 1 THE SYSTEM SHALL exit with a
  clear error message before processing any entries.
- WHEN any entry raises an exception during concurrent write THE SYSTEM SHALL record the error
  in the result for that entry, continue processing other entries, and not abort the run.
- WHEN `--dry-run` is passed THE SYSTEM SHALL not be affected by the concurrency change —
  dry-run continues to produce synchronous preview output.

## Boundaries

**Always:**
- The `task` tool sub-agent batch size is 4–5 files per batch. Combined with `SECTION_CONCURRENCY=5`
  from P1, the maximum simultaneous Bedrock calls is `MIGRATE_AGENT_CONCURRENCY × SECTION_CONCURRENCY`.
  The default of 3 sub-agents × 5 section concurrency = 15 concurrent calls stays within the
  `≤ 15` rule-of-thumb derived from quota research (session 3, 2026-06-01).
- `migrate.py` is a self-contained PEP 723 script — it must not import from `arkeology`. All
  async logic uses `asyncio` from the stdlib; no new dependencies are added.
- Concurrency in `migrate.py` applies to the write step (`write_artifact` function calls) only.
  Description generation (Bedrock Nova Lite calls) may also be parallelised as a secondary
  optimisation if straightforward; otherwise it remains sequential.
- The `write_artifact` function in `migrate.py` is already reentrant (no shared mutable state
  between calls for different artifacts). Concurrent calls to it are safe without locking.
- S3 and S3 Vectors concurrent writes are safe: each artifact has a unique deterministic key;
  `PutObject` and `PutVectors` are atomic per key; two entries never conflict.

**Ask First:**
- Whether description generation in `migrate.py` should also be parallelised in this spec, or
  left for a future iteration. (Recommendation: keep sequential for now — description generation
  is fast relative to embedding + S3 writes, and sequential logic is simpler to reason about.)
- Whether the `task` tool sub-agent fallback (return metadata when `write_artifact` is
  unavailable) should be tested empirically before this spec is implemented, or whether the
  skill text handles it via instructions only.

**Never:**
- Do not add a `--concurrency` CLI flag to `migrate.py` — use the `MIGRATE_CONCURRENCY`
  environment variable for consistency with the server's env-var convention.
- Do not change the JSON output format of `migrate.py` — the result array schema is unchanged;
  only how entries are processed (concurrently vs sequentially) changes.
- Do not add an explicit agent-level concurrency gate to the SKILL.md for the ≥ 10 path —
  the instruction is to use the `task` tool; the `task` tool manages its own parallelism.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/migrating-to-arkeology/SKILL.md` | Modify | Update Step 5 Path A to two phases (≥10: enrich-all then parallel-write; 1–9: sequential as today); update Path B gate from "< 30" to "< 5"; add `MIGRATE_CONCURRENCY` env var to Path B execution notes |
| `skills/migrating-to-arkeology/scripts/migrate.py` | Modify | Wrap `process_entry` calls with `asyncio.gather` + `asyncio.Semaphore`; make the write step (`write_artifact` inner function) safe to call from async context; read `MIGRATE_CONCURRENCY` from env (default 3, min 1); update `main()` to use `asyncio.run` |

## Testing Approach

This spec has no unit test suite (the skill is markdown; `migrate.py` is a standalone script
without a pytest harness). Verification is manual and dry-run based.

**SKILL.md changes — verification:**
- Read the updated Step 5 and confirm the two-phase Path A instruction is unambiguous:
  a developer agent following it would complete all enrichments before any `write_artifact`
  call, then spawn batches.
- Confirm the Path B gate reads "fewer than 5 files" for Path A and "5 or more files" for
  Path B consistently throughout the skill text.

**migrate.py changes — verification:**

Dry-run smoke test:
- Create a 5-entry `ARKEOLOGY_IMPORT.yaml` pointing at real files with `--dry-run`; run
  `uv run skills/migrating-to-arkeology/scripts/migrate.py --manifest ARKEOLOGY_IMPORT.yaml --dry-run`;
  assert JSON output contains 5 entries with `would_write: true` and no errors.

Concurrent write test (manual, requires AWS credentials):
- Run the same manifest without `--dry-run`; confirm all 5 entries appear in `list_artifacts`
  and are searchable via `search_artifacts`.
- Re-run the same manifest (idempotency check); confirm no errors and no duplicate artifacts.

Error handling test:
- Add one entry with a non-existent `path`; confirm the JSON output reports `error` for that
  entry and `written: true` for the others (partial failure does not abort the run).

Concurrency validation:
- Add `MIGRATE_CONCURRENCY=0` to the environment; run `migrate.py`; confirm the script exits
  with a clear error before processing any entries.
- Run with `MIGRATE_CONCURRENCY=2` on a 6-entry manifest; confirm all 6 entries are processed
  and the stderr log shows concurrent activity (entries do not appear strictly in order).

## Open Questions

- [x] Do sub-agents spawned by the `task` tool in opencode inherit the parent session's
  Arkeology MCP connections? **Closed as moot.** This spec is `status: superseded` — the
  opencode sub-agent migration path it describes was never implemented, so the question
  does not apply to what was built.
- [x] Should description generation in `migrate.py` be parallelised in this spec or deferred?
  **Closed as moot.** Same reason: this spec's `migrate.py` flow was never implemented.
