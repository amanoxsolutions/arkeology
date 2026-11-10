---
type: Spec
id: p12-t54-search-age-transparency
title: Surface artifact last-edited age in search results (Option A)
description: Add the last-edited timestamp to each search_artifacts result so agents can judge and discount stale artifacts; no ranking change.
tags: [retrieval, search, staleness, review-fix]
status: stable
okf_version: "0.2"
sources:
  - resource: docs/planning-artifacts/backlog.md
    title: Backlog (B-6 — recency-weighted ranking, Option B)
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements (FR-03, AC-66)
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/planning-artifacts/plan.md
    title: Plan Arkeology (Phase 12, T54)
generated:
  by: "axians-pm/claude-opus-4.8"
  at: 2026-07-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T19:06:35Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# Surface artifact last-edited age in search results (Option A)

## TL;DR

`search_artifacts` returns semantically ranked artifacts but exposes no last-edited time, so an agent cannot tell a fresh note from a six-month-old superseded one — the "quietly wrong" failure vision.md's own Product-Value-Failure Pre-Mortem section names. This feature adds the last-edited timestamp to every search result so agents can discount stale hits themselves. Ranking behaviour is deliberately unchanged (recency-weighted ranking is Option B, deferred to backlog B-6).

## 1. Problem Statement

Staleness is named as a fatal risk in vision.md, yet retrieval carries no recency signal. Search results already include `date` (the nominal artifact date), but not the actual last-write time. `last_edited_ulid` — a monotonic, time-sortable ULID — is already stored in every artifact's vector metadata and is already surfaced by `read_artifact` and `list_artifacts`; `search_artifacts` is the one retrieval surface that omits it. Adding it is a near-free transparency win that directly addresses the "agent retrieves an artifact, trusts it, and acts on superseded information" failure mode, without touching ranking or requiring any re-index.

Both stories are P1: US-1 (P1) — agent sees artifact age in search results; US-2 (P1) — missing or malformed timestamps degrade gracefully.

## 2. Rules — Last-edited age in search results

### R1 — A search result carries the raw `last_edited_ulid` and a derived `last_edited_at`

When `search_artifacts` builds a result entry and the artifact's vector metadata contains a
parseable `last_edited_ulid`, the entry includes both the raw `last_edited_ulid` and a
human-legible ISO 8601 `last_edited_at` derived from it.

**Example**

- Given an artifact was written with a valid `last_edited_ulid` in its vector metadata, when an
  agent calls `search_artifacts` and that artifact is in the results, then the result entry
  includes the raw `last_edited_ulid` and a human-legible ISO 8601 `last_edited_at` derived from
  it.

### R2 — Missing or malformed timestamps degrade gracefully

When an artifact whose vector metadata has no `last_edited_ulid`, or a value that is not a
parseable ULID, appears in `search_artifacts` results, the entry's fields are set as below and no
error is raised to the caller:

| `last_edited_ulid` in vector metadata | `last_edited_ulid` in the entry | `last_edited_at` in the entry | Also |
|---|---|---|---|
| Absent | `null` | `null` | — |
| Present but not a parseable ULID | The raw value, unchanged | `null` | A warning is logged (matching `propose_commit_links` behaviour) |

## 3. Rules — Ranking

### R3 — Result ordering is unchanged

When `search_artifacts` returns results, the existing result ordering is preserved unchanged —
pure semantic score; no recency weighting is applied. This feature is transparency only.

## 4. Boundaries

**Always:**
- Reuse the existing ULID→ISO 8601 derivation already used by `propose_commit_links` / `resources.py` — do not invent a new parsing scheme.
- Keep result ordering identical to today (pure semantic score); this feature is transparency only.
- Match the existing `read_artifact` / `list_artifacts` convention for the raw `last_edited_ulid` field (`meta.get(...) or None`).

**Ask First:**
- Whether to extract a shared ULID→ISO helper (would also touch `propose_commit_links.py` and `resources.py`) versus deriving inline in `search.py`. Confirm with the PM before touching files beyond `search.py` and its tests. This decision does not block starting from the inline approach.

**Never:**
- Never add recency-weighted ranking, decay, or age penalties — that is Option B (backlog B-6) and requires an ADR first.
- Never change the `synthesise_artifacts` response shape (out of scope; it already returns full content).
- Never add a new config variable, change vector metadata, or trigger any re-index — `last_edited_ulid` is already stored on every vector.

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/tools/search.py` | Modify | In the Step 6 result-builder loop (~L154), add `last_edited_ulid` (raw, `meta.get("last_edited_ulid") or None`) and derived `last_edited_at` (ISO 8601 or `null`) to each appended entry. Primary change. |
| `tests/unit/test_tools_search.py` | Modify | Add unit tests for R1 and R2 (US-1 and US-2) (see Testing Approach). |
| `src/arkeology/resources.py` | Modify (doc) | *Uncertain / defer to Tech Writer.* The `last_edited_ulid` system-generated field table (~L88) may warrant a note that `search_artifacts` now returns it plus a derived `last_edited_at`. Flag rather than assume. |

Derivation reference (do not copy verbatim — reuse or extract): `propose_commit_links.py` converts a ULID to ISO via `ULID.from_str(ulid_str).datetime.isoformat()` and sets `None` on `ValueError`; `_derive_last_modified` in `resources.py` is the annotation-side equivalent.

### Contracts

None.

### Testing Approach

Project convention is **TDD** — write each test and see it fail before implementing.

1. **`tests/unit/test_tools_search.py` (write first):**
   - `last_edited_at` and raw `last_edited_ulid` present and correct when an artifact is written then found by search (asserts the ISO string matches the ULID's timestamp) — gates R1 (US-1).
   - Metadata missing `last_edited_ulid` → both fields `null`; result still returned — gates R2 (US-2).
   - Metadata with a non-ULID `last_edited_ulid` → `last_edited_at` is `null`, raw value returned unchanged, warning logged — gates R2 (US-2).
   - Ordering-unchanged regression: a result set's order is identical with and without the new fields (recency does not reorder) — gates the ranking-invariance requirement (R3).
2. **Implement** the `search.py` result-builder change only after the above fail for the right reason.
3. Run the full unit suite + `ruff` + `ruff format --check` + `mypy` per the project quality gates before handoff.
