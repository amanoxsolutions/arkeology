---
type: code_review
title: Review Fix 18 — Minor Tool Improvements
description: Code review spec for eight tool layer issues — unnecessary orphan cleanup call on new tier-3 writes, duplicated throttle retry logic, silent top_k clamping, missing source_artifacts in list response, variable shadows, and cosmetic comment gaps.
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
# Review Fix 18 — Minor Tool Improvements

## Problem Statement

Eight small issues in the tool layer reduce correctness, consistency, and readability:
an unnecessary `list_vectors_by_metadata` call fires on every new tier-3 write; throttle
retry logic is duplicated across two embed branches; `top_k` clamping is silent; the
`list_artifacts` response omits `source_artifacts`; a variable shadow in `reconcile.py`
obscures intent; two cosmetic comment gaps in `freshness.py` mislead readers; and a
shadowed variable name in `search.py` reduces clarity.

## User Stories

### Story 1 — New tier-3 artifact skips orphan cleanup (P2)

**Acceptance criteria:**
- Given a tier-3 artifact with a brand-new key (no prior `head_object` hit), when
  `write_artifact` is called, then `list_vectors_by_metadata` is NOT called during the
  orphan cleanup step.
- Given a tier-3 artifact that already existed (prior `head_object` hit), when
  `write_artifact` is called, then `list_vectors_by_metadata` IS called to clean up
  orphan vectors.

### Story 2 — Clamped `top_k` is surfaced to callers (P2)

**Acceptance criteria:**
- Given `top_k=200` is passed to `search_artifacts` (limit 100), when the response is
  returned, then `"clamped": true` and `"effective_top_k": 100` appear in the response.
- Given `top_k=50` is passed (within limit), when the response is returned, then
  `"clamped"` is absent or `false`.

### Story 3 — `list_artifacts` returns `source_artifacts` (P2)

**Acceptance criteria:**
- Given an artifact with `source_artifacts=["adr-2026-my-adr"]`, when `list_artifacts`
  is called, then each result dict includes a `source_artifacts` field.

## Requirements

- WHEN `write_artifact` writes a brand-new tier-3 artifact THE SYSTEM SHALL skip the
  orphan cleanup `list_vectors_by_metadata` call.
- WHEN `write_artifact` rewrites an existing tier-3 artifact THE SYSTEM SHALL still call
  `list_vectors_by_metadata` to clean up orphan vectors.
- WHEN `search_artifacts` or `synthesise_artifacts` clamps `top_k` THE SYSTEM SHALL
  include `"clamped": true` and `"effective_top_k": <clamped_value>` in the response.
- WHEN `list_artifacts` returns results THE SYSTEM SHALL include `source_artifacts` in
  each result dict, matching the field already present in `search_artifacts` results.
- WHEN throttle retry logic is needed during embedding THE SYSTEM SHALL use a shared
  `_embed_with_retry(bedrock, text, model, dims)` helper (no duplication).

## Boundaries

**Always:**
- M13 optimization must not change behaviour for re-writes — orphan cleanup must still
  run when the artifact previously existed.
- `all_fresh=True` semantics in `freshness.py` are unchanged — `True` after deletion
  means "no remaining issues", not "nothing was deleted".
- Rename `data` shadow in `search.py` must not alter the runtime value or type.

**Never:**
- Change the `all_fresh` definition or `confirm=True` semantics in `freshness.py`.
- Alter the shape of the `search_artifacts` or `synthesise_artifacts` response beyond
  adding the `clamped` / `effective_top_k` fields.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_write.py` | Modify | Add tests asserting skip/run of orphan cleanup based on `is_new_artifact` (Red before M13 change) |
| `tests/unit/test_tools_search.py` | Modify | Add test for `clamped: true` field in response (Red before m18 change) |
| `tests/unit/test_tools_list.py` | Modify | Add test asserting `source_artifacts` in result dict (Red before m19 change) |
| `tests/unit/test_tools_synthesise.py` | Modify | Add test for `clamped: true` field in response (Red before m18 change) |
| `src/cairn_mcp/tools/write.py` | Modify | M13: pass `is_new_artifact` flag; m17: extract `_embed_with_retry` helper |
| `src/cairn_mcp/tools/search.py` | Modify | m18: add `clamped`/`effective_top_k` to response; m25: rename shadowed `data` variable |
| `src/cairn_mcp/tools/list.py` | Modify | m19: add `source_artifacts` to result dict |
| `src/cairn_mcp/tools/synthesise.py` | Modify | m18: add `clamped`/`effective_top_k` to response |
| `src/cairn_mcp/tools/reconcile.py` | Modify | m20: rename `line` → `raw_line` / `entry_line` to remove shadow |
| `src/cairn_mcp/tools/freshness.py` | Modify | m21, m22: add inline comments only — no logic change |

## Testing Approach

**TDD cycle:** write failing tests first → implement → confirm `ruff` and `mypy` clean.

**`tests/unit/test_tools_write.py` additions (before `write.py` M13 change):**
- New artifact (fake `head_object` returns 404): assert `list_vectors_by_metadata` call
  count is 0 after write.
- Existing artifact (fake `head_object` returns metadata): assert
  `list_vectors_by_metadata` is called once during orphan cleanup.

**`tests/unit/test_tools_search.py` additions (before `search.py` m18 change):**
- `top_k=200` → response contains `"clamped": True`, `"effective_top_k": 100`.
- `top_k=10` → response does not contain `"clamped": True`.

**`tests/unit/test_tools_synthesise.py` additions:**
- Same clamping assertions as `search.py` above.

**`tests/unit/test_tools_list.py` additions (before `list.py` m19 change):**
- Artifact with `source_artifacts="adr-2026-x"` → result dict key `"source_artifacts"`
  is present and matches.
- Artifact with no source artifacts → `"source_artifacts"` present and empty.

**`reconcile.py` and `freshness.py` changes:** no new tests — confirm existing
`test_tools_reconcile.py` and `test_tools_freshness.py` pass after rename/comments.

## Open Questions

*(none — all behaviour is defined)*
