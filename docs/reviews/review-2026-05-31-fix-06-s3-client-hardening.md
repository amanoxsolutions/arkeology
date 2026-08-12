---
type: code_review
title: Review Fix 06 — S3 Client Hardening
description: Fixes two S3 client defects — 403 Access Denied responses incorrectly mapped to KeyError, and FakeS3Client returning list_objects results in insertion order instead of lexicographic order.
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
# Review Fix 06 — S3 Client Hardening (M5, M8)

## Problem Statement

Two defects weaken the S3 client layer. First (`M5`): `s3.py` maps HTTP 403 to `KeyError`
alongside `NoSuchKey` and `404`. A 403 is an Access Denied response — the object may exist but
the caller lacks permission. Callers such as `read_artifact` and `reconcile_index` silently treat
permission errors as "not found", masking IAM misconfiguration. Second (`M8`): `FakeS3Client.list_objects`
returns keys in dict insertion order. Real S3 `ListObjectsV2` returns keys in lexicographic order.
Tests that rely on ordering pass locally but fail in production.

## User Stories

### Story 1 — 403 surfaces as credential error, not KeyError (P1)

**Acceptance criteria:**
- Given `head_object` receives an HTTP 403 response, when `read_artifact` calls it, then a
  `CredentialError` (or re-raised `ClientError`) is returned — not `KeyError`.
- Given `head_object` receives `NoSuchKey` or HTTP 404, when called, then `KeyError` is raised
  as before.

### Story 2 — Fake list_objects returns lexicographic order (P1)

**Acceptance criteria:**
- Given objects inserted into `FakeS3Client` in arbitrary order, when `list_objects` is called,
  then keys are returned in lexicographic ascending order.
- Given an empty store, when `list_objects` is called, then an empty list is returned.

## Requirements

- WHEN `head_object` receives an HTTP 403 response THE SYSTEM SHALL NOT raise `KeyError` — it
  SHALL propagate as `CredentialError` via the existing `is_credential_error` path or re-raise
  the `ClientError`.
- WHEN `head_object` receives `NoSuchKey` or HTTP 404 THE SYSTEM SHALL raise `KeyError` as before.
- WHEN `FakeS3Client.list_objects` is called THE SYSTEM SHALL return keys in lexicographic
  ascending order, matching real S3 `ListObjectsV2` behaviour.

## Boundaries

**Always:**
- `NoSuchKey` and `404` must still map to `KeyError` — this is a load-bearing contract.
- `list_objects` return type stays `list[str]` — no shape change.
- Verify that the existing `is_credential_error` check in `head_object`'s `ClientError` handler
  already handles 403 before removing it from the tuple; if not, add an explicit check first.

**Ask First:**
- Confirm whether any tool currently depends on insertion-order behaviour of `list_objects`
  before merging — if yes, surface the tool for separate review.

**Never:**
- Do not change `get_object` or any other method — scope is `head_object` and `list_objects` only.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_fake_s3.py` | Modify | Add tests for lexicographic order and 403-not-KeyError (written first — Red) |
| `src/arkeology/clients/s3.py` | Modify | Remove `"403"` from the `("NoSuchKey", "404", "403")` tuple in `head_object` |
| `src/arkeology/clients/fakes/fake_s3.py` | Modify | Wrap `list_objects` return in `sorted(...)` |

## Testing Approach

**TDD cycle:** update `test_fake_s3.py` first (Red) → fix `fake_s3.py` and `s3.py` (Green).

**`tests/unit/clients/test_fake_s3.py` — new tests:**
- `test_list_objects_lexicographic_order` — insert keys `["b/key", "a/key", "c/key"]`, call
  `list_objects`, assert result is `["a/key", "b/key", "c/key"]`.
- `test_list_objects_empty` — empty store returns `[]`.
- `test_head_object_403_does_not_raise_key_error` — configure fake to raise a simulated 403
  `ClientError`; assert the exception is NOT `KeyError`.

## Open Questions

*(none — all behaviour is defined)*
