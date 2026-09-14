---
type: Contract
title: arkeology.tools.search
description: The search_artifacts MCP tool — embeds a natural-language query and returns the most semantically similar artifacts subject to the cross-scope gate, with explicit transparency flags when the result set was limited by something other than the true match count.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p2-t8-search-artifacts.md
  - docs/specs/p12-t54-search-age-transparency.md
  - docs/specs/p10-t41-rename-feature-tags-to-tags.md
  - docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "architect"
  date: 2026-09-14
---

# arkeology.tools.search

## Scope

The semantic recall boundary — the primary way an agent finds artifacts it cannot name. Its
transparency flags are part of the contract: a caller must be able to distinguish "nothing matched"
from "the loop gave up".

## Symbols

### search_artifacts

```python
async def search_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface | None = None,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    query: str,
    top_k: int | None = None,
    type: str | None = None,
    tags: list[str] | None = None,
    team: str | None = None,
    project: str | None = None,
    tier: int | None = None,
    status: str | None = None,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Every failure is a returned dict carrying an `"error"` key.

- `validation_error` — an invalid filter or parameter value.
- `credential_error` — an AWS call raised `CredentialError`, at the embed call or inside the
  shared `_search_helper.run_search_loop` re-fetch loop.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- `top_k` omitted uses the configured default. `top_k` above the 100 ceiling is **clamped, not
  rejected**, and the response says so via `clamped` and `effective_top_k`.
- Own-scope results pass no cross-scope gate. Foreign-scope results are restricted to `tier == 3`
  and `visibility == "shared"`. An absent or unparseable `tier` or `visibility` denies; the gate
  never raises over a stored value.
- **A malformed candidate is skipped, never fatal.** A vector entry whose stored metadata cannot be
  read into a result — no usable `artifact_id`, a `tier` that will not coerce — is dropped and the
  loop continues. One unreadable record in the index must not withhold every readable one beside it,
  which is what an escape to the catch-all does: the caller gets `internal_error` and no results at
  all. The skip is counted and reported, never silent.
- A candidate the cross-scope gate denied is **not** a skip and is never counted. Counting it would
  disclose that a foreign artifact exists, which is the disclosure the gate exists to prevent.
- Own-scope and foreign-scope results are merged and **re-ranked together**, so a caller never sees
  scope-ordered output masquerading as relevance-ordered.
- Multiple section vectors for one artifact collapse to a single result. The response is per
  artifact, never per section.
- `score` is `1.0 - cosine_distance`, i.e. cosine similarity in `[-1, 1]` where `1.0` is most
  similar. It is **not** a distance. The conversion is already applied before results are returned;
  a caller must not negate it or re-interpret it.
- The re-fetch loop stops early when a full iteration yields no new artifact ids, and stops at the
  configured maximum iterations, returning whatever it has rather than erroring.
- The loop's shared implementation lives in `_search_helper.run_search_loop` and is used by this
  tool and `synthesise_artifacts` alike. The loop is fixed there, never patched per tool.

**Preconditions**

- `query` is a natural-language string; it is embedded, so an empty query is not meaningful.
- `bedrock` and `vectors` are required. `s3` is optional because this tool returns metadata and
  scores, not content.

**Postconditions**

- Returns `{"artifacts": [...]}`, each entry carrying at least `artifact_id` and `score`.
- Zero matches returns `{"artifacts": [], "zero_results": True}` — an explicit signal, not an
  ambiguous empty list. `skipped_malformed_count` accompanies it when it applies, alongside
  `index_corruption_detected`: a zero result reached because every candidate was unreadable is
  precisely the case a caller must not mistake for "no such artifact exists".
- `fetch_exhausted: True` is included when the loop's own fetch budget, rather than the true number
  of matches, limited the count below `top_k`. More matches may exist.
- `index_corruption_detected: True` is included when the loop stopped because a vector result was
  missing its `distance` field. Whatever results were already collected are still returned; this is
  a soft signal, never a hard error.
- `skipped_malformed_count` is included **only when non-zero**, so its presence is itself the signal
  that the index holds records this call could not read. It is a count, not a list of ids: the
  identifier is frequently the very field that is missing, and an id list is the one place a
  gated-out foreign artifact could be named. A skipped candidate does not count towards the returned
  artifact total.
- These flags are the only way a caller can tell a short result set apart from an exhaustive
  one. Dropping any of them silently converts "incomplete" into "complete".
