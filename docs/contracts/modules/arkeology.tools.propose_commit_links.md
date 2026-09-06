---
type: Contract
title: arkeology.tools.propose_commit_links
description: The propose_commit_links MCP tool — read-only discovery of own-scope artifacts carrying no commit_refs, optionally bounded to those written since a session-start ULID, deciding eligibility from each artifact's durable S3 object annotations.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p10-t37-propose-commit-links.md
  - docs/specs/p10-t35-filter-range-operators.md
  - docs/specs/p12-t58-commit-refs-cap-references-removal.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "architect"
  date: 2026-09-06
---

# arkeology.tools.propose_commit_links

## Scope

The discovery half of the commit-linking pair: it proposes, `link_metadata` writes. Keeping the
read and write halves separate is what lets an agent surface candidates for approval without any
risk of mutation.

## Symbols

### propose_commit_links

```python
async def propose_commit_links(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    commit_sha: str,
    since_ulid: str | None = None,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Every failure is a returned dict carrying an `"error"` key.

- `credential_error` — a `CredentialError` from any store read aborts the whole call, including a
  per-candidate link-field read.
- `annotation_unavailable` — the durable link-field annotation read failed because the annotation
  store is unavailable or access to it is denied. Startup check 8 proves availability before the
  server accepts a request, so at runtime this means post-setup IAM drift; the code names that
  condition instead of collapsing it into `internal_error`. It is the same code every other tool
  returns for this condition — see `s3-annotations.artifact` for the single-code rule and where the
  mapping lives.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- **Strictly read-only.** No write to S3, to annotations, or to the vector index, under any
  argument combination. The tool has no confirmation gate because it needs none.
- Own scope only. A foreign-scope artifact is never proposed.
- Eligibility — whether `commit_refs` is empty — is decided from the artifact's S3 object
  annotations, their sole source of truth, **not** from a single vector's metadata. The vector copy
  is a capped, derived filter index, so a multi-section artifact whose `commit_refs` live on another
  section vector, or which aged out of the cap, would otherwise be silently re-proposed as unlinked
  on every call.
- Per-candidate link-field reads are issued **concurrently**, not one sequential call per candidate.
- A failure on any candidate's link-field read aborts the call rather than degrading that candidate
  to "not yet linked". Annotations are the sole source of truth, so a degraded candidate would be
  indistinguishable from a genuinely unlinked one and would be proposed for linking on the strength
  of a transient error.
- `since_ulid` is optional. When absent, all unlinked own-scope artifacts are returned regardless of
  age — absence means "no lower bound", never "none".
- `s3` is required, not optional. The server injects a real client into every tool call, so this
  narrows an already-always-satisfied signature.

**Preconditions**

- `commit_sha` is opaque to the tool — a full SHA, short SHA, PR URL, or tag are all valid and none
  is validated for format.

**Postconditions**

- Returns `{"proposed": [...], "commit_sha": "<commit_sha>"}`, echoing the input `commit_sha` so a
  caller can pipe the result straight into `link_metadata` without re-threading it.
- One entry per distinct artifact, never per section vector.
- Calling it twice with the same arguments returns the same proposals — it has no side effect that
  would change its own answer.
