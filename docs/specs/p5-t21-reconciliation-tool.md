---
type: spec
title: T21 — Reconciliation Tool
description: Introduces a reconcile_index MCP tool that repairs S3/vector-index inconsistencies by replaying the failure log and scanning for orphaned S3 objects, returning a structured summary of recovered and failed artifacts.
tags: []
timestamp: 2026-05-31T00:00:00Z
okf_version: "0.1"
feature: p5-t21-reconciliation-tool
status: ready
phase: 5
task: 21
references: []
authored:
  by: "architect"
  date: "2026-05-31"
revised:
  by: ""
  date: ""
---

# T21 — Reconciliation Tool

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Two failure modes leave the artifact store in an inconsistent state where S3 and the
vector index disagree. First, a partial write: S3 succeeded but vector indexing failed;
the artifact is durable but unsearchable, and a failure log entry was written. Second, a
partial delete: vector deletion succeeded but the S3 object delete failed; the artifact
is gone from search but its S3 object is a "ghost". Without a repair tool, orphaned
artifacts accumulate silently and the failure log grows indefinitely. The reconciliation
tool closes both gaps in a single operator-triggered pass.

## User Stories

### Story 1 — Failure log entries are replayed and cleared (P1)

An operator notices the failure log has entries from a previous partial write. They call
`reconcile_index` and the orphaned artifacts are re-indexed, the failure log is cleared,
and the summary tells them which artifacts were recovered.

**Acceptance criteria:**
- Given a `.cairn_failures.jsonl` file with one entry for an artifact whose S3 object
  exists, when `reconcile_index` is called, then the artifact becomes searchable and the
  failure log entry is removed.
- Given a failure log entry whose S3 object no longer exists, when `reconcile_index` is
  called, then the entry is removed from the log and reported in `failed` with the reason
  "S3 object not found".
- Given no failure log exists, when `reconcile_index` is called, then the tool proceeds
  to the orphan scan without error.

### Story 2 — Orphaned S3 objects are detected and re-indexed (P1)

An artifact is present in S3 under `WRITE_PREFIX` but has no entry in the vector index
(write-failure orphan or partial-delete orphan where vectors were deleted but S3 was not).

**Acceptance criteria:**
- Given an S3 object under `WRITE_PREFIX` with no corresponding vector index entries,
  when `reconcile_index` is called, then the artifact is re-indexed and reported in
  `reconciled` with `source: "orphan_scan"`.
- Given an S3 object that already has vector index entries, when `reconcile_index` is
  called, then it is not re-indexed and not reported as reconciled.
- Given all S3 objects already have vector index entries, when `reconcile_index` is
  called, then `orphans_found` is 0 and `reconciled` contains no orphan-scan entries.

### Story 3 — Structured summary returned (P1)

**Acceptance criteria:**
- Given the tool runs successfully (regardless of how many artifacts were reconciled),
  when the response is read, then it contains `reconciled` (list), `failed` (list),
  `failure_log_entries_before` (int), `failure_log_entries_after` (int),
  `orphans_found` (int), and `total_reconciled` (int).
- Given reconciliation produces no recoverable artifacts, when the response is read,
  then `reconciled` is an empty list and `total_reconciled` is 0.

## Requirements

- WHEN `reconcile_index` is called THE SYSTEM SHALL process the failure log first (if it
  exists), then perform the orphan scan regardless of the failure log outcome.
- WHEN a failure log entry is successfully re-indexed THE SYSTEM SHALL remove that entry
  from the log and include the artifact in `reconciled` with `source: "failure_log"`.
- WHEN a failure log entry cannot be re-indexed THE SYSTEM SHALL retain the entry in the
  log and include the artifact in `failed` with a `reason` field.
- WHEN an S3 object under `WRITE_PREFIX` has no corresponding vector index entries THE
  SYSTEM SHALL re-index it and include it in `reconciled` with `source: "orphan_scan"`.
- WHEN an S3 object is already present in the vector index THE SYSTEM SHALL skip it
  during the orphan scan.
- WHEN re-indexing an artifact THE SYSTEM SHALL read its content via `get_object` and
  its metadata via `head_object`, reconstruct vector metadata, parse sections, embed each
  section (or document-level fallback), and call `put_vector` for each — following the
  same logic as `write_artifact`.
- WHEN `put_vector` is called during re-indexing THE SYSTEM SHALL treat it as an upsert
  (confirmed idempotent — T17 Learnings) — no prior cleanup of existing keys is needed.
- WHEN the failure log is empty after processing THE SYSTEM SHALL delete the file.
- WHEN `reconcile_index` is called THE SYSTEM SHALL scope all operations to
  `WRITE_PREFIX` — never touch foreign-scope objects.
- WHEN any unexpected exception occurs THE SYSTEM SHALL return
  `{"error": "internal_error", "message": str(exc)}` — never let raw exceptions escape.

## Boundaries

**Always:**
- Scoped to own scope (`WRITE_PREFIX`) only — never scan or modify foreign-scope
  prefixes.
- Follow the `public_fn / _inner` delegation pattern from `AGENTS.md` (Phase 3
  retrospective learning): `reconcile_index` delegates to `_reconcile_index_inner`
  wrapped in `try/except Exception`.
- Re-indexing uses the same section-embedding logic as `write_artifact` — no shortcut
  paths that diverge from the established embedding format.
- Multiple failure log entries for the same `artifact_id` are deduplicated before
  re-indexing — attempt re-index once per unique ID, not once per log entry.
- The failure log rewrite must be atomic from the perspective of the caller: on success
  the file contains only unresolved entries; on unexpected write error the original file
  is preserved.
- The tool never requires `confirm=True` — reconciliation is a safe, read-then-repair
  operation with no destructive effects.

**Ask First:**
- Nothing — all outcomes are defined.

**Never:**
- Do not re-index artifacts from foreign scopes even if the failure log contains entries
  from a prior misconfigured run.
- Do not skip the orphan scan when the failure log is absent — the two phases are
  independent.
- Do not call `write_artifact` to re-index — that would put a new S3 object for an
  artifact that is already in S3. Re-indexing is vectors-only: `parse_sections` → embed
  → `put_vector`. The S3 object is already there.
- Do not require `bedrock` to be `None`-safe — reconciliation always needs all three
  clients (`s3`, `vectors`, `bedrock`). Pass all three.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_reconcile.py` | Create | Written first (Red) — all unit tests against fakes |
| `src/cairn_mcp/tools/reconcile.py` | Create | Written after unit tests pass (Green) |
| `tests/integration/test_tools_reconcile.py` | Create | Written after unit tests (Red for integration), implemented by the same tool |
| `src/cairn_mcp/server.py` | Modify | Import and register `reconcile_index` inside `register_tools()` |

## Testing Approach

**TDD cycle:** write `test_tools_reconcile.py` first (Red) → implement `reconcile.py`
(Green) → write integration test (Red) → integration passes (Green).

---

**`tests/unit/test_tools_reconcile.py` — unit tests (fakes only, no AWS):**

Failure log replay:
- No failure log file → tool runs, `failure_log_entries_before` is 0, no error.
- Failure log with one resolvable entry (S3 object exists in fake) → entry re-indexed,
  `reconciled` contains one entry with `source: "failure_log"`, log file removed or
  contains no remaining entries.
- Failure log with one unresolvable entry (S3 object absent from fake) → entry kept in
  log, `failed` contains one entry with `reason` including "not found".
- Failure log with two entries for the same artifact_id → only one re-index attempt.
- Failure log with mixed entries (one resolvable, one not) → one in `reconciled`, one
  in `failed`, log retains only the unresolved entry.

Orphan scan:
- No S3 objects → `orphans_found` is 0.
- One S3 object with matching vector entries → not re-indexed, `orphans_found` is 0.
- One S3 object with no vector entries → re-indexed, `orphans_found` is 1, `reconciled`
  has one entry with `source: "orphan_scan"`.
- S3 object from a foreign scope prefix (key not starting with `write_prefix + "/"`) →
  not touched.

Re-indexing mechanics (via fake):
- An artifact with two `##` sections → `put_vector` called twice (one per section),
  `sections_indexed` is 2 in the reconciled entry.
- An artifact with no `##` sections → `put_vector` called once (document-level
  fallback), `sections_indexed` is 1.

Response structure:
- All six fields present in every non-error response: `reconciled`, `failed`,
  `failure_log_entries_before`, `failure_log_entries_after`, `orphans_found`,
  `total_reconciled`.
- `total_reconciled` equals `len(reconciled)`.

Scope gate:
- S3 fake contains one own-scope object and one foreign-scope object → only own-scope
  object is scanned; foreign-scope object is never touched.

Error handling:
- Unexpected exception from `vectors.list_vectors_by_metadata` → returns
  `{"error": "internal_error", "message": ...}`.

---

**`tests/integration/test_tools_reconcile.py` — integration tests (real AWS):**

All tests decorated `@pytest.mark.integration`. Teardown must call `delete_artifact`
with `confirm=True` for every artifact written during the test run.

- Write an artifact, then manually delete its vectors (via `vectors.delete_vectors`),
  then call `reconcile_index` → artifact appears in `reconciled` with
  `source: "orphan_scan"`, is now searchable again.
- Write a failure log entry for a known artifact, call `reconcile_index` → artifact
  appears in `reconciled` with `source: "failure_log"`, failure log is cleared.
- Write a failure log entry for a non-existent artifact_id, call `reconcile_index` →
  entry appears in `failed`, failure log entry retained.
- Empty state (no failure log, all vectors present) → `total_reconciled` is 0,
  `orphans_found` is 0, no error.

## Open Questions

*(none — all behaviour is defined)*
