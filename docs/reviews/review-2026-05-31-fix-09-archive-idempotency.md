---
type: code_review
title: Review Fix 09 — Archive Idempotency
description: "Makes archive_artifact idempotent by returning early with already_archived: true when the artifact is already inactive, avoiding unnecessary S3 and S3 Vectors writes."
tags: []
timestamp: 2026-05-31T00:00:00Z
okf_version: "0.1"
status: ready
references: []
authored:
  by: "developer"
  date: "2026-05-31"
revised:
  by: "developer"
  date: "2026-08-12"
---
# Review Fix 09 — Archive Idempotency (M10)

## Verification — 2026-08-12

Re-verified against current `main`. The core idempotency guard was resolved the same day
this spec was authored, in `f642725` ("production hardening — 20 review-fix specs (76
findings resolved)"), the single commit that landed all 20 `fix-01`..`fix-20` specs
together — this document's tracking was never updated afterward.

- **Changed enough to need restating.** The early-return response shape this spec asked for
  — `{"artifact_id": ..., "status": "inactive", "already_archived": True}`, with no S3 or
  vector writes — is still exactly what `archive.py` returns today, and Story 2 (active
  artifact unaffected, no `already_archived` key) still holds. But the guard condition
  itself is no longer "S3 object status already inactive" alone. `a84613c` ("close
  self-healing gaps in archive/reconcile/write recovery paths") found that the original
  S3-only check had a real bug: if a prior archive attempt flipped the S3 object to
  `inactive` but failed partway through the vector-side writes, every retry would hit the
  idempotency short-circuit immediately and the stale-active vectors would never be
  repaired — a permanently half-archived artifact. The guard now checks both sides: it
  short-circuits only when S3 reports `inactive` *and* every existing vector for the
  artifact already agrees; otherwise it falls through to complete the interrupted
  vector-side flip. This is a strictly more correct version of the same idempotency
  contract the spec asked for, not a regression or a different feature — the "no
  unnecessary S3/S3 Vectors writes on a truly-already-archived artifact" goal is intact.
- Test coverage: `test_archive_already_inactive_returns_already_archived` and
  `test_archive_already_inactive_makes_no_writes` in `tests/unit/test_tools_archive.py`
  cover the original story; newer tests in the same file cover the half-archived
  (S3-inactive-but-vectors-still-active) repair path this spec didn't anticipate.

Aggregate: 1 changed enough to need restating (shape and intent preserved; guard condition
hardened by later, unrelated bug-fix work).

## Problem Statement

`archive_artifact` does not check whether an artifact is already archived before proceeding.
Calling it on an already-inactive artifact re-reads content, re-writes S3 object metadata, and
re-writes every vector entry for zero net effect. Under concurrent access this produces transient
inconsistency; it also wastes S3 and S3 Vectors API calls unnecessarily.

## User Stories

### Story 1 — Archiving an already-inactive artifact is a no-op (P1)

**Acceptance criteria:**
- Given an artifact whose `status` metadata is already `"inactive"`, when `archive_artifact` is
  called, then it returns `{"artifact_id": ..., "status": "inactive", "already_archived": True}`
  without writing to S3 or S3 Vectors.

### Story 2 — Archiving an active artifact is unchanged (P1)

**Acceptance criteria:**
- Given an artifact whose `status` metadata is `"active"`, when `archive_artifact` is called,
  then it proceeds exactly as before and does NOT include `"already_archived"` in the response.

## Requirements

- WHEN `archive_artifact` is called on an artifact whose `status` is already `"inactive"` THE
  SYSTEM SHALL return `{"artifact_id": ..., "status": "inactive", "already_archived": True}`
  without calling `put_object` or `put_vector`.
- WHEN `archive_artifact` is called on an active artifact THE SYSTEM SHALL behave exactly as
  before (no change to existing logic or response shape).
- WHEN the early return fires THE SYSTEM SHALL still have validated scope and confirmed the
  artifact exists (early return comes after `head_object`, not before).

## Boundaries

**Always:**
- Early return must come after `head_object` so scope and existence are still validated.
- The `already_archived` key must appear ONLY in the early-return response, not in the normal
  archive response.

**Ask First:**
- Nothing — all outcomes are defined.

**Never:**
- Skip the scope check or existence check in the early-return path.
- Change the existing response shape for the normal (active → inactive) archive path.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_archive.py` | Modify | Add idempotency test (written first — Red) |
| `src/arkeology/tools/archive.py` | Modify | Add early-return guard after `head_object` when `status == "inactive"` |

## Testing Approach

**TDD cycle:** update `test_tools_archive.py` first (Red) → implement guard in `archive.py` (Green).

**`tests/unit/test_tools_archive.py` — new tests:**
- `test_archive_already_inactive_returns_already_archived` — seed `FakeS3Client` with an object
  whose metadata contains `status = "inactive"`; call `archive_artifact`; assert response has
  `"already_archived": True` and `"status": "inactive"`.
- `test_archive_already_inactive_makes_no_writes` — same setup; assert `fake_s3.put_object_calls`
  count is 0 and `fake_vectors.put_vector_calls` count is 0 after the call.
- `test_archive_active_artifact_unchanged` — existing active-artifact tests must still pass
  without `"already_archived"` in the response.

## Open Questions

*(none — all behaviour is defined)*
