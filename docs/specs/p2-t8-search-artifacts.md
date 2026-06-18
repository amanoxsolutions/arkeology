---
type: spec
title: T8 — Search Artifacts Tool
description: Feature spec for the search_artifacts MCP tool that performs semantic vector search with a re-fetch loop, cross-scope gate enforcement, and metadata filter support.
tags: []
timestamp: 2026-05-30T00:00:00Z
okf_version: "0.1"
feature: p2-t8-search-artifacts
status: ready
phase: 2
task: 8
references: []
authored:
  by: "architect"
  date: "2026-05-30"
revised:
  by: ""
  date: ""
---

# T8 — Search Artifacts Tool

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Storage without retrieval is archiving, not memory. The search tool is where the value of
cairn-mcp becomes real: an agent starting a new session issues a natural language query and
receives the most relevant artifacts from its own scope plus any shared artifacts from
subscribed foreign scopes — without fetching full content. The re-fetch loop handles the
fundamental mismatch between section-level vector granularity and artifact-level result
granularity, and the cross-scope gate enforces the tier 3 + shared visibility contract
without relying on infrastructure-level controls.

## User Stories

### Story 1 — Agent finds prior work via semantic search (P1)

A developer agent starting work on the `auth` module searches for prior artifacts. The
server returns the most relevant artifacts by semantic similarity, metadata only.

**Acceptance criteria:**
- Given an artifact written with type="code_review" and three sections, when
  `search_artifacts` is called with a query semantically related to one section, then that
  artifact appears in the results.
- Given `top_k=3` and five matching artifacts in the index, when `search_artifacts` returns,
  then exactly three artifacts are in the result list.
- Given a result list, when it is inspected, then no result contains a `content` field —
  only metadata and description.

### Story 2 — Cross-scope gate is enforced server-side (P1)

A foreign-scope tier 2 artifact must never surface in search results, regardless of its
visibility setting.

**Acceptance criteria:**
- Given a tier 2 artifact in a subscribed foreign scope, when `search_artifacts` is called,
  then that artifact is absent from the results even if it matches the query perfectly.
- Given a tier 3 shared artifact in a subscribed foreign scope, when `search_artifacts` is
  called, then that artifact appears in the results if it matches the query.
- Given a tier 3 hidden artifact in a subscribed foreign scope, when `search_artifacts`
   is called, then that artifact is absent from the results.

### Story 3 — Re-fetch loop collects the requested count without exceeding iteration cap (P1)

The index contains many section vectors per artifact. The loop must group them by artifact
and collect the right number without looping forever.

**Acceptance criteria:**
- Given `top_k=5` and `SEARCH_MAX_ITERATIONS=3`, when fewer than 5 matching artifacts exist
  across all iterations, then `search_artifacts` returns whatever it found (fewer than 5) and
  does not raise an error.
- Given `top_k=5` and the index is exhausted after iteration 2 (no new artifact IDs found),
  when `search_artifacts` returns, then exactly 2 iterations ran — the loop did not run to
  `SEARCH_MAX_ITERATIONS`.
- Given `top_k=5` and `SEARCH_MAX_ITERATIONS=2`, when 10 matching artifacts exist, then at
  most 2 S3 Vectors query calls are made and up to 5 results are returned.

### Story 4 — Metadata filters reduce the result set correctly (P1)

An agent wants only code reviews for the `payments` feature. The filter must exclude all
other types and feature tags.

**Acceptance criteria:**
- Given `type="code_review"` filter and a mix of types in the index, when `search_artifacts`
  is called, then all returned artifacts have `type == "code_review"`.
- Given `tags=["payments"]` filter and artifacts with various tags, when
  `search_artifacts` is called, then all returned artifacts have `"payments"` in their
  `tags`.
- Given `tier=3` filter, when `search_artifacts` returns, then all results are tier 3.

## Requirements

- WHEN `search_artifacts` is called THE SYSTEM SHALL embed the query using
  `settings.bedrock_embedding_model` before querying the index.
- WHEN no `top_k` is provided THE SYSTEM SHALL use `settings.search_default_top_k`.
- WHEN `top_k` exceeds 100 THE SYSTEM SHALL cap it at 100 and proceed.
- WHEN querying the own scope (WRITE_PREFIX) THE SYSTEM SHALL apply no cross-scope gate —
  all tiers and visibility values are accessible.
- WHEN querying a subscribed foreign scope (READ_PREFIXES) THE SYSTEM SHALL restrict results
  to tier=3 AND visibility="shared" artifacts only.
- WHEN building the filter for each S3 Vectors call THE SYSTEM SHALL include: user-provided
  metadata filters (type, tags, team, project, tier), a `status="active"` gate
  (archived artifacts excluded by default), and `artifact_id $nin already_seen_ids`.
- WHEN the index returns multiple section vectors for the same artifact THE SYSTEM SHALL
  group them by `artifact_id` and keep only the highest-scoring section's score as the
  artifact score.
- WHEN a full iteration produces zero new artifact IDs THE SYSTEM SHALL stop the loop early
  (index exhausted) rather than running to `SEARCH_MAX_ITERATIONS`.
- WHEN `SEARCH_MAX_ITERATIONS` is reached THE SYSTEM SHALL return whatever artifacts have
  been collected so far — this is not an error.
- WHEN results span own scope and foreign scopes THE SYSTEM SHALL merge and re-rank all
  results by score descending before returning.
- WHEN `search_artifacts` returns THE SYSTEM SHALL include per result: `artifact_id`, `score`
  (float), `type`, `team`, `project`, `tier`, `date`, `status`, `title`, `visibility`,
  `tags`, `author_role` (null if absent), `description`. Never `content`.
- WHEN a CredentialError is raised at any point THE SYSTEM SHALL return a structured error
  response — never a raw exception.
- WHEN the index returns zero results across all iterations THE SYSTEM SHALL return an empty
  list with a `"zero_results"` signal field — distinguishable from a service error.

## Boundaries

**Always:**
- Issue **one** `query_vectors` call per iteration using a combined `$or` filter that covers
  own scope (unrestricted) and all foreign scopes (tier=3 + visibility=shared). `$or`, `$nin`,
  `$in`, `$and`, and `$eq` are all confirmed supported by S3 Vectors.
- The `$nin` filter on `artifact_id` excludes already-seen artifact IDs from each subsequent
  iteration. Omit the `$nin` clause entirely on the first iteration (the API requires a
  non-empty array; an empty seen set means no exclusions are needed).
- The `scope` field in vector metadata encodes the owning deployment's WRITE_PREFIX. This is
  the field used to distinguish own-scope vectors from foreign-scope vectors in a shared
  index.
- Search results never include full artifact content (NFR-02). Any field derived from S3
  object content is forbidden in the response.
- Results that do not pass the cross-scope gate are silently excluded — no error, no partial
  result with a warning.
- The tool function receives `settings`, `s3` (unused in this tool but injected for
  consistency), `vectors`, and `bedrock` as injected dependencies.

**Ask First:**
- Whether to include `inactive` (archived) artifacts when `status` is explicitly passed as
  a filter parameter. Default assumed: passing `status="inactive"` overrides the default
  active-only gate.

**Never:**
- Do not fetch S3 object content during search — all data returned must come from S3 Vectors
  metadata.
- Do not return more than 100 artifacts regardless of `top_k`.
- Do not expose the `scope` internal metadata field in the MCP response.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_search.py` | Create | Written first (Red) |
| `src/cairn_mcp/tools/search.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_search.py` | Create | Written before integration wiring |
| `src/cairn_mcp/server.py` | Modify | Register `search_artifacts` tool on `_app` |

## Testing Approach

**TDD cycle A (unit):** write `test_tools_search.py` first → fail → implement
`tools/search.py` → unit tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

---

**`test_tools_search.py` — unit tests (FakeVectorsClient + FakeBedrockClient):**

Seed the fake with a known set of vectors covering: own scope + foreign scope, tier 2 + tier
3, shared + hidden visibility, multiple sections per artifact, active + archived.

Happy path:
- Query returns up to `top_k` distinct artifacts (no artifact appears twice).
- Results contain no `content` field.
- Score is a float; results are ordered by score descending.
- `artifact_id` in each result matches a key present in the fake index.

Metadata filters (test each independently):
- `type` filter excludes wrong-type artifacts.
- `tags` filter: artifact must have the requested tag in its list.
- `team` filter excludes wrong-team artifacts.
- `project` filter excludes wrong-project artifacts.
- `tier` filter excludes wrong-tier artifacts.
- Default active-only gate: archived (`status="inactive"`) artifacts are excluded.

Cross-scope gate:
- Tier 2 foreign-scope artifact: absent from results regardless of query match.
- Tier 3 shared foreign-scope artifact: present in results when it matches.
- Tier 3 hidden foreign-scope artifact: absent from results.
- Own-scope tier 2 hidden artifact: present in results.

Re-fetch loop:
- With `top_k=2` and 5 artifacts in fake: exactly 2 returned.
- Loop stops early when no new artifact IDs found in an iteration (exhaust the fake index
  by setting top_k very high on the fake, then verify iteration count via call tracking).
- `SEARCH_MAX_ITERATIONS=1` cap: only one round of queries, however many scopes.
- `top_k` defaults to `settings.search_default_top_k` when not provided.
- `top_k` capped at 100.

Zero results:
- Empty fake → result list is empty; `zero_results` signal present in response.

Credential failure:
- Bedrock credential failure (embed) → structured error, no vectors query attempted.
- Vectors credential failure → structured error.

**`test_tools_search.py` — integration tests (`@pytest.mark.integration`):**

Prerequisites: run after T7 integration tests have written known artifacts.
- Write three artifacts (via T7 tool or directly via clients); search with a semantically
  related query; verify at least one of the three appears in results.
- Metadata filter `type` reduces results correctly.
- Zero-result query (semantically unrelated query on a small index) returns empty list
  without error.
- Confirm the combined single-query approach works end-to-end: own-scope result and a
  foreign-scope tier 3 shared result both appear; a foreign-scope tier 2 result is absent.

## Filter and Query Structure — Decision

**All confirmed supported by S3 Vectors:** `$nin`, `$in`, `$eq`, `$ne`, `$and`, `$or`,
`$exists`. Source: AWS S3 Vectors metadata filtering documentation. No over-fetch fallback
is needed.

### Single combined query per iteration (not per-scope)

S3 Vectors supports `$or`, so the own-scope gate and all foreign-scope gates can be
expressed in one filter. Issue **one** `query_vectors` call per iteration, not one per
scope. This is simpler and makes fewer API calls.

Cross-scope filter structure per iteration:

```
{
  "$and": [
    <user_filters: type, tags, team, project, tier — omitted if not provided>,
    {"status": {"$eq": "active"}},
    {"artifact_id": {"$nin": [<already_seen_artifact_ids>]}},
    {
      "$or": [
        {"scope": {"$eq": "<settings.write_prefix>"}},
        {
          "$and": [
            {"scope": {"$in": [<settings.read_prefixes_list>]}},
            {"tier": {"$eq": 3}},
            {"visibility": {"$eq": "shared"}}
          ]
        }
      ]
    }
  ]
}
```

Notes:
- If `settings.read_prefixes_list` is empty, drop the `$or` wrapper entirely — use a plain
  `{"scope": {"$eq": settings.write_prefix}}` filter.
- On the first iteration, `seen_artifact_ids` is empty; drop the `$nin` clause entirely
  (the API requires a non-empty array).
- `tags` filter uses `{"tags": {"$eq": tag}}` — S3 Vectors `$eq` on an
  array field returns true if the value matches **any element** in the array.
- The `$nin` array grows each iteration. At 100 artifacts × ~60 chars each the payload is
  ~6 KB — well within service limits.

### Re-fetch loop — single-query variant

```
seen_ids = set()
results = []
for iteration in 1..SEARCH_MAX_ITERATIONS:
    build filter (omit $nin if seen_ids is empty, omit $or if no READ_PREFIXES)
    call query_vectors(query_vector, top_k=SEARCH_FETCH_TOP_K, filter=filter)
    group section vectors by artifact_id, keep max score per artifact
    new = [a for a in grouped if a.artifact_id not in seen_ids]
    if not new:
        break  # index exhausted — stop early
    results.extend(new)
    seen_ids.update(a.artifact_id for a in new)
    if len(results) >= top_k:
        break
return sorted(results, key=score, reverse=True)[:top_k]
```

Update unit tests accordingly: the re-fetch loop test now tracks a single `query_vectors`
call per iteration, not one per scope.

## Open Questions

*(none — all decisions resolved)*
