---
type: code_review
title: Review Fix 02 — Vector Score Semantics
description: Aligns real and fake vector clients to use cosine similarity (1.0 - cosine_distance) so numeric score ranges match between tests and production.
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
# Review Fix 02 — Vector Score Semantics

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

`VectorsClientImpl.query_vectors` computes `score = -distance` (range [-2, 0] where 0
means identical). `FakeVectorsClient.query_vectors` computes cosine similarity (range
[-1, 1] where 1 means identical). Both maintain "higher = more similar" ordering, but
the numeric ranges differ. Any code that displays scores, logs them, or applies a numeric
threshold will behave differently in tests versus production. The fix aligns both clients
to cosine similarity (`1.0 - cosine_distance`), yielding range [0, 2] where 2 means
identical and 0 means orthogonal.

## User Stories

### Story 1 — Real and fake clients return equivalent scores (P1)

A developer runs a search in unit tests and in production with the same vectors. The
scores are numerically identical, not just ranked the same.

**Acceptance criteria:**
- Given the real client receives a query and a stored vector that are identical, when
  `query_vectors` returns, then `score` is 2.0.
- Given the fake client receives a query and a stored vector that are identical, when
  `query_vectors` returns, then `score` is 2.0.
- Given query and stored vector are orthogonal, when `query_vectors` returns, then
  `score` is 0.0 in both clients.

### Story 2 — Score ordering is preserved (P1)

**Acceptance criteria:**
- Given two stored vectors where vector A is more similar to the query than vector B,
  when `query_vectors` returns, then vector A has a higher score than vector B in both
  clients.

## Requirements

- WHEN `query_vectors` is called THE SYSTEM SHALL return scores using cosine similarity
  (`1.0 - cosine_distance`) with range [0, 2].
- WHEN the real client and fake client are given the same query and stored vectors THE
  SYSTEM SHALL return numerically equivalent scores.
- WHEN `query_vectors` returns results THE SYSTEM SHALL preserve the `score` field name
  in the result schema unchanged.

## Boundaries

**Always:**
- Score ordering (higher = more similar) must be preserved after the change.
- Both the real client (`vectors.py`) and the fake (`fake_vectors.py`) must use the same
  formula: `score = 1.0 - cosine_distance`.

**Ask First:**
- If any existing tool applies a numeric threshold on score values (e.g., filter out
  scores below 0.5), confirm the threshold value before changing the scale — the numeric
  range shifts from [-2, 0] to [0, 2].

**Never:**
- Change the return schema of `query_vectors` — the field name `score` must remain.
- Change the sort order of results (descending by score).

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_fake_vectors.py` | Modify | Add assertions on score values for known vectors; verify range [0, 2] |
| `src/arkeology/clients/vectors.py` | Modify | Change `score = -distance` to `score = 1.0 - distance` at lines 136–142 |
| `src/arkeology/clients/fakes/fake_vectors.py` | Modify | Verify cosine similarity formula; update comment to document range [0, 2] |

## Testing Approach

**TDD cycle:** add failing score-value assertions first (Red) → fix formula (Green).

**`tests/unit/clients/test_fake_vectors.py` — new/updated cases:**
- Identical query and stored vector → `score == 2.0`.
- Orthogonal query and stored vector → `score == 0.0` (within float tolerance).
- Two stored vectors where one is more similar than the other → more-similar vector has
  higher score in both ordinal and numeric terms.
- All returned scores are in range [0, 2] (assert `0.0 <= score <= 2.0` for each result).

## Open Questions

- **Score threshold audit — RESOLVED (2026-05-31):** Audited all tool files. Neither
  `search.py` nor `synthesise.py` applies an absolute numeric threshold against `score`.
  Both only use relative comparisons (`score > best_by_id[aid][0]`) for deduplication.
  Changing from `-distance` (range [-2, 0]) to `1.0 - distance` (range [0, 2]) is safe
  — no threshold values require updating. Implement as specified.
