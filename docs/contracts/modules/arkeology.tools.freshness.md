---
type: Contract
title: arkeology.tools.freshness
description: The check_synthesis_freshness MCP tool — audits synthesis artifacts for stale, archived, and missing sources, and for structurally malformed empty-source syntheses, optionally hard-deleting the malformed ones on explicit confirmation.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p5-t22-synthesis-freshness-check.md
  - docs/specs/p3-t16-synthesise-artifacts.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "architect"
  date: 2026-09-04
---

# arkeology.tools.freshness

## Scope

The synthesis-integrity audit. A synthesis is a derived artifact whose value decays as its sources
change; this tool reports that decay and is the one place a destructive cleanup is offered as a
side effect of an audit.

## Symbols

### check_synthesis_freshness

```python
async def check_synthesis_freshness(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    confirm: bool = False,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Every failure is a returned dict carrying an `"error"` key.

- `credential_error` — an AWS call raised `CredentialError`, at the list step or mid-scan.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- With `confirm=False` — the default — the tool is **strictly read-only**. It audits and reports;
  it deletes nothing. An audit that could destroy data by default would be unsafe to run for
  information.
- With `confirm=True` it hard-deletes **only structurally malformed syntheses**: those with an empty
  `source_artifacts`. A stale, archived-source, or missing-source synthesis is reported but **never**
  deleted, at any `confirm` value — those are judgement calls for the caller.
- Source lookup applies the cross-scope gate. It must not query source artifacts by bare
  `artifact_id` with no scope clause and no tier/visibility check: that was a real gate-bypass
  defect, leaking the existence, archival state, and update recency of foreign tier-2 and hidden
  artifacts that `read_artifact` would deny. A source that fails the gate is reported in
  `missing_sources`, **indistinguishable from a genuinely absent one** — that collapse is deliberate,
  not an approximation. A separate "inaccessible" category would itself leak the fact that a foreign
  tier-2 or hidden artifact exists, which is the very disclosure this invariant exists to prevent, so
  no such category may be added.
- Own-scope only for the destructive path.
- The audit covers **active** syntheses only; an archived synthesis is not audited. Consistent with
  the active-only referrer detection in `delete_artifact` and `archive_artifact` — archiving marks an
  artifact as out of active use, and auditing it would report problems the operator has already set
  aside. Returning such a synthesis to active status brings it back into the audit.
- Staleness is determined by comparing each source's **write recency** against the synthesis's,
  using `last_edited_ulid` — monotonic, bumped by every content write, and deliberately left
  untouched by operations that must not mark a synthesis stale (a link-field backfill, an archive
  status flip, a reconcile re-index). It is **not** `date`, which is the artifact's *subject* date
  rather than its write time. Comparing `date` was wrong in both directions: it missed a tier-3
  source overwritten in place under an unchanged date, and it flagged a later-dated source that was
  actually written before the synthesis and is therefore already reflected in it.
- `date` remains the fallback when either side lacks a `last_edited_ulid` — artifacts written before
  it was recorded compare no worse than they did before.
- `confirm=True` only when the caller intends the malformed-synthesis deletion. It is not required
  for the audit.

**Postconditions**

- Returns `stale`, `archived_sources`, `missing_sources`, `malformed`, `deleted_malformed`,
  `total_checked`, and `all_fresh`.
- `deleted_malformed` is empty whenever `confirm` was `False`, which is what makes a default-mode
  run provably non-destructive.
- `all_fresh` is a convenience summary; a caller must not infer from it that no malformed syntheses
  exist without reading `malformed`.
- Every reported category is disjoint enough to act on independently — a caller can address
  malformed syntheses without touching stale ones.
