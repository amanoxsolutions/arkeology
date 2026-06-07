---
type: feature-spec
feature: p9-t33-filter-range-operators
status: ready
phase: 9
task: 33
references:
  - docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md
authored:
  by: "analyst"
  date: "2026-06-06"
revised:
  by: ""
  date: ""
---

# T23 — Filter Range Operators ($gte / $lte)

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add `$gte` (greater-than-or-equal) and `$lte` (less-than-or-equal) comparison operators to
`filter.py`, the shared in-process metadata filter evaluator. This is a prerequisite for
`propose_commit_links`, which must range-filter on `last_edited_ulid` strings. No tool or
client interface changes are required — only `filter.py` and its tests.

## Problem Statement

`filter.py` currently supports `$eq`, `$in`, `$nin`, `$and`, and `$or`. There is no way to
express "field value is at least X" or "field value is at most Y", which is required to
filter artifacts by write-time ULID range. Without `$gte`/`$lte`, the `propose_commit_links`
tool cannot constrain its vector scan to artifacts written after a given session-start
timestamp — it would be forced to scan all artifacts in scope on every call.

ULIDs are lexicographically sortable strings, so Python string comparison (`>=`, `<=`) is
the correct operator implementation for both ULID range queries and any other string-valued
range fields added in the future (e.g., ISO-8601 date ranges).

## User Stories

### Story 1 — Range filter on a scalar string field (P1)

A caller constructs `{"last_edited_ulid": {"$gte": "01JXYZ..."}}` and passes it to
`matches_filter`. Only metadata dicts where `last_edited_ulid >= "01JXYZ..."` should match.

**Acceptance criteria:**
- Given a metadata dict with `last_edited_ulid = "01JXYZ_HIGH"` and a filter
  `{"last_edited_ulid": {"$gte": "01JXYZ_LOW"}}`, when `matches_filter` is called, it
  returns `True`.
- Given a metadata dict with `last_edited_ulid = "01JXYZ_LOW"` and a filter
  `{"last_edited_ulid": {"$gte": "01JXYZ_HIGH"}}`, when `matches_filter` is called, it
  returns `False`.
- Given equality at the boundary (`$gte` with the same value), when `matches_filter` is
  called, it returns `True` (inclusive).

### Story 2 — Upper bound filter on a scalar string field (P1)

A caller constructs `{"last_edited_ulid": {"$lte": "01JXYZ..."}}`. Only dicts where the
field is at or below the bound should match.

**Acceptance criteria:**
- Given a metadata dict with `last_edited_ulid` below the bound, when `matches_filter` is
  called with `$lte`, it returns `True`.
- Given a metadata dict with `last_edited_ulid` above the bound, when `matches_filter` is
  called with `$lte`, it returns `False`.
- Given equality at the boundary (`$lte` with the same value), it returns `True` (inclusive).

### Story 3 — Combined $gte + $lte in an $and expression (P1)

A caller needs a closed interval: `{"$and": [{"f": {"$gte": lo}}, {"f": {"$lte": hi}}]}`.

**Acceptance criteria:**
- Given a value within the interval, `matches_filter` returns `True`.
- Given a value below the lower bound, `matches_filter` returns `False`.
- Given a value above the upper bound, `matches_filter` returns `False`.

### Story 4 — Unsupported operator still raises ValueError (P1)

**Acceptance criteria:**
- Given a filter with an unknown operator (e.g. `$gt` without the `e`), when
  `matches_filter` is called, it raises `ValueError` — not silently returns `False`.

## Requirements

- WHEN `matches_filter` encounters `{"field": {"$gte": value}}` THE SYSTEM SHALL return
  `True` if and only if `metadata[field] >= value` using Python string comparison.
- WHEN `matches_filter` encounters `{"field": {"$lte": value}}` THE SYSTEM SHALL return
  `True` if and only if `metadata[field] <= value` using Python string comparison.
- WHEN the field is absent from the metadata dict THE SYSTEM SHALL treat the field value as
  `None`; `None >= value` and `None <= value` evaluate to `False`.
- WHEN both `$gte` and `$lte` are used on the same field in an `$and` expression THE
  SYSTEM SHALL evaluate each clause independently and AND them.
- WHEN an unknown operator string is encountered THE SYSTEM SHALL raise `ValueError` with a
  message identifying the operator — unchanged from current behaviour.

## Boundaries

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

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_filter.py` | Create | Written first (Red); all range operator tests |
| `src/cairn_mcp/clients/filter.py` | Modify | Add `$gte` and `$lte` branches; update module docstring |

## Testing Approach

**TDD cycle (unit only — `filter.py` is pure Python, no AWS):**

Write `tests/unit/clients/test_filter.py` first → run → all range tests fail → add `$gte`
and `$lte` branches to `matches_filter` → all tests pass.

---

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

## Open Questions

*(none — all constraints are defined)*
