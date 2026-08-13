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
  by: "developer"
  date: "2026-08-12"
---
# Review Fix 18 — Minor Tool Improvements

## Verification — 2026-08-12

Re-verified finding-by-finding against current `main`. All eight items were fixed the
same day this spec was authored, by `f642725` (2026-05-31, "production hardening — 20
review-fix specs"). One item (the duplicated throttle-retry logic) later moved to a
different, more consolidated location under unrelated work — see its inline marker.

- **Resolved:** 8 of 8 — orphan-cleanup skip on new tier-3 writes, throttle-retry
  dedup, `top_k` clamping surfaced, `source_artifacts` in `list_artifacts`, the
  `reconcile.py` variable shadow, both `freshness.py` comment gaps, and the `search.py`
  variable shadow.
- **Still valid / no longer applicable:** none.

See inline `[Verified 2026-08-12 — …]` markers below and the "Items Resolved Since Last
Review" section at the end.

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
  **[Verified 2026-08-12 — ✅ RESOLVED (both bullets).** `write.py`'s orphan-cleanup
  step is gated `if is_existing:` before the `list_vectors_by_metadata` call — a
  brand-new artifact skips it entirely, an existing one still runs it. Fixed by
  `f642725`, deliberate.]
- WHEN `search_artifacts` or `synthesise_artifacts` clamps `top_k` THE SYSTEM SHALL
  include `"clamped": true` and `"effective_top_k": <clamped_value>` in the response.
  **[Verified 2026-08-12 — ✅ RESOLVED.** Both `search.py` and `synthesise.py` compute
  `effective_top_k = min(requested_top_k, 100)` / `clamped = effective_top_k <
  requested_top_k` and add `response["clamped"] = True` /
  `response["effective_top_k"]` when clamped. Fixed by `f642725`, deliberate.]
- WHEN `list_artifacts` returns results THE SYSTEM SHALL include `source_artifacts` in
  each result dict, matching the field already present in `search_artifacts` results.
  **[Verified 2026-08-12 — ✅ RESOLVED.** `list.py` computes
  `source_artifacts_val = coerce_list_field(meta, "source_artifacts")` and includes it
  in every result dict. Fixed by `f642725`, deliberate.]
- WHEN throttle retry logic is needed during embedding THE SYSTEM SHALL use a shared
  `_embed_with_retry(bedrock, text, model, dims)` helper (no duplication).
  **[Verified 2026-08-12 — ✅ RESOLVED, relocated.** No `_embed_with_retry` helper
  exists in `write.py` — instead, the retry/backoff logic moved one layer down into
  `clients/bedrock.py`'s shared `_invoke(...)` helper (used by both `embed` and the text
  model call, with a single-retry-on-transient-error policy documented on the method).
  This is a stronger fix than the spec asked for: the duplication is eliminated at the
  client boundary rather than re-created behind a tools-layer wrapper, so no tool-layer
  call site can drift out of sync with it. Fixed by `f642725`, deliberate (the
  consolidation into `clients/bedrock.py` specifically is part of the same commit, not a
  later change).]

## Boundaries

**Always:**
- M13 optimization must not change behaviour for re-writes — orphan cleanup must still
  run when the artifact previously existed.
- `all_fresh=True` semantics in `freshness.py` are unchanged — `True` after deletion
  means "no remaining issues", not "nothing was deleted".

  **[Verified 2026-08-12 — ✅ RESOLVED.** `freshness.py` carries the exact clarifying
  comment: "`all_fresh=True` means no issues remain; it does NOT mean nothing was
  deleted." (m21/m22 — both cosmetic comment gaps from the Problem Statement). Fixed by
  `f642725`, deliberate.]
- Rename `data` shadow in `search.py` must not alter the runtime value or type.

  **[Verified 2026-08-12 — ✅ RESOLVED, moot.** No `data`-named variable shadow exists
  in current `search.py` — the file was substantially rewritten by the later
  `_search_helper.py` extraction and 2026-06-29 simplification pass (shared
  `run_search_loop`), which removed the local variable this finding was about along with
  it. Original fix landed same-day via `f642725`; the file's subsequent rewrite is
  unrelated later work, not a reversion.]

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
| `src/arkeology/tools/write.py` | Modify | M13: pass `is_new_artifact` flag; m17: extract `_embed_with_retry` helper |
| `src/arkeology/tools/search.py` | Modify | m18: add `clamped`/`effective_top_k` to response; m25: rename shadowed `data` variable |
| `src/arkeology/tools/list.py` | Modify | m19: add `source_artifacts` to result dict |
| `src/arkeology/tools/synthesise.py` | Modify | m18: add `clamped`/`effective_top_k` to response |
| `src/arkeology/tools/reconcile.py` | Modify | m20: rename `line` → `raw_line` / `entry_line` to remove shadow |
| `src/arkeology/tools/freshness.py` | Modify | m21, m22: add inline comments only — no logic change |

**[Verified 2026-08-12 — ✅ RESOLVED — reconcile.py (m20).** `reconcile.py`'s
failure-log parse loop uses `for raw_line in raw_lines: entry_line = raw_line.strip();
...` — the shadow is gone. Fixed by `f642725`, deliberate.]

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

## Items Resolved Since Last Review

<!-- changelog-style: prepend new entries -->
- 2026-08-12 — **Re-verification pass (developer): all 8 items confirmed resolved.**
  This spec sat with `status: ready` and no closure note for ~2.5 months despite the
  code having matched every requirement since the day it was authored. `f642725`
  ("production hardening — 20 review-fix specs", 2026-05-31, same day as this review)
  deliberately implemented the orphan-cleanup `is_existing` guard, `top_k`
  clamping surfaced in both `search.py` and `synthesise.py`, `source_artifacts` in
  `list_artifacts`, the `reconcile.py` rename, and both `freshness.py` comment gaps. Two
  items evolved further under unrelated later work, neither a regression: the throttle-
  retry helper was consolidated one layer down into `clients/bedrock.py`'s shared
  `_invoke` (stronger than the spec's tools-layer `_embed_with_retry` ask); the
  `search.py` `data` shadow variable no longer exists because the file was rewritten by
  the later `_search_helper.py` extraction. No code was changed by this re-verification
  pass.
