---
status: ready
references: []
authored:
  by: "developer"
  date: "2026-05-31"
revised:
  by: ""
  date: ""
---
# Review Fix 10 — List Tool Scope Filter (M11)

## Problem Statement

`list_artifacts` in `list.py` builds a metadata filter for type/team/project/tier/status/tags
but does NOT include a scope clause. The vector query returns results from all scopes; the
cross-scope gate runs in Python afterwards. In multi-scope deployments or stores with many
artifacts, this fetches far more data from S3 Vectors than necessary, wasting API quota and
increasing latency.

## User Stories

### Story 1 — Vector query includes scope filter (P1)

**Acceptance criteria:**
- Given a `list_artifacts` call from scope `"team-a"`, when the vector query is issued, then the
  filter passed to `list_vectors_by_metadata` includes a scope clause that excludes vectors from
  unrelated scopes.
- Given the same call, the cross-scope Python gate at lines 140-147 still runs as
  defence-in-depth after the query returns.

### Story 2 — Scope filter logic is identical to search.py (P1)

**Acceptance criteria:**
- Given `list_artifacts` and `search_artifacts` are both called from the same scope, when both
  issue their vector queries, then both use the same scope filter structure (`$or` of own-scope
  unrestricted + foreign scopes tier-3 + shared only).

## Requirements

- WHEN `list_artifacts` queries the vector index THE SYSTEM SHALL include a scope `$or` filter
  in the clauses list passed to `list_vectors_by_metadata`.
- WHEN the scope filter is constructed THE SYSTEM SHALL use the same logic as `search.py` — own
  scope unrestricted, foreign scopes restricted to tier-3 + shared visibility.
- WHEN the scope filter is applied THE SYSTEM SHALL still apply the Python cross-scope gate
  (lines 140-147) as a correctness safety net.

## Boundaries

**Always:**
- Scope filter logic must be identical to `search.py` — do not invent a new scheme or diverge.
- The existing Python-side cross-scope gate stays in place as defence-in-depth.
- If `search.py` defines the scope filter in a helper, extract it to a shared location and
  import it from both `list.py` and `search.py` rather than duplicating it.

**Ask First:**
- Nothing — all outcomes are defined.

**Never:**
- Remove the existing Python-side cross-scope gate (lines 140-147).
- Build a different scope filter scheme than the one already used in `search.py`.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_list.py` | Modify | Add test asserting scope clause in vector query (written first — Red) |
| `src/cairn_mcp/tools/list.py` | Modify | Add scope `$or` filter to `clauses` before calling `list_vectors_by_metadata` |
| `src/cairn_mcp/tools/search.py` | Modify (maybe) | Extract scope filter to shared helper if duplication arises |
| `src/cairn_mcp/clients/filter.py` | Modify (maybe) | Candidate location for shared scope filter builder |

## Testing Approach

**TDD cycle:** update `test_tools_list.py` first (Red) → implement scope filter in `list.py` (Green).

**`tests/unit/test_tools_list.py` — new tests:**
- `test_list_vectors_called_with_scope_filter` — call `list_artifacts` with a known scope;
  inspect `fake_vectors.list_vectors_by_metadata_calls[-1]`; assert the filter argument
  contains a scope-related clause (e.g. a key matching `"scope"` or `"$or"` with scope conditions).
- `test_cross_scope_gate_still_applied` — seed the fake vector store with a foreign-scope
  vector that passes the scope filter; confirm the Python gate removes it from the final result.
- Existing `list_artifacts` unit tests must continue to pass unchanged.

## Open Questions

*(none — all behaviour is defined)*
