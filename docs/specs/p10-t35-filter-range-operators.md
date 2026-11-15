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
  - resource: docs/learnings.md
    title: Learnings
  - resource: tests/integration/clients/test_vectors_filter_semantics.py
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
  - resource: docs/specs/p10-t37-propose-commit-links.md
    title: T37 — propose_commit_links Tool
generated:
  by: "axians-analyst/unknown"
  at: 2026-06-06T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:19:59Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
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
tool cannot keep, from the own-scope vectors it lists, only the artifacts written at or after the
`last_edited_ulid` its caller passes as `since_ulid` — a value the server returned on an earlier
write.

ULIDs are lexicographically sortable strings, so Python string comparison (`>=`, `<=`) is
the correct way to evaluate a ULID range in process. This spec covers that in-process evaluation
only; where a string range may be evaluated at all is `s3vectors.artifact` § Compatibility
Guarantees.

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
- Range operators on string values are evaluated in process only, never in a filter sent to the
  vector index (`s3vectors.artifact` § Compatibility Guarantees states the rule and why a passing
  unit test proves nothing about it).
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

- `docs/contracts/data/s3vectors.artifact.md` § Storage Shape and § Compatibility Guarantees — `last_edited_ulid` as the string field the range operators compare (R1–R4), and a string range evaluated in process, never sent to the index (Boundaries).

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
