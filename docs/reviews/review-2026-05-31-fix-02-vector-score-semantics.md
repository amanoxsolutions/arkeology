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
  by: "developer"
  date: "2026-08-12"
---
# Review Fix 02 — Vector Score Semantics

<!-- SCOPE BLOCK — frozen after approval -->

## Verification — 2026-08-12

Re-verified against current `main`. This spec was fixed the same day it was authored —
commit `f642725` ("production hardening — 20 review-fix specs", 2026-05-31) applied the
`score = 1.0 - distance` formula this spec requires — but this document was never
annotated to reflect that.

- **Core fix (formula alignment) — RESOLVED.** `VectorsClientImpl.query_vectors` in
  `clients/vectors.py` computes `"score": 1.0 - distance`. The moto `query_vectors`
  extension in `tests/unit/conftest.py` (which replaced the hand-rolled
  `FakeVectorsClient` referenced throughout this spec — see below) uses the identical
  `1.0 - cosine_distance` formula, so real and test-path scores are numerically
  equivalent as Story 1 and the Requirements section require.
- **Range claims — CHANGED ENOUGH TO NEED RESTATING.** This spec's own arithmetic is
  wrong: it states the fix yields range `[0, 2]` ("2 means identical, 0 means
  orthogonal") and that an identical query/stored vector pair should score `2.0`
  (Story 1's acceptance criteria, the Requirements section, and the Testing Approach all
  repeat this). That does not follow from the stated formula — cosine distance for
  normalised vectors is `1 - cosine_similarity` (range `[0, 2]`), so
  `1.0 - distance = cosine_similarity`, range **`[-1, 1]`**, not `[0, 2]`. Under the
  actually-implemented (and correct) formula, identical vectors score `1.0`, not `2.0`;
  orthogonal vectors score `0.0` as stated (the one case where the arithmetic error
  happens to cancel out). Current code, the moto extension's own docstring, and
  `AGENTS.md`'s High-Friction Areas entry ("Vector scores are `1.0 - distance` ... scores
  in `[−1, 1]`") all agree with the corrected range, confirming this is a defect in the
  review document's own numbers, not in the shipped code. No action needed on the code;
  restated here so the acceptance criteria aren't taken at face value if this spec is
  ever consulted again.
- **`fake_vectors.py` references — NO LONGER APPLICABLE.** The Files-to-Touch and Testing
  Approach sections name `src/arkeology/clients/fakes/fake_vectors.py` and
  `tests/unit/clients/test_fake_vectors.py`. Neither exists: S3 Vectors is mocked via
  moto (`aws_mock`/`vectors_client_*` fixtures) with a cosine-similarity extension
  patched once in `tests/unit/conftest.py`
  (`tests/unit/clients/test_moto_query_vectors_extension.py` verifies it directly), per
  `AGENTS.md`'s Testing Conventions. This predates the fix commit (`76358a8`, landed
  just before `f642725` on 2026-05-31) and is unrelated to this spec — the equivalent
  formula-alignment guarantee now lives in the moto extension instead.
- **Story 2 (score ordering preserved) — RESOLVED.** Ordering is unaffected by an affine
  transform of distance (`1.0 - distance` is monotonically decreasing in `distance`
  regardless of the constant), and both the real client and the moto extension sort
  descending by the same `score` field.

**Aggregate:** formula-alignment fix resolved (same-day, `f642725`); the spec's own
stated numeric range and Story 1's `2.0`/`0.0` acceptance values are wrong and need
restating; the `fake_vectors.py` file references are no longer applicable following the
moto migration. No open work — the code is correct and self-consistent with `AGENTS.md`.

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

## Items Resolved Since Last Review

<!-- changelog-style: prepend new entries -->
- 2026-08-12 — **Re-verification pass (developer): formula-alignment fix confirmed
  resolved, but the spec's own range/score-value claims are wrong and restated.** Fixed
  same-day by `f642725` (2026-05-31). `vectors.py` and the moto `query_vectors`
  extension (which superseded the `fake_vectors.py` this spec references — moto
  migration `76358a8` landed first) both compute `score = 1.0 - distance`. That formula
  actually produces range `[-1, 1]` (cosine similarity), not the `[0, 2]` this document
  claims throughout — identical vectors score `1.0`, not the `2.0` Story 1 and the
  Testing Approach assert. `AGENTS.md` and the current code agree with the corrected
  range; only this document's arithmetic was wrong. See inline
  `## Verification — 2026-08-12` note above.
