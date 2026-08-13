---
type: code_review
title: Review Fix 12 — Test Infrastructure Consolidation
description: Code review spec for consolidating duplicated test infrastructure — shared settings helper, asyncio pattern fix, and integration client fixtures.
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
# Review Fix 12 — Test Infrastructure Consolidation

## Verification — 2026-08-12

Re-verified story-by-story against current `main`. The project has grown since 2026-05-31 — 18
unit and 16 integration `test_tools_*.py` files now exist, not 11 — but that growth doesn't change
whether each story's underlying pattern holds.

- **Story 1 (single `_make_settings` definition) — 🔄 RESOLVED, ADAPTED.** `tests/unit/conftest.py`
  defines a module-level `_make_settings(monkeypatch, *, tmp_path=None, **overrides)` that builds
  the base `Settings` env. Most `test_tools_*.py` files import and call it directly. A handful
  (`test_tools_delete.py`, `test_tools_read.py`, and others) define a same-named local
  `_make_settings` that is a thin one-line wrapper — `return _make_settings_base(monkeypatch,
  READ_PREFIXES="other-team", **overrides)` — applying a per-file default override. The single
  source of truth (`_make_settings_base` in `tests/unit/conftest.py`) is real: a new env var still
  requires exactly one edit, and every wrapper still funnels through it. This is a reasonable,
  narrower reading of "single definition" than the spec's literal
  acceptance criterion (no local `_make_settings` at all), but it satisfies the story's actual
  intent (one edit point).
- **Story 2 (`test_resources.py` uses a supported asyncio pattern) — ⚠️ PARTIALLY RESOLVED /
  CHANGED ENOUGH TO NEED RESTATING.** `test_resources.py` still calls
  `asyncio.run(app._list_resources())` inside a plain `def` test (three call sites now, not one) —
  the literal ask (`@pytest.mark.asyncio` or equivalent) was not adopted. What *was* added is the
  comment the acceptance criteria asked for: `# type: ignore[attr-defined]  # FastMCP 3.x exposes
  resources via _list_resources(); no public enumeration API exists`. The project has since adopted
  `pytest-asyncio` with `asyncio_mode = "auto"` project-wide (`pyproject.toml`), which would make
  the originally-requested pattern (`async def test_...(): ... await app._list_resources()`,
  no explicit marker needed under auto mode) trivial to adopt — it simply wasn't applied here. The
  fragility this story worried about (a private API surviving a FastMCP bump) is unrelated to
  `asyncio.run()` vs. `await`; only the "no public API exists" documentation half of the ask
  landed.
- **Story 3 (single source of truth for integration client fixtures) — ❌ STILL VALID, NOT
  RESOLVED.** `tests/integration/conftest.py` still does not define `settings`/`s3`/`vectors`/
  `bedrock`. All 16 `tests/integration/test_tools_*.py` files (e.g. `test_tools_health.py`,
  `test_tools_purge.py`, `test_tools_write.py`) independently redefine the identical four
  session-scoped fixtures verbatim. Updating all four today still requires 16 file edits, not one
  — the story's acceptance criterion is unmet. `tests/integration/conftest.py` did gain substantial
  new content since 2026-05-31 (`load_env`, `isolate_run_scope`, `integration_settings` — see the
  fix-14 verification below), so the file isn't neglected, but the specific `settings`/`s3`/
  `vectors`/`bedrock` consolidation this story asked for was never done.

Net: 1 of 3 stories resolved (adapted), 1 partially resolved (documentation half only), 1 not
resolved. No single commit claims to close this spec; `f642725` ("production hardening — 20
review-fix specs", 2026-05-31) credits only "`tests/unit/conftest.py`: shared `_make_settings`
consolidates 11 duplicates" and "integration tests: `unique_run_id` fixture prevents parallel-run
collisions" in its body — Story 2 and Story 3 were never claimed as done, consistent with what's
found in code today.

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
