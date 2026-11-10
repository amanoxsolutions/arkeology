---
type: Spec
id: p5-t22-synthesis-freshness-check
title: T22 — Synthesis Freshness Check Tool
description: Adds a check_synthesis_freshness MCP tool that audits synthesis artifacts for staleness, archived sources, missing sources, and malformed empty-source syntheses, enabling operators to identify and clean outdated knowledge summaries.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-31T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T12:05:23Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T22 — Synthesis Freshness Check Tool

## TL;DR

`check_synthesis_freshness` audits the own-scope synthesis artifacts and reports those whose
sources were written after them (stale), have been archived, or are missing, so operators can
identify and clean outdated knowledge summaries. Syntheses written without any `source_artifacts`
are malformed: they are always reported, and hard-deleted only when the tool is called with
`confirm=True`.

## 1. Problem Statement

Synthesis artifacts consolidate findings from multiple source artifacts into a single summary. Over
time, source artifacts evolve: an implementation note may be rewritten after a refactor, or an ADR
may be archived when a decision is reversed. A synthesis that was accurate when written becomes
stale or misleading without any visible signal. There is currently no way to identify which
synthesis artifacts are out-of-date or reference archived sources — an agent reading a synthesis
has no signal that it no longer reflects current knowledge. A third class of problem also exists:
synthesis artifacts written without any `source_artifacts` are structurally malformed — a synthesis
that references nothing cannot be traced and should not remain in the store.

This tool provides a freshness audit that (1) identifies stale and archived-source syntheses for
operator review, and (2) hard-deletes any malformed (empty-source) syntheses when called with
`confirm=True`. The five stories — stale syntheses identified, syntheses referencing archived
sources flagged, missing sources flagged, an all-fresh report returning a clean summary, and
malformed syntheses reported and deleted — are all P1.

## 2. Rules — What is checked

### R1 — Only active own-scope syntheses are scanned, via the vector index

When `check_synthesis_freshness` is called, the system scans all active `synthesis` type artifacts
in own scope (`WRITE_PREFIX`) via the vector index: only syntheses whose `artifact_id` starts with
`write_prefix + "/"` are checked and deleted.

Source: none

### R2 — Syntheses are deduplicated by `artifact_id`

The system deduplicates synthesis artifacts by `artifact_id` before checking sources — multiple
section vectors share the same `artifact_id`.

Source: none

### R3 — Each unique source is looked up once, in the full vector index

The system deduplicates all unique source artifact IDs across all syntheses and fetches their
metadata once each — it does not issue redundant queries per synthesis. Source artifact metadata
lookups use the full vector index (not scoped) — a source artifact may be from a foreign scope that
was shared and is legitimately in the index.

Source: none

### R4 — Freshness data comes from the vector index only

The system does not fetch S3 content for freshness checks — all freshness data comes from the
vector index. S3 reads are only used during malformed-synthesis deletion to confirm existence
before deleting (via `head_object`).

Source: none

## 3. Rules — Source checks

### R5 — A source is stale when it was written after the synthesis

A source is stale when it was **written** after the synthesis, judged by `last_edited_ulid` rather
than `date`. `date` is the artifact's subject date, not its write time, so comparing it missed a
source overwritten in place under an unchanged date and flagged a later-dated source written before
the synthesis. `date` remains only the fallback when either side lacks a `last_edited_ulid`. A
synthesis with a stale source appears in `stale`, with its stale sources listed under
`stale_sources`.

**Example** — the `date` fallback, where either side lacks a `last_edited_ulid`

- Given a synthesis with `date: "2026-01-01"` that references a source with `date: "2026-03-15"`,
  when `check_synthesis_freshness` is called, then the synthesis appears in `stale` with the source
  listed under `stale_sources`.
- Given a synthesis with `date: "2026-06-01"` that references a source with `date: "2026-03-15"`,
  when `check_synthesis_freshness` is called, then the synthesis does not appear in `stale`.
- Given a synthesis with multiple sources, some newer and some older than the synthesis, when
  `check_synthesis_freshness` is called, then only the newer sources appear in `stale_sources`.

Source: `docs/contracts/modules/arkeology.tools.freshness.md`, commit 151844a

### R6 — A source with `status: "inactive"` is reported as archived

A synthesis may reference a source ADR that has since been archived (superseded by a newer
decision): the synthesis is still active but references outdated content. When a source artifact
has `status: "inactive"` in vector metadata, the system reports it as an archived source for that
synthesis: the synthesis appears in `archived_sources` with the archived source listed. A source
with `status: "active"` does not appear in `archived_sources`.

Source: none

### R7 — A source with no vector index entries is reported as missing

A synthesis may reference a source that no longer has any vector index entries — it was
hard-deleted from both S3 and the vector index. When a source artifact ID returns no results from
`list_vectors_by_metadata`, the system reports it as a missing source for that synthesis: that
source appears in `missing_sources` for that synthesis.

Source: none

## 4. Rules — Malformed syntheses

### R8 — A synthesis with no `source_artifacts` is reported as malformed regardless of `confirm`

A synthesis artifact with an empty `source_artifacts` list was written without any sources, making
it untraceable and useless for knowledge lineage. When a synthesis has no entries in its
`source_artifacts` metadata field, the system includes it in `malformed` in the response regardless
of `confirm` — when `check_synthesis_freshness` is called with or without `confirm`, the synthesis
appears in `malformed`.

Source: none

### R9 — With `confirm=True`, a malformed synthesis is hard-deleted, vectors first

The operator calls `check_synthesis_freshness(confirm=True)` and the malformed synthesis is deleted
and reported in the response. When `confirm=True` and a synthesis has an empty `source_artifacts`
field, the system hard-deletes it from S3 and the vector index — vectors first, then S3 object —
following the same ordering as `delete_artifact`, and includes it in `deleted_malformed` in the
response.

Source: none

### R10 — Without `confirm=True`, a malformed synthesis is reported but not deleted

When `confirm` is `False` or absent and a malformed synthesis is found, the system reports it in
`malformed` but does NOT delete it.

Source: none

## 5. Rules — Response

### R11 — Every non-error response carries seven fields, and `all_fresh` summarises them

When `check_synthesis_freshness` is called, the system returns:

| Field | Type |
|-------|------|
| `stale` | list |
| `archived_sources` | list |
| `missing_sources` | list |
| `malformed` | list |
| `deleted_malformed` | list |
| `total_checked` | int |
| `all_fresh` | bool |

`all_fresh` is `True` iff `stale`, `archived_sources`, `missing_sources`, and `malformed` are all
empty.

| Given | When `check_synthesis_freshness` is called, then |
|-------|--------------------------------------------------|
| All synthesis artifacts reference only active, non-stale sources | `stale` and `archived_sources` and `missing_sources` are all empty and `all_fresh` is `true` |
| No synthesis artifacts exist in own scope | `total_checked` is 0, `all_fresh` is `true`, and no error is returned |
| No malformed syntheses exist | `malformed` is an empty list and `deleted_malformed` is an empty list |

Source: none

### R12 — An unexpected exception returns `internal_error`

When any unexpected exception occurs, the system returns
`{"error": "internal_error", "message": str(exc)}`.

Source: none

## 6. Boundaries

**Always:**
- Scoped to own-scope synthesis artifacts only — only syntheses whose `artifact_id`
  starts with `write_prefix + "/"` are checked and deleted.
- Source artifact metadata lookups use the full vector index (not scoped) — a source
  artifact may be from a foreign scope that was shared and is legitimately in the index.
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

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_freshness.py` | Create | Written first (Red) — all unit tests against fakes |
| `src/arkeology/tools/freshness.py` | Create | Written after unit tests pass (Green); accepts `confirm: bool = False` |
| `tests/integration/test_tools_freshness.py` | Create | Written after unit tests (Red for integration), implemented by the same tool |
| `src/arkeology/server.py` | Modify | Import and register `check_synthesis_freshness(confirm=False)` inside `register_tools()` |

### Contracts

- [`docs/contracts/modules/arkeology.tools.freshness.md`](../contracts/modules/arkeology.tools.freshness.md),
  `## Symbols` — the staleness invariant of `check_synthesis_freshness` is the normative statement
  of when a source is stale (written after the synthesis, judged by `last_edited_ulid`, with `date`
  only as the fallback).

### Testing Approach

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
- `test_source_written_before_synthesis_is_not_stale_despite_a_later_date` — a source written
  before the synthesis is not stale even though its `date` is later.

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
