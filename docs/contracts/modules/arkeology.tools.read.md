---
type: Contract
title: arkeology.tools.read
description: The read_artifact MCP tool — fetches one artifact's content and metadata from S3, applying the cross-scope tier and visibility gate before any content is fetched.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p2-t9-read-artifact.md
  - docs/specs/p12-t46-references-field.md
  - docs/specs/p12-t55-metadata-validation.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "architect"
  date: 2026-09-14
---

# arkeology.tools.read

## Scope

The single-artifact read boundary. This is one of the two places the cross-scope access gate is
enforced on a direct fetch, so its gate behaviour is a security contract, not a convenience.

## Symbols

### read_artifact

```python
async def read_artifact(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface | None = None,
    bedrock: BedrockClientInterface | None = None,
    artifact_id: str,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Every failure is a returned dict carrying an `"error"` key.

- `not_found` — the artifact does not exist in any readable scope. Also returned when the object is
  found to be gone part-way through the read — an `ObjectNotFoundError` from the durable link-field
  annotation read, meaning it was deleted between the metadata fetch and that read. That race
  reports absence, never empty link fields; see `s3-annotations.artifact` under **Not-Found
  Semantics** for why the three not-found causes are distinguishable at all.
- `access_denied` — the artifact exists in a foreign scope but fails the tier and visibility gate.
- `corrupt_metadata` — the artifact's stored metadata could not be read into the response. The
  message names the offending field and its value. Today `tier` is the only field this can apply to,
  because it is the only one coerced rather than passed through.
- `credential_error` — an AWS call raised `CredentialError`, at the metadata fetch, the content
  fetch, the link-field annotation read, or the foreign-scope reference filtering step.
- `annotation_unavailable` — the durable link-field annotation read failed because the annotation
  store is unavailable or access to it is denied. Startup check 8 proves availability before the
  server accepts a request, so at runtime this means post-setup IAM drift; the code names that
  condition instead of collapsing it into `internal_error`. It is the same code every other tool
  returns for this condition — see `s3-annotations.artifact` for the single-code rule and where the
  mapping lives.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- The scope and access-control gate is applied **before** content is fetched. A denied read never
  transfers the object body.
- Own-scope membership is tested as `artifact_id.startswith(scope + "/")`, never a bare
  `startswith(scope)`.
- **Corrupt stored metadata fails loudly and specifically, and is never defaulted.** This tool
  returns one artifact and so has nothing to skip: where an iterating tool drops a malformed
  candidate and counts it, this one returns `corrupt_metadata` naming the field. It must not
  substitute a value the writer never stored — `tier` is one of the two fields the cross-scope gate
  keys on, so a read reporting a defaulted `tier` teaches its caller a value the gate did not agree
  to. `internal_error` is equally excluded: the cause is known and nameable.
- **The gate's verdict pre-empts the corruption report.** A foreign-scope artifact whose `tier` is
  absent or unparseable is denied by the gate and returns `access_denied`, never
  `corrupt_metadata` — reporting the stored state of an artifact the gate has just withheld would
  disclose exactly what the denial exists to withhold. `corrupt_metadata` is therefore reachable on
  an own-scope read, or on a foreign artifact the gate has already admitted whose other fields are
  corrupt.
- A foreign-scope artifact is readable only when its stored `tier` is 3 **and** its `visibility` is
  `"shared"`. An absent or unparseable `tier` or `visibility` is not an affirmative reading and
  denies; the gate never raises over a stored value. Any other foreign artifact is denied with
  `access_denied`, which is deliberately
  distinguishable from `not_found`: the spec (see `docs/specs/p2-t9-read-artifact.md`, "Never")
  forbids silently downgrading a gated foreign artifact to "not found", so that a caller can tell
  why retrieval failed. Existence in a foreign scope is therefore observable; only the artifact's
  metadata and content are withheld.
- `references` returned to a **foreign-scope** reader is filtered to targets that reader is
  independently permitted to read. Own-scope reads return `references` exactly as stored.
- A title sourced from S3 object metadata is decoded via `decode_metadata_value`, so it can never
  disagree with the title `search_artifacts` returns for the same artifact.

**Preconditions**

- `artifact_id` is the full S3 key, including the scope prefix and file extension.

**Postconditions**

- On success, returns all artifact fields including `content`.
- `commit_refs` and `references` are sourced from the artifact's S3 object annotations, their sole
  source of truth, and never from vector metadata.
- An own-scope read issues **zero** vector-index scans. The vector-metadata copy of `commit_refs` is
  a derived filter index with no server-side filter of its own, so reading it back would mean
  paginating the whole index once per artifact. Reintroducing that is the regression this forbids.
- A failed annotation read surfaces as an error. It is never degraded into a successful read
  reporting empty link fields, which a caller could not distinguish from an artifact that has
  none.
- Denial reveals nothing beyond the error code — no title, no metadata, no content, no
  `references`. The error code itself does distinguish denial from absence, by design.
