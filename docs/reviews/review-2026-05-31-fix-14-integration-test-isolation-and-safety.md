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
  by: ""
  date: ""
---
# Review Fix 14 — Integration Test Isolation and Safety

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
