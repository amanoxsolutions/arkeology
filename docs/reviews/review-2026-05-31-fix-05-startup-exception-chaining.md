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
# Review Fix 05 — Startup Exception Chaining

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

`startup.py` raises `StartupValidationError` from inside `except` blocks at five
locations (lines 69, 90, 103, 136, 162) without using `raise ... from exc`. The original
exception's traceback is swallowed by Python's implicit exception chaining suppression.
An operator investigating a startup failure sees "cannot write to this prefix" but has no
visibility into whether the root cause was a 403 Forbidden, a DNS failure, a network
timeout, or something else entirely. Proper exception chaining via `raise X from exc`
preserves the original boto3/botocore exception as `__cause__` and makes it visible in
tracebacks.

## User Stories

### Story 1 — Startup failure traceback shows original cause (P1)

The server fails to start because the S3 write probe returns 403 Forbidden. The operator
inspects the traceback and sees both the `StartupValidationError` message and the original
`ClientError: Access Denied` as its cause.

**Acceptance criteria:**
- Given `startup.py` catches a boto3 `ClientError` and re-raises as
  `StartupValidationError`, when a developer inspects the exception, then
  `exc.__cause__` is the original `ClientError`.
- Given `startup.py` catches any exception inside an `except` block, when it re-raises
  as `StartupValidationError`, then `exc.__cause__` is set to the caught exception via
  `raise StartupValidationError(...) from exc`.

## Requirements

- WHEN `startup.py` catches an exception in an `except` block and re-raises as
  `StartupValidationError` THE SYSTEM SHALL use `raise StartupValidationError(...) from
  exc` to preserve the original exception as `__cause__`.
- WHEN a developer inspects a `StartupValidationError` raised during startup THE SYSTEM
  SHALL expose the original boto3/botocore exception as the traceback cause.

## Boundaries

**Always:**
- Every `raise StartupValidationError(...)` that sits inside an `except` block must use
  `from exc` (where `exc` is the locally caught exception variable).
- The `except` clause must name the exception variable explicitly: `except SomeError as
  exc:` before `raise ... from exc` is used.

**Ask First:**
- Nothing — all five locations are identified and the fix is mechanical.

**Never:**
- Change the `StartupValidationError` class definition or its message strings.
- Add `from exc` to the two guard raises at approximately lines 188–207 that are NOT
  inside `except` blocks — they have no cause to chain.
- Change the exception types that are caught — only add `from exc` to existing raises.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_startup.py` | Modify | Add assertions that `exc.__cause__` is set on the 5 affected raises |
| `src/cairn_mcp/startup.py` | Modify | Add `from exc` to raises at lines 69, 90, 103, 136, 162; rename bare `except` clauses to `except ... as exc:` where needed |

## Testing Approach

**TDD cycle:** add failing `__cause__` assertions first (Red) → add `from exc` (Green).

**`tests/unit/test_startup.py` — new/updated cases (one per affected raise site):**
- Fake S3 raises on write probe (line ~69) → `pytest.raises(StartupValidationError)` →
  `exc_info.value.__cause__` is the original fake exception (not `None`).
- Fake S3 raises on delete probe (line ~90) → same assertion pattern.
- Fake vectors raises on `list_vectors_by_metadata` (line ~103) → same.
- Fake S3 raises on read-prefix head probe (line ~136) → same.
- Fake vectors raises on `VectorIndexNotFoundError` path (line ~162) → same.

For each case, use `pytest.raises` as a context manager and assert on
`exc_info.value.__cause__` being an instance of the expected underlying exception type.

## Open Questions

*(none — all five locations are identified and the fix is mechanical)*
