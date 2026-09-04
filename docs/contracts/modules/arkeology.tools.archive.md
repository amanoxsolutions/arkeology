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
  therefore reads the current link fields forward via the union-of-both-stores model before the
  re-PUT and re-applies them afterwards. Removing that read-forward silently destroys
  `commit_refs` and `references` on every archive.
- The re-PUT is guarded by ETag compare-and-swap.
- `AnnotationUnavailableError` degrades gracefully — warn, do not fail the archive — while
  `CredentialError` aborts. Archiving is not the tool whose purpose is the durable link write, so
  unlike `link_metadata` it does not surface `annotation_unavailable` as a hard error.
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
  artifact ids) and `"warning_message"` when own-scope referrers were found.
- The artifact remains fully readable by `read_artifact` — archiving is not deletion.
- Link fields are unchanged in value across the operation.
