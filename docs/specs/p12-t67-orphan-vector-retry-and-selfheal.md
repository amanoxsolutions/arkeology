---
type: Spec
id: p12-t67-orphan-vector-retry-and-selfheal
title: T67 — Orphan-Vector Inline Retry + reconcile_index Self-Heal Repair
description: "write.py's Step 8 orphan-vector cleanup claims reconcile_index \"can collect any leftover orphan vectors later,\" but nothing makes that true today — the failure isn't logged, and none of reconcile_index's three existing repair mechanisms detect \"an artifact has some correct vectors and some stale extra ones mixed together.\" Operator-approved fix, in order: (b) wrap Step 8's delete_vectors call in a bounded inline retry with backoff, matching bedrock.py's existing throttle-retry shape, so a transient failure self-heals immediately; (c) when retries are exhausted, log a distinct failure-log entry kind carrying the exact orphan vector keys still needing deletion, and extend reconcile_index's Phase 1 to recognise and repair that kind directly (a targeted delete_vectors call, not a full re-index), participating in T62's existing reconcile_attempts/stuck_failures bounding rather than a parallel mechanism."
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/specs/p12-t62-bounded-reconcile-retry.md
    title: T62 — Bounded reconcile_index Failure-Log Retry + Fetch-and-Reindex Dedup
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
    title: Vector Metadata Budget Hardening, Guard Coverage, and Migration Self-Heal
    last_modified: 2026-09-25T00:00:00Z
  - resource: src/arkeology/clients/bedrock.py
  - resource: src/arkeology/annotations.py
generated:
  by: "axians-architect/unknown"
  at: 2026-08-19T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T20:12:46Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T67 — Orphan-Vector Inline Retry + `reconcile_index` Self-Heal Repair

## TL;DR

`write.py`'s Step 8 deletes a previous version's stale section vectors after a successful `overwrite=True` rewrite. Today, a failure in that `delete_vectors` call is only `logger.warning`'d — never logged, never retried, and never recoverable by `reconcile_index` (J-1: none of its three existing repair mechanisms — failure-log replay, orphan scan, dangling-vector prune — detect "this artifact's index has some correct vectors and some stale extra ones mixed in"). This spec implements both operator-approved decisions from `plan.md`'s Phase 12 T67 entry: (b) an inline bounded retry around the `delete_vectors` call, mirroring `bedrock.py`'s `_invoke` retry shape exactly (one retry, fixed sleep + jitter, retrying only documented transient error codes); and (c), when that retry is exhausted, a new failure-log entry kind — distinguished by the presence of an `orphan_keys` field — that `reconcile_index`'s Phase 1 recognises and repairs with a direct `delete_vectors(orphan_keys)` call (no re-embedding), participating in T62's existing `reconcile_attempts`/`stuck_failures` bounding under a corrected `(artifact_id, kind)` dedup key (see R10 — the existing bare-`artifact_id` dedup key would otherwise silently drop one of two co-existing entry kinds for the same artifact).

## 1. Problem Statement

Failure scenario (from the review finding): an `overwrite=True` write on an existing multi-section artifact succeeds through S3 and vector indexing, but Step 8's `vectors.delete_vectors(orphan_keys)` call transiently fails (a brief credential hiccup, a throttle). The stale pre-overwrite section vectors are now permanently uncollectible by any documented recovery path — `reconcile_index` silently does nothing for them — polluting search results for that artifact with duplicate/stale section content forever, contradicting the Step 8 code comment's explicit claim.

Five design decisions close this gap correctly, each verified against this codebase's existing conventions or AWS's documented API contract (not guessed): 1. **Retry bound and backoff** (R1, R2); 2. **Blocking the event loop** (R3); 3. **Failure-log discriminator** (R7); 4. **Idempotent repair** (R9); 5. **Dedup-key collision** (R10).

Stories 1–5 are P1; Story 6 is P2. Story 1 — a transient Step 8 `delete_vectors` failure self-heals inline (R1, R2, R5). Story 2 — a retries-exhausted failure is durably logged with the exact orphan keys (R4, R5). Story 3 — `reconcile_index` repairs the orphan-cleanup kind directly, without re-indexing (R7, R8, R9). Story 4 — orphan-cleanup entries participate in T62's `reconcile_attempts`/`stuck_failures` bounding (R11, R12, R13). Story 5 — co-existing reindex and orphan-cleanup entries for the same `artifact_id` are each resolved independently (R10). Story 6 — T62's spec gets a forward-pointing revision note (R14).

## 2. Rules — Step 8 inline retry (`write_artifact`)

### R1 — A transient `DeleteVectors` failure is retried exactly once, after `2.0 + random.uniform(0, 1)` seconds

When Step 8's `delete_vectors(orphan_keys)` call raises a `ClientError` whose `Error.Code` is `RequestTimeoutException` (408, "Retry your request"), `ServiceUnavailableException` (503, "retry your request"), or `TooManyRequestsException` (429, throttling), AND this is the first attempt, Step 8 sleeps `2.0 + random.uniform(0, 1)` seconds and retries exactly once more (2 total attempts) — mirroring `bedrock.py`'s `_invoke` constants and shape exactly: `_invoke` retries exactly once (`for attempt in range(2)`), sleeping `_RETRY_SLEEP_SECONDS = 2.0` seconds plus `random.uniform(0, 1)` jitter, and retries only a curated set of documented transient `ClientError` codes (`_TRANSIENT_ERROR_CODES`), not every exception. The three codes are S3 Vectors' own documented transient codes for `DeleteVectors`.

When the retry attempt succeeds, `write_artifact` returns its normal success response (`artifact_id`, `sections_indexed`, `last_edited_ulid`) and no failure-log entry is written.

Confirmed 2026-08-19: the three transient codes, against `docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_DeleteVectors.html`.

Source: plan Phase 12 T67 (b) (the operator's locked instruction to reuse `bedrock.py`'s retry shape/philosophy)

### R2 — A credential, non-transient or other failure is not retried

When `delete_vectors` raises `CredentialError`, OR a `ClientError` whose code is not one of the three transient codes in R1, OR any other `Exception`, Step 8 does not retry — it fails on the current attempt. A `CredentialError` is not retried at all (zero additional attempts) and a non-transient `ClientError` code is not retried (fails on the first attempt); each proceeds directly to the fallback failure-log entry (R4). A `CredentialError` is already translated by `VectorsClientImpl.delete_vectors`'s own `wrap_credential_errors` wrapper before it ever reaches Step 8, and is never retried — mirroring `bedrock.py`'s philosophy that a credential failure is not a transient condition eligible for the same one-shot retry.

Source: plan Phase 12 T67 (b)

### R3 — The retry runs via `asyncio.to_thread`, never blocking the event loop

When the retry (the delete call and its sleep) runs, it executes via `asyncio.to_thread`, never as a blocking call on the event loop thread. `bedrock.py`'s header comment states its blocking `time.sleep` retry is safe only because every async caller offloads the call to a worker thread; Step 8's current `delete_vectors` call runs synchronously, inline, directly on the event loop — harmless today because it never sleeps. Adding a retry with a blocking sleep without offloading it would freeze the event loop for up to ~3 seconds on every transient orphan-cleanup failure, on a server whose `write_artifacts` bulk path runs many concurrent writes. This mirrors `reconcile.py`'s Phase 3 dangling-vector-prune call (`await asyncio.to_thread(vectors.delete_vectors, keys_to_delete)`) — an idiom already established in this codebase for exactly this kind of non-embed blocking vector-client call (`write.py`'s dedicated `_EMBED_EXECUTOR` is reserved for embed calls only, per its own top-of-file comment, so this does not share that pool).

Source: None

### R4 — An exhausted retry budget writes a failure-log entry carrying the exact orphan keys

When Step 8's retry budget is exhausted (any of Story 1's non-retried or retry-exhausted paths: R1's retry-exhausted path, or R2's `CredentialError` or non-transient-`ClientError` paths), a failure-log entry is appended via an extended `_log_partial_write_failure` (new optional `orphan_keys: list[str] | None = None` parameter, included in the written dict only when not `None`) with `failure_step: "orphan_vector_cleanup"` and `orphan_keys` set to the full list of orphan keys that still need deleting — the exact list computed earlier in Step 8, not a partial/attempted subset. The entry contains `artifact_id`, `title`, `type`, `tier`, `date`, `failure_step: "orphan_vector_cleanup"`, `reason`, `timestamp`, and `orphan_keys`.

The freshly logged entry carries no `reconcile_attempts` key (consistent with every other failure-log entry's first write — the field is introduced by `reconcile.py`'s `entry.get("reconcile_attempts", 0)` default, per T62, not written eagerly at log time).

Source: plan Phase 12 T67 (c)

### R5 — `write_artifact`'s success response is never changed by Step 8

When Step 8's retry budget is exhausted, `write_artifact`'s return value does not change — still a plain success dict: no `partial_write` error, no new response field; only the existing `logger.warning` (as today) plus the new failure-log entry. The retry and its fallback logging never invert a successful write to an error.

Source: None

### R6 — A failing `list_vectors_by_metadata` read is handled exactly as today

When `list_vectors_by_metadata` itself fails (the read that computes `orphan_keys`, upstream of the retry), handling is unchanged by this task — still caught by Step 8's existing outer `except Exception:` with only a `logger.warning`, no failure-log entry (the orphan keys are unknown in that case, so nothing actionable could be logged).

Source: None

## 3. Rules — `reconcile_index` orphan-cleanup repair (Phase 1)

### R7 — An entry carrying `orphan_keys` is repaired by a direct `delete_vectors` call

When `reconcile_index`'s Phase 1 processes a failure-log entry containing an `orphan_keys` field, it classifies it as an orphan-cleanup entry and calls `vectors.delete_vectors(entry["orphan_keys"])` directly (via `asyncio.to_thread`) — no `head_object`, no `get_object`, no `bedrock.embed`, never a `_fetch_and_reindex`/`_reindex_artifact` call for that entry.

The new kind is distinguished by the presence of an `orphan_keys: list[str]` field on the entry — not a new `kind`/`type` field. `orphan_keys` is exactly the data the repair action needs, so checking for its presence is simultaneously "do I have what I need to do the cheap repair" and "is this the cheap-repair kind" — one guard, one source of truth, nothing that can drift out of sync the way an independent label field could. `failure_step` is still set to the human-readable value `"orphan_vector_cleanup"` (alongside the existing `"bedrock_embed"` / `"put_vector"` / `"annotation_write"` values) purely for operator-facing log/audit consistency — `reconcile.py`'s branching logic never string-matches it.

Source: plan Phase 12 T67 (c)

### R8 — A successful repair is pruned and reported in `reconciled` with its own shape

When an orphan-cleanup entry's delete succeeds, the entry is pruned from the failure log and appended to `reconciled` with the shape `{"artifact_id", "title", "orphan_keys_deleted", "source": "orphan_vector_cleanup"}` — `title` read directly from the failure-log entry (no S3 fetch needed); no `sections_indexed` key (nothing was re-embedded). This shape is distinct from the existing `{"artifact_id", "title", "sections_indexed", "source"}` shape used for `"failure_log"`/`"orphan_scan"` sources; callers must branch on `source` before assuming `sections_indexed` is present.

Source: None

### R9 — The repair is idempotent: absent keys do not fail it

When an orphan-cleanup entry's `delete_vectors` call succeeds, the entry is treated as resolved regardless of whether some/all of its `orphan_keys` no longer exist in the index (already deleted by a prior partial success, or never existed) — no pre-check that every key still exists, no post-delete existence re-check, no distinct "partially succeeded" state. When `delete_vectors` is called with the full list, it does not raise, and the entry is still resolved exactly as a fully-successful delete.

Checked 2026-08-19: the AWS `DeleteVectors` API's documented error list has no per-key "not found" error class — `NotFoundException` there refers to the vector bucket/index resource, not an individual key — matching the same idempotent-delete convention as S3's own `DeleteObjects`; and moto's `S3VectorsBackend.delete_vectors` mirrors this exactly (`index.vectors.pop(key, None)` — a silent no-op for an absent key). Deleting an already-deleted or never-existed key is not a failure under either the real API or this codebase's test double.

Source: None

### R10 — Phase 1 deduplicates and resolves entries by `(artifact_id, kind)`

When Phase 1 deduplicates and later prunes failure-log entries, it uses `(artifact_id, kind)` as the uniqueness/resolution key, where `kind` is `"orphan_cleanup"` if `orphan_keys` is present on the entry else `"reindex"` — a pure, no-persisted-field function of the entry's own shape. Resolving one kind's entry for a given `artifact_id` does NOT prune the other kind's still-unresolved entry for the same `artifact_id`.

**Example**

- Given the failure log contains two entries for the same `artifact_id` — one reindex-kind, one orphan-cleanup-kind — when Phase 1 deduplicates and processes entries, then both are attempted this run.
- Given one of the two entries resolves and the other does not (fails or is skipped as stuck), when the failure log is rewritten, then only the resolved entry is pruned — the other survives in the log with its own `reconcile_attempts` state, never silently dropped as a side effect of the other's resolution.
- Given only a single entry exists for an `artifact_id` (the only case possible before this task), then its behaviour is unchanged — the composite key is unique either way, so this is backward-compatible.

Without this key the dedup collides — a defect this task's own change would otherwise introduce. `reconcile.py`'s Phase 1 today deduplicates failure-log entries by bare `artifact_id`, keeping only the first entry seen per unique ID, and prunes **every** entry sharing that `artifact_id` from the log once any one of them resolves. Before this task, at most one unresolved entry per `artifact_id` was ever realistic (a write's partial failure is logged once; the next successful reconcile clears it). This task makes a second, very plausible scenario real: a write fails after `bedrock_embed` (logging a `"bedrock_embed"`-kind entry, unresolved), then a later successful `overwrite=True` write on the *same* artifact_id fully re-indexes it but has its own Step 8 orphan cleanup exhaust its retries (logging a second, `orphan_keys`-kind entry for the *same* `artifact_id`). Under the existing bare-`artifact_id` dedup, only the first (now-stale, already-superseded) entry would be attempted; if it "succeeds" (a no-op re-index of already-correct content), its `artifact_id` is added to `resolved_ids`, and the log rewrite prunes **both** entries — silently discarding the still-needed orphan-cleanup entry with no repair ever attempted.

Source: None

### R11 — A stuck orphan-cleanup entry is not attempted and is reported in `stuck_failures`

When an orphan-cleanup entry's `reconcile_attempts` (before this run) is already `>= CAS_MAX_ATTEMPTS`, `reconcile_index` does **not** call `delete_vectors` for it, and adds it to `stuck_failures` — carrying `orphan_keys` alongside the existing `artifact_id`/`reason`/`reconcile_attempts` fields (the additional field, additive to T62's existing reindex-kind shape).

Source: plan Phase 12 T67 (c); the `CAS_MAX_ATTEMPTS` reuse: p12-t62-bounded-reconcile-retry, adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4

### R12 — A failed orphan-cleanup repair is counted and routed exactly as T62 routes the reindex kind

When an orphan-cleanup entry's `delete_vectors` call fails on this run, its `reconcile_attempts` is incremented by one and it is classified into `failed` or `stuck_failures` exactly as T62 already does for the reindex kind (`>= CAS_MAX_ATTEMPTS` after increment → `stuck_failures`), with `orphan_keys` included on the reported entry.

- When, after incrementing, its `reconcile_attempts` reaches `CAS_MAX_ATTEMPTS`, it is reported in `stuck_failures` for this run (not `failed`) — the threshold-crossing run is where the transition is visible, exactly matching T62's Story 2 for the reindex kind.
- When it fails below the threshold, it is reported in `failed` (carrying the same additional `orphan_keys` field) and retained in the log with its incremented `reconcile_attempts`.

Source: plan Phase 12 T67 (c); the `CAS_MAX_ATTEMPTS` reuse: p12-t62-bounded-reconcile-retry, adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4

### R13 — The reindex kind's `failed`/`stuck_failures` shape is unchanged

For a reindex-kind entry (no `orphan_keys`), the `failed`/`stuck_failures` shape is completely unchanged by this task — no `orphan_keys` key appears on it.

Source: None

## 4. Rules — T62 revision note

### R14 — T62's spec carries a forward-pointing revision note

Given a future reader opens `docs/specs/p12-t62-bounded-reconcile-retry.md`, when they read it top-to-bottom, then a `## Revision — 2026-08-19` section appears above the frozen `<!-- SCOPE BLOCK -->` marker, stating that a second failure-log entry kind now exists (this spec) and pointing forward to it — without altering a single line of the frozen content below that marker.

Source: None

## 5. Boundaries

**Always:**
- Retry only the three documented S3 Vectors `DeleteVectors` transient
  codes; exactly one retry (2 total attempts); sleep `2.0 +
  random.uniform(0, 1)` seconds between attempts — mirrors `bedrock.py`'s
  `_invoke` exactly, per the operator's locked instruction to reuse its
  shape/philosophy rather than inventing a new retry idiom.
- Route the retry (delete call + sleep) through `asyncio.to_thread` — never
  a blocking `time.sleep` directly on the event-loop thread.
- `CredentialError` is never retried inline — goes straight to the Story 2
  fallback log, matching `bedrock.py`'s non-retry of credential-class
  failures.
- Step 8 must never invert `write_artifact`'s success response into an
  error — both the retry and its fallback logging remain best-effort,
  exactly as today.
- Reuse `CAS_MAX_ATTEMPTS` from `annotations.py` for the orphan-cleanup
  kind's bounding too — do not introduce an independently configurable
  threshold (T62 precedent, ADR D4).
- Dedup/resolve failure-log entries by `(artifact_id, kind)` — never bare
  `artifact_id` — so a co-existing reindex entry and orphan-cleanup entry
  for the same `artifact_id` are always processed and pruned independently.
- The orphan-cleanup repair calls `vectors.delete_vectors(orphan_keys)`
  directly — never routes through `_fetch_and_reindex`/`_reindex_artifact`
  (no re-embedding, no `bedrock.embed` call, no S3 read).

**Ask First:**
- Nothing — the discriminator shape (`orphan_keys` presence), the retry
  bound/backoff numbers, the transient error code set, the dedup-key fix,
  and the T62 revision-note placement were all resolved during spec-writing
  against documented AWS behaviour (verified 2026-08-19 against the
  `DeleteVectors` API reference) and this codebase's existing conventions
  (`bedrock.py`'s retry shape, `reconcile.py`'s Phase 3 `asyncio.to_thread`
  idiom, T62's `reconcile_attempts`/`stuck_failures` mechanism) — none
  require a further operator decision before implementation.

**Never:**
- Do not add a new independently-configurable retry-attempt-count or
  reconcile-attempts threshold setting.
- Do not call `_reindex_artifact`/`_fetch_and_reindex` for an orphan-cleanup
  entry — it never needs re-embedding.
- Do not prune an orphan-cleanup entry that failed or is stuck — it must
  remain visible in the failure log (matching T62's existing rule for the
  reindex kind) until an operator resolves it or a later run succeeds.
- Do not let the retry's sleep block the event loop directly (no bare
  `time.sleep` outside `asyncio.to_thread`).
- Do not modify `docs/specs/p12-t62-bounded-reconcile-retry.md`'s
  `<!-- SCOPE BLOCK -->` content — only add the additive `## Revision —
  2026-08-19` note above it.
- Do not pre-check `orphan_keys` for existence before calling
  `delete_vectors` — the call is idempotent by the documented API contract
  and by moto's mock; a pre-check adds a redundant round trip for no benefit.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_write.py` | Modify | Add: `delete_vectors` `side_effect` raising a transient `ClientError` once then succeeding → assert called twice, `time.sleep` mocked/asserted-called-once (via `mocker.patch("arkeology.tools.write.time.sleep")`), `write_artifact` still returns its normal success dict, no failure-log entry written. A second test: `delete_vectors` always raising a transient `ClientError` → assert called exactly twice (retry budget exhausted), failure-log entry written with `failure_step="orphan_vector_cleanup"` and `orphan_keys` matching the computed orphan set exactly, `write_artifact` response still success. A third test: `delete_vectors` raising `CredentialError` → assert called exactly once (never retried), same fallback-log/success-response assertions. A fourth test: `delete_vectors` raising a non-transient `ClientError` code (e.g. `ValidationException`) → assert called exactly once (not retried), same fallback assertions — Red first |
| `src/arkeology/tools/write.py` | Modify | Add `import random`, `import time`, `import botocore.exceptions`. Extend `_log_partial_write_failure` with `orphan_keys: list[str] \| None = None`, included in the entry dict only when not `None`. Add module-level constants `_ORPHAN_DELETE_RETRY_ATTEMPTS = 2`, `_ORPHAN_DELETE_RETRY_SLEEP_SECONDS = 2.0`, `_ORPHAN_DELETE_TRANSIENT_ERROR_CODES = frozenset({"RequestTimeoutException", "ServiceUnavailableException", "TooManyRequestsException"})`. Add a synchronous helper `_delete_orphan_vectors_with_retry(vectors, orphan_keys) -> Exception \| None` implementing the bounded retry (returns the final exception rather than raising, so the async caller logs it without an extra try/except layer). In Step 8: after computing `orphan_keys`, when non-empty, `await asyncio.to_thread(_delete_orphan_vectors_with_retry, vectors, orphan_keys)`; on a non-`None` result, call the extended `_log_partial_write_failure(..., failure_step="orphan_vector_cleanup", reason=str(failure), orphan_keys=orphan_keys)` and keep the existing `logger.warning`. The outer `except Exception:` around `list_vectors_by_metadata` stays exactly as today (unchanged failure mode for that sub-step) |
| `tests/unit/test_tools_reconcile.py` | Modify | Add: seed a failure-log entry with `artifact_id` + `orphan_keys` (pointing at real vector keys already indexed via the test fixtures) → run `reconcile_index` → assert `vectors.delete_vectors` called (via `mocker.spy`) with exactly those keys, assert `s3.get_object`/`s3.head_object`/`bedrock.embed` were **not** called for that entry, assert the entry is pruned from the log and appears in `reconciled` with the `orphan_keys_deleted`/`source="orphan_vector_cleanup"` shape (no `sections_indexed` key). Add a co-existence test: seed one reindex-kind entry and one orphan-cleanup-kind entry for the *same* `artifact_id`, force one to succeed and the other to fail, assert only the failed one survives in the rewritten log (Story 5). Add a bounding test: seed an orphan-cleanup entry with `reconcile_attempts=2`, force `delete_vectors` to fail, assert it lands in `stuck_failures` (not `failed`) this run and is never attempted again on a subsequent run. Add an idempotency test: seed `orphan_keys` containing one key still indexed and one already absent, assert the call does not raise and the entry resolves — Red first |
| `src/arkeology/tools/reconcile.py` | Modify | Add a small `_entry_kind(entry) -> str` helper (`"orphan_cleanup"` if `"orphan_keys" in entry` else `"reindex"`). Change Phase 1's `seen_ids`/`unique_entries` dedup and the final `resolved_ids`/`remaining_entries` filter to key on `(artifact_id, _entry_kind(entry))` instead of bare `artifact_id`. In `_process_failure_log_entry`, branch early on `_entry_kind(entry) == "orphan_cleanup"`: skip the existing `head_object`/`_fetch_and_reindex` path entirely, instead `await asyncio.to_thread(vectors.delete_vectors, entry["orphan_keys"])` (still behind the existing `CAS_MAX_ATTEMPTS`-skip check, still under the existing `semaphore`), on success build the `{"artifact_id", "title": entry.get("title", ""), "orphan_keys_deleted": len(entry["orphan_keys"]), "source": "orphan_vector_cleanup"}` reconciled entry, on failure the same `reconcile_attempts` increment/`failed`-vs-`stuck_failures` routing as the reindex kind, additionally carrying `orphan_keys` on the reported `failed`/`stuck_failures` dict |
| `docs/specs/p12-t62-bounded-reconcile-retry.md` | Modify | Add a `## Revision — 2026-08-19` section directly under the `# T62 — ...` H1 title, above the `<!-- SCOPE BLOCK -->` marker, stating that a second failure-log entry kind (distinguished by an `orphan_keys` field) now exists per this spec, and that Phase 1's dedup/resolution key is now `(artifact_id, kind)` rather than bare `artifact_id` — pointing forward to `docs/specs/p12-t67-orphan-vector-retry-and-selfheal.md`. Do not touch anything at or below the `<!-- SCOPE BLOCK -->` marker |
| `tests/integration/test_tools_reconcile.py` or `tests/integration/test_tools_write.py` | Modify (flag) | Real-AWS: confirm `DeleteVectors` does not error when called with a mix of existing and already-deleted keys (Problem Statement point 4) — Red for integration, if a suitable fixture exists |

### Contracts

None.

### Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_tools_write.py` → `write.py`** — the four Step 8 retry scenarios
   (transient-then-success, transient-exhausted, `CredentialError`
   not-retried, non-transient-code not-retried) described in Files to Touch.
   Assert call counts on `delete_vectors` precisely (never more than 2), the
   sleep is mocked (tests must never actually sleep), the failure-log entry's
   `orphan_keys` field matches the computed orphan set exactly on the two
   exhausted-retry paths, and `write_artifact`'s response is the unchanged
   success shape on every path (never `partial_write`, never a new response
   field).
2. **`test_tools_reconcile.py` → `reconcile.py`** — the orphan-cleanup
   repair path (direct `delete_vectors`, no re-index calls, correct
   `reconciled` shape), the Story 5 co-existence/dedup-key test, the Story 4
   `reconcile_attempts`/`stuck_failures` bounding test (mirroring T62's own
   boundary-crossing test shape, reused for the new kind), and the Story 3
   idempotency test (a mix of still-indexed and already-absent keys in one
   entry's `orphan_keys`).

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; `FakeBedrockClient`
for embeddings (to assert it is *not* called on the orphan-cleanup path);
`tmp_path`/`settings.failure_log_path` fixture for direct log-file seeding
and inspection, consistent with existing `test_tools_reconcile.py`
failure-log tests. `mocker.patch.object(client, "method", side_effect=...)`
for injected `ClientError`/`CredentialError` failures and `mocker.spy` for
call-count/no-call assertions, per this repo's testing conventions (never a
hand-rolled fake for either purpose).
