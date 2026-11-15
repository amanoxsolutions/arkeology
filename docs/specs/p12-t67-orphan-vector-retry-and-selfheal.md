---
type: Spec
id: p12-t67-orphan-vector-retry-and-selfheal
title: T67 — Orphan-Vector Failure Logging + reconcile_index Self-Heal Repair
description: "write.py's Step 8 orphan-vector cleanup claims reconcile_index \"can collect any leftover orphan vectors later\"; this spec makes it true. A failed Step 8 delete_vectors call — after the SDK client's own retries, with no application-level retry on top — logs a distinct failure-log entry kind carrying the exact orphan vector keys still needing deletion, and reconcile_index's Phase 1 recognises and repairs that kind directly (a targeted delete_vectors call of the keys a prune-time re-check finds still stale, not a full re-index), participating in T62's existing reconcile_attempts/stuck_failures bounding rather than a parallel mechanism."
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
  - resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
  - resource: docs/specs/p15-t92-numbered-vector-keys.md
    title: T92 — Numbered Vector Keys and Per-Artifact Vector Access by Key
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
generated:
  by: "axians-architect/unknown"
  at: 2026-08-19T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:28:28Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T67 — Orphan-Vector Failure Logging + `reconcile_index` Self-Heal Repair

## TL;DR

`write.py`'s Step 8 deletes a previous version's stale section vectors after a successful `overwrite=True` rewrite. A failure of that `delete_vectors` call, once the SDK client's own retries are spent, is recorded as a new failure-log entry kind — distinguished by the presence of an `orphan_keys` field — with no application-level retry on top; `reconcile_index`'s Phase 1 recognises that kind and repairs it by deleting the recorded keys a prune-time re-check finds still stale (no re-embedding), participating in T62's existing `reconcile_attempts`/`stuck_failures` bounding under a corrected `(artifact_id, kind)` dedup key (see R10 — the existing bare-`artifact_id` dedup key would otherwise silently drop one of two co-existing entry kinds for the same artifact). None of `reconcile_index`'s other repair mechanisms — failure-log replay, orphan scan, dangling-vector prune — detects "this artifact's index has some correct vectors and some stale extra ones mixed in".

## 1. Problem Statement

Failure scenario (from the review finding): an `overwrite=True` write on an existing multi-section artifact succeeds through S3 and vector indexing, but Step 8's `vectors.delete_vectors(orphan_keys)` call transiently fails (a brief credential hiccup, a throttle). The stale pre-overwrite section vectors are now permanently uncollectible by any documented recovery path — `reconcile_index` silently does nothing for them — polluting search results for that artifact with duplicate/stale section content forever, contradicting the Step 8 code comment's explicit claim.

Five design decisions close this gap correctly, each verified against this codebase's existing conventions or AWS's documented API contract (not guessed): 1. **No retry beyond the SDK's** (R2); 2. **Blocking the event loop** (R3); 3. **Failure-log discriminator** (R7); 4. **Idempotent repair** (R9); 5. **Dedup-key collision** (R10).

Stories 1–5 are P1; Story 6 is P2. Story 1 — a failed Step 8 `delete_vectors` call is never retried in application code and never changes the write's success response (R2, R3, R5). Story 2 — a failed delete is durably logged with the exact orphan keys (R4, R5). Story 3 — `reconcile_index` repairs the orphan-cleanup kind without re-indexing, deleting only the recorded keys still stale (R7, R8, R9). Story 4 — orphan-cleanup entries participate in T62's `reconcile_attempts`/`stuck_failures` bounding (R11, R12, R13). Story 5 — co-existing reindex and orphan-cleanup entries for the same `artifact_id` are each resolved independently (R10). Story 6 — T62's own rules state the two kinds and their key (R14).

## 2. Rules — Step 8 failure handling (`write_artifact`)

### R2 — A failed delete is never retried in application code

When Step 8's `delete_vectors(orphan_keys)` call raises — a `ClientError` the SDK client's own retries did not clear, a `CredentialError` (already translated by `VectorsClientImpl.delete_vectors`'s `wrap_credential_errors` wrapper), or any other `Exception` — Step 8 makes no further attempt and proceeds directly to the failure-log entry (R4).

**Why:** the SDK client already retries throttling and transient responses with exponential backoff before it raises, so an application-level attempt seconds later would cover only the window between "the SDK's retries are spent" and "the service is back", on a call a developer makes a few times a day; the failure-log entry and `reconcile_index`'s cheap delete (R7) repair what is left.

**Example**

- Given `delete_vectors` raising a `ClientError` with code `TooManyRequestsException`, when an overwriting write reaches Step 8, then `delete_vectors` is called once, a failure-log entry carrying `orphan_keys` is written, and `write_artifact` returns its normal success response.

Source: arkeology.tools.reconcile

### R3 — The delete runs via `asyncio.to_thread`, never blocking the event loop

Step 8's `delete_vectors` call executes via `asyncio.to_thread`, never as a blocking call on the event loop thread. The SDK client's own retries back off with a blocking sleep inside the call; run inline, that would freeze the event loop for the whole backoff on every throttled orphan cleanup, on a server whose `write_artifacts` bulk path runs many concurrent writes. This mirrors `reconcile.py`'s Phase 3 dangling-vector-prune call (`await asyncio.to_thread(vectors.delete_vectors, keys_to_delete)`) — an idiom already established in this codebase for exactly this kind of non-embed blocking vector-client call (`write.py`'s dedicated `_EMBED_EXECUTOR` is reserved for embed calls only, per its own top-of-file comment, so this does not share that pool).

Source: None

### R4 — A failed delete writes a failure-log entry carrying the exact orphan keys

When Step 8's `delete_vectors` call fails (R2), a failure-log entry is appended via an extended `_log_partial_write_failure` (new optional `orphan_keys: list[str] | None = None` parameter, included in the written dict only when not `None`) with `failure_step: "orphan_vector_cleanup"` and `orphan_keys` set to the full list of orphan keys that still need deleting — the exact list computed earlier in Step 8, not a partial/attempted subset. The entry contains `artifact_id`, `title`, `type`, `tier`, `date`, `failure_step: "orphan_vector_cleanup"`, `reason`, `timestamp`, and `orphan_keys`.

The freshly logged entry carries no `reconcile_attempts` key (consistent with every other failure-log entry's first write — the field is introduced by `reconcile.py`'s `entry.get("reconcile_attempts", 0)` default, per T62, not written eagerly at log time).

Source: plan Phase 12 T67 (c)

### R5 — `write_artifact`'s success response is never changed by Step 8

When Step 8's `delete_vectors` call fails, `write_artifact`'s return value does not change — still a plain success dict: no `partial_write` error, no new response field; only the existing `logger.warning` plus the new failure-log entry. The failure logging never inverts a successful write to an error.

Source: None

### R6 — A failing `list_vectors_by_metadata` read is handled exactly as today

When `list_vectors_by_metadata` itself fails (the read that computes `orphan_keys`, upstream of the delete), handling is unchanged by this task — still caught by Step 8's existing outer `except Exception:` with only a `logger.warning`, no failure-log entry (the orphan keys are unknown in that case, so nothing actionable could be logged).

Source: None

## 3. Rules — `reconcile_index` orphan-cleanup repair (Phase 1)

### R7 — An entry carrying `orphan_keys` is repaired by deleting the recorded keys still stale, without re-indexing

When `reconcile_index`'s Phase 1 processes a failure-log entry containing an `orphan_keys` field, it classifies it as an orphan-cleanup entry and repairs it without re-indexing — no `get_object`, no `bedrock.embed`, never a `_fetch_and_reindex`/`_reindex_artifact` call for that entry. A recorded key list says what was stale when the entry was written, not what is stale now: a later successful overwrite may have re-created one of those keys with live content. So before deleting, the replay re-checks each recorded key at prune time and deletes only the keys still stale — a key whose vector carries a `last_edited_ulid` equal to or newer than the artifact's current one is spared as live, and a key already gone needs no delete — as `arkeology.tools.reconcile` § reconcile_index states, with the token test for numbered keys in `p15-t92-numbered-vector-keys` R8.

**Example**

- Given an entry recording three leftover keys of an artifact that a later overwrite grew back to six sections, re-creating those three keys with live content, when `reconcile_index` replays the entry, then none of the three is deleted, the entry resolves, and `orphan_keys_deleted` is `0`.
- Given an entry whose three recorded keys still hold the previous version's vectors, when it is replayed, then all three are deleted and `orphan_keys_deleted` is `3`.

The new kind is distinguished by the presence of an `orphan_keys: list[str]` field on the entry — not a new `kind`/`type` field. `orphan_keys` is exactly the data the repair action needs, so checking for its presence is simultaneously "do I have what I need to do the cheap repair" and "is this the cheap-repair kind" — one guard, one source of truth, nothing that can drift out of sync the way an independent label field could. `failure_step` is still set to the human-readable value `"orphan_vector_cleanup"` (alongside the existing `"bedrock_embed"` / `"put_vector"` / `"annotation_write"` values) purely for operator-facing log/audit consistency — `reconcile.py`'s branching logic never string-matches it.

Source: plan Phase 12 T67 (c); arkeology.tools.reconcile; p15-t92-numbered-vector-keys R8

### R8 — A successful repair is pruned and reported in `reconciled` with its own shape

When an orphan-cleanup entry's repair succeeds, the entry is pruned from the failure log and appended to `reconciled` with the shape `{"artifact_id", "title", "orphan_keys_deleted", "source": "orphan_vector_cleanup"}` — `title` read directly from the failure-log entry; `orphan_keys_deleted` counting the keys actually deleted, so a recorded key spared as live or already gone shows as the difference from the entry's recorded list; no `sections_indexed` key (nothing was re-embedded). This shape is distinct from the existing `{"artifact_id", "title", "sections_indexed", "source"}` shape used for `"failure_log"`/`"orphan_scan"` sources; callers must branch on `source` before assuming `sections_indexed` is present.

Source: None

### R9 — The repair is idempotent: absent keys do not fail it

An orphan-cleanup entry resolves whether or not some or all of its `orphan_keys` still exist in the index (already deleted by a prior partial success, or never existed): a recorded key the R7 re-check finds gone is simply not deleted, and there is no distinct "partially succeeded" state and no post-delete existence re-check. A replay whose re-check finds every recorded key gone or live resolves the entry with nothing deleted.

The AWS `DeleteVectors` API's documented error list has no per-key "not found" error class — `NotFoundException` there refers to the vector bucket/index resource, not an individual key — matching the same idempotent-delete convention as S3's own `DeleteObjects`; and moto's `S3VectorsBackend.delete_vectors` mirrors this exactly (`index.vectors.pop(key, None)` — a silent no-op for an absent key). Deleting an already-deleted key is not a failure under either the real API or this codebase's test double, so a key removed between the re-check and the delete does not fail the replay either.

Source: arkeology.tools.reconcile

### R10 — Phase 1 deduplicates and resolves entries by `(artifact_id, kind)`

When Phase 1 deduplicates and later prunes failure-log entries, it uses `(artifact_id, kind)` as the uniqueness/resolution key, where `kind` is `"orphan_cleanup"` if `orphan_keys` is present on the entry else `"reindex"` — a pure, no-persisted-field function of the entry's own shape. Resolving one kind's entry for a given `artifact_id` does NOT prune the other kind's still-unresolved entry for the same `artifact_id`.

**Example**

- Given the failure log contains two entries for the same `artifact_id` — one reindex-kind, one orphan-cleanup-kind — when Phase 1 deduplicates and processes entries, then both are attempted this run.
- Given one of the two entries resolves and the other does not (fails or is skipped as stuck), when the failure log is rewritten, then only the resolved entry is pruned — the other survives in the log with its own `reconcile_attempts` state, never silently dropped as a side effect of the other's resolution.
- Given only a single entry exists for an `artifact_id` (the only case possible before this task), then its behaviour is unchanged — the composite key is unique either way, so this is backward-compatible.

Without this key the dedup collides — a defect this task's own change would otherwise introduce. `reconcile.py`'s Phase 1 today deduplicates failure-log entries by bare `artifact_id`, keeping only the first entry seen per unique ID, and prunes **every** entry sharing that `artifact_id` from the log once any one of them resolves. Before this task, at most one unresolved entry per `artifact_id` was ever realistic (a write's partial failure is logged once; the next successful reconcile clears it). This task makes a second, very plausible scenario real: a write fails after `bedrock_embed` (logging a `"bedrock_embed"`-kind entry, unresolved), then a later successful `overwrite=True` write on the *same* artifact_id fully re-indexes it but has its own Step 8 orphan cleanup fail (logging a second, `orphan_keys`-kind entry for the *same* `artifact_id`). Under the existing bare-`artifact_id` dedup, only the first (now-stale, already-superseded) entry would be attempted; if it "succeeds" (a no-op re-index of already-correct content), its `artifact_id` is added to `resolved_ids`, and the log rewrite prunes **both** entries — silently discarding the still-needed orphan-cleanup entry with no repair ever attempted.

Source: None

### R11 — A stuck orphan-cleanup entry is not attempted and is reported in `stuck_failures`

When an orphan-cleanup entry's `reconcile_attempts` (before this run) is already `>= CAS_MAX_ATTEMPTS`, `reconcile_index` does **not** call `delete_vectors` for it. Its artifact is checked exactly as for the reindex kind (`p12-t62-bounded-reconcile-retry` R2): a deleted artifact resolves it, and so does one a later write has indexed, once any link values the group saved are re-applied to the annotations — a failure of that re-application leaves it in `stuck_failures` with the failure's code, as T62 R2 states; otherwise it is added to `stuck_failures` — carrying `orphan_keys` alongside the existing `artifact_id`/`reason`/`reconcile_attempts` fields (the additional field, additive to T62's existing reindex-kind shape).

Source: plan Phase 12 T67 (c); the `CAS_MAX_ATTEMPTS` reuse: p12-t62-bounded-reconcile-retry, adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4; the check: p12-t62-bounded-reconcile-retry R2

### R12 — A failed orphan-cleanup repair is counted and routed exactly as T62 routes the reindex kind

When an orphan-cleanup entry's `delete_vectors` call fails on this run, the failure is given its error code, counted only when the code counts toward the bound, and routed into `failed` or `stuck_failures` exactly as `p12-t62-bounded-reconcile-retry` R5 does for the reindex kind (`>= CAS_MAX_ATTEMPTS` after increment → `stuck_failures`), with `orphan_keys` included on the reported entry.

- When, after incrementing, its `reconcile_attempts` reaches `CAS_MAX_ATTEMPTS`, it is reported in `stuck_failures` for this run (not `failed`) — the threshold-crossing run is where the transition is visible, exactly matching T62's Story 2 for the reindex kind.
- When it fails below the threshold, it is reported in `failed` (carrying the same additional `orphan_keys` field) and retained in the log with its `reconcile_attempts` as that classification left it.

Source: plan Phase 12 T67 (c); the `CAS_MAX_ATTEMPTS` reuse: p12-t62-bounded-reconcile-retry, adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4

### R13 — The reindex kind's `failed`/`stuck_failures` shape is unchanged

For a reindex-kind entry (no `orphan_keys`), the `failed`/`stuck_failures` shape is completely unchanged by this task — no `orphan_keys` key appears on it.

Source: None

## 4. Rules — T62's rules state the two kinds

### R14 — T62's Phase 1 rules state the `(artifact_id, kind)` key

`docs/specs/p12-t62-bounded-reconcile-retry.md` states in its own Phase 1 rules that an entry is the group sharing one `(artifact_id, kind)` and that the bounding applies to both kinds alike, so a reader of T62 alone does not take its dedup to be by bare `artifact_id`.

Source: None

## 5. Boundaries

**Always:**
- Every failure of Step 8's delete — throttle, timeout, `CredentialError`
  or any other — goes straight to the failure-log entry (R2, R4); the SDK
  client's own retries are the only retries.
- Route the delete through `asyncio.to_thread` — never a blocking call
  directly on the event-loop thread (R3).
- Step 8 must never invert `write_artifact`'s success response into an
  error — its failure logging remains best-effort.
- Reuse `CAS_MAX_ATTEMPTS` from `annotations.py` for the orphan-cleanup
  kind's bounding too — do not introduce an independently configurable
  threshold (T62 precedent, adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D4).
- Dedup/resolve failure-log entries by `(artifact_id, kind)` — never bare
  `artifact_id` — so a co-existing reindex entry and orphan-cleanup entry
  for the same `artifact_id` are always processed and pruned independently.
- The orphan-cleanup repair never re-indexes — never routes through
  `_fetch_and_reindex`/`_reindex_artifact` (no re-embedding, no
  `bedrock.embed` call, no content read) — and deletes only the recorded keys
  its prune-time re-check finds still stale (R7).

**Ask First:**
- Nothing — the discriminator shape (`orphan_keys` presence) and the
  dedup-key fix rest on documented AWS behaviour (the `DeleteVectors` API
  reference) and this codebase's existing conventions (`reconcile.py`'s
  Phase 3 `asyncio.to_thread` idiom, T62's
  `reconcile_attempts`/`stuck_failures` mechanism), and the prune-time
  re-check is the reconcile contract's — none require a further operator
  decision before implementation.

**Never:**
- Do not add an application-level retry around Step 8's delete — revisit
  if orphan-cleanup entries become frequent enough that waiting for the next
  `reconcile_index` run to delete them matters.
- Do not add an independently-configurable reconcile-attempts threshold
  setting.
- Do not call `_reindex_artifact`/`_fetch_and_reindex` for an orphan-cleanup
  entry — it never needs re-embedding.
- Do not prune an orphan-cleanup entry that failed or is stuck — it remains
  in the failure log (matching T62's rule for the reindex kind) until a
  later run succeeds or the check of `p12-t62-bounded-reconcile-retry` R2
  resolves it.
- Do not call the delete on the event-loop thread (R3).
- Do not delete a recorded orphan key without the prune-time re-check of
  R7 — a later overwrite may have re-created it with live content, and
  deleting it would silently drop that section from search with no later
  reconcile pass able to see the loss.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_write.py` | Modify | One test parameterised over `delete_vectors` raising a transient `ClientError` (`TooManyRequestsException`), a non-transient `ClientError` (`ValidationException`) and `CredentialError` → in each case `delete_vectors` is called exactly once (no application-level retry), a failure-log entry is written with `failure_step="orphan_vector_cleanup"` and `orphan_keys` matching the computed orphan set exactly, and `write_artifact` returns its normal success dict; no test patches or expects a sleep — Red first |
| `src/arkeology/tools/write.py` | Modify | Extend `_log_partial_write_failure` with `orphan_keys: list[str] \| None = None`, included in the entry dict only when not `None`. In Step 8: after computing `orphan_keys`, when non-empty, `await asyncio.to_thread(vectors.delete_vectors, orphan_keys)` inside a `try`; on any exception, call the extended `_log_partial_write_failure(..., failure_step="orphan_vector_cleanup", reason=str(exc), orphan_keys=orphan_keys)` and keep the existing `logger.warning`. No retry helper, retry constants, `time.sleep` or `random` jitter. The outer `except Exception:` around `list_vectors_by_metadata` stays exactly as it is (unchanged failure mode for that sub-step) |
| `tests/unit/test_tools_reconcile.py` | Modify | Add: seed a failure-log entry with `artifact_id` + `orphan_keys` (pointing at real vector keys already indexed via the test fixtures, their `last_edited_ulid` older than the object's) → run `reconcile_index` → assert `vectors.delete_vectors` called (via `mocker.spy`) with exactly those keys, assert `s3.get_object`/`bedrock.embed` were **not** called for that entry, assert the entry is pruned from the log and appears in `reconciled` with the `orphan_keys_deleted`/`source="orphan_vector_cleanup"` shape (no `sections_indexed` key). Add a re-created-key test: one recorded key re-written since with a `last_edited_ulid` equal to the object's → it is not deleted, the entry resolves, and `orphan_keys_deleted` counts only the keys deleted (R7, R8). Add a co-existence test: seed one reindex-kind entry and one orphan-cleanup-kind entry for the *same* `artifact_id`, force one to succeed and the other to fail, assert only the failed one survives in the rewritten log (Story 5). Add a bounding test: seed an orphan-cleanup entry with `reconcile_attempts=2`, force `delete_vectors` to fail with a counting failure (a `ClientError` carrying `ValidationException`), assert it lands in `stuck_failures` (not `failed`) with `error: "validation_error"` this run and is never attempted again on a subsequent run; force a throttling `ClientError` instead and assert it lands in `failed` with `internal_error` and its counter stays at 2. Add an idempotency test: seed `orphan_keys` containing one key still indexed and one already absent, assert the call does not raise and the entry resolves — Red first |
| `src/arkeology/tools/reconcile.py` | Modify | Add a small `_entry_kind(entry) -> str` helper (`"orphan_cleanup"` if `"orphan_keys" in entry` else `"reindex"`). Change Phase 1's `seen_ids`/`unique_entries` dedup and the final `resolved_ids`/`remaining_entries` filter to key on `(artifact_id, _entry_kind(entry))` instead of bare `artifact_id`. In `_process_failure_log_entry`, branch early on `_entry_kind(entry) == "orphan_cleanup"`: skip the existing `_fetch_and_reindex` path entirely; instead read the object's current `last_edited_ulid` (`head_object`) and the recorded keys with metadata by one `GetVectors`, and `await asyncio.to_thread(vectors.delete_vectors, stale_keys)` for only the keys the prune-time re-check finds stale (`arkeology.tools.reconcile` § reconcile_index) (still behind the `CAS_MAX_ATTEMPTS` check of `p12-t62-bounded-reconcile-retry` R2, still under the existing `semaphore`); on success build the `{"artifact_id", "title": entry.get("title", ""), "orphan_keys_deleted": len(stale_keys), "source": "orphan_vector_cleanup"}` reconciled entry, on failure the same `reconcile_attempts` increment/`failed`-vs-`stuck_failures` routing as the reindex kind, additionally carrying `orphan_keys` on the reported `failed`/`stuck_failures` dict |
| `docs/specs/p12-t62-bounded-reconcile-retry.md` | Verify | Its Phase 1 rules define an entry as the group sharing one `(artifact_id, kind)`, the kind told by the presence of `orphan_keys` (R14) |
| `tests/integration/test_tools_reconcile.py` or `tests/integration/test_tools_write.py` | Modify (flag) | Real-AWS: confirm `DeleteVectors` does not error when called with a mix of existing and already-deleted keys (Problem Statement point 4) — Red for integration, if a suitable fixture exists |

### Contracts

- `docs/contracts/modules/arkeology.tools.write.md` § write_artifact — the leftover-vector cleanup an overwrite makes, and the success response its failure never changes (R2–R6).
- `docs/contracts/modules/arkeology.tools.reconcile.md` § reconcile_index — the orphan-cleanup kind, its prune-time re-check, grouping by `(artifact_id, kind)`, its `reconciled` entry and its bounding (R7–R13).
- `docs/contracts/data/s3vectors.artifact.md` § Storage Shape and § Compatibility Guarantees — the numbered keys a recorded orphan key names, and the earlier key shapes an old entry may record (R7, R9).

### Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_tools_write.py` → `write.py`** — the Step 8 failure scenarios
   (transient code, non-transient code, `CredentialError`) described in Files
   to Touch. Assert `delete_vectors` is called exactly once on every path, the
   failure-log entry's `orphan_keys` field matches the computed orphan set
   exactly, and `write_artifact`'s response is the unchanged success shape on
   every path (never `partial_write`, never a new response field).
2. **`test_tools_reconcile.py` → `reconcile.py`** — the orphan-cleanup
   repair path (prune-time re-check, `delete_vectors` of the still-stale
   keys only, no re-index calls, correct `reconciled` shape), the
   re-created-key test, the Story 5 co-existence/dedup-key test, the Story 4
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
