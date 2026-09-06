---
type: Contract
title: arkeology.tools.reconcile
description: "The reconcile_index MCP tool — the repair path: replays the partial-write failure log, re-indexes S3 objects absent from the vector index, prunes dangling vectors, and gives up loudly on entries that cannot be fixed."
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p5-t21-reconciliation-tool.md
  - docs/specs/p9-t32-reconcile-phase3-dangling-vectors.md
  - docs/specs/p12-t48-reconcile-from-annotations.md
  - docs/specs/p12-t62-bounded-reconcile-retry.md
  - docs/specs/p12-t67-orphan-vector-retry-and-selfheal.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "architect"
  date: 2026-09-06
---

# arkeology.tools.reconcile

## Scope

The repair boundary. Every other tool's partial-failure mode is designed on the assumption that
this one can finish the job, which makes its rebuild fidelity a system-wide invariant rather than a
local one.

## Symbols

### reconcile_index

```python
async def reconcile_index(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Every failure is a returned dict carrying an `"error"` key.

- `credential_error` — an AWS call raised `CredentialError`.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- S3 is the rebuild source of record. The entire vector index can be reconstructed from S3 objects
  plus their annotations; the reverse is not possible, and no reconcile path may assume otherwise.
- The rebuild is **lossless for link fields**: `commit_refs` and `references` are read from the
  durable annotation store and re-applied to rebuilt vector metadata. A rebuild that read only
  vector metadata would erase the annotation-only `references` copy entirely.
- Only the **capped** `commit_refs` value is placed into rebuilt vector metadata; the annotation
  copy is left complete and uncapped.
- Re-embedding uses the same shared `_section_pipeline` as `write_artifact` — same minimum-length
  filter, same maximum-sections cap, same per-section truncation. Bypassing it would re-submit a
  section that was truncated at write time at full length, failing the embedding input limit
  forever on every replay.
- Metadata budgets are checked before the vector write, exactly as on the write path. Without it
  the repair tool can recreate the very oversize write it exists to fix.
- The automatic retry loop is **bounded**. An entry reaching the maximum attempt count is no longer
  auto-retried and is surfaced in `stuck_failures`, so a genuinely unfixable entry fails loudly
  once rather than retrying forever.
- A failure-log entry whose S3 object **no longer exists** is **resolved, not retried** — it is pruned
  from the log and reported in `reconciled` with the `failure_log_obsolete` source. There is nothing
  left to reconcile: the artifact is gone, and Phase 3 already prunes any vectors it left behind. This
  is deliberately not routed through the attempt counter, because `stuck_failures` asks an operator to
  fix an underlying cause and a deleted artifact presents none. Classifying it `failed` instead would
  breach the bounded-retry invariant above: `failed` entries are retained in the rewritten log and do
  not increment the counter, so such an entry would be replayed and re-reported on every run forever
  and `failure_log_entries_after` would never drop. Safety rests on three properties that must hold
  together — the absence check distinguishes a genuine 404 from a transient or credential failure,
  which keep their existing counter-bearing paths; the dangling-vector prune re-checks existence at
  prune time, so it cannot race a concurrent write; and if the object reappears after the entry is
  pruned, the orphan scan re-indexes any S3 key carrying zero vectors on the following run. Weakening
  any one of the three invalidates this classification.
- **An entry's `failure_step` names the step that failed, and the set of values is open.** Nothing
  in this tool branches on it: an entry's kind is derived from whether it carries `orphan_keys`, and
  its identity for pruning is the whole entry as read back from disk. A producer may therefore split
  one step name into several without a schema change here, and an entry written before such a split
  keeps its own value through both the replay and the prune, because both sides read it from the same
  bytes. The field exists for the operator reading the log to learn why a given artifact is in it, so
  a producer that can tell its steps apart is expected to stamp them apart rather than fix one value
  standing for all of them.
- A failure-log entry may carry two **optional** link-field copies, `commit_refs` and `references`,
  recorded by whichever producer wrote it when a step failed after the object had already been
  re-PUT. Phase 1 re-applies them before re-indexing, so the rebuilt vector metadata is derived from
  the restored value. This is the only path by which they can come back: the re-PUT
  cleared the annotation copy, `references` is in vector metadata nowhere, and the vector
  `commit_refs` copy is capped, so every entry past that cap would otherwise be lost permanently.
- An entry carrying either copy also records, as a third **optional** field, the artifact's
  `last_edited_ulid` as it stood when the failure was recorded. It is the supersession token the
  `references` restore rule below is decided on, and it is the entry's only purpose — nothing else
  reads it. See `s3.artifact` for the field itself.
- **Absence of either link field means "nothing to restore", never "clear the field".** Entries
  written before the fields existed carry neither and must replay unchanged, leaving the object's
  annotations exactly as they are.
- `commit_refs` is restored as the **union** of the entry's copy and the artifact's current
  annotation value, unconditionally and with no supersession test. It is an append-only audit trail
  on which removal is not a supported operation, so a value re-added between the failure and the
  replay lives only in the current copy and the union is the only way to keep both.
- `references` is restored **only while the entry's recorded `last_edited_ulid` still equals the
  artifact's current one.** When the two differ, the entry's copy is discarded and the current
  annotation value is left exactly as it stands. Every write replaces `references` outright (see
  `arkeology.tools.write`), so a differing ULID means a later successful write has already
  established what the field says, and restoring the entry's copy over it would resurrect
  references that write deliberately removed. Unioning here — the rule this replaces — weighed
  additions only and contradicted the replace semantics on every removal.
- The supersession token is `last_edited_ulid`, never the object's ETag. The ULID changes on exactly
  the operation whose `references` semantics are replacement — a `write_artifact` write — and is
  deliberately left untouched by an archive status flip, a `link_metadata` backfill, and a reconcile
  re-index, none of which replace `references`. An ETag tracks bytes rather than writes: an
  overwriting write that changes only `references` and leaves the body byte-identical carries the
  **same** ETag, so an ETag comparison would miss precisely the supersession this rule exists to
  detect. How an ETag is derived at all also varies with bucket encryption, making it
  deployment-dependent where the ULID is not.
- An entry recording **no** `last_edited_ulid` — one written before the token existed, or one for an
  artifact that carries none — restores `references` by union, exactly as entries did before. An
  absent token is missing evidence of supersession, not evidence of it, and discarding on it would
  destroy the only surviving copy of a value no later write had touched.
- The rebuilt vector metadata's `commit_refs` is derived from the artifact's annotation, its sole
  source of truth, never carried over from the vector being replaced. A failed annotation read fails
  that artifact — it is reported under `failed` and no vectors are written for it — because rebuilding
  from a spurious empty would write that emptiness over the artifact's real link fields. The run
  itself still completes; the failure is per artifact.
- Failure-log entries are classified by their own shape — the presence of `orphan_keys` marks the
  cheap orphan-cleanup kind — so a reindex-kind and an orphan-cleanup-kind entry for the same
  artifact are processed and pruned independently.
- Dangling vectors, whose S3 object no longer exists, are pruned rather than re-indexed.
- The orphan scan indexes **artifacts only**. A candidate key is re-indexed only when its S3 object
  metadata carries a `type` that is a member of `ARTIFACT_TYPES`; anything else under the write
  prefix — a manual upload, a `.DS_Store`, a partial multipart artefact — is skipped and reported.
  The discriminator is the object's metadata, not its key shape: an artifact id is deterministic and
  begins with a type slug, but title slugs and the configurable file extension make a key-shape match
  brittle, and a stray file can begin with a type slug by coincidence. Metadata is also free here —
  the scan already fetches it, so the check happens before any embedding or index write.
- Accepted trade-off: an artifact whose `type` metadata is missing or corrupt is skipped rather than
  indexed with an empty type. Such an artifact is already broken — `read_artifact` reports a blank
  type for it — and reporting it as unrecognisable is more honest than silently adding a typeless,
  titleless entry that then surfaces in searches and listings. `skipped_non_artifacts` is what keeps
  that case recoverable.

**Preconditions**

- All four clients required; re-indexing embeds, so `bedrock` is mandatory.
- Safe to run at any time, including concurrently with normal writes — it is idempotent with
  respect to already-consistent artifacts.

**Postconditions**

- Every `reconciled` entry carries a `source` discriminator naming which mechanism dealt with it:
  `failure_log` (replayed from the failure log and re-indexed), `orphan_scan` (an S3 key found with no
  vectors and re-indexed), `orphan_vector_cleanup` (leftover orphan vector keys deleted, nothing
  re-indexed), or `failure_log_obsolete` (entry dropped because its artifact no longer exists, nothing
  re-indexed). `reconciled` therefore means "this entry was dealt with", not "this artifact was
  re-indexed" — two of the four sources index nothing, and a consumer counting re-index work must
  filter on `source` rather than on the list's length.

- Returns `reconciled`, `failed`, `failure_log_entries_before`, `failure_log_entries_after`,
  `orphans_found`, `total_reconciled`, `dangling_artifacts_found`, `dangling_vectors_pruned`, and
  `dangling_artifacts`.
- `stuck_failures` is present **only when non-empty**, so its presence is itself the signal that
  manual intervention is required.
- `skipped_non_artifacts` — the own-scope keys the orphan scan found without vectors and declined to
  index, per the artifacts-only invariant above — is present **only when non-empty**, on the same
  terms as `stuck_failures`. Probe keys are excluded from the scan entirely and never appear in it.
  A skipped key does **not** count towards `orphans_found`, which counts artifact orphans needing
  re-index rather than every candidate key the scan examined. Probe keys are already excluded before
  that count for the same reason, and the two categories of "not an artifact" must agree: a permanent
  stray object would otherwise hold `orphans_found` at a non-zero floor on every future run, so an
  operator watching it trend to zero would never see it arrive. Strays are reported in
  `skipped_non_artifacts` instead, where their persistence is the point rather than a false signal.
- A successfully reconciled entry is pruned from the failure log. `failure_log_entries_after`
  counts what the log holds after the end-of-run rewrite, which re-reads it under the appender's
  lock and removes only the entries this run resolved — so an entry another writer appended while
  the run was in flight is retained and counted, and `failure_log_entries_after` is not guaranteed
  to be lower than `failure_log_entries_before` when that happens.
- An artifact rejected by the budget check is not silently retried into the same failure; it lands
  in `failed` or `stuck_failures`.
