---
status: ready
references: []
authored:
  by: "developer"
  date: "2026-05-31"
revised:
  by: ""
  date: ""
---
# Review Fix 12 — Test Infrastructure Consolidation

## Problem Statement

Three independent duplication problems inflate test maintenance cost. (M15) `_make_settings()` is
copy-pasted identically into all 11 unit tool test files — a new env var requires 11 edits.
(M17) `test_resources.py:46` uses `asyncio.run(app._list_resources())` — a private FastMCP API
with no `@pytest.mark.asyncio`, fragile across FastMCP version bumps. (M18) The four
session-scoped fixtures (`settings`, `s3`, `vectors`, `bedrock`) are copy-pasted into all 11
integration tool test files; `tests/integration/conftest.py` does not define them.

## User Stories

### Story 1 — Single `_make_settings` definition for unit tests

**Acceptance criteria:**
- Given a new env var is added to `Settings`, when a developer updates the test helper, then
  only one file requires an edit and all 11 unit test files pick up the change automatically.

### Story 2 — `test_resources.py` uses a supported asyncio pattern

**Acceptance criteria:**
- Given `test_resources.py` tests resource registration, when the test runs, then it does not
  call `asyncio.run()` directly and uses `@pytest.mark.asyncio` or an equivalent supported
  pattern; a comment explains why `_list_resources()` is used if no public API exists.

### Story 3 — Single source of truth for integration client fixtures

**Acceptance criteria:**
- Given the four integration fixtures change, when a developer updates `conftest.py`, then all
  11 integration test files pick up the change automatically.

## Requirements

- WHEN any unit test imports or uses `_make_settings` THE SYSTEM SHALL resolve it from
  `tests/unit/conftest.py` — not from a local definition.
- WHEN `test_resources.py` tests resource registration THE SYSTEM SHALL use
  `@pytest.mark.asyncio` (not `asyncio.run()`).
- WHEN any integration test uses `settings`, `s3`, `vectors`, or `bedrock` fixtures THE SYSTEM
  SHALL resolve them from `tests/integration/conftest.py`.
- WHEN the four integration fixtures are updated THE SYSTEM SHALL require exactly one file edit.

## Boundaries

**Always:**
- Test behavior must be identical after consolidation — this is a pure refactor.
- Preserve all test-specific fixtures (written artifact IDs, teardown state, per-test data).

**Ask First:**
- Confirm whether `tests/unit/conftest.py` already exists and whether it has content to
  preserve before creating or overwriting it.

**Never:**
- Consolidate fixtures that are test-specific (e.g., artifact IDs seeded per test).
- Change any assertion logic or test semantics during this refactor.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/conftest.py` | Create or Modify | Define `_make_settings` as a module-level helper; check for existing content first |
| `tests/unit/test_tools_*.py` (all 11) | Modify | Remove local `_make_settings`; import or use from conftest |
| `tests/unit/test_resources.py` | Modify | Replace `asyncio.run(app._list_resources())` with `@pytest.mark.asyncio`; add comment if private API is retained |
| `tests/integration/conftest.py` | Modify | Add session-scoped `settings`, `s3`, `vectors`, `bedrock` fixtures |
| `tests/integration/test_tools_*.py` (all 11) | Modify | Remove local definitions of the four fixtures; rely on conftest |

## Testing Approach

This is a pure refactor. The TDD constraint means the existing tests act as the regression suite.

| Order | File | Purpose |
|-------|------|---------|
| 1 | `tests/unit/conftest.py` | Create/update with `_make_settings` (all unit tests now Red until local copies removed) |
| 2 | `tests/unit/test_tools_*.py` (all 11) | Remove local `_make_settings`; tests go Green |
| 3 | `tests/unit/test_resources.py` | Replace `asyncio.run()`; confirm test passes |
| 4 | `tests/integration/conftest.py` | Add four session-scoped fixtures |
| 5 | `tests/integration/test_tools_*.py` (all 11) | Remove local fixture definitions; tests go Green |

Run `uv run pytest tests/unit/ -q -m 'not integration'` after each step.

## Open Questions

1. Does `tests/unit/conftest.py` already exist with content to preserve? Check before creating.
