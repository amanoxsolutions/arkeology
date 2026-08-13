---
type: code_review
title: Review Fix 14 — Integration Test Isolation and Safety
description: Code review spec fixing unsafe integration tests — unique run IDs to prevent collisions, independent cleanup deletes, non-vacuous search assertions, and isolation warnings on destructive tests.
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
# Review Fix 14 — Integration Test Isolation and Safety

## Verification — 2026-08-12

Re-verified story-by-story against current `main`. The literal "Decision (2026-05-31)" (UUID
suffix on `title`) was implemented same-day per `f642725`'s summary ("integration tests:
`unique_run_id` fixture prevents parallel-run collisions") but was later **superseded** by a
structurally stronger mechanism, added in `a770bb8` (2026-07-02, "isolate integration suite under
run-scoped ephemeral prefix"): `tests/integration/_isolation.py` now overrides `WRITE_PREFIX` and
`READ_PREFIXES` for the whole session with an ephemeral `integration-tests/<ULID>` pair before any
`Settings()` is built, and best-effort deletes everything under both prefixes at session end. This
changes the shape of several stories below.

- **Story 1 (unique artifact IDs across parallel runs) — ✅ RESOLVED, VIA A DIFFERENT MECHANISM.**
  Two parallel runs now get disjoint `WRITE_PREFIX` values (each keyed by its own ULID), not just
  disjoint titles within a shared prefix — collision is impossible at the scope level, which is a
  strictly stronger guarantee than the spec asked for. The originally-implemented `unique_run_id`
  title-suffix fixture from `f642725` was removed/superseded by this later work.
- **Story 2 (cleanup deletes are independent) — 🔄 CHANGED ENOUGH TO NEED RESTATING, RESOLVED AT A
  DIFFERENT LAYER.** Per-test `finally` blocks (`test_tools_purge.py` and others) still do NOT wrap
  each `delete_artifact` call in its own `try/except Exception: pass` — e.g.
  `test_purge_two_archived_artifacts_both_absent`'s `finally` loops over `[id1, id2]` with a bare
  `await delete_artifact(...)`; a failure on `id1` still skips `id2`'s cleanup at that layer, exactly
  the M21 problem. However, `_isolation.py`'s session-end `teardown_run_scope` independently wraps
  each S3 object delete and each vector-scope delete in its own `try/except Exception` (see
  `_delete_s3_objects_under_prefix`, `_delete_vectors_for_scope`) and runs regardless of per-test
  cleanup outcome — so anything a failed per-test cleanup leaves behind is still swept up at session
  end. The story's literal acceptance criterion (per-test `finally` block) is unmet; its underlying
  safety goal (no leaked non-test data from a failed delete) is met at the session level instead.
- **Story 3 (search tests assert on seeded data) — ❌ STILL VALID, NOT RESOLVED.**
  `test_type_filter_reduces_results` and `test_own_scope_and_foreign_tier3_shared_present_tier2_absent`
  in `tests/integration/test_tools_search.py` still call `search_artifacts` with no seeding step and
  iterate `result["artifacts"]` with no `assert len(...) > 0` guard beforehand — the exact M19/M20
  vacuous-pass shape the review described. This is now arguably a live bug, not just a latent one:
  because of the run-scoped isolation added in `a770bb8`, the write scope is guaranteed empty at the
  start of every run unless a test seeds it itself, so these two tests will now *always* run their
  loop bodies zero times and pass vacuously, every run — the isolation work that fixed Story 1
  incidentally made Story 3's gap unconditional rather than incidental.
- **Story 4 (destructive tests documented as requiring isolation) — ⭕ NO LONGER APPLICABLE.**
  No such comment exists in `test_tools_purge.py` or `test_tools_freshness.py`, but the premise
  Story 4 was hedging against — running destructive `confirm=True` operations against a shared,
  real, operator-configured environment — no longer holds. `_isolation.py`'s own module docstring
  states the intent directly: "The integration suite must be safe to run against ANY configured
  store, including one already holding real team memory... replaced unconditionally with an
  ephemeral prefix." `purge_archived`/`check_synthesis_freshness(confirm=True)` now only ever see
  the ephemeral run-scoped prefix, never the operator's real data — so the dedicated-isolated-
  environment requirement Story 4 asked to document is now structurally false, not just undocumented.

Net: 1 of 4 stories cleanly resolved, 1 resolved at a different architectural layer than specified,
1 still valid (and arguably sharper now), 1 no longer applicable because the premise it warned about
was eliminated outright rather than documented.

## Problem Statement

Four problems make integration tests unsafe and unreliable. (C7/C8) `purge_archived` and
`check_synthesis_freshness` with `confirm=True` operate on ALL data in the configured write
scope; running them in a shared environment permanently deletes non-test data. (M19/M20) Two
`search_artifacts` tests assert on an empty index with zero-iteration loops — passing vacuously.
(M21) Bare `await delete_artifact(...)` in `finally` blocks means one failed delete skips all
subsequent cleanup and masks the original failure. (M22) Fixed artifact IDs cause data races
between parallel test runs.

## User Stories

### Story 1 — Each test run uses unique artifact IDs

**Acceptance criteria:**
- Given two integration test runs execute simultaneously, when both create artifacts, then their
  artifact IDs do not collide and neither run's data interferes with the other.

### Story 2 — Cleanup deletes are independent

**Acceptance criteria:**
- Given a `finally` block deletes three artifacts and the first delete fails, when the block
  completes, then the second and third deletes are still attempted.
- Given a cleanup delete fails, when the test suite reports results, then the original test
  failure (not the cleanup exception) is surfaced.

### Story 3 — Search tests assert on seeded data

**Acceptance criteria:**
- Given `test_type_filter_reduces_results` runs, when it calls `search_artifacts`, then at least
  one artifact was seeded beforehand and `len(result["artifacts"]) > 0` is asserted.
- Given `test_own_scope_and_foreign_tier3_shared_present_tier2_absent` runs, when it calls
  `search_artifacts`, then data is seeded and a non-empty result is asserted before iterating.

### Story 4 — Destructive tests are documented as requiring isolation

**Acceptance criteria:**
- Given `test_tools_purge.py` or `test_tools_freshness.py` is opened, when a developer reads
  the file header, then a comment or docstring states these tests require a dedicated isolated
  AWS environment and explains why.

## Requirements

- WHEN an integration test `finally` block deletes multiple artifacts THE SYSTEM SHALL wrap each
  delete in `try/except Exception: pass` so a failure on one does not skip the others.
- WHEN a search integration test asserts on results THE SYSTEM SHALL seed data first and assert
  `len(result["artifacts"]) > 0` before iterating result lists.
- WHEN two integration test runs execute in parallel THE SYSTEM SHALL use distinct artifact IDs
  (via a `unique_run_id` fixture) to avoid interference.
- WHEN `test_tools_purge.py` or `test_tools_freshness.py` is run THE SYSTEM SHALL document
  (via comment or docstring) that a dedicated isolated AWS environment is required.

## Boundaries

**Always:**
- Cleanup must still run even if individual deletes fail — use `try/except Exception: pass` per
  delete, not a single blanket catch around all of them.
- All existing assertions must be preserved — no tests may be weakened or removed.

**Decision (2026-05-31):**
- UUID suffix on **`title`**. The artifact key is deterministic from `title`:
  `{type_slug}-{date}-{title_slug}` (tier 2) or `{type_slug}-{title_slug}` (tier 3).
  Suffixing `project` has no effect on key uniqueness. Appending a short UUID run-ID
  to `title` (e.g., `"Integration write test abc12345"`) is the only strategy that
  guarantees unique artifact IDs across parallel runs.

**Never:**
- Use `pytest.skip` to hide the destructive-test problem without documenting it.
- Remove or weaken any existing assertion.
- Add a `confirm=True` guard that silently no-ops instead of warning.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/integration/conftest.py` | Modify | Add `unique_run_id` session fixture (`str(uuid.uuid4())[:8]`); add docstring on isolation requirement |
| `tests/integration/test_tools_purge.py` | Modify | Wrap each cleanup delete in `try/except Exception: pass`; add isolation warning comment |
| `tests/integration/test_tools_freshness.py` | Modify | Same wrapping and isolation comment |
| `tests/integration/test_tools_search.py` | Modify | Seed data in vacuous tests; assert `len > 0` before iterating |
| `tests/integration/test_tools_*.py` (all others) | Modify | Wrap individual cleanup deletes in `try/except Exception: pass` |

## Testing Approach

This spec modifies integration tests only. The TDD constraint applies to the seeding additions
in the search tests: write the assertion first (it will fail on an empty index), then add the
seed+teardown scaffolding.

| Order | File | Purpose |
|-------|------|---------|
| 1 | `tests/integration/conftest.py` | Add `unique_run_id` fixture |
| 2 | `tests/integration/test_tools_search.py` | Add seed + `assert len > 0` (Red → Green) |
| 3 | `tests/integration/test_tools_purge.py` | Wrap cleanup; add isolation comment |
| 4 | `tests/integration/test_tools_freshness.py` | Wrap cleanup; add isolation comment |
| 5 | All remaining integration test files | Wrap cleanup deletes |

Run `uv run pytest tests/integration/ -q` after all changes against a dedicated test environment.

## Open Questions

- **Uniqueness strategy — RESOLVED (2026-05-31):** UUID suffix on `title`. See the
  decision note in Boundaries above.

**[Verified 2026-08-12 — SUPERSEDED.** The `title`-suffix strategy was implemented same-day, then
replaced on 2026-07-02 by whole-prefix run-scoped isolation (`tests/integration/_isolation.py`),
which achieves uniqueness (and more) at the scope level instead. See Verification section above.]
