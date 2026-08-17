---
type: spec
title: T59 — Remove the references= Filter Parameter from list_artifacts
description: Remove the references= server-side filter parameter from list_artifacts outright, rather than silently returning empty results, now that T58 has removed references from S3 Vectors metadata and the filter can no longer match anything. commit_refs= filtering is unaffected.
tags: []
timestamp: 2026-08-17T00:00:00Z
okf_version: "0.1"
feature: p12-t59-remove-references-filter-param
status: ready
phase: 12
task: 59
references:
  - docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
  - docs/specs/p12-t58-commit-refs-cap-references-removal.md
  - docs/specs/p12-t46-references-field.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-08-17"
---

# T59 — Remove the `references=` Filter Parameter from `list_artifacts`

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

T58 removed `references` from S3 Vectors metadata, so `list_artifacts`'s existing `references=[...]` server-side `$eq` filter parameter can no longer match anything — it would silently degrade into a filter that always returns zero matching artifacts, which is worse than not offering it at all. This task removes the `references=` parameter from `list_artifacts` outright (raising a clear signal to any caller still passing it) rather than leaving it present-but-inert. `commit_refs=[...]` filtering is unaffected — `commit_refs` stays in vector metadata (capped, per T58) and its filter continues to work exactly as today. (ADR D2 / OQ6.)

**Correction to source documents (found during spec-writing, flagged for the PM):** the ADR text and `plan.md`'s T59 line both describe this task as removing a `references=` filter from **both** `list_artifacts` *and* `search_artifacts`. A direct read of the current codebase (`src/arkeology/tools/search.py`, `src/arkeology/server.py`) shows `search_artifacts` has never accepted a `references` parameter — only `list_artifacts` (`src/arkeology/tools/list.py`) does. This spec is written against the actual code: it removes the parameter from `list_artifacts` only. There is nothing to remove from `search_artifacts`.

## Problem Statement

`list_artifacts`'s Step 1 filter-building adds one `{"references": {"$eq": ref}}` clause per identifier supplied in the `references=[...]` parameter. Once T58 ships, no vector ever carries a `references` key, so this clause always evaluates to zero matches for any non-empty `references` filter — a caller who supplies `references=["some-id"]` would silently get `{"artifacts": []}` regardless of whether any artifact actually references `"some-id"` (which is now only knowable via the artifact's S3 annotation, not the vector index). A parameter that can never match anything and gives no error is a worse contract than removing it: it looks like a legitimate empty-result query, not a capability that no longer exists.

## User Stories

### Story 1 — `references=` parameter no longer accepted (P1)

**Acceptance criteria:**
- Given `list_artifacts` is called with a `references=[...]` argument, when the call runs then it is rejected as an unexpected keyword argument at the MCP tool-signature level (the parameter no longer exists on `list_artifacts`/`_list_artifacts_inner`) — not silently ignored, and not returning an empty result set as if it had matched nothing.
- Given `list_artifacts` is called without any `references` argument, when the call runs then it behaves exactly as before this task — no other filter, no response shape, is affected.

### Story 2 — `commit_refs=` filtering continues to work unchanged (P1)

**Acceptance criteria:**
- Given `list_artifacts` is called with `commit_refs=["<sha>"]`, when the call runs then it returns exactly the artifacts whose (capped, per T58) vector-metadata `commit_refs` contains that SHA — identical behaviour to before this task.
- Given the existing `commit_refs=[...]` filter test suite, when this task lands then every existing `commit_refs` test continues to pass unmodified.

## Requirements

- WHEN `list_artifacts` (the MCP-registered tool in `server.py`) and `_list_artifacts_inner` (`list.py`) are defined THE SYSTEM SHALL NOT accept a `references` parameter — remove it from both signatures.
- WHEN `list.py`'s Step 1 filter-building runs THE SYSTEM SHALL NOT build a `{"references": {"$eq": ref}}` clause under any circumstance — remove the `if references: ...` block entirely.
- WHEN `list_artifacts`'s docstring (in both `list.py` and the `server.py` tool wrapper) is updated THE SYSTEM SHALL no longer document a `references` filter parameter, and SHALL continue to document `commit_refs` exactly as today.
- WHEN an artifact's returned `references` field is populated in each `list_artifacts` entry THE SYSTEM SHALL continue to source it from `read_current_link_fields` (the annotation-backed union helper) exactly as today — this task removes only the filter *parameter*, never the returned field. (`list.py` already sources the per-entry `references` value this way, not from vector metadata directly — no change needed there.)

## Boundaries

**Always:**
- This is a breaking API change, shipped and documented as such (see Consequences in the ADR) — not silently absorbed or degraded.
- `commit_refs=[...]` filtering is completely unaffected — do not touch its filter-clause construction, its docstring, or its tests as part of this task.
- The returned `references` field on each `list_artifacts` entry is unaffected — only the input filter parameter is removed.

**Ask First:**
- Nothing — the removal itself is locked (ADR D2/OQ6). The ADR/plan.md's mention of `search_artifacts` is addressed above as a documentation correction, not an open question requiring a decision — there is no `references` parameter on `search_artifacts` to remove.

**Never:**
- Do not leave `references=` accepted-but-silently-ignored (e.g. accept the parameter, log a warning, return unfiltered results) — that reintroduces exactly the "looks like a legitimate query, isn't" problem this task exists to close. Remove the parameter outright.
- Do not touch `search_artifacts` — it has no `references` parameter today; there is nothing to remove.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_list.py` | Modify | Remove/replace any test asserting `references=[...]` filtering behaviour with a test asserting the parameter is rejected (`TypeError` at the Python call level, or the FastMCP-level equivalent for the registered tool); add/keep a `commit_refs=[...]` regression test proving it is unaffected — Red first |
| `src/arkeology/tools/list.py` | Modify | Remove the `references` parameter from `list_artifacts`/`_list_artifacts_inner` signatures and the Step 1 `{"references": {"$eq": ref}}` clause-building block; update docstrings |
| `src/arkeology/server.py` | Modify | Remove the `references` parameter from the `list_artifacts` tool-registration wrapper (signature, docstring, and the call into `_list_artifacts`) |
| `docs/planning-artifacts/prd.md` | Not touched by this task | AC-57 (`list_artifacts` `references` filter) becomes stale once this ships — flagged in this spec's parent task's PM report as a documentation follow-up, not fixed here (PRD is out of scope for this spec-writing pass) |

## Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_tools_list.py` → `list.py` / `server.py`** — calling `list_artifacts(references=[...])` raises a `TypeError` (unexpected keyword argument) rather than returning any result; a call with no `references` argument and no other change in behaviour; `commit_refs=[...]` filter test(s) continue to pass unchanged, proving no cross-contamination between the two fields' handling.

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures.

## Open Questions

- **PRD staleness (flagged, not resolved here).** AC-57 currently describes `list_artifacts`'s `references` filter as a supported capability. This spec does not edit `prd.md` (out of scope per this spec-writing task's instructions — spec files only). Flagged to the PM as a documentation follow-up once T57–T62 are dispatched: AC-57 needs either removal or a superseded-note, consistent with how AC-38/AC-39/AC-50 were annotated `*Superseded — ...*` when `link_commit` was retired.
