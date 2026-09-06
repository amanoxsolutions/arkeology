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
  by: "architect"
  date: 2026-09-06
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

- `not_found` — no such artifact in the own scope, including the case where a concurrent delete
  removes the object between the initial read and a compare-and-swap retry's re-read. Nothing has
  been written in that case, so no failure-log entry is appended.
- `access_denied` — the artifact is not in the own scope. Archiving is own-scope only; a foreign
  artifact can never be archived.
- `conflict` — the bounded compare-and-swap retry cycle was exhausted on the status re-PUT.
- `annotation_unavailable` — the read-forward or the re-apply failed because the durable link store
  is unavailable or access to it is denied. This is the same code every other tool returns for this
  condition — see `s3-annotations.artifact` for the single-code rule and where the mapping lives.
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
- Across compare-and-swap attempts the read-forward values **accumulate** rather than being replaced,
  but only while the object's `last_edited_ulid` is unchanged from the attempt the accumulation
  started under. An attempt's own status re-PUT clears the annotations, so the next attempt reads
  them back as absent; replacing on that reading would archive away the link fields the first
  attempt had already read, which is what the accumulation exists to prevent.
- When a retry's re-read finds a **different** `last_edited_ulid`, a concurrent write has landed
  between attempts and its annotation value is the authoritative one. `references` is then reset to
  exactly the freshly read value — discarding what earlier attempts accumulated — and the ULID it
  was read under becomes the new accumulation baseline. `commit_refs` keeps accumulating across that
  boundary, being append-only and already carried forward by that concurrent write. Accumulating
  `references` across it instead would undo the removals that write made, contradicting its replace
  semantics (see `arkeology.tools.write`) in the same way the reconcile replay's union once did.
  `last_edited_ulid` is the token here for the same reasons it is in `arkeology.tools.reconcile`:
  archive never alters it, so it moves only when a write establishes new `references` truth.
- **Any** failure of the annotation re-apply after the status flip is durable leaves a failure-log
  entry — credential, compare-and-swap exhaustion, or an unknown transient error alike. At that
  point S3 says `inactive`, the re-PUT has cleared the annotations, and the vectors still say
  `active`; without an entry `reconcile_index` sees a fully indexed artifact and never repairs any
  of it. A genuinely unknown error is re-raised after recording, so it still surfaces as
  `internal_error` to the caller; a diagnosable one takes its own code instead, per the
  annotation-unavailable invariant below.
- That entry's `failure_step` names the step that actually failed — a retry's re-read, the
  annotation read, the content fetch, the status re-PUT, the annotation re-apply, or the vector flip
  — rather than one value standing for all six. Whether an entry is recorded is keyed on durability;
  what it is stamped with is keyed on cause. Nothing branches on the value; see
  `arkeology.tools.reconcile` for the field's rule.
- That entry also carries the read-forward `commit_refs` and `references` as two **optional**
  fields, for the same reason the write path does: they have no other surviving source once the
  re-PUT cleared the annotations. Absence means "nothing to restore", never "clear the field". It
  further carries the object's `last_edited_ulid` — which archive preserves rather than regenerates
  — so a write landing after the entry moves the ULID and `reconcile_index` discards the entry's
  `references` on replay, while its `commit_refs` still unions.
- A failed re-apply is never reported as a success, whatever its cause. An annotation-unavailable
  failure takes the same failure-log entry as any other — annotations are the sole durable store for
  both link fields and the re-PUT has already cleared them — and then returns
  `annotation_unavailable` rather than `internal_error`, because the condition is diagnosable and
  the code should name it. At runtime an unavailability failure means post-setup IAM drift: startup
  check 8 proves availability before the server accepts a request.
- The own-scope `referenced_by` check is **warn-but-don't-block**, with reversible-action phrasing.
  It never prevents the archive.
- The check covers `source_artifacts` **only**. `references`-based referrers are not detected,
  because `references` is no longer in vector metadata and an unbounded full-corpus annotation scan
  was evaluated and rejected. An own-scope artifact referencing the archived one only via
  `references` will not appear in the warning — a known, accepted gap.
- Referrer detection is own-scope only. A foreign-scope referrer identifier must never appear in a
  warning.

**Preconditions**

- Referrer detection covers **active** referrers only. An archived synthesis that still names this
  artifact in its `source_artifacts` produces no warning. This is deliberate and consistent with
  `check_synthesis_freshness`, which likewise audits only active syntheses: archiving is the signal
  that an artifact is out of active use, so warning about it would be noise the operator has already
  dismissed. The information is deferred rather than lost — if such a synthesis is later returned to
  active status, the freshness audit reports the deleted source under `missing_sources` at the point
  it becomes relevant again. A caller needing the stricter check must query archived syntheses itself.
- `artifact_id` is a full own-scope S3 key.

**Postconditions**

- On success, returns `{"artifact_id": str, "status": "inactive"}`, plus `"referrers"` (referring
  artifact ids) and `"warning_message"` when own-scope referrers were found. There is no
  `"annotation_warning"` key: a failed link-field re-apply is an error, not a warning.
- The artifact remains fully readable by `read_artifact` — archiving is not deletion.
- Link fields are unchanged in value across the operation.
