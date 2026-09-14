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
  - docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "architect"
  date: 2026-09-14
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
  only at `tier == 3` and `visibility == "shared"`. An absent or unparseable `tier` or `visibility`
  denies; the gate never raises over a stored value.
- **A malformed candidate is skipped, never fatal.** A vector entry whose stored metadata cannot be
  read into a listing entry — no usable `artifact_id`, a `tier` that will not coerce — is dropped
  and the page continues. One unreadable record must not withhold every readable one on the page.
  The skip is counted and reported, never silent. A candidate the gate denied is not a skip and is
  never counted: counting it would disclose that a foreign artifact exists.
- **An artifact whose object is gone is omitted from the page and counted; a failed link-field read
  is not.** The distinction is what the read established. An `ObjectNotFoundError` from the durable
  link store is not a read that failed — it answered definitively that the artifact no longer
  exists, so omitting it from a listing is the correct result rather than a lossy one, and failing a
  read-only call over a benign concurrent delete would be disproportionate when a retry can meet the
  same race. Nothing can be written over empty here: this tool only reads.
- **A failed or ambiguous link-field read still fails the whole listing.** A transient failure, a
  permission denial, and an unclassified not-found establish nothing about absence, so none may
  become an artifact listed with empty `commit_refs`/`references` — indistinguishable from one that
  genuinely has none, with no second copy of those fields to recover from. The page is recoverable
  by asking again. See `s3-annotations.artifact` under **Not-Found Semantics** for which error means
  which.
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
- `skipped_malformed_count` is included **only when non-zero**, so its presence is itself the signal
  that the page omits records this call could not read. It is a count, not a list of ids: the
  identifier is frequently the very field that is missing, and an id list is the one place a
  gated-out foreign artifact could be named.
- `skipped_deleted_count` is included on the same terms, counting artifacts whose object was found
  to be gone during the link-field read and were therefore omitted. It is a **separate** key from
  `skipped_malformed_count` and the two must not be merged: this one is ordinary churn, routinely
  non-zero and self-healing — reconcile prunes the leftover vectors as a dangling artifact — while a
  non-zero malformed count means corrupt stored data that wants investigation. One shared number
  would sit at a floor set by the benign cause, and the serious one would never surface. A single
  occurrence needs no action; persistence across runs does.
- These two are the only conditional keys in the response; `artifacts` is unconditional.
- A failed or ambiguous link-field read for one artifact surfaces as an error for the whole call —
  never as a successful listing in which that artifact reports empty `commit_refs`/`references`.
  This is the same rule as the corresponding invariant above, stated from the caller's side.
