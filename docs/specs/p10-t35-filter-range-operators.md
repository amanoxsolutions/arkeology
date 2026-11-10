---
type: Spec
id: p10-t35-filter-range-operators
title: T35 — Filter Range Operators ($gte / $lte)
description: Spec to add $gte and $lte comparison operators to filter.py, enabling ULID range queries required by the propose_commit_links tool.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md
    title: Artifact Commit References
    last_modified: 2026-07-03T00:00:00Z
generated:
  by: "axians-analyst/unknown"
  at: 2026-06-06T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T17:13:45Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T35 — Filter Range Operators ($gte / $lte)

## TL;DR

Add `$gte` (greater-than-or-equal) and `$lte` (less-than-or-equal) comparison operators to
`filter.py`, the shared in-process metadata filter evaluator. This is a prerequisite for
`propose_commit_links`, which must range-filter on `last_edited_ulid` strings. No tool or
client interface changes are required — only `filter.py` and its tests.

## 1. Problem Statement

`filter.py` currently supports `$eq`, `$in`, `$nin`, `$and`, and `$or`. There is no way to
express "field value is at least X" or "field value is at most Y", which is required to
filter artifacts by write-time ULID range. Without `$gte`/`$lte`, the `propose_commit_links`
tool cannot constrain its vector scan to artifacts written after a given session-start
timestamp — it would be forced to scan all artifacts in scope on every call.

ULIDs are lexicographically sortable strings, so Python string comparison (`>=`, `<=`) is
the correct operator implementation for both ULID range queries and any other string-valued
range fields added in the future (e.g., ISO-8601 date ranges).

All four user stories this spec covers — a lower bound, an upper bound, a combined interval, and
an unsupported operator still raising — are P1.

## 2. Rules — Range operators

### R1 — `$gte` matches a field at or above the operand (inclusive)

When `matches_filter` encounters `{"field": {"$gte": value}}` — e.g. a caller constructs
`{"last_edited_ulid": {"$gte": "01JXYZ..."}}` and passes it to `matches_filter` — it returns
`True` if and only if `metadata[field] >= value` using Python string comparison. Equality at the
boundary matches.

**Example**

- Given a metadata dict with `last_edited_ulid = "01JXYZ_HIGH"` and a filter
  `{"last_edited_ulid": {"$gte": "01JXYZ_LOW"}}`, when `matches_filter` is called, then it
  returns `True`.
- Given a metadata dict with `last_edited_ulid = "01JXYZ_LOW"` and a filter
  `{"last_edited_ulid": {"$gte": "01JXYZ_HIGH"}}`, when `matches_filter` is called, then it
  returns `False`.
- Given equality at the boundary (`$gte` with the same value), when `matches_filter` is called,
  then it returns `True` (inclusive).

### R2 — `$lte` matches a field at or below the operand (inclusive)

When `matches_filter` encounters `{"field": {"$lte": value}}` — e.g.
`{"last_edited_ulid": {"$lte": "01JXYZ..."}}` — it returns `True` if and only if
`metadata[field] <= value` using Python string comparison. Equality at the boundary matches.

**Example**

- Given a metadata dict with `last_edited_ulid` below the bound, when `matches_filter` is called
  with `$lte`, then it returns `True`.
- Given a metadata dict with `last_edited_ulid` above the bound, when `matches_filter` is called
  with `$lte`, then it returns `False`.
- Given equality at the boundary (`$lte` with the same value), then it returns `True` (inclusive).

### R3 — An absent field matches neither range operator

When the field is absent from the metadata dict, `matches_filter` treats the field value as
`None`; `None >= value` and `None <= value` evaluate to `False`.

### R4 — `$gte` and `$lte` on the same field in an `$and` form a closed interval

When both `$gte` and `$lte` are used on the same field in an `$and` expression —
`{"$and": [{"f": {"$gte": lo}}, {"f": {"$lte": hi}}]}` — `matches_filter` evaluates each clause
independently and ANDs them.

**Example**

- Given a value within the interval, then `matches_filter` returns `True`.
- Given a value below the lower bound, then `matches_filter` returns `False`.
- Given a value above the upper bound, then `matches_filter` returns `False`.

## 3. Rules — Unsupported operators

### R5 — An unknown operator still raises `ValueError`

When `matches_filter` encounters an unknown operator string, it raises `ValueError` with a
message identifying the operator — not silently returns `False` — unchanged from current
behaviour.

**Example**

- Given a filter with an unknown operator (e.g. `$gt` without the `e`), when `matches_filter` is
  called, then it raises `ValueError`.

## 4. Boundaries

**Always:**
- `$gte`/`$lte` use Python `>=`/`<=` string comparison — no type coercion, no numeric
  parsing. ULIDs and ISO-8601 dates are both lexicographically correct with this approach.
- The implementation goes only in `filter.py` — no changes to client interfaces, vector
  client, or any tool.
- The docstring in `filter.py` must be updated to list `$gte` and `$lte` among supported
  operators.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not add numeric range semantics (integer or float coercion) — string comparison only.
- Do not add `$gt` or `$lt` (strict inequality) in this task — only the inclusive variants
  are needed and approved.
- Do not modify `$eq` list-field semantics — `$gte`/`$lte` only need to handle scalar
  fields (ULID strings are never stored as lists).

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_filter.py` | Create | Written first (Red); all range operator tests |
| `src/arkeology/clients/filter.py` | Modify | Add `$gte` and `$lte` branches; update module docstring |

### Contracts

None.

### Testing Approach

**TDD cycle (unit only — `filter.py` is pure Python, no AWS):**

Write `tests/unit/clients/test_filter.py` first → run → all range tests fail → add `$gte`
and `$lte` branches to `matches_filter` → all tests pass.

**`tests/unit/clients/test_filter.py` — unit tests:**

Check that `tests/unit/clients/` exists or create it with an `__init__.py` before placing
the test file.

`$gte` scalar:
- Field value `> operand` → `True`.
- Field value `== operand` → `True` (inclusive lower bound).
- Field value `< operand` → `False`.
- Field absent → `False`.

`$lte` scalar:
- Field value `< operand` → `True`.
- Field value `== operand` → `True` (inclusive upper bound).
- Field value `> operand` → `False`.
- Field absent → `False`.

Combined `$and` interval:
- Value within `[lo, hi]` → `True`.
- Value `< lo` → `False`.
- Value `> hi` → `False`.
- Value `== lo` → `True`.
- Value `== hi` → `True`.

Existing operators still pass (regression guard):
- `$eq`, `$in`, `$nin` scalar and list variants each tested with one assertion.
- Unknown operator raises `ValueError`.
