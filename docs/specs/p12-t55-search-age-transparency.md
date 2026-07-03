---
type: spec
title: Surface artifact last-edited age in search results (CA-4 Option A)
description: Add the last-edited timestamp to each search_artifacts result so agents can judge and discount stale artifacts; no ranking change.
tags: [retrieval, search, staleness, review-fix]
timestamp: 2026-07-03T00:00:00Z
okf_version: "0.1"
feature: "Phase 12 · T55 — CA-4 Option A: search age transparency"
status: ready
references:
  - "../../.docs/reviews/review-2026-07-02-full-project-review.md (CA-4)"
  - "docs/planning-artifacts/backlog.md (B-6 — recency-weighted ranking, Option B)"
  - "docs/planning-artifacts/prd.md (FR-03, AC-66)"
  - "docs/planning-artifacts/plan.md (Phase 12, T55)"
authored:
  by: "pm"
  date: "2026-07-03"
revised:
  by: "pm"
  date: "2026-07-03"
---

# Surface artifact last-edited age in search results (CA-4 Option A)

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR
`search_artifacts` returns semantically ranked artifacts but exposes no last-edited time, so an agent cannot tell a fresh note from a six-month-old superseded one — the "quietly wrong" failure the PRD's own Product Value Failure section names. This feature adds the last-edited timestamp to every search result so agents can discount stale hits themselves. Ranking behaviour is deliberately unchanged (recency-weighted ranking is Option B, deferred to backlog B-6).

## Problem Statement
Review finding CA-4 flags that staleness is named as a fatal risk in the PRD, yet retrieval carries no recency signal. Search results already include `date` (the nominal artifact date), but not the actual last-write time. `last_edited_ulid` — a monotonic, time-sortable ULID — is already stored in every artifact's vector metadata and is already surfaced by `read_artifact` and `list_artifacts`; `search_artifacts` is the one retrieval surface that omits it. Adding it is a near-free transparency win that directly addresses the "agent retrieves an artifact, trusts it, and acts on superseded information" failure mode, without touching ranking or requiring any re-index.

## User Stories

**US-1 (P1) — Agent sees artifact age in search results.**
Given an artifact was written with a valid `last_edited_ulid` in its vector metadata,
When an agent calls `search_artifacts` and that artifact is in the results,
Then the result entry includes the raw `last_edited_ulid` and a human-legible ISO 8601 `last_edited_at` derived from it.

**US-2 (P1) — Missing or malformed timestamps degrade gracefully.**
Given an artifact whose vector metadata has no `last_edited_ulid`, or a value that is not a parseable ULID,
When it appears in `search_artifacts` results,
Then `last_edited_at` is `null` (and `last_edited_ulid` is `null` when absent, or the raw unparseable value when present), and no error is raised to the caller.

## Requirements
- WHEN `search_artifacts` builds a result entry AND the artifact's vector metadata contains a parseable `last_edited_ulid` THE SYSTEM SHALL include in that entry both the raw `last_edited_ulid` and a derived ISO 8601 `last_edited_at`.
- WHEN the `last_edited_ulid` metadata value is absent THE SYSTEM SHALL set both `last_edited_ulid` and `last_edited_at` to `null` in the entry.
- WHEN the `last_edited_ulid` metadata value is present but not a parseable ULID THE SYSTEM SHALL set `last_edited_at` to `null`, return the raw value in `last_edited_ulid` unchanged, and log a warning (matching `propose_commit_links` behaviour).
- WHEN `search_artifacts` returns results THE SYSTEM SHALL preserve the existing result ordering unchanged (no recency weighting is applied).

## Boundaries

**Always**
- Reuse the existing ULID→ISO 8601 derivation already used by `propose_commit_links` / `resources.py` — do not invent a new parsing scheme.
- Keep result ordering identical to today (pure semantic score); this feature is transparency only.
- Match the existing `read_artifact` / `list_artifacts` convention for the raw `last_edited_ulid` field (`meta.get(...) or None`).

**Ask First**
- Whether to extract a shared ULID→ISO helper (would also touch `propose_commit_links.py` and `resources.py`) versus deriving inline in `search.py`. Confirm with the PM before touching files beyond `search.py` and its tests.

**Never**
- Never add recency-weighted ranking, decay, or age penalties — that is Option B (backlog B-6) and requires an ADR first.
- Never change the `synthesise_artifacts` response shape (out of scope; it already returns full content).
- Never add a new config variable, change vector metadata, or trigger any re-index — `last_edited_ulid` is already stored on every vector.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/cairn_mcp/tools/search.py` | Modify | In the Step 6 result-builder loop (~L154), add `last_edited_ulid` (raw, `meta.get("last_edited_ulid") or None`) and derived `last_edited_at` (ISO 8601 or `null`) to each appended entry. Primary change. |
| `tests/unit/test_tools_search.py` | Modify | Add unit tests for US-1 and US-2 (see Testing Approach). |
| `src/cairn_mcp/resources.py` | Modify (doc) | *Uncertain / defer to Tech Writer.* The `last_edited_ulid` system-generated field table (~L88) may warrant a note that `search_artifacts` now returns it plus a derived `last_edited_at`. Flag rather than assume. |

Derivation reference (do not copy verbatim — reuse or extract): `propose_commit_links.py:135-137` converts a ULID to ISO via `ULID.from_str(ulid_str).datetime.isoformat()` and sets `None` on `ValueError`; `resources.py:522` (`_derive_last_modified`) is the annotation-side equivalent.

## Testing Approach
Project convention is **TDD** — write each test and see it fail before implementing.

1. **`tests/unit/test_tools_search.py` (write first):**
   - `last_edited_at` and raw `last_edited_ulid` present and correct when an artifact is written then found by search (asserts the ISO string matches the ULID's timestamp) — gates US-1.
   - Metadata missing `last_edited_ulid` → both fields `null`; result still returned — gates US-2.
   - Metadata with a non-ULID `last_edited_ulid` → `last_edited_at` is `null`, raw value returned unchanged, warning logged — gates US-2.
   - Ordering-unchanged regression: a result set's order is identical with and without the new fields (recency does not reorder) — gates the ranking-invariance requirement.
2. **Implement** the `search.py` result-builder change only after the above fail for the right reason.
3. Run the full unit suite + `ruff` + `ruff format --check` + `mypy` per the project quality gates before handoff.

## Open Questions
- None blocking. The only decision — shared helper vs inline derivation — is captured under Boundaries → Ask First and does not block starting from the inline approach.
