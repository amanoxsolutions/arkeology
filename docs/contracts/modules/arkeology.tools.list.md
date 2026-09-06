---
type: Contract
title: arkeology.tools.list
description: The list_artifacts MCP tool — metadata-only listings from the vector index with metadata filtering and cross-scope gate enforcement, with link fields resolved from each artifact's durable S3 object annotations.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p3-t10-list-artifacts.md
  - docs/specs/p10-t41-rename-feature-tags-to-tags.md
  - docs/specs/p12-t58-commit-refs-cap-references-removal.md
  - docs/specs/p12-t59-remove-references-filter-param.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "architect"
  date: 2026-09-06
---

# arkeology.tools.list

## Scope

The browse boundary: filtered, metadata-only enumeration with no embedding call and no content
fetch. Distinct from `search_artifacts`, which is semantic and returns content.

## Symbols

### list_artifacts

```python
async def list_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    type: str | None = None,
    tags: list[str] | None = None,
    commit_refs: list[str] | None = None,
    team: str | None = None,
    project: str | None = None,
    tier: int | None = None,
    status: str = "active",
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Every failure is a returned dict carrying an `"error"` key.

- `validation_error` — an invalid filter value, e.g. a `type` outside `ARTIFACT_TYPES`.
- `credential_error` — an AWS call raised `CredentialError`, including during the concurrent
  link-field resolution.
- `annotation_unavailable` — the durable link-field annotation read failed because the annotation
  store is unavailable or access to it is denied. Startup check 8 proves availability before the
  server accepts a request, so at runtime this means post-setup IAM drift; the code names that
  condition instead of collapsing it into `internal_error`. It is the same code every other tool
  returns for this condition — see `s3-annotations.artifact` for the single-code rule and where the
  mapping lives.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- Metadata-only. No Bedrock embedding call, and no S3 object body is fetched.
- The cross-scope gate applies to every candidate: own-scope always listable; foreign-scope listable
  only at `tier == 3` and `visibility == "shared"`.
- `status` defaults to `"active"`, so archived artifacts are excluded unless explicitly requested.
- `commit_refs` and `references` are resolved from each artifact's S3 object annotations, their sole
  source of truth, **not** read off whichever single section vector happened to be returned. A
  multi-section artifact can otherwise surface an arbitrary section's stale, capped copy.
- The whole call issues **exactly one** vector-index scan — its own page query — regardless of page
  size. The retired union read model cost one additional full index scan per artifact in the page,
  because the vector copy of `commit_refs` has no server-side filter and can only be matched in
  memory. A page of 200 artifacts performed 200 such scans.
- A failed annotation read for any artifact in the page surfaces as an error rather than degrading
  that artifact to empty link fields.
- `tags` filtering matches an individual element, relying on vector metadata storing `tags` as
  `list[str]`.
- The `commit_refs` **filter** is a server-side `$eq` against the vector-metadata copy, which
  `s3vectors.artifact` caps to the most-recent 20 entries. Filtering therefore searches that bounded
  window, **not** an artifact's full commit history: an artifact linked to 25 commits is not returned
  for any of its five oldest SHAs, even though `read_artifact` and this tool's own returned
  `commit_refs` field (annotation-sourced) do show them. The asymmetry is inherent to the
  vector cap and cannot be closed inside the filter — a caller needing an exhaustive commit lookup
  must read candidates and match `commit_refs` itself.
- There is **no** `references` filter parameter. It was removed outright when `references` stopped
  being written to vector metadata; this is a deliberate breaking change, not an omission.
- `references` returned to a foreign-scope reader is filtered to independently-readable targets,
  which costs one additional batched query page.

**Preconditions**

- Filter values must be well-formed for their field; `tier` is an int, `status` one of the artifact
  status values.

**Postconditions**

- Returns `{"artifacts": [...]}` — metadata per artifact, never `content`.
- One entry per artifact, not per section vector, regardless of how many section vectors an
  artifact has.
- A link-field read failure for one artifact degrades that artifact's `commit_refs`/`references` to
  empty rather than aborting the whole listing.
