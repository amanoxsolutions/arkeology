---
type: Spec
id: p5-t21-reconciliation-tool
title: T21 — Reconciliation Tool
description: Introduces a reconcile_index MCP tool that repairs S3/vector-index inconsistencies by replaying the failure log and scanning for orphaned S3 objects, returning a structured summary of recovered and failed artifacts.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-31T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T13:13:28Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T21 — Reconciliation Tool

## TL;DR

`reconcile_index` is an operator-triggered MCP tool that repairs inconsistencies between S3 and the
vector index in a single pass: it replays the failure log, then scans own-scope S3 objects for
orphans with no vector entries, re-indexing them vectors-only. It returns a structured summary of
reconciled and failed artifacts, so partial writes and partial deletes no longer leave orphaned
artifacts accumulating silently or the failure log growing indefinitely.

## 1. Problem Statement

Two failure modes leave the artifact store in an inconsistent state where S3 and the vector index
disagree. First, a partial write: S3 succeeded but vector indexing failed; the artifact is durable
but unsearchable, and a failure log entry was written. Second, a partial delete: vector deletion
succeeded but the S3 object delete failed; the artifact is gone from search but its S3 object is a
"ghost". Without a repair tool, orphaned artifacts accumulate silently and the failure log grows
indefinitely. The reconciliation tool closes both gaps in a single operator-triggered pass. The
three stories — failure log entries replayed and cleared, orphaned S3 objects detected and
re-indexed, and a structured summary returned — are all P1.

This spec covers the S3↔vector reconciliation. In addition to it, `reconcile_index` also rebuilds
the `commit_refs` and `references` vector metadata fields from the artifact's **durable S3 object
annotations** (reading annotations, not user-defined object metadata), which closes the earlier
"reconcile drops `commit_refs`" limitation (ADR-011, 2026-07-03). That behaviour is specced in
`p12-t48`, not in this spec.

## 2. Rules — Run order and scope

### R1 — The failure log is processed first, then the orphan scan always runs

When `reconcile_index` is called, the system processes the failure log first (if it exists), then
performs the orphan scan regardless of the failure log outcome — the two phases are independent.

**Example**

- Given no failure log exists, when `reconcile_index` is called, then the tool proceeds to the
  orphan scan without error.

Source: none

### R2 — All operations are scoped to `WRITE_PREFIX`

When `reconcile_index` is called, the system scopes all operations to `WRITE_PREFIX` — it never
touches foreign-scope objects. Artifacts from foreign scopes are not re-indexed even if the failure
log contains entries from a prior misconfigured run.

Source: none

## 3. Rules — Failure log replay

### R3 — A re-indexed failure log entry is removed and reported as reconciled

An operator who notices the failure log has entries from a previous partial write calls
`reconcile_index`; the orphaned artifacts are re-indexed, the failure log is cleared, and the
summary tells them which artifacts were recovered. When a failure log entry is successfully
re-indexed, the system removes that entry from the log and includes the artifact in `reconciled`
with `source: "failure_log"`.

**Example**

- Given a `.arkeology_failures.jsonl` file with one entry for an artifact whose S3 object exists,
  when `reconcile_index` is called, then the artifact becomes searchable and the failure log entry
  is removed.

Source: none

### R4 — A failure log entry that cannot be re-indexed is kept and reported as failed

When a failure log entry cannot be re-indexed, the system retains the entry in the log and
includes the artifact in `failed` with a `reason` field.

Source: none

### R5 — An entry whose S3 object no longer exists is resolved as obsolete, not failed

When a failure log entry's S3 object no longer exists, the entry is resolved, not failed: it is
reported once in `reconciled` with `source: "failure_log_obsolete"`, nothing is re-indexed, and the
entry is pruned from the log. It is not routed through the bounded-retry counter. Leaving it in
`failed` would replay it on every run forever.

Source: `docs/contracts/modules/arkeology.tools.reconcile.md`, [`p12-t62-bounded-reconcile-retry.md`](p12-t62-bounded-reconcile-retry.md) `## Revision — 2026-09-05`, commit 773c164

### R6 — An empty failure log file is deleted

When the failure log is empty after processing, the system deletes the file.

Source: none

## 4. Rules — Orphan scan

### R7 — An S3 object with no vector entries is re-indexed and reported as an orphan

An orphan is an artifact present in S3 under `WRITE_PREFIX` with no entry in the vector index — a
write-failure orphan, or a partial-delete orphan where vectors were deleted but S3 was not. When
an S3 object under `WRITE_PREFIX` has no corresponding vector index entries, the system re-indexes
it and includes it in `reconciled` with `source: "orphan_scan"`.

Source: none

### R8 — An S3 object already in the vector index is skipped

When an S3 object is already present in the vector index, the system skips it during the orphan
scan: it is not re-indexed and not reported as reconciled.

**Example**

- Given all S3 objects already have vector index entries, when `reconcile_index` is called, then
  `orphans_found` is 0 and `reconciled` contains no orphan-scan entries.

Source: none

## 5. Rules — Re-indexing

### R9 — Re-indexing follows `write_artifact`'s section-embedding logic, vectors-only

When re-indexing an artifact, the system reads its content via `get_object` and its metadata via
`head_object`, reconstructs vector metadata, parses sections, embeds each section (or
document-level fallback), and calls `put_vector` for each — following the same logic as
`write_artifact`. Re-indexing is vectors-only: the S3 object is already there, so no new S3 object
is put.

Source: none

### R10 — `put_vector` during re-indexing is an upsert

When `put_vector` is called during re-indexing, the system treats it as an upsert (confirmed
idempotent — T17 Learnings) — no prior cleanup of existing keys is needed.

Source: none

## 6. Rules — Response

### R11 — Every non-error response is a structured summary with six fields

Given the tool runs successfully (regardless of how many artifacts were reconciled), the response
contains:

| Field | Type |
|-------|------|
| `reconciled` | list |
| `failed` | list |
| `failure_log_entries_before` | int |
| `failure_log_entries_after` | int |
| `orphans_found` | int |
| `total_reconciled` | int |

Given reconciliation produces no recoverable artifacts, `reconciled` is an empty list and
`total_reconciled` is 0.

Source: none

### R12 — An unexpected exception returns `internal_error`

When any unexpected exception occurs, the system returns
`{"error": "internal_error", "message": str(exc)}` — never letting raw exceptions escape.

Source: none

## 7. Boundaries

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

## 8. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_reconcile.py` | Create | Written first (Red) — all unit tests against fakes |
| `src/arkeology/tools/reconcile.py` | Create | Written after unit tests pass (Green) |
| `tests/integration/test_tools_reconcile.py` | Create | Written after unit tests (Red for integration), implemented by the same tool |
| `src/arkeology/server.py` | Modify | Import and register `reconcile_index` inside `register_tools()` |

### Contracts

- [`docs/contracts/modules/arkeology.tools.reconcile.md`](../contracts/modules/arkeology.tools.reconcile.md),
  `## Symbols` — the `reconcile_index` Invariants and Postconditions are the normative statement of
  the obsolete failure-log entry behaviour (an entry whose S3 object no longer exists is reported
  in `reconciled` with `source: "failure_log_obsolete"` and pruned from the log).

### Testing Approach

**TDD cycle:** write `test_tools_reconcile.py` first (Red) → implement `reconcile.py`
(Green) → write integration test (Red) → integration passes (Green).

---

**`tests/unit/test_tools_reconcile.py` — unit tests (fakes only, no AWS):**

Failure log replay:
- No failure log file → tool runs, `failure_log_entries_before` is 0, no error.
- Failure log with one resolvable entry (S3 object exists in fake) → entry re-indexed,
  `reconciled` contains one entry with `source: "failure_log"`, log file removed or
  contains no remaining entries.
- Failure log with one entry whose S3 object is absent from fake → nothing re-indexed,
  `reconciled` contains one entry with `source: "failure_log_obsolete"`, entry pruned from
  the log.
- Failure log with two entries for the same artifact_id → only one re-index attempt.

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
