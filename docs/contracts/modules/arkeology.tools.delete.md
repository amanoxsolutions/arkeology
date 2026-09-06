---
type: Contract
title: arkeology.tools.delete
description: The delete_artifact MCP tool — irreversibly removes one own-scope artifact's S3 object and every section vector, vectors-first so a partial failure leaves a recoverable orphan rather than orphaned vectors.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p3-t12-delete-artifact.md
  - docs/specs/p12-t50-referenced-by-warning.md
  - docs/specs/p12-t60-narrow-reverse-lookup-warning.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: ""
  date: YYYY-MM-DD
---

# arkeology.tools.delete

## Scope

The irreversible destruction boundary for a single artifact. For a store whose purpose is never
losing memory, this is the highest-consequence tool in the surface, and its confirmation gate and
ordering guarantees are the contract.

## Symbols

### delete_artifact

```python
async def delete_artifact(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_id: str,
    confirm: bool = False,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Every failure is a returned dict carrying an `"error"` key.

- `confirmation_required` — `confirm` was not `True`. Returned before anything is deleted.
- `not_found` — no such artifact in the own scope.
- `access_denied` — the artifact is not in the own scope.
- `delete_vectors_failed` — the vector deletion failed; the S3 object was **not** touched, so the
  artifact remains fully intact and the call is safe to retry.
- `partial_delete` — vectors were deleted but the S3 object removal failed, leaving a recoverable
  S3 orphan that `reconcile_index` can re-index.
- `credential_error` — an AWS call raised `CredentialError`.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- `confirm=True` is mandatory. The default is `False`, so an accidental call deletes nothing.
- Own-scope only, tested via `startswith(scope + "/")`. A foreign artifact can never be deleted.
- **Deletion order is vectors-first, S3-second, and may not be reversed.** The worst case under this
  order is an S3 orphan — content still present, searchability lost, fully repairable by
  `reconcile_index`. The reverse order's worst case is orphaned vectors pointing at absent content,
  which is not repairable from the remaining state.
- The own-scope `referenced_by` check is **warn-but-don't-block**, with permanent-action phrasing
  stronger than `archive_artifact`'s. It never prevents the deletion.
- The check covers `source_artifacts` **only**; `references`-based referrers are not detected. An
  own-scope artifact referencing the deleted one only via `references` will not appear in the
  warning — a known, accepted gap.
- The synthesis reference check is scoped to the own scope only. A foreign-scope synthesis
  identifier must never appear in a delete warning.

**Preconditions**

- `artifact_id` is a full own-scope S3 key.
- The caller has already surfaced the consequences to a human, or is acting on explicit human
  instruction — the confirmation gate is the tool's only protection and it cannot distinguish an
  agent's `True` from a user's.

**Postconditions**

- On success, returns `{"artifact_id": str, "deleted": True}`, plus `"warnings"` and
  `"warning_message"` when own-scope referrers were found.
- On success both stores are clean: no S3 object, no section vectors.
- On `delete_vectors_failed` nothing was deleted from either store.
- On `partial_delete` the S3 object remains and is discoverable by `reconcile_index`.
- Every failure response after the vector deletion has been attempted carries `vectors_deleted`
  (bool). The error code still names what the caller must act on — a credential failure stays
  `credential_error` — so `vectors_deleted` is the only thing distinguishing "the vectors are gone
  and the S3 object still stands" from a delete that never started. Without it a caller cannot tell
  a half-deleted artifact (unsearchable but not destroyed, and repairable by `reconcile_index`) from
  one left completely intact.
