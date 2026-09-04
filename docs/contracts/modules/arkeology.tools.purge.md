---
type: Contract
title: arkeology.tools.purge
description: The purge_archived MCP tool — hard-deletes every inactive artifact in the own scope, cascading to synthesis artifacts whose every source is in the purge set, and reporting per-artifact outcomes rather than aborting on first failure.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p3-t13-purge-archived.md
  - docs/specs/p3-t12-delete-artifact.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: ""
  date: YYYY-MM-DD
---

# arkeology.tools.purge

## Scope

The bulk irreversible destruction boundary. This is the widest-blast-radius tool in the surface —
it deletes an unbounded set in one call — so its confirmation gate, scope restriction, and
partial-outcome reporting are the contract.

## Symbols

### purge_archived

```python
async def purge_archived(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    confirm: bool = False,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Systemic failures are a returned dict carrying an `"error"` key; per-artifact
failures are reported in the `failed` list instead.

- `confirmation_required` — `confirm` was not `True`. Returned before anything is deleted.
- `credential_error` — raised during discovery, or mid-loop. A mid-loop credential failure still
  reports the artifacts already purged rather than discarding that progress.
- `delete_vectors_failed` / `partial_delete` — surfaced per artifact in `failed`, with the same
  meanings as in `delete_artifact`.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- `confirm=True` is mandatory; the default is `False`.
- Own scope only. A foreign-scope artifact is never purged regardless of its status or visibility.
- Only `inactive` artifacts are eligible. An `active` artifact is never touched, so
  `archive_artifact` is a required prior step and acts as the deliberate two-stage gate on
  permanent deletion.
- Cascade deletion applies to a synthesis artifact only when **every** one of its
  `source_artifacts` is in the purge set. A synthesis retaining at least one surviving source is
  left intact — partial-source syntheses are never destroyed.
- Per-artifact deletion follows `delete_artifact`'s vectors-first, S3-second ordering, so a
  worst-case per-artifact failure leaves a recoverable S3 orphan.
- A single artifact's failure does not abort the run. The loop continues and reports.
- `purged_count` and `purged_ids` reflect artifacts **actually fully deleted** — S3 object removed.
  An artifact that failed part-way is in `failed`, never counted as purged.

**Preconditions**

- `confirm=True`, set deliberately.
- The caller has established that every archived artifact in scope is genuinely disposable — the
  tool takes no per-artifact selection, so it cannot express "purge all but this one".

**Postconditions**

- Returns `{"purged_count": int, "purged_ids": [...], "cascade_deleted": [...], "failed": [...]}`.
- `failed` is empty when all succeeded; each entry is
  `{"artifact_id": str, "error": str, "message": str}`.
- `cascade_deleted` lists the cascade syntheses actually deleted, distinct from `purged_ids`.
- Re-running after a partially failed run is safe: already-purged artifacts are simply no longer
  discoverable as inactive.
