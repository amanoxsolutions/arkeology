---
type: feature-spec
feature: p5-t22-synthesis-freshness-check
created: 2026-05-31
status: ready
phase: 5
task: 22
---

# T22 — Synthesis Freshness Check Tool

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Synthesis artifacts consolidate findings from multiple source artifacts into a single
summary. Over time, source artifacts evolve: an implementation note may be rewritten
after a refactor, or an ADR may be archived when a decision is reversed. A synthesis
that was accurate when written becomes stale or misleading without any visible signal.
There is currently no way to identify which synthesis artifacts are out-of-date or
reference archived sources — an agent reading a synthesis has no signal that it no longer
reflects current knowledge. A third class of problem also exists: synthesis artifacts
written without any `source_artifacts` are structurally malformed — a synthesis that
references nothing cannot be traced and should not remain in the store.

This tool provides a freshness audit that (1) identifies stale and archived-source
syntheses for operator review, and (2) hard-deletes any malformed (empty-source)
syntheses when called with `confirm=True`.

## User Stories

### Story 1 — Stale syntheses identified by date comparison (P1)

A synthesis artifact was written six months ago. Since then, two of its source
implementation notes have been rewritten (their `date` field updated). The operator
calls `check_synthesis_freshness` and the synthesis appears in the `stale` list with
the two updated sources identified.

**Acceptance criteria:**
- Given a synthesis with `date: "2026-01-01"` that references a source with
  `date: "2026-03-15"`, when `check_synthesis_freshness` is called, then the synthesis
  appears in `stale` with the source listed under `stale_sources`.
- Given a synthesis with `date: "2026-06-01"` that references a source with
  `date: "2026-03-15"`, when `check_synthesis_freshness` is called, then the synthesis
  does not appear in `stale`.
- Given a synthesis with multiple sources, some newer and some older than the synthesis,
  when `check_synthesis_freshness` is called, then only the newer sources appear in
  `stale_sources`.

### Story 2 — Syntheses referencing archived sources are flagged (P1)

A synthesis references a source ADR that has since been archived (superseded by a newer
decision). The synthesis is still active but references outdated content.

**Acceptance criteria:**
- Given a synthesis that references a source with `status: "inactive"`, when
  `check_synthesis_freshness` is called, then the synthesis appears in `archived_sources`
  with the archived source listed.
- Given a synthesis that references a source with `status: "active"`, when
  `check_synthesis_freshness` is called, then that source does not appear in
  `archived_sources`.

### Story 3 — Missing sources are flagged (P1)

A synthesis references a source that no longer has any vector index entries — it was
hard-deleted from both S3 and the vector index.

**Acceptance criteria:**
- Given a synthesis that references an `artifact_id` that returns no results from
  `list_vectors_by_metadata`, when `check_synthesis_freshness` is called, then that
  source appears in `missing_sources` for that synthesis.

### Story 4 — All-fresh report returns clean summary (P1)

**Acceptance criteria:**
- Given all synthesis artifacts reference only active, non-stale sources, when
  `check_synthesis_freshness` is called, then `stale` and `archived_sources` and
  `missing_sources` are all empty and `all_fresh` is `true`.
- Given no synthesis artifacts exist in own scope, when `check_synthesis_freshness`
  is called, then `total_checked` is 0, `all_fresh` is `true`, and no error is returned.

### Story 5 — Malformed syntheses are reported and deleted (P1)

A synthesis artifact exists with an empty `source_artifacts` list — it was written
without any sources, making it untraceable and useless for knowledge lineage. The
operator calls `check_synthesis_freshness(confirm=True)` and the malformed synthesis is
deleted and reported in the response.

**Acceptance criteria:**
- Given a synthesis with an empty `source_artifacts` field, when
  `check_synthesis_freshness` is called (with or without `confirm`), then the synthesis
  appears in `malformed` in the response.
- Given a synthesis with an empty `source_artifacts` field, when
  `check_synthesis_freshness(confirm=True)` is called, then the synthesis is hard-deleted
  from S3 and the vector index, and appears in `deleted_malformed` in the response.
- Given a synthesis with an empty `source_artifacts` field, when
  `check_synthesis_freshness` is called without `confirm=True`, then the synthesis
  appears in `malformed` but is NOT deleted.
- Given no malformed syntheses exist, when `check_synthesis_freshness` is called, then
  `malformed` is an empty list and `deleted_malformed` is an empty list.

## Requirements

- WHEN `check_synthesis_freshness` is called THE SYSTEM SHALL scan all active `synthesis`
  type artifacts in own scope (`WRITE_PREFIX`) via the vector index.
- WHEN comparing dates THE SYSTEM SHALL compare the `date` field of each source artifact
  against the synthesis artifact's `date` field using ISO-8601 string comparison; a
  source is stale if `source.date > synthesis.date`.
- WHEN a source artifact has `status: "inactive"` in vector metadata THE SYSTEM SHALL
  report it as an archived source for that synthesis.
- WHEN a source artifact ID returns no results from `list_vectors_by_metadata` THE SYSTEM
  SHALL report it as a missing source for that synthesis.
- WHEN a synthesis has no entries in its `source_artifacts` metadata field THE SYSTEM
  SHALL include it in `malformed` in the response regardless of `confirm`.
- WHEN `confirm=True` AND a synthesis has an empty `source_artifacts` field THE SYSTEM
  SHALL hard-delete it (vectors first, then S3 object) following the same ordering as
  `delete_artifact`, and include it in `deleted_malformed` in the response.
- WHEN `confirm` is `False` or absent AND a malformed synthesis is found THE SYSTEM
  SHALL report it in `malformed` but NOT delete it.
- THE SYSTEM SHALL NOT fetch S3 content for freshness checks — all freshness data comes
  from the vector index; S3 reads are only used during malformed-synthesis deletion to
  confirm existence before deleting (via `head_object`).
- THE SYSTEM SHALL deduplicate synthesis artifacts by `artifact_id` before checking
  sources — multiple section vectors share the same artifact_id.
- THE SYSTEM SHALL deduplicate all unique source artifact IDs across all syntheses and
  fetch their metadata once each — do not issue redundant queries per synthesis.
- WHEN `check_synthesis_freshness` is called THE SYSTEM SHALL return `stale` (list),
  `archived_sources` (list), `missing_sources` (list), `malformed` (list),
  `deleted_malformed` (list), `total_checked` (int), and `all_fresh` (bool).
- `all_fresh` SHALL be `True` iff `stale`, `archived_sources`, `missing_sources`, and
  `malformed` are all empty.
- WHEN any unexpected exception occurs THE SYSTEM SHALL return
  `{"error": "internal_error", "message": str(exc)}`.

## Boundaries

**Always:**
- Scoped to own-scope synthesis artifacts only — only syntheses whose `artifact_id`
  starts with `write_prefix + "/"` are checked and deleted.
- Source artifact metadata lookups use the full vector index (not scoped) — a source
  artifact may be from a foreign scope that was shared and is legitimately in the index.
- ISO-8601 date comparison is a string comparison (`"2026-06-01" > "2026-01-01"`) — this
  is correct and safe for the `YYYY-MM-DD` format used throughout the system.
- Follow the `public_fn / _inner` delegation pattern: `check_synthesis_freshness`
  delegates to `_check_synthesis_freshness_inner` wrapped in `try/except Exception`.
- Malformed-synthesis deletion follows the same ordering as `delete_artifact`: vectors
  first (`delete_vectors`), then S3 object (`delete_object`). A partial delete (vectors
  gone, S3 delete failed) leaves a recoverable S3 orphan — report in `failed` and
  continue processing remaining artifacts.
- `bedrock` is accepted as a parameter for interface consistency but is always unused —
  mark with `_ = bedrock`.
- `s3` is used only during malformed-synthesis deletion — pass it through; do not mark
  it as unused.

**Ask First:**
- Nothing — all outcomes are defined.

**Never:**
- Do not fetch S3 object content for freshness checks — content is never needed for date
  or status comparisons.
- Do not delete or modify synthesis artifacts during a freshness check unless
  `confirm=True`.
- Do not delete foreign-scope synthesis artifacts — malformed deletion is scoped to
  `write_prefix` only.
- Do not issue one `list_vectors_by_metadata` call per source per synthesis — collect
  all distinct source IDs first, then look up each unique ID once.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_freshness.py` | Create | Written first (Red) — all unit tests against fakes |
| `src/cairn_mcp/tools/freshness.py` | Create | Written after unit tests pass (Green); accepts `confirm: bool = False` |
| `tests/integration/test_tools_freshness.py` | Create | Written after unit tests (Red for integration), implemented by the same tool |
| `src/cairn_mcp/server.py` | Modify | Import and register `check_synthesis_freshness(confirm=False)` inside `register_tools()` |

## Testing Approach

**TDD cycle:** write `test_tools_freshness.py` first (Red) → implement `freshness.py`
(Green) → write integration test (Red) → integration passes (Green).

---

**`tests/unit/test_tools_freshness.py` — unit tests (fakes only, no AWS):**

Empty state:
- No synthesis artifacts in fake → `total_checked` is 0, `all_fresh` is `True`,
  `stale`, `archived_sources`, `missing_sources` all empty.

All-fresh state:
- One synthesis, two sources both older than synthesis, both active → `all_fresh` is
  `True`, `stale` is empty, `archived_sources` is empty.

Stale detection:
- One synthesis (`date: "2026-01-01"`), one source (`date: "2026-06-01"`) → synthesis
  appears in `stale`, source listed in `stale_sources`.
- One synthesis, two sources — one newer, one older → only the newer source appears in
  `stale_sources`.
- Synthesis date equals source date (same-day) → NOT reported as stale (boundary: only
  strictly greater `source.date > synthesis.date`).

Archived source detection:
- One synthesis referencing one source with `status: "inactive"` → synthesis appears in
  `archived_sources`.
- Same source is both newer and archived → appears in both `stale` (under that
  synthesis) AND `archived_sources` (under that synthesis).

Missing source detection:
- One synthesis whose source ID has no vector index entries → source appears in
  `missing_sources` for that synthesis.

Deduplication:
- Two section vectors for the same synthesis artifact_id → counted as one synthesis,
  not two.
- Same source artifact referenced by two different syntheses → source lookup called once
  (not twice) — verify via fake call count.

Scope gate:
- Fake contains two synthesis vectors: one in own scope, one in a foreign scope prefix →
  only own-scope synthesis is checked; `total_checked` is 1.

Response structure:
- All seven fields present in every non-error response: `stale`, `archived_sources`,
  `missing_sources`, `malformed`, `deleted_malformed`, `total_checked`, `all_fresh`.
- `all_fresh` is `True` iff `stale`, `archived_sources`, `missing_sources`, and
  `malformed` are all empty.

Error handling:
- Unexpected exception from `vectors.list_vectors_by_metadata` → returns
  `{"error": "internal_error", "message": ...}`.

Malformed synthesis — report only (no confirm):
- One synthesis with empty `source_artifacts` field, `confirm=False` (default) → appears
  in `malformed`, NOT in `deleted_malformed`, artifact still exists in fake S3 and
  vector index after the call.
- `all_fresh` is `False` when `malformed` is non-empty (even with no stale/archived).

Malformed synthesis — deletion (confirm=True):
- One synthesis with empty `source_artifacts` field, `confirm=True` → appears in
  `deleted_malformed`, NOT in `malformed`; artifact is removed from both fake S3 and
  fake vector index after the call.
- Two syntheses: one malformed, one valid with a stale source — both issues reported
  in same response; malformed one deleted (confirm=True), valid one reported in `stale`
  but not deleted.
- Malformed synthesis deletion follows vectors-first ordering: verify fake receives
  `delete_vectors` call before `delete_object` call.

---

**`tests/integration/test_tools_freshness.py` — integration tests (real AWS):**

All tests decorated `@pytest.mark.integration`. Teardown must call `delete_artifact`
with `confirm=True` for every artifact written during the test run (including any that
the tool itself deletes — teardown must be idempotent on missing artifacts).

- Write a source artifact, write a synthesis referencing it with an older date → source
  appears in `stale_sources` of the synthesis entry.
- Write a source artifact, archive it, write a synthesis referencing it → source appears
  in `archived_sources`.
- Write a synthesis with a source ID that does not exist → source appears in
  `missing_sources`.
- Write a synthesis whose sources are all fresh and active → `all_fresh` is `True` for
  that synthesis.
- Write a synthesis with empty `source_artifacts`, call without `confirm` → appears in
  `malformed`, artifact still present in index.
- Write a synthesis with empty `source_artifacts`, call with `confirm=True` → appears in
  `deleted_malformed`, artifact no longer retrievable.

## Open Questions

*(none — empty-source deletion resolved: hard-delete with confirm=True, report without confirm)*
