---
type: Spec
id: p4-t17-integration-test-suite
title: T17 — Run Full Integration Test Suite
description: Closes the Phase 3 empirical gap by running the full integration test suite against live AWS credentials to confirm upsert semantics, valid S3 Vectors key characters, and $nin filter support.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-31T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T12:05:23Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T17 — Run Full Integration Test Suite

## TL;DR

The full integration test suite runs against live AWS credentials for the first time, confirming
three behaviours Phase 3 deferred: `PutVectors` upsert semantics on key re-use, `#` as a valid
character in S3 Vectors keys, and `$nin` in S3 Vectors metadata filters. If upsert is not
confirmed, the tier 3 overwrite path is fixed with an explicit delete-then-re-put. The outcome is
recorded in the plan, closing Q1 and the Phase 3 retrospective, so T19's setup docs rest on
verified behaviour.

## 1. Problem Statement

Phase 3 implementation is complete with 370 unit tests passing, but the integration test suite has
never run against live AWS credentials. Three empirical checkpoints were intentionally deferred to
this task: (1) `PutVectors` upsert semantics on key re-use — the write tool assumes overwrite
behaviour on duplicate keys; if AWS behaves differently, tier 3 overwrite and tier 2 idempotent
re-write are both broken; (2) validity of `#` as a character in S3 Vectors keys; (3) `$nin`
operator in S3 Vectors metadata filters. Open question Q1 remains unresolved. Until the full suite
passes green against real AWS, Phase 3's retrospective remains open and T19 setup docs cannot be
finalised on verified behaviour. This task closes that gap. Its three stories — upsert semantics
confirmed or corrected, the full integration suite passing green, and the plan updated with the
Phase 3 retrospective closed — are all P1.

## 2. Rules — Integration suite run

### R1 — The full integration suite passes with zero failures

When `uv run pytest tests/integration/ -q` is run with real AWS credentials in `.env`, all tests
pass with zero failures.

Source: none

### R2 — `#` in vector keys raises no key-format errors

Section vectors use `#` as a separator in their keys (`{artifact_key}#{section_slug}`). When the
write and search integration tests run, no key-format errors occur.

Source: none

### R3 — `$nin` in re-fetch loop filters raises no filter validation errors

The search re-fetch loop uses `$nin` in its filters. When the search integration tests run, no
filter validation errors are returned from S3 Vectors.

Source: none

### R4 — Teardown fixtures for T7–T9 call `delete_artifact`

When integration tests are run, the teardown fixtures for T7–T9 (write, search, read) are verified
to call `delete_artifact`, so no test data persists in the live index after the run.

Source: none

## 3. Rules — Upsert semantics

### R5 — A tier 3 re-write leaves exactly one vector per section key

The write tool re-uses existing vector keys for same-id artifacts. The expected behaviour is silent
overwrite (upsert). If AWS `PutVectors` raises or duplicates instead, the tier 3 overwrite path is
broken and must be fixed before the suite can pass green.

**Example**

- Given a tier 3 artifact written twice with the same title, when the vector index is queried for
  that `artifact_id`, then exactly one vector entry per section key exists.

Source: none

### R6 — If upsert is not confirmed, tier 3 overwrite becomes an explicit delete-then-re-put

When `PutVectors` does NOT confirm upsert semantics, the tier 3 overwrite in `tools/write.py` is
updated to an explicit delete-then-re-put pattern:

1. call `list_vectors_by_metadata` filtered by `artifact_id` to collect all existing section vector
   keys;
2. call `delete_vectors` with those keys;
3. put the new section vectors.

The affected unit tests are updated, both suites are re-run green, and then the result is
recorded. Once the corrective fix is applied and the suite re-run, all write-related integration
tests pass green.

Source: none

## 4. Rules — Plan update

### R7 — The upsert result and the Q1 closure are recorded in the plan

Plan Learnings and the Q1 closure in `docs/planning-artifacts/plan.md` are updated regardless of
the upsert outcome:

- When `PutVectors` confirms upsert semantics (overwrite on duplicate key), the result is recorded
  in plan Learnings and Q1 is closed with "confirmed — no code change needed".
- Given the suite passes green, plan Learnings records the upsert result (confirmed or denied +
  resolution).
- Given Q1 is resolved, the Risks section shows Q1 closed with its outcome noted.

Source: none

### R8 — The Phase 3 retrospective flag is removed once all integration tests pass

When all integration tests pass, the Phase 3 retrospective flag is removed from the plan Status
line.

Source: none

## 5. Boundaries

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

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/integration/**/*.py` | Run (read-only unless bugs found) | Execute the full suite; fix failures in underlying code, not tests |
| `tests/integration/test_tools_write.py` | Verify | Confirm T7–T9 teardown uses `delete_artifact` |
| `tests/integration/test_tools_search.py` | Verify | Same teardown check |
| `tests/integration/test_tools_read.py` | Verify | Same teardown check |
| `src/arkeology/tools/write.py` | Modify (conditional) | Only if upsert NOT confirmed — add explicit delete-then-re-put for tier 3 section vectors |
| `tests/unit/test_tools_write.py` | Modify (conditional) | Only if write.py changes — update or add tier 3 overwrite tests written first |
| `tests/integration/test_tools_write.py` | Modify (conditional) | Only if write.py changes — add/update test asserting no duplicate section vectors after tier 3 re-write |
| `docs/planning-artifacts/plan.md` | Modify | Update Learnings (Q1 result), remove Phase 3 retrospective flag from Status, close Q1 in Risks |

### Contracts

None.

### Testing Approach

This task is the test execution task. There is no new business logic being written unless the
conditional upsert fix is triggered.

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
