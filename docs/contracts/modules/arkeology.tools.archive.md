---
type: Contract
title: arkeology.tools.archive
description: The archive_artifact MCP tool — flips an artifact's status to inactive in S3 object metadata and every corresponding vector entry, preserving link fields across the status re-PUT that would otherwise wipe them.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p3-t11-archive-artifact.md
  - docs/specs/p12-t50-referenced-by-warning.md
  - docs/specs/p12-t60-narrow-reverse-lookup-warning.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: ""
  date: YYYY-MM-DD
---

# arkeology.tools.archive

## Scope

The reversible retirement boundary. Archiving hides an artifact from default listings and searches
without destroying it; `purge_archived` is what later makes it permanent.

## Symbols

### archive_artifact

```python
async def archive_artifact(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_id: str,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Every failure is a returned dict carrying an `"error"` key.

- `not_found` — no such artifact in the own scope.
- `access_denied` — the artifact is not in the own scope. Archiving is own-scope only; a foreign
  artifact can never be archived.
- `conflict` — the bounded compare-and-swap retry cycle was exhausted on the status re-PUT.
- `credential_error` — an AWS call raised `CredentialError`.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- Own-scope only, tested via `startswith(scope + "/")`.
- The status flip is applied to **both** S3 object metadata and **all** of the artifact's vector
  metadata entries. A partial flip that updates one store leaves the artifact inconsistent between
  browse and read paths.
- The status flip is an in-place S3 re-PUT, which **clears the object's annotations**. This tool
  therefore reads the current link fields forward from the annotations, their sole source of truth,
  before the re-PUT and re-applies them afterwards. Removing that read-forward silently destroys
  `commit_refs` and `references` on every archive.
- The re-PUT is guarded by ETag compare-and-swap.
- **Any** failure of the annotation re-apply after the status flip is durable leaves a failure-log
  entry — credential, compare-and-swap exhaustion, or an unknown transient error alike. At that
  point S3 says `inactive`, the re-PUT has cleared the annotations, and the vectors still say
  `active`; without an entry `reconcile_index` sees a fully indexed artifact and never repairs any
  of it. The unknown-error case is re-raised after recording, so it still surfaces as
  `internal_error` to the caller.
- That entry also carries the read-forward `commit_refs` and `references` as two **optional**
  fields, for the same reason the write path does: they have no other surviving source once the
  re-PUT cleared the annotations. Absence means "nothing to restore", never "clear the field".
- A failed re-apply is never reported as a success, whatever its cause. `AnnotationUnavailableError`
  is handled like any other unknown failure — failure-log entry, then a structured error — because
  annotations are the sole durable store for both link fields and the re-PUT has already cleared
  them. At runtime an unavailability failure means post-setup IAM drift: startup check 8 proves
  availability before the server accepts a request.
- The own-scope `referenced_by` check is **warn-but-don't-block**, with reversible-action phrasing.
  It never prevents the archive.
- The check covers `source_artifacts` **only**. `references`-based referrers are not detected,
  because `references` is no longer in vector metadata and an unbounded full-corpus annotation scan
  was evaluated and rejected. An own-scope artifact referencing the archived one only via
  `references` will not appear in the warning — a known, accepted gap.
- Referrer detection is own-scope only. A foreign-scope referrer identifier must never appear in a
  warning.

**Preconditions**

- `artifact_id` is a full own-scope S3 key.

**Postconditions**

- On success, returns `{"artifact_id": str, "status": "inactive"}`, plus `"warning"` (referring
  artifact ids) and `"warning_message"` when own-scope referrers were found. There is no
  `"annotation_warning"` key: a failed link-field re-apply is an error, not a warning.
- The artifact remains fully readable by `read_artifact` — archiving is not deletion.
- Link fields are unchanged in value across the operation.
