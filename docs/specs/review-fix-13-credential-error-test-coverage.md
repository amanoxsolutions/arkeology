---
type: feature-spec
feature: review-fix-13-credential-error-test-coverage
created: 2026-05-31
status: ready
---

# Review Fix 13 — CredentialError Test Coverage for Freshness and Reconcile

## Problem Statement

Neither `tests/unit/test_tools_freshness.py` nor `tests/unit/test_tools_reconcile.py` contains
any test for `CredentialError` paths. Each source file has 8+ `except CredentialError` handlers;
none are exercised by tests. A future refactor that accidentally removes a handler would go
undetected. This spec is test-only — no source code changes.

## User Stories

### Story 1 — CredentialError paths in freshness.py are covered

**Acceptance criteria:**
- Given a `CredentialError` is raised by `list_vectors_by_metadata` (initial synthesis scan),
  when `check_synthesis_freshness` is called, then the response contains
  `{"error": "credential_error", ...}`.
- Given a `CredentialError` is raised by the source artifact lookup, when
  `check_synthesis_freshness` is called, then the response contains
  `{"error": "credential_error", ...}`.
- Given a `CredentialError` is raised by `delete_vectors`, when `check_synthesis_freshness` is
  called with `confirm=True`, then the response contains `{"error": "credential_error", ...}`.
- Given a `CredentialError` is raised by `delete_object`, when `check_synthesis_freshness` is
  called with `confirm=True`, then the response contains `{"error": "credential_error", ...}`.

### Story 2 — CredentialError paths in reconcile.py are covered

**Acceptance criteria:**
- Given a `CredentialError` is raised by `head_object` during failure log replay, when
  `reconcile_index` is called, then the response contains `{"error": "credential_error", ...}`.
- Given a `CredentialError` is raised by `list_objects` during the orphan scan, when
  `reconcile_index` is called, then the response contains `{"error": "credential_error", ...}`.
- Given a `CredentialError` is raised by `list_vectors_by_metadata` during the orphan index
  scan, when `reconcile_index` is called, then the response contains
  `{"error": "credential_error", ...}`.

## Requirements

- WHEN a `CredentialError` is raised at any AWS call site in `freshness.py` THE SYSTEM SHALL
  return `{"error": "credential_error", ...}` to the caller.
- WHEN a `CredentialError` is raised at any AWS call site in `reconcile.py` THE SYSTEM SHALL
  return `{"error": "credential_error", ...}` to the caller.
- EACH `CredentialError` handler in both source files SHALL be covered by at least one unit
  test.

## Boundaries

**Always:**
- Use the existing fake clients' credential simulation mechanism — never mock boto3 directly.
- Unit tests only — no integration tests in this spec.
- No source code changes — tests must pass against the existing implementation.

**Never:**
- Add integration tests in this spec.
- Change any handler logic in `freshness.py` or `reconcile.py`.
- Mock boto3 or AWS SDK internals directly.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_freshness.py` | Modify | Add one `CredentialError` test per major AWS call site in `freshness.py` |
| `tests/unit/test_tools_reconcile.py` | Modify | Add one `CredentialError` test per major AWS call site in `reconcile.py` |

## Testing Approach

TDD: tests are written first (they should pass immediately if handlers already exist; they will
fail if a handler is missing, revealing a gap in the implementation).

| Order | File | Purpose |
|-------|------|---------|
| 1 | `tests/unit/test_tools_freshness.py` | Add `CredentialError` tests for each call site |
| 2 | `tests/unit/test_tools_reconcile.py` | Add `CredentialError` tests for each call site |

Before writing tests, read `freshness.py` and `reconcile.py` to enumerate every
`except CredentialError` block and map each to an AWS call site. Write one test per site.
Verify the fake clients support raising `CredentialError` on demand; add that capability to the
fakes if it is absent (that change belongs in the fake client files, not in source).

## Open Questions

*(none — scope is fully defined)*
