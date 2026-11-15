---
type: Spec
id: p12-t62-bounded-reconcile-retry
title: T62 — Bounded reconcile_index Failure-Log Retry + Fetch-and-Reindex Dedup
description: "reconcile_index's failure-log replay (Phase 1) currently retries every entry every run, indefinitely, with no attempt count — a genuinely unfixable entry (e.g. an artifact that fails T57's own budget guard) would be replayed identically forever. Add a per-entry reconcile_attempts counter persisted in the failure log; once an entry crosses the existing CAS_MAX_ATTEMPTS = 3 precedent, stop auto-retrying it and report it once, loudly, in a new stuck_failures response field, instead of blending it into failed indistinguishably from a first-time failure. Also fixes a related gap: Phase 1 (failure-log replay) and Phase 2 (orphan scan) each independently duplicate the same get_object → _reindex_artifact → append-to-reconciled sequence — fixed by extracting one shared _fetch_and_reindex helper, since this task is already reopening Phase 1's exact loop."
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
    title: Vector Metadata Budget Hardening, Guard Coverage, and Migration Self-Heal
    last_modified: 2026-09-25T00:00:00Z
  - resource: docs/specs/p12-t57-guard-coverage.md
    title: T57 — Guard Coverage in link_metadata.py and reconcile.py + Control-Character Validation Fix
    last_modified: 2026-08-17T00:00:00Z
  - resource: src/arkeology/annotations.py
  - resource: docs/specs/p12-t67-orphan-vector-retry-and-selfheal.md
    title: T67 — Orphan-Vector Failure Logging + reconcile_index Self-Heal Repair
  - resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
generated:
  by: "axians-architect/claude-sonnet-5"
  at: 2026-08-17T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:28:28Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T62 — Bounded `reconcile_index` Failure-Log Retry + Fetch-and-Reindex Dedup

## TL;DR

`reconcile_index`'s Phase 1 (failure-log replay) retries every entry on every run, indefinitely —
there is no attempt count anywhere in the failure-log entry schema. An entry that fails identically
every time (for example, a genuinely oversize `commit_refs`/`references` payload now correctly
rejected by T57's guard) is replayed forever, appearing in `failed` on every single reconcile run
with no signal that it is stuck rather than merely unlucky this time. This spec adds a per-entry
`reconcile_attempts` counter, persisted back into the failure-log JSONL alongside the entry it
belongs to, incremented each time a replay attempt fails for a reason no retry can cure — a failure
whose error code counts toward the bound; a throttle or an annotation-store outage leaves it
unchanged. Once an entry's counter reaches the
existing `CAS_MAX_ATTEMPTS = 3` precedent (`annotations.py`, reused rather than made independently
configurable), `reconcile_index` stops attempting to re-index it and reports it in a new, distinct
`stuck_failures` response field instead of `failed` — unless a check of its artifact finds it
deleted, or indexed since by a later write, which resolves it.
(adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4.)

Folded into the same spec: Phase 1's failure-log replay loop and Phase 2's orphan-scan loop each independently do the identical `get_object` → `_reindex_artifact` → append `{"artifact_id", "title", "sections_indexed", "source"}` to `reconciled` sequence, differing only in whether `head_object` was already fetched and the `source` label (`"failure_log"` vs. `"orphan_scan"`). This task is already reopening Phase 1's exact loop to add the `reconcile_attempts` counter, so the two are extracted into one shared fetch-and-reindex helper here rather than as a separate task.

## 1. Problem Statement

Phase 1's failure-log replay reads every entry, groups the entries by `(artifact_id, kind)` — the orphan-cleanup kind when an entry carries `orphan_keys` (T67), the re-index kind otherwise — and replays each group. A group that resolves is pruned from the log; a group that fails stays in the log, to be retried on the very next run. This is correct and desirable for transient failures (a momentary Bedrock throttle, a race with a concurrent write) — but it has no concept of "this entry has failed so many times in a row that retrying it again is pointless without an operator fixing the underlying cause." Left unbounded, a genuinely unfixable entry (the exact "self-perpetuating failure-log replay" outcome `p12-t55`'s own TL;DR states must never happen) is retried — and fails — identically on every single `reconcile_index` invocation forever, with no way for a caller to distinguish "this just failed for the first time" from "this has failed 50 times in a row and needs a human." The bound therefore counts only the failures a retry cannot cure: counting a throttle the same as an unfixable payload would mark stuck, and stop retrying, an entry the next run could resolve.

Folded in: this task is already reopening Phase 1's replay loop to thread the `reconcile_attempts` counter through it, which is the natural, free place to also close the duplication between Phase 1 and Phase 2. Today, Phase 1 fetches `raw_meta` via `head_object` first (with its own `KeyError` → "S3 object not found" handling), then, in a separate `try` block, reads `content` via `get_object`, calls `_reindex_artifact`, and appends a `reconciled` entry tagged `"source": "failure_log"`. Phase 2 does the same three steps — `get_object`, then `head_object`, then `_reindex_artifact`, then an identically-shaped `reconciled` entry tagged `"source": "orphan_scan"` — inside one `try` block. The only real differences are the `source` label and which phase already has `raw_meta` in hand before the shared sequence starts; extracting one shared helper removes the duplication without changing either phase's error-handling shape.

Stories 1, 2 and 3 are P1; Story 4 is P2. Story 1 — an entry failing fewer than 3 times behaves exactly as today (R5, R6). Story 2 — an entry crossing the attempt threshold stops being retried (R2, R5, R6). Story 3 — existing callers unaffected (R7, R8). Story 4 — Phase 1 and Phase 2 share one fetch-and-reindex helper (R11, R12, R13, R14).

## 2. Rules — Bounded failure-log retry (Phase 1)

In the rules below, an *entry* is the group of failure-log entries sharing one `(artifact_id,
kind)`, where the kind is the orphan-cleanup kind when the entry carries `orphan_keys`
(`p12-t67-orphan-vector-retry-and-selfheal` R10) and the re-index kind otherwise. A group is
replayed, counted, resolved and pruned as one; its counter is the highest `reconcile_attempts` any
member carries; and an entry of one kind for an `artifact_id` never resolves or prunes the other
kind's entry for it. How a group's link values and orphan keys combine is stated in
`arkeology.tools.reconcile` § reconcile_index.

### R1 — `reconcile_attempts` defaults to `0` when absent

When a failure-log entry is parsed in Phase 1, its `reconcile_attempts` value is read, defaulting to `0` when the key is absent (backward-compatible with every entry written before this task).

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4

### R2 — An entry already at or above `CAS_MAX_ATTEMPTS` is not replayed; its artifact is checked, and it is resolved or reported in `stuck_failures`

When a unique entry's `reconcile_attempts` is already `>= CAS_MAX_ATTEMPTS` (3) before this run's replay, `reconcile_index` does **not** call `_reindex_artifact` for it — no `bedrock.embed` call, no `put_vector` call for it. It first checks the entry's artifact, as `arkeology.tools.reconcile` § reconcile_index states:

| The artifact | The entry |
|---|---|
| No longer exists | Resolved and pruned as R12 states, with the `failure_log_obsolete` source |
| Indexed by a write made after the entry's newest member was recorded | Its saved `commit_refs` and tokenless `references` first re-applied to the annotations by the union `p12-t48-reconcile-from-annotations` R8 uses, never clearing a field; then resolved and pruned, nothing re-indexed, with the `failure_log_superseded` source. When that annotation read or write fails, not pruned: added to `stuck_failures` with the failure's code as `error`, its counter unchanged, and checked again on the next run |
| Anything else | Added to `stuck_failures` instead of `failed`, its `reason` ending with the path of the failure log |

**Example**

- Given an entry stuck after three refusals of one section by the embedding model, when the
  developer lowers `EMBED_MAX_SECTION_LENGTH`, restarts the server and overwrites the artifact
  successfully, then the next `reconcile_index` run makes no embed call for the entry, prunes it,
  and reports it in `reconciled` with `source: "failure_log_superseded"`.
- Given a stuck entry recording fifteen `commit_refs` from a failed overwrite, and a later overwrite
  that indexed the artifact with an empty `commit_refs` annotation, when `reconcile_index` runs,
  then the annotation holds all fifteen before the entry is pruned. When that annotation write is
  denied, the entry stays in the log and is in `stuck_failures` with
  `error: "annotation_unavailable"`.
- Given a stuck entry whose artifact has not been written since, when `reconcile_index` runs, then
  it is in `stuck_failures` with a `reason` ending with the failure log's path, and no embed call is
  made for it.
- Given a stuck entry whose artifact has been deleted, when `reconcile_index` runs, then it is
  pruned and reported in `reconciled` with `source: "failure_log_obsolete"`.

**Why:** a stuck entry is never attempted again, so without the check the only exit would be
editing a state file whose path no response gave. A failed overwrite's re-PUT cleared the
object's annotations and the superseding write carried that empty value forward, so the entry
holds the only copy of its links; pruning it without re-applying them would lose them for good.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4, Open Questions resolution 4; arkeology.tools.reconcile; p12-t48-reconcile-from-annotations R8

### R3 — An entry below the threshold is replayed exactly as today

When a unique entry's `reconcile_attempts` is `< CAS_MAX_ATTEMPTS`, `reconcile_index` attempts `_reindex_artifact` for it exactly as today.

Source: None

### R4 — A successful replay resolves the entry exactly as today

When a replay attempt for an entry below the threshold succeeds, the entry is resolved and pruned from the log — the `reconcile_attempts` counter is irrelevant once resolved.

Source: None

### R5 — A failed replay is classified by its error code; only a counting code increments the counter, then routes by the incremented value

When a replay attempt for an entry below the threshold fails, the failure is given the error code `arkeology.tools.reconcile` § reconcile_index assigns it, which the reported entry carries as `error`. When the code is one that counts toward the bound, the entry's `reconcile_attempts` is incremented by one and the code recorded beside it (both in the entry that will be written back to the log), and THEN the entry is routed: if the incremented value is `>= CAS_MAX_ATTEMPTS`, it is added to `stuck_failures`; otherwise it is added to `failed`. When the code does not count, the counter is left as it was and the entry is added to `failed`.

**Example**

- Given an entry at `reconcile_attempts=0` whose re-index breaches a metadata budget on three consecutive runs, then it is in `failed` with `error: "validation_error"` on runs 1 and 2 (counter 1, then 2), and in `stuck_failures` with the same code on run 3 — the transition to "stuck" is visible at the exact run where the threshold is crossed, not delayed to the following run.
- Given an entry at `reconcile_attempts=0` whose re-index is throttled by Bedrock past the client's own retry on three consecutive runs, then it is in `failed` with `error: "internal_error"` on every run, its counter stays at 0, and the first run that is not throttled resolves it.
- Given an entry at `reconcile_attempts=2` whose annotation read raises `AnnotationUnavailableError`, then it is in `failed` with `error: "annotation_unavailable"` and its counter stays at 2.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4, Open Questions resolution 4

### R6 — Retained entries persist their counter; a stuck entry is never pruned

When the failure log is rewritten at the end of the run, each retained entry carries its (possibly incremented) `reconcile_attempts` value, and only the entries this run resolved are removed — an entry another writer appended while the run was in flight is kept (`arkeology.tools.reconcile` § reconcile_index).

- An entry that failed below the threshold is retained (not pruned) with its `reconcile_attempts` counter as R5 left it — one above its prior value after a counting failure, unchanged after any other.
- An entry classified as stuck is retained in the log, and pruned only once R2's check resolves it — it remains visible, but is never auto-retried again while its `reconcile_attempts` stays at or above the threshold.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4

### R7 — `stuck_failures` is present only when non-empty

When the `reconcile_index` response is assembled, it includes a `stuck_failures` field only when non-empty, matching the existing optional-field convention (`skipped_existing`, `generation_failed`). In a run in which no entry crosses the threshold, the response contains no `stuck_failures` field at all.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4, Open Questions resolution 4

### R8 — `failed` keeps every below-threshold failure

For an existing caller that reads only the `failed` field, `failed` still contains every genuinely-failing-for-the-first-few-times entry — the new `stuck_failures` field is purely additive; nothing that was in `failed` below the threshold moves elsewhere.

Source: None

### R9 — Phase 2 (orphan scan) is unaffected by the bounding

When Phase 2 (orphan scan) runs, it is entirely unaffected by this task — its `failed` list is ephemeral per call and never persisted back to the failure log (no failure-log entry, no `reconcile_attempts` counter, exists for an orphan-scan failure), so there is no replay loop to bound there.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4, Open Questions resolution (the Phase-1-only scope)

## 3. Rules — Shared fetch-and-reindex helper

### R10 — Phase 1 and Phase 2 re-index through one shared step

Once Phase 1 or Phase 2 has an artifact's `raw_meta` from `head_object`, both re-index it through one shared fetch-and-reindex step — read the content, re-index, and build the `reconciled` entry — so the entry has the same shape, `{"artifact_id", "title", "sections_indexed", "source"}`, whichever phase produced it, differing only in `source` (`"failure_log"` or `"orphan_scan"`).

Source: None

### R11 — The extraction is a pure refactor

Given the existing Phase 1 and Phase 2 test scenarios (failure-log replay success/failure, orphan-scan success/failure, `CredentialError` from either phase), every existing assertion continues to pass unchanged once the extraction lands — the extraction is a pure refactor with no response-shape or behavior change.

Source: None

### R12 — Phase 1's `head_object` pre-fetch stays ahead of the helper, and its `KeyError` branch resolves the entry

When Phase 1 has already fetched an entry's `raw_meta` via `head_object` and hands it to the shared step, the step does not re-fetch `head_object` itself. Phase 1's existing `head_object` `KeyError` → "S3 object not found" handling stays exactly where it is, ahead of the shared step and deliberately kept out of it.

That `KeyError` branch resolves the entry: the entry is pruned and reported in `reconciled` with the `failure_log_obsolete` source, since a deleted artifact leaves nothing to reconcile and no operator action to request. It is not routed through `reconcile_attempts`. Were the branch to return a bare `failed` result carrying no `reconcile_attempts`, then — because the end-of-run rewrite retains every entry that was not resolved, and because only the counter-bearing paths can ever reach `stuck_failures` — an entry whose artifact had since been deleted would be replayed and re-reported as `failed` on every subsequent run, forever, with `failure_log_entries_after` never dropping: the precise "self-perpetuating failure-log replay" outcome the Problem Statement sets out to make impossible. The bounded-retry rule does not reach this branch on its own, because the branch sits ahead of the replay attempt rather than inside it. The normative statement of this behaviour, including the three properties its safety depends on, lives in [`docs/contracts/modules/arkeology.tools.reconcile.md`](../contracts/modules/arkeology.tools.reconcile.md), which is the authority.

Source: the placement: None; the classification: arkeology.tools.reconcile (Revision 2026-09-05)

### R13 — Phase 2 pre-fetches `raw_meta` via `head_object` ahead of the helper

When Phase 2's orphan-scan loop uses the shared step, it pre-fetches `raw_meta` via `head_object` before the step, mirroring Phase 1's existing pre-fetch shape — reordering Phase 2's two read calls (`head_object` now ahead of `get_object`, reversed from today) is accepted as behavior-neutral because both calls are read-only and idempotent, and both already land in the same generic `except Exception` handling in Phase 2 today. When an orphan is re-indexed, the resulting `reconciled` entry is identical in shape and content to today's, tagged `"source": "orphan_scan"`.

Source: None

### R14 — The shared step propagates exceptions unchanged; each caller classifies them

When the shared step's content read or re-index raises, the exception propagates unchanged to the caller rather than being caught or reclassified inside the step — so Phase 1 keeps its `reconcile_attempts`-aware routing (R5) and Phase 2 keeps its existing generic `failed` handling, both unchanged, in their respective call sites.

- A `CredentialError` caught by either phase's caller still returns the existing structured credential-error response, propagated unchanged through the shared step.
- Any other `Exception` caught by Phase 1's caller is classified, counted and routed exactly as R5 specifies — the shared step only fetches and re-indexes, it never classifies a failure; Phase 2's caller reports its failure in `failed` with the code R5's classification assigns, and keeps no counter.

Source: None

## 4. Boundaries

**Always:**
- The bounded-retry mechanism applies **only** to Phase 1's failure-log replay — Phase 2's orphan scan has no persisted failure record and is out of scope (ADR context: "Phase 2 orphan scan... its `failed` list is ephemeral per call — not persisted back to the failure log, so orphan-scan failure does not itself create a replay loop").
- Reuse `CAS_MAX_ATTEMPTS = 3` from `annotations.py` as-is — do not introduce a new, independently
  configurable threshold (adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4, rejected
  alternative: an independently configurable threshold was considered and rejected for lack of
  evidence 3 is wrong here).
- `reconcile_attempts` increments only on an actual replay *attempt* that fails with a counting code (R5) — an entry already at/above the threshold is skipped, not attempted, so its counter does not grow further once stuck (it is reported in `stuck_failures` on every subsequent run at the same fixed count until R2's check resolves it).
- `stuck_failures` and `failed` are mutually exclusive per entry per run — an entry is in exactly one of the two lists (or in `resolved_ids`, or below-threshold-and-not-yet-attempted-this-run, which cannot occur since every unique entry is either skipped-as-stuck or attempted).
- The shared fetch-and-reindex step is a pure refactor — it must not change any existing response field, the `reconciled`/`failed` entry shape, or Phase 1's `reconcile_attempts`/`stuck_failures` routing introduced by this task's primary scope.

**Ask First:**
- Nothing — the threshold value, its source (`CAS_MAX_ATTEMPTS`), and the new field name
  (`stuck_failures`) are all locked, operator-approved decisions
  (adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4, Open Questions resolution 4).
  The shared step and Phase 2's pre-fetch reordering carry no open design question either.

**Never:**
- Do not introduce a new configurable threshold setting — reuse `CAS_MAX_ATTEMPTS` exactly.
- Do not prune a stuck entry R2's check does not resolve — it remains in the log, and in `stuck_failures` with the log's path on every run, until its artifact is deleted or a later write indexes it.
- Do not add a tool that removes a stuck entry on request — revisit if operators meet stuck entries whose artifact they can neither rewrite nor delete.
- Do not apply any bounding logic to Phase 2's orphan scan — it has no persisted entry to bound.
- Do not silently blend a stuck entry into `failed` — Story 2 (R2, R5) requires it to be distinguishable via the new field, not merely inferable from a growing internal counter no response field exposes.
- Do not move the `reconcile_attempts` increment/routing logic (Story 2; R5) into the shared fetch-and-reindex step — it stays Phase-1-only, in the caller; the shared step only fetches and re-indexes, it never classifies a failure.


## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_reconcile.py` | Modify | Add: every `failed`/`stuck_failures` entry carries `error` — assert on the code, never on the wording of `reason`; a failure raising a throttling `ClientError`, and one raising `AnnotationUnavailableError`, each land in `failed` with `internal_error` / `annotation_unavailable` and leave the counter unchanged on disk; entry with `reconcile_attempts` unset/0/1/2 that fails with a counting failure (`MetadataTooLargeError`) → increments and lands in `failed` with `validation_error`, log retains it with the incremented count and the recorded code; entry with `reconcile_attempts=2` that fails this run → increments to 3, lands in `stuck_failures` (not `failed`) this same run; entry with `reconcile_attempts>=3` already → skipped entirely (no `_reindex_artifact` call, via `mocker.spy`), lands in `stuck_failures` with its recorded code, or `internal_error` when the entry records none, and a `reason` ending with `settings.failure_log_path`; the same stuck entry after its artifact was overwritten successfully (the object's and `#0`'s `last_edited_ulid` equal and later than the entry's `timestamp`) → pruned, in `reconciled` with `source: "failure_log_superseded"`, no `_reindex_artifact` call; after its object was deleted → pruned with `failure_log_obsolete`; with vectors present but carrying an older `last_edited_ulid` than the object's → still in `stuck_failures`; entry that succeeds → pruned from log regardless of prior `reconcile_attempts`; a run with no stuck entries → no `stuck_failures` key in response; Phase 2 orphan-scan failures unaffected (no counter, no `stuck_failures` entry ever produced from that phase). **Fetch-and-reindex dedup:** rerun the existing Phase 1/Phase 2 success, failure, and `CredentialError` cases (already present in this file) unchanged after the extraction, plus one new test asserting Phase 1 and Phase 2 both route through `_fetch_and_reindex` (`mocker.spy`) with the correct `source` argument each — Red first |
| `src/arkeology/tools/reconcile.py` | Modify | Classify every per-artifact failure to the code `arkeology.tools.reconcile` § reconcile_index assigns and put it on each `failed`/`stuck_failures` entry as `error`; increment and record `reconcile_error` only for a counting code. In Phase 1's replay loop: read each group's highest `reconcile_attempts` (absent → `0`); when `>= CAS_MAX_ATTEMPTS` (import `CAS_MAX_ATTEMPTS` from `arkeology.annotations`, already imported for `read_link_annotations`), never attempt it: check the artifact by one `head_object` and one `GetVectors` of `{artifact_id}#0` (R2) — resolve it as obsolete, resolve it as `failure_log_superseded`, or classify it stuck with the failure log's path appended to its `reason`; key the dedup and the resolved-entry prune on `(artifact_id, kind)` (T67's `_entry_kind`), never bare `artifact_id`; on a failed attempt, increment `entry["reconcile_attempts"]` and route to `failed` vs. `stuck_failures` based on the post-increment value; add `stuck_failures: list[dict[str, Any]]` alongside the existing `failed` list; include it in the returned response dict only when non-empty. **Fetch-and-reindex dedup:** add a module-level `async def _fetch_and_reindex(artifact_id, raw_meta, source, settings, s3, vectors, bedrock) -> dict[str, Any]` performing the `get_object` read, the `_reindex_artifact` call (via `asyncio.to_thread`, as today), and building the `reconciled`-entry dict tagged with `source`; call it from Phase 1 after the existing `head_object` pre-fetch (passing `"failure_log"`), with the `reconcile_attempts` increment/routing staying in Phase 1's own `except Exception` block, not in the helper; call it from Phase 2 after moving its `head_object` fetch ahead of the shared call (passing `"orphan_scan"`), removing the now-duplicated `get_object`/`_reindex_artifact`/append lines from both phases |
| `tests/integration/test_tools_reconcile.py` | Modify (flag) | Real-AWS: force an entry to fail 3 times in a row (e.g. via a genuinely oversize payload that fails T57's guard every time) and assert it moves from `failed` to `stuck_failures` on the third run — Red for integration, if a suitable fixture exists |

### Contracts

- `docs/contracts/modules/arkeology.tools.reconcile.md` § reconcile_index — the error codes and which count toward the bound, the check of a group at its bound, `stuck_failures` and its `reason`, the end-of-run rewrite, and Phase 1's `head_object` `KeyError` branch with the three properties its safety depends on (R2, R5–R7, R12, R14).
- `docs/contracts/data/s3.artifact.md` § Storage Shape — the object's `last_edited_ulid`, which may be absent, that the at-bound check compares (R2).
- `docs/contracts/data/s3vectors.artifact.md` § Storage Shape — the `#0` vector the at-bound check reads by key (R2).
- `docs/contracts/data/s3-annotations.artifact.md` § read_link_annotations and § apply_link_annotations — the read and write that re-apply a superseded group's saved link values (R2).

### Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_tools_reconcile.py` → `reconcile.py`** — write a failure-log entry directly (bypassing the normal write-path failure logging, to control `reconcile_attempts` precisely) with `reconcile_attempts` set to `0`, `1`, `2`, and `3+` in separate test cases; force `_reindex_artifact` to fail deterministically with a counting failure (`mocker.patch.object` raising `MetadataTooLargeError`, or a genuinely-oversize seeded payload); assert the counter increments correctly and each reported entry carries `error: "validation_error"`, the `failed`/`stuck_failures` routing matches the boundary exactly (2→3 crosses into `stuck_failures` this run; already-3+ skips the attempt and its spy-call-count assertion), and the rewritten failure log on disk carries the updated counter. A separate test simulates three consecutive `reconcile_index` calls against the same unresolved entry and asserts it appears in `failed` on runs 1–2 and in `stuck_failures` from run 3 onward, with `_reindex_artifact` never called again on run 4+. A third simulates three consecutive runs whose failure is a throttling `ClientError` and asserts the entry is in `failed` with `internal_error` on all three and its counter on disk is still unchanged. A fourth seeds an entry at `reconcile_attempts=3` and asserts R2's three outcomes — artifact overwritten since, artifact deleted, artifact unchanged — with no `_reindex_artifact` call in any of them.
2. **`test_tools_reconcile.py` → `reconcile.py`** (fetch-and-reindex dedup) — before extracting, confirm the existing Phase 1 and Phase 2 test suites (success, failure, `CredentialError`) pass; after extracting `_fetch_and_reindex`, rerun them unchanged and assert they still pass (Green — this is a refactor gated by non-regression, not new failing behavior). Add one new test that `mocker.spy`s `_fetch_and_reindex` and asserts it is called once from a Phase 1 replay with `source="failure_log"` and once from a Phase 2 orphan-scan with `source="orphan_scan"`, each with the `raw_meta` already fetched by its caller (no duplicate `head_object` call — assert via `mocker.spy` on `s3.head_object` that it is called exactly once per artifact across both the pre-fetch and the helper combined).

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; `FakeBedrockClient` for embeddings; `tmp_path`/`settings.failure_log_path` fixture for direct log-file seeding and inspection, consistent with existing `test_tools_reconcile.py` failure-log tests.
