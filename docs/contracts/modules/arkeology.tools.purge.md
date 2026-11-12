---
type: Contract
id: arkeology.tools.purge
title: arkeology.tools.purge
description: The purge_archived MCP tool — hard-deletes every inactive artifact in the own scope, cascading to synthesis artifacts whose every source is in the purge set, and reporting per-artifact outcomes rather than aborting on first failure.
tags: []
okf_version: "0.2"
sources:
  - resource: docs/specs/p3-t13-purge-archived.md
    title: T13 — Purge Archived Tool
    last_modified: 2026-06-29T00:00:00Z
  - resource: docs/specs/p3-t12-delete-artifact.md
    title: T12 — Delete Artifact Tool
    last_modified: 2026-05-30T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-05-29-aws-backend-selection.md
    title: AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend
    last_modified: 2026-11-12T13:11:40Z
  - resource: docs/specs/p15-t92-numbered-vector-keys.md
    title: T92 — Numbered Vector Keys and Per-Artifact Vector Access by Key
    last_modified: 2026-11-12T13:11:40Z
  - resource: docs/specs/p1-t3-aws-client-layer.md
    title: T3 — AWS Client Layer
    last_modified: 2026-11-10T16:40:30Z
  - resource: .docs/reviews/architecture-review-2026-11-10-arkeology.md
    title: "Architecture review — Arkeology (whole design record)"
    last_modified: 2026-11-10T11:21:17Z
generated:
  by: "axians-tech-writer/claude-opus-5"
  at: 2026-09-04T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-12T13:11:40Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
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
- **Each artifact's vectors are read by key.** Each purged or cascade-deleted artifact's vectors are
  found by one `GetVectors` over `{artifact_id}#0` to `{artifact_id}#99` (`s3vectors.artifact`), and
  only the keys it returned are deleted, as in `delete_artifact`. The call's whole-index scans are
  its two scope-wide discovery steps — the inactive artifacts and the active syntheses for the
  cascade — so their number does not grow with how many artifacts it purges. A scan or a filtered
  query per purged artifact is the regression this forbids.
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
