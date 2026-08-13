---
type: code_review
title: Review Fix 05 — Startup Exception Chaining
description: Adds raise ... from exc at five startup.py raise sites so the original boto3/botocore exception is preserved as __cause__ and visible in operator tracebacks.
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
# Review Fix 05 — Startup Exception Chaining

<!-- SCOPE BLOCK — frozen after approval -->

## Verification — 2026-08-12

Re-verified against current `main`. This spec was fixed the same day it was authored —
commit `f642725` ("production hardening — 20 review-fix specs", 2026-05-31) — but this
document was never annotated to reflect that.

- **Story 1 (startup failure traceback shows original cause) — RESOLVED, and generalised
  to every raise site added since.** `startup.py` has grown from the five/six checks in
  scope when this spec was written to a seven-check sequence (Phase 12 added check 7,
  the text-model probe was check 6 at review time). Every `raise StartupValidationError(...)`
  that sits inside an `except` block across all seven checks (`_check_credentials`,
  `_check_write_prefix`, `_check_read_prefixes`, `_check_vector_index`,
  `_check_model_dimension`, `_check_embedding_probe`, `_check_text_model`) uses
  `from exc`, and every enclosing `except` clause names its exception variable. The
  Boundaries' "Never" clause (no `from exc` on the two non-`except`-block guard raises)
  also still holds — `_check_model_dimension`'s dimension-mismatch raise has no `from`
  clause because it isn't chained from a caught exception.

Test coverage matches: `tests/unit/test_startup.py` has a dedicated "Spec 05: Exception
chaining (`__cause__`)" section asserting `exc_info.value.__cause__` on the write-probe,
read-prefix, and vector-index-missing failure paths, plus a credential-failure chaining
assertion.

**Aggregate:** 1 story, resolved — the fix was applied at all five original locations and
has scaled correctly to the two additional raise sites startup.py gained since. No open
work.

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
| `src/arkeology/startup.py` | Modify | Add `from exc` to raises at lines 69, 90, 103, 136, 162; rename bare `except` clauses to `except ... as exc:` where needed |

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

## Items Resolved Since Last Review

<!-- changelog-style: prepend new entries -->
- 2026-08-12 — **Re-verification pass (developer): confirmed resolved and scaled to
  later growth.** Fixed same-day by `f642725` (2026-05-31). All `except`-block
  `StartupValidationError` raises across `startup.py`'s now-seven-check sequence use
  `raise ... from exc`; the non-`except`-block guard raise this spec explicitly
  excluded from the fix (dimension mismatch) correctly still has no `from` clause. See
  inline `## Verification — 2026-08-12` note above.
