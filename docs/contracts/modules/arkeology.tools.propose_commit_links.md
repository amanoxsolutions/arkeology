---
type: Contract
title: arkeology.tools.propose_commit_links
description: The propose_commit_links MCP tool — read-only discovery of own-scope artifacts carrying no commit_refs, optionally bounded to those written since a session-start ULID, deciding eligibility from the union of both durable stores.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p10-t37-propose-commit-links.md
  - docs/specs/p10-t35-filter-range-operators.md
  - docs/specs/p12-t58-commit-refs-cap-references-removal.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: ""
  date: YYYY-MM-DD
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
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- **Strictly read-only.** No write to S3, to annotations, or to the vector index, under any
  argument combination. The tool has no confirmation gate because it needs none.
- Own scope only. A foreign-scope artifact is never proposed.
- Eligibility — whether `commit_refs` is empty — is decided from the union-of-both-durable-stores
  read, **not** from a single vector's metadata. A multi-section artifact whose `commit_refs` live
  on a section vector other than the one deduplication kept would otherwise be silently
  re-proposed as unlinked on every call.
- Per-candidate link-field reads are issued **concurrently**, not one sequential call per candidate.
- A non-`CredentialError` failure on one candidate's link-field read degrades that candidate to
  "not yet linked" rather than aborting the call. A supplementary read failure for one candidate
  must not hide every other candidate's proposal.
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
