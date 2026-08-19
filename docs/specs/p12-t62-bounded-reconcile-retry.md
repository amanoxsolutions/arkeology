---
type: spec
title: T62 — Bounded reconcile_index Failure-Log Retry + Fetch-and-Reindex Dedup
description: reconcile_index's failure-log replay (Phase 1) currently retries every entry every run, indefinitely, with no attempt count — a genuinely unfixable entry (e.g. an artifact that fails T57's own budget guard) would be replayed identically forever. Add a per-entry reconcile_attempts counter persisted in the failure log; once an entry crosses the existing CAS_MAX_ATTEMPTS = 3 precedent, stop auto-retrying it and report it once, loudly, in a new stuck_failures response field, instead of blending it into failed indistinguishably from a first-time failure. Also fixes a related gap: Phase 1 (failure-log replay) and Phase 2 (orphan scan) each independently duplicate the same get_object → _reindex_artifact → append-to-reconciled sequence — fixed by extracting one shared _fetch_and_reindex helper, since this task is already reopening Phase 1's exact loop.
tags: []
timestamp: 2026-08-17T00:00:00Z
okf_version: "0.1"
feature: p12-t62-bounded-reconcile-retry
status: ready
phase: 12
task: 62
references:
  - docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
  - docs/specs/p12-t57-guard-coverage.md
  - src/arkeology/annotations.py
authored:
  by: "architect"
  date: "2026-08-17"
---

# T62 — Bounded `reconcile_index` Failure-Log Retry + Fetch-and-Reindex Dedup

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

`reconcile_index`'s Phase 1 (failure-log replay) retries every entry on every run, indefinitely — there is no attempt count anywhere in the failure-log entry schema. An entry that fails identically every time (for example, a genuinely oversize `commit_refs`/`references` payload now correctly rejected by T57's guard) is replayed forever, appearing in `failed` on every single reconcile run with no signal that it is stuck rather than merely unlucky this time. This task adds a per-entry `reconcile_attempts` counter, persisted back into the failure-log JSONL alongside the entry it belongs to, incremented each time a replay attempt fails. Once an entry's counter reaches the existing `CAS_MAX_ATTEMPTS = 3` precedent (`annotations.py`, reused rather than made independently configurable), `reconcile_index` stops attempting to re-index it and reports it in a new, distinct `stuck_failures` response field instead of `failed`. (ADR D4.)

Folded into the same spec: Phase 1's failure-log replay loop and Phase 2's orphan-scan loop each independently do the identical `get_object` → `_reindex_artifact` → append `{"artifact_id", "title", "sections_indexed", "source"}` to `reconciled` sequence, differing only in whether `head_object` was already fetched and the `source` label (`"failure_log"` vs. `"orphan_scan"`). This task is already reopening Phase 1's exact loop to add the `reconcile_attempts` counter, so the two are extracted into one shared `_fetch_and_reindex(artifact_id, raw_meta, source, ...)` helper here rather than as a separate task.

## Problem Statement

Phase 1's failure-log replay reads every entry, deduplicates by `artifact_id`, and attempts `_reindex_artifact` for each unique entry. An entry that resolves is pruned from the log (added to `resolved_ids`); an entry that fails stays in the log verbatim, to be retried on the very next run. This is correct and desirable for transient failures (a momentary Bedrock throttle, a race with a concurrent write) — but it has no concept of "this entry has failed so many times in a row that retrying it again is pointless without an operator fixing the underlying cause." Left unbounded, a genuinely unfixable entry (the exact "self-perpetuating failure-log replay" outcome `p12-t55`'s own TL;DR states must never happen) is retried — and fails — identically on every single `reconcile_index` invocation forever, with no way for a caller to distinguish "this just failed for the first time" from "this has failed 50 times in a row and needs a human."

Folded in: this task is already reopening Phase 1's replay loop to thread the `reconcile_attempts` counter through it, which is the natural, free place to also close the duplication between Phase 1 and Phase 2. Today, Phase 1 fetches `raw_meta` via `head_object` first (with its own `KeyError` → "S3 object not found" handling), then, in a separate `try` block, reads `content` via `get_object`, calls `_reindex_artifact`, and appends a `reconciled` entry tagged `"source": "failure_log"`. Phase 2 does the same three steps — `get_object`, then `head_object`, then `_reindex_artifact`, then an identically-shaped `reconciled` entry tagged `"source": "orphan_scan"` — inside one `try` block. The only real differences are the `source` label and which phase already has `raw_meta` in hand before the shared sequence starts; extracting a `_fetch_and_reindex(artifact_id, raw_meta, source, ...)` helper removes the duplication without changing either phase's error-handling shape.

## User Stories

### Story 1 — An entry failing fewer than 3 times behaves exactly as today (P1)

**Acceptance criteria:**
- Given a failure-log entry that fails to re-index on this run for the first or second time, when `reconcile_index` completes then it appears in the existing `failed` list, exactly as today — no behaviour change below the threshold.
- Given the same entry, when the failure log is rewritten at the end of the run, then it is retained (not pruned) with its `reconcile_attempts` counter incremented by one from its prior value.

### Story 2 — An entry crossing the attempt threshold stops being retried (P1)

**Acceptance criteria:**
- Given a failure-log entry whose `reconcile_attempts` (before this run) is already at or above `CAS_MAX_ATTEMPTS` (3), when `reconcile_index` runs then it does **not** attempt `_reindex_artifact` for that entry — no `bedrock.embed` call, no `put_vector` call for it — and it is reported in a new, distinct `stuck_failures` response field instead of `failed`.
- Given a failure-log entry that fails on this run and, after incrementing, its `reconcile_attempts` now reaches `CAS_MAX_ATTEMPTS`, when the response is assembled then it is reported in `stuck_failures` for this run (not `failed`) — the transition to "stuck" is visible at the exact run where the threshold is crossed, not delayed to the following run.
- Given an entry is classified as stuck, when the failure log is rewritten at the end of the run, then the entry is still retained in the log (never pruned) — it remains visible and available for manual intervention, but is never auto-retried again while its `reconcile_attempts` stays at or above the threshold.

### Story 3 — Existing callers unaffected (P1)

**Acceptance criteria:**
- Given an existing caller reads only the `failed` field, when this task lands then `failed` still contains every genuinely-failing-for-the-first-few-times entry — the new `stuck_failures` field is purely additive; nothing that was in `failed` below the threshold moves elsewhere.
- Given a run in which no entry crosses the threshold, when `reconcile_index` completes then the response contains no `stuck_failures` field at all (omitted when empty, matching the existing convention for `skipped_existing`/`generation_failed`-style optional fields).

### Story 4 — Phase 1 and Phase 2 share one fetch-and-reindex helper (P2)

**Acceptance criteria:**
- Given the existing Phase 1 and Phase 2 test scenarios (failure-log replay success/failure, orphan-scan success/failure, `CredentialError` from either phase), when this task lands then every existing assertion continues to pass unchanged — the extraction is a pure refactor with no response-shape or behavior change.
- Given Phase 1 has already fetched an entry's `raw_meta` via `head_object` (its existing `KeyError` → "S3 object not found" handling stays exactly where it is, ahead of the shared helper), when Phase 1 calls the shared helper with that `raw_meta`, then the helper does not re-fetch `head_object` itself.
- Given Phase 2 now pre-fetches `raw_meta` via `head_object` ahead of the shared helper (mirroring Phase 1's pre-fetch shape), when an orphan is re-indexed, then the resulting `reconciled` entry is identical in shape and content to today's, tagged `"source": "orphan_scan"`.
- Given the shared helper's `get_object` or `_reindex_artifact` call raises `CredentialError`, when either phase's caller catches it, then it still returns the existing structured credential-error response, propagated unchanged through the helper.
- Given the shared helper's call raises any other `Exception`, when Phase 1's caller catches it, then this task's own `reconcile_attempts` increment and `failed`-vs-`stuck_failures` routing (Story 2) still applies exactly as specified — the helper only fetches and re-indexes, it never classifies a failure; Phase 2's caller keeps its existing generic `failed` handling, also unchanged.

## Requirements

- WHEN a failure-log entry is parsed in Phase 1 THE SYSTEM SHALL read its `reconcile_attempts` value, defaulting to `0` when the key is absent (backward-compatible with every entry written before this task).
- WHEN a unique entry's `reconcile_attempts` is already `>= CAS_MAX_ATTEMPTS` before this run's replay THE SYSTEM SHALL NOT call `_reindex_artifact` for it, and SHALL add it to a new `stuck_failures` list instead of attempting replay.
- WHEN a unique entry's `reconcile_attempts` is `< CAS_MAX_ATTEMPTS` THE SYSTEM SHALL attempt `_reindex_artifact` for it exactly as today.
- WHEN that attempt succeeds THE SYSTEM SHALL add the `artifact_id` to `resolved_ids` exactly as today (pruned from the log) — the `reconcile_attempts` counter is irrelevant once resolved.
- WHEN that attempt fails THE SYSTEM SHALL increment the entry's `reconcile_attempts` by one (mutating the entry dict that will be written back to the log) and THEN classify it: if the incremented value is `>= CAS_MAX_ATTEMPTS`, add it to `stuck_failures`; otherwise add it to `failed`, exactly as today.
- WHEN the failure log is rewritten at the end of Phase 1 THE SYSTEM SHALL persist each retained entry's (possibly incremented) `reconcile_attempts` value — the existing `remaining_entries` filter (entries whose `artifact_id` is not in `resolved_ids`) already retains the same dict objects that were mutated during this run, so no additional plumbing is needed beyond incrementing in place.
- WHEN the `reconcile_index` response is assembled THE SYSTEM SHALL include a `stuck_failures` field only when non-empty, matching the existing optional-field convention (`skipped_existing`, `generation_failed`).
- WHEN Phase 2 (orphan scan) runs THE SYSTEM SHALL be entirely unaffected by this task — its `failed` list is ephemeral per call and never persisted back to the failure log (no failure-log entry, no `reconcile_attempts` counter, exists for an orphan-scan failure), so there is no replay loop to bound there.
- WHEN Phase 1 and Phase 2 each already have an artifact's `raw_meta` fetched via `head_object` THE SYSTEM SHALL call one shared `_fetch_and_reindex(artifact_id, raw_meta, source, settings, s3, vectors, bedrock)` helper that performs the `get_object` read, the `_reindex_artifact` call, and builds the `{"artifact_id", "title", "sections_indexed", "source"}` entry — replacing the duplicated sequence in both phases.
- WHEN the helper's `get_object` or `_reindex_artifact` call raises THE SYSTEM SHALL propagate the exception unchanged to the caller rather than catching or reclassifying it inside the helper — so Phase 1 keeps its `reconcile_attempts`-aware routing (this task's own Requirements, above) and Phase 2 keeps its existing generic `failed` handling, both unchanged, in their respective call sites.
- WHEN Phase 2's orphan-scan loop is refactored to use the shared helper THE SYSTEM SHALL pre-fetch `raw_meta` via `head_object` before calling the helper, mirroring Phase 1's existing pre-fetch shape — reordering Phase 2's two read calls (`head_object` now ahead of `get_object`, reversed from today) is accepted as behavior-neutral because both calls are read-only and idempotent, and both already land in the same generic `except Exception` handling in Phase 2 today.

## Boundaries

**Always:**
- The bounded-retry mechanism applies **only** to Phase 1's failure-log replay — Phase 2's orphan scan has no persisted failure record and is out of scope (ADR context: "Phase 2 orphan scan... its `failed` list is ephemeral per call — not persisted back to the failure log, so orphan-scan failure does not itself create a replay loop").
- Reuse `CAS_MAX_ATTEMPTS = 3` from `annotations.py` as-is — do not introduce a new, independently configurable threshold (ADR D4, rejected alternative: an independently configurable threshold was considered and rejected for lack of evidence 3 is wrong here).
- `reconcile_attempts` increments only on an actual replay *attempt* that fails — an entry already at/above the threshold is skipped, not attempted, so its counter does not grow further once stuck (it is reported in `stuck_failures` on every subsequent run at the same fixed count until manually resolved).
- `stuck_failures` and `failed` are mutually exclusive per entry per run — an entry is in exactly one of the two lists (or in `resolved_ids`, or below-threshold-and-not-yet-attempted-this-run, which cannot occur since every unique entry is either skipped-as-stuck or attempted).
- The `_fetch_and_reindex` extraction is a pure refactor — it must not change any existing response field, the `reconciled`/`failed` entry shape, or Phase 1's `reconcile_attempts`/`stuck_failures` routing introduced by this task's primary scope.

**Ask First:**
- Nothing — the threshold value, its source (`CAS_MAX_ATTEMPTS`), and the new field name (`stuck_failures`) are all locked, operator-approved decisions (ADR D4, Open Questions resolution 4). The `_fetch_and_reindex` helper's signature (`_fetch_and_reindex(artifact_id, raw_meta, source, ...)`) has no open design choice either.

**Never:**
- Do not introduce a new configurable threshold setting — reuse `CAS_MAX_ATTEMPTS` exactly.
- Do not prune a stuck entry from the failure log — it must remain visible (in the log file, and reported every run in `stuck_failures`) until an operator resolves the underlying cause (fixes the payload and forces a fresh write, or manually edits/removes the log entry).
- Do not apply any bounding logic to Phase 2's orphan scan — it has no persisted entry to bound.
- Do not silently blend a stuck entry into `failed` — Story 2 requires it to be distinguishable via the new field, not merely inferable from a growing internal counter no response field exposes.
- Do not move the `reconcile_attempts` increment/routing logic (Story 2) into the shared `_fetch_and_reindex` helper — it stays Phase-1-only, in the caller, exactly as this task's own Requirements specify; the helper only fetches and re-indexes, it never classifies a failure.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_reconcile.py` | Modify | Add: entry with `reconcile_attempts` unset/0/1/2 that fails → increments and lands in `failed`, log retains it with the incremented count; entry with `reconcile_attempts=2` that fails this run → increments to 3, lands in `stuck_failures` (not `failed`) this same run; entry with `reconcile_attempts>=3` already → skipped entirely (no `_reindex_artifact` call, via `mocker.spy`), lands in `stuck_failures`; entry that succeeds → pruned from log regardless of prior `reconcile_attempts`; a run with no stuck entries → no `stuck_failures` key in response; Phase 2 orphan-scan failures unaffected (no counter, no `stuck_failures` entry ever produced from that phase). **Fetch-and-reindex dedup:** rerun the existing Phase 1/Phase 2 success, failure, and `CredentialError` cases (already present in this file) unchanged after the extraction, plus one new test asserting Phase 1 and Phase 2 both route through `_fetch_and_reindex` (`mocker.spy`) with the correct `source` argument each — Red first |
| `src/arkeology/tools/reconcile.py` | Modify | In Phase 1's replay loop: read `entry.get("reconcile_attempts", 0)`; skip-and-classify-stuck when `>= CAS_MAX_ATTEMPTS` (import `CAS_MAX_ATTEMPTS` from `arkeology.annotations`, already imported for `read_current_link_fields`); on a failed attempt, increment `entry["reconcile_attempts"]` and route to `failed` vs. `stuck_failures` based on the post-increment value; add `stuck_failures: list[dict[str, Any]]` alongside the existing `failed` list; include it in the returned response dict only when non-empty. **Fetch-and-reindex dedup:** add a module-level `async def _fetch_and_reindex(artifact_id, raw_meta, source, settings, s3, vectors, bedrock) -> dict[str, Any]` performing the `get_object` read, the `_reindex_artifact` call (via `asyncio.to_thread`, as today), and building the `reconciled`-entry dict tagged with `source`; call it from Phase 1 after the existing `head_object` pre-fetch (passing `"failure_log"`), with the `reconcile_attempts` increment/routing staying in Phase 1's own `except Exception` block, not in the helper; call it from Phase 2 after moving its `head_object` fetch ahead of the shared call (passing `"orphan_scan"`), removing the now-duplicated `get_object`/`_reindex_artifact`/append lines from both phases |
| `tests/integration/test_tools_reconcile.py` | Modify (flag) | Real-AWS: force an entry to fail 3 times in a row (e.g. via a genuinely oversize payload that fails T57's guard every time) and assert it moves from `failed` to `stuck_failures` on the third run — Red for integration, if a suitable fixture exists |

## Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_tools_reconcile.py` → `reconcile.py`** — write a failure-log entry directly (bypassing the normal write-path failure logging, to control `reconcile_attempts` precisely) with `reconcile_attempts` set to `0`, `1`, `2`, and `3+` in separate test cases; force `_reindex_artifact` to fail deterministically (e.g. `mocker.patch.object` raising an exception, or a genuinely-oversize seeded payload); assert the counter increments correctly, the `failed`/`stuck_failures` routing matches the boundary exactly (2→3 crosses into `stuck_failures` this run; already-3+ skips the attempt and its spy-call-count assertion), and the rewritten failure log on disk carries the updated counter. A separate test simulates three consecutive `reconcile_index` calls against the same unresolved entry and asserts it appears in `failed` on runs 1–2 and in `stuck_failures` from run 3 onward, with `_reindex_artifact` never called again on run 4+.
2. **`test_tools_reconcile.py` → `reconcile.py`** (fetch-and-reindex dedup) — before extracting, confirm the existing Phase 1 and Phase 2 test suites (success, failure, `CredentialError`) pass; after extracting `_fetch_and_reindex`, rerun them unchanged and assert they still pass (Green — this is a refactor gated by non-regression, not new failing behavior). Add one new test that `mocker.spy`s `_fetch_and_reindex` and asserts it is called once from a Phase 1 replay with `source="failure_log"` and once from a Phase 2 orphan-scan with `source="orphan_scan"`, each with the `raw_meta` already fetched by its caller (no duplicate `head_object` call — assert via `mocker.spy` on `s3.head_object` that it is called exactly once per artifact across both the pre-fetch and the helper combined).

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; `FakeBedrockClient` for embeddings; `tmp_path`/`settings.failure_log_path` fixture for direct log-file seeding and inspection, consistent with existing `test_tools_reconcile.py` failure-log tests.

## Open Questions

*(none — the threshold, its source, the field name, and the Phase-1-only scope are all locked per ADR D4 and its Open Questions resolution. The `_fetch_and_reindex` helper's signature and Phase 2 pre-fetch reordering were verified against the current `reconcile.py` during spec-writing — see Boundaries — so they carry no open design question either.)*
