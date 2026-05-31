---
type: feature-spec
feature: p4-t17-integration-test-suite
created: 2026-05-31
status: ready
phase: 4
task: 17
---

# T17 — Run Full Integration Test Suite

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Phase 3 implementation is complete with 370 unit tests passing, but the integration test
suite has never run against live AWS credentials. Three empirical checkpoints were
intentionally deferred to this task: (1) `PutVectors` upsert semantics on key re-use —
the write tool assumes overwrite behaviour on duplicate keys; if AWS behaves differently,
tier 3 overwrite and tier 2 idempotent re-write are both broken; (2) validity of `#` as a
character in S3 Vectors keys; (3) `$nin` operator in S3 Vectors metadata filters. Open
question Q1 remains unresolved. Until the full suite passes green against real AWS,
Phase 3's retrospective remains open and T19 setup docs cannot be finalised on verified
behaviour. This task closes that gap.

## User Stories

### Story 1 — Upsert semantics confirmed or corrected (P1)

The write tool re-uses existing vector keys for same-id artifacts. The expected behaviour
is silent overwrite (upsert). If AWS PutVectors raises or duplicates instead, the tier 3
overwrite path is broken and must be fixed before the suite can pass green.

**Acceptance criteria:**
- Given a tier 3 artifact written twice with the same title, when the vector index is
  queried for that artifact_id, then exactly one vector entry per section key exists.
- Given upsert confirmed, when plan Learnings is updated, then Q1 is closed with
  "confirmed — no code change needed".
- Given upsert NOT confirmed, when the corrective fix is applied and the suite re-run,
  then all write-related integration tests pass green.

### Story 2 — Full integration suite passes green (P1)

**Acceptance criteria:**
- Given real AWS credentials in `.env`, when `uv run pytest tests/integration/ -q` runs,
  then all tests pass with zero failures.
- Given `#` used as a separator in vector keys (section vectors use
  `{artifact_key}#{section_slug}`), when write and search integration tests run, then no
  key-format errors occur.
- Given `$nin` used in search re-fetch loop filters, when search integration tests run,
  then no filter validation errors are returned from S3 Vectors.

### Story 3 — Plan updated and Phase 3 retrospective closed (P1)

**Acceptance criteria:**
- Given the suite passes green, when `docs/planning-artifacts/plan.md` Learnings is read,
  then the upsert result is recorded (confirmed or denied + resolution).
- Given the suite passes green, when the plan Status line is read, then the Phase 3
  retrospective flag is removed.
- Given Q1 is resolved, when the Risks section is read, then Q1 is closed with its
  outcome noted.

## Requirements

- WHEN `uv run pytest tests/integration/ -q` is run THE SYSTEM SHALL pass with zero
  failures.
- WHEN `PutVectors` confirms upsert semantics (overwrite on duplicate key) THE SYSTEM SHALL
  record this in plan Learnings and close Q1 with "confirmed — no code change needed".
- WHEN `PutVectors` does NOT confirm upsert semantics THE SYSTEM SHALL update
  `tools/write.py` tier 3 overwrite to an explicit delete-then-re-put pattern:
  (1) call `list_vectors_by_metadata` filtered by `artifact_id` to collect all existing
  section vector keys, (2) call `delete_vectors` with those keys, (3) put the new section
  vectors; update affected unit tests, re-run both suites green, then record the result.
- WHEN all integration tests pass THE SYSTEM SHALL remove the Phase 3 retrospective flag
  from the plan Status line.
- WHEN integration tests are run THE SYSTEM SHALL verify that teardown fixtures for T7–T9
  (write, search, read) call `delete_artifact` so no test data persists in the live index
  after the run.

## Boundaries

**Always:**
- Run the complete integration suite — no subset.
- All integration test teardown must use `delete_artifact` to clean up written artifacts;
  verify T7–T9 fixtures do this before running the full suite.
- Plan Learnings and the Q1 closure are updated regardless of the upsert outcome.
- If the conditional write fix is needed: write updated unit tests first (Red) before
  modifying `write.py` (TDD cycle must be maintained).

**Ask First:**
- Nothing — all outcomes are defined in the done conditions.

**Never:**
- Do not skip tests for components that appear likely to work — all tests must run.
- Do not silently leave Q1 open; it must be closed with a recorded result.
- Do not modify a test's pass/fail condition to make it pass; fix the underlying code.
- Do not proceed to T19 until this task completes — T17 is the phase gate for T19.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/integration/**/*.py` | Run (read-only unless bugs found) | Execute the full suite; fix failures in underlying code, not tests |
| `tests/integration/test_tools_write.py` | Verify | Confirm T7–T9 teardown uses `delete_artifact` |
| `tests/integration/test_tools_search.py` | Verify | Same teardown check |
| `tests/integration/test_tools_read.py` | Verify | Same teardown check |
| `src/cairn_mcp/tools/write.py` | Modify (conditional) | Only if upsert NOT confirmed — add explicit delete-then-re-put for tier 3 section vectors |
| `tests/unit/test_tools_write.py` | Modify (conditional) | Only if write.py changes — update or add tier 3 overwrite tests written first |
| `tests/integration/test_tools_write.py` | Modify (conditional) | Only if write.py changes — add/update test asserting no duplicate section vectors after tier 3 re-write |
| `docs/planning-artifacts/plan.md` | Modify | Update Learnings (Q1 result), remove Phase 3 retrospective flag from Status, close Q1 in Risks |

## Testing Approach

This task is the test execution task. There is no new business logic being written unless
the conditional upsert fix is triggered.

**Execution steps:**
1. Ensure `.env` contains valid AWS credentials and all required vars.
2. Run `uv run pytest tests/integration/ -q`. Observe all results.
3. If any test fails due to unexpected AWS behaviour (not environment issues), record the
   failure and determine whether it is the Q1 upsert scenario or something else.
4. If Q1 upsert is not confirmed, apply the TDD cycle:
   - Write/update `test_tools_write.py` unit tests first (Red) asserting the explicit
     delete-then-re-put behaviour.
   - Modify `write.py` (Green) to perform `list_vectors_by_metadata` + `delete_vectors`
     before re-putting section vectors for a tier 3 artifact being overwritten.
   - Run `uv run pytest tests/unit/ -q` — must pass.
   - Update `tests/integration/test_tools_write.py` to confirm no duplicate vectors.
   - Re-run `uv run pytest tests/integration/ -q` — must pass.
5. Update `plan.md`.

## Open Questions

*(none — all outcomes are defined)*
