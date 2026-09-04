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
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: ""
  date: YYYY-MM-DD
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
- Failure-log entries are classified by their own shape — the presence of `orphan_keys` marks the
  cheap orphan-cleanup kind — so a reindex-kind and an orphan-cleanup-kind entry for the same
  artifact are processed and pruned independently.
- Dangling vectors, whose S3 object no longer exists, are pruned rather than re-indexed.

**Preconditions**

- All four clients required; re-indexing embeds, so `bedrock` is mandatory.
- Safe to run at any time, including concurrently with normal writes — it is idempotent with
  respect to already-consistent artifacts.

**Postconditions**

- Returns `reconciled`, `failed`, `failure_log_entries_before`, `failure_log_entries_after`,
  `orphans_found`, `total_reconciled`, `dangling_artifacts_found`, `dangling_vectors_pruned`, and
  `dangling_artifacts`.
- `stuck_failures` is present **only when non-empty**, so its presence is itself the signal that
  manual intervention is required.
- A successfully reconciled entry is pruned from the failure log, so
  `failure_log_entries_after < failure_log_entries_before` on any productive run.
- An artifact rejected by the budget check is not silently retried into the same failure; it lands
  in `failed` or `stuck_failures`.
