---
type: code_review
title: Review Fix 13 — CredentialError Test Coverage for Freshness and Reconcile
description: Code review spec adding CredentialError unit test coverage for all AWS call sites in freshness.py and reconcile.py.
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
# Review Fix 13 — CredentialError Test Coverage for Freshness and Reconcile

## Verification — 2026-08-12

Re-verified story-by-story against current `main`. Both test files now carry a section explicitly
labelled "Spec 13" (`tests/unit/test_tools_freshness.py`, `tests/unit/test_tools_reconcile.py`), so
this spec was consciously worked — but coverage is uneven between the two files.

- **Story 1 (freshness.py) — 🔄 CHANGED ENOUGH TO NEED RESTATING, PARTIALLY RESOLVED.**
  `freshness.py` still has 8 `except CredentialError` handlers. Only 2 are exercised:
  `test_credential_error_on_list_vectors_returns_credential_error` (the initial synthesis-scan
  `list_vectors_by_metadata` call) and `test_credential_error_on_s3_head_object_during_malformed_delete`
  (`s3.head_object`, confirm-path existence check). The `delete_vectors` and `s3.delete_object`
  handlers named in the original acceptance criteria (confirm-path deletion) have no
  `CredentialError` test — only non-credential-error variants of those two calls are tested
  (`test_non_credential_s3_delete_error_continues_and_reports_failed`,
  `test_non_credential_vector_delete_error_reports_failed`). The third original scenario
  ("source artifact lookup") no longer maps cleanly onto the code: the added test's own docstring
  states head_object "is the ONLY freshness path that reads S3 ... the source-metadata audit never
  reads S3 (T22)" — a later fix (the T22 item, resolved per the 2026-06-29 simplification review)
  removed the S3 fallback from that path, so it's no longer an AWS call site to test. Net: the
  *shape* of Story 1 still holds (not every handler is covered), but two of the four originally
  named scenarios are gone or unmet, and the "EACH handler... at least one test" requirement is not
  met (2 of 8).
- **Story 2 (reconcile.py) — 🔄 CLOSE, NOT FULLY RESOLVED.** `reconcile.py` has 5 `except
  CredentialError` handlers. `test_credential_error_on_list_objects_returns_credential_error`
  (labelled "Spec 01", predating this spec) covers the combined `list_objects` +
  `list_vectors_by_metadata` orphan-scan try block by raising on `list_objects` — since both calls
  share one `except CredentialError` clause, this also exercises the handler the
  `list_vectors_by_metadata`-during-orphan-scan criterion asks for, even though that specific call
  was never itself the one raising. `test_credential_error_on_bedrock_embed_returns_credential_error`
  and `test_credential_error_on_vectors_put_returns_credential_error` (both "Spec 13") and
  `test_phase3_credential_error_on_delete` (`vectors.delete_vectors` during dangling-vector prune)
  add coverage beyond what the spec named. The one gap: the `head_object`-during-failure-log-replay
  handler (the first scenario named in Story 2) has no `CredentialError` test anywhere in the file —
  only a non-`CredentialError` spy variant exists. 4 of 5 handlers effectively covered, 1 gap
  remains.

Net: partially resolved, unevenly — reconcile.py close to complete (1 gap), freshness.py has more
open ground (2 of 4 named scenarios genuinely uncovered, one made moot by an unrelated later fix).
Both "Spec 13"-labelled sections were added in `f642725` (2026-05-31, "20 review-fix specs") — the
same commit that resolved the other 05-31 fix specs — but that commit's summary doesn't credit
fix-13 by name, and the coverage it actually added stopped short of "each handler" for both files
(2 of 8 in freshness.py, 3 of 5 in reconcile.py at that point). The remaining reconcile.py gap
closer — `test_phase3_credential_error_on_delete` (`vectors.delete_vectors` during dangling-vector
prune) — arrived coincidentally in a much later commit (`9412bff`, "implement Scenario 3 —
dangling vector pruning") as ordinary test coverage for a brand-new feature, not as a fix-13
follow-up; the `list_objects`/`list_vectors_by_metadata` combined-handler coverage traces to an
even earlier "Spec 01" test (fix-01, credential-error hardening) that happens to also satisfy part
of fix-13's ask.

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
