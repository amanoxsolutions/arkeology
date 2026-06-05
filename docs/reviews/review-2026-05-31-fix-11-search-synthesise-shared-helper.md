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
# Review Fix 11 — Extract Shared Re-Fetch Helper for Search and Synthesise

## Problem Statement

`synthesise.py` (lines 100-172) duplicates approximately 40 lines of the re-fetch loop from
`search.py` (lines 112-217): user filter construction, scope filter construction, and the
iteration-with-deduplication loop are copy-pasted. The two copies have already diverged:
`synthesise.py` omits the `tier` filter and the `source_artifacts` field in results. A bug fix
in one copy must be manually applied to the other.

## User Stories

### Story 1 — Single source of truth for the re-fetch loop

**Acceptance criteria:**
- Given `search_artifacts` is called with any valid parameters, when it returns, then its
  results are identical to before the refactor.
- Given `synthesise_artifacts` is called with any valid parameters, when it returns, then its
  results are identical to before the refactor.
- Given a bug is fixed in the shared helper, when both tools are called, then both reflect the
  fix without any additional code change.

### Story 2 — Behavioral differences are preserved

**Acceptance criteria:**
- Given `synthesise_artifacts` is called, when the helper is invoked, then `status="active"` is
  always applied and no `tier` filter is passed.
- Given `search_artifacts` is called with a `tier` parameter, when the helper is invoked, then
  the `tier` filter is forwarded correctly.
- Given `search_artifacts` returns results, when the response is read, then `source_artifacts`
  is present in each result; `synthesise_artifacts` results do not include `source_artifacts`.

## Requirements

- WHEN `search_artifacts` is called THE SYSTEM SHALL delegate the scope-filter construction and
  deduplicating re-fetch loop to the shared helper.
- WHEN `synthesise_artifacts` is called THE SYSTEM SHALL delegate to the same shared helper,
  passing `status="active"` and no `tier` filter.
- WHEN the shared helper is called THE SYSTEM SHALL produce results identical to the previous
  per-tool implementations (no behavioral change).
- WHEN any parameter accepted by the existing tools is passed THE SYSTEM SHALL forward it
  correctly through the helper.

## Boundaries

**Always:**
- Preserve all behavioral differences: `synthesise_artifacts` always uses `status="active"`,
  omits `tier` filter, fetches full content via S3; `search_artifacts` passes caller-supplied
  `tier` and does not fetch full content.
- Keep both tools as separate MCP-registered functions — do not merge them.
- Follow the `public_fn / _inner` delegation pattern already in the codebase.

**Decision (2026-05-31):**
- Shared helper lives in `src/cairn_mcp/tools/_search_helper.py` (new private module).
  Rationale: keeps `search.py` scoped to one tool; the single-underscore prefix follows
  Python convention for private modules; no `_helper.py` precedent exists in the tools
  directory so the new file makes the shared-implementation intent explicit without
  polluting the public tool namespace.

**Never:**
- Merge `search_artifacts` and `synthesise_artifacts` into a single MCP tool.
- Change the external interface (parameter names, return shape) of either tool.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_search.py` | Modify | Add edge-case test for shared helper if new path introduced; verify existing tests still pass |
| `tests/unit/test_tools_synthesise.py` | Modify | Add edge-case test for shared helper if new path introduced; verify existing tests still pass |
| `src/cairn_mcp/tools/search.py` | Modify | Extract scope-filter + deduplicating re-fetch loop into helper; `search_artifacts` calls it |
| `src/cairn_mcp/tools/synthesise.py` | Modify | Replace copy-pasted loop with call to shared helper |
| `src/cairn_mcp/tools/_search_helper.py` | Create (if chosen) | Alternative: shared helper in its own module |

## Testing Approach

TDD: confirm all existing unit tests pass before touching implementation. Add new tests for any
edge case the helper introduces that was not covered before, then implement.

| Order | File | Purpose |
|-------|------|---------|
| 1 | `tests/unit/test_tools_search.py` | Add/verify helper edge cases (Red if new) |
| 2 | `tests/unit/test_tools_synthesise.py` | Add/verify helper edge cases (Red if new) |
| 3 | `src/cairn_mcp/tools/_search_helper.py` (or `search.py`) | Implement shared helper (Green) |
| 4 | `src/cairn_mcp/tools/search.py` | Refactor to use helper |
| 5 | `src/cairn_mcp/tools/synthesise.py` | Replace duplicate loop with helper call |

All existing unit tests must remain green after every step.

## Open Questions

- **Shared helper location — RESOLVED (2026-05-31):** Use `_search_helper.py` (new
  private module). See the decision note in Boundaries above.
