---
type: Spec
id: p2-t8-search-artifacts
title: T8 — Search Artifacts Tool
description: Feature spec for the search_artifacts MCP tool that performs semantic vector search with a re-fetch loop, cross-scope gate enforcement, and metadata filter support.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-08-12-status-all-sentinel-convention.md
    title: The `status="all"` Sentinel as a Cross-Tool Convention for Query-Shaped Tools
    last_modified: 2026-09-25T00:00:00Z
generated:
  by: "axians-architect/unknown"
  at: 2026-05-30T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-10T06:08:45Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T8 — Search Artifacts Tool

## TL;DR

`search_artifacts` is the MCP tool through which an agent starting a new session issues a natural
language query and receives the most relevant artifacts — metadata only, never content — from its
own scope plus shared artifacts from subscribed foreign scopes. A re-fetch loop turns
section-level vector hits into artifact-level results, and the cross-scope gate enforces the
tier 3 + shared visibility contract server-side, with metadata filters narrowing the result set.

## 1. Problem Statement

Storage without retrieval is archiving, not memory. The search tool is where the value of
Arkeology becomes real: an agent starting a new session issues a natural language query and
receives the most relevant artifacts from its own scope plus any shared artifacts from
subscribed foreign scopes — without fetching full content. The re-fetch loop handles the
fundamental mismatch between section-level vector granularity and artifact-level result
granularity, and the cross-scope gate enforces the tier 3 + shared visibility contract
without relying on infrastructure-level controls. Its four user stories — finding prior work via
semantic search, the server-side cross-scope gate, the bounded re-fetch loop, and metadata filters
— are all priority P1.

## 2. Rules — Query

### R1 — The query is embedded and matched by semantic similarity

When `search_artifacts` is called, it embeds the query using `settings.bedrock_embedding_model`
before querying the index, and returns the most relevant artifacts by semantic similarity,
metadata only.

**Example**

- Given an artifact written with type="code_review" and three sections, when `search_artifacts` is
  called with a query semantically related to one section, then that artifact appears in the
  results.

### R2 — `top_k` default and cap

When no `top_k` is provided, `search_artifacts` uses `settings.search_default_top_k`. When `top_k`
exceeds 100, it is capped at 100 and the search proceeds. The query returns up to `top_k` distinct
artifacts — no artifact appears twice.

**Example**

- Given `top_k=3` and five matching artifacts in the index, when `search_artifacts` returns, then
  exactly three artifacts are in the result list.

## 3. Rules — Cross-scope gate

### R3 — Own scope is unrestricted

When querying the own scope (WRITE_PREFIX), no cross-scope gate is applied — all tiers and
visibility values are accessible. An own-scope tier 2 hidden artifact is present in the results.

### R4 — Foreign scopes return tier 3 shared artifacts only

When querying a subscribed foreign scope (READ_PREFIXES), results are restricted to tier=3 AND
visibility="shared" artifacts only, enforced server-side. A foreign-scope tier 2 artifact must never
surface in search results, regardless of its visibility setting. Results that do not pass the
cross-scope gate are silently excluded — no error, no partial result with a warning.

**Example**

- Given a tier 2 artifact in a subscribed foreign scope, when `search_artifacts` is called, then
  that artifact is absent from the results even if it matches the query perfectly.
- Given a tier 3 shared artifact in a subscribed foreign scope, when `search_artifacts` is called,
  then that artifact appears in the results if it matches the query.
- Given a tier 3 hidden artifact in a subscribed foreign scope, when `search_artifacts` is called,
  then that artifact is absent from the results.

### R5 — The `scope` metadata field identifies the owning deployment

The `scope` field in vector metadata encodes the owning deployment's WRITE_PREFIX. It is the field
used to distinguish own-scope vectors from foreign-scope vectors in a shared index.

## 4. Rules — Filters

### R6 — User metadata filters narrow the result set

The filter for each S3 Vectors call includes the user-provided metadata filters (type, tags, team,
project, tier); each excludes artifacts that do not match. The `tags` filter uses
`{"tags": {"$eq": tag}}` — S3 Vectors `$eq` on an array field returns true if the value matches
**any element** in the array — so an artifact must have the requested tag in its list.

**Example**

- Given `type="code_review"` filter and a mix of types in the index, when `search_artifacts` is
  called, then all returned artifacts have `type == "code_review"`.
- Given `tags=["payments"]` filter and artifacts with various tags, when `search_artifacts` is
  called, then all returned artifacts have `"payments"` in their `tags`.
- Given `tier=3` filter, when `search_artifacts` returns, then all results are tier 3.

### R7 — `status` defaults to active-only, with two explicit overrides

The filter for each S3 Vectors call includes a `status="active"` gate, so archived artifacts are
excluded by default:

| `status` argument | Outcome |
|-------------------|---------|
| Omitted | Active artifacts only |
| `"active"` / `"inactive"` | Validated and filtered normally — `"inactive"` returns archived artifacts only |
| `"all"` | The status clause is omitted from the filter entirely, so artifacts are returned regardless of status |
| Anything else (e.g. `"activ"`) | `validation_error` — the result set is never silently widened by an unrecognised value |

(Formerly the **Revised (2026-08-12)** note under Requirements.) `status="all"` is recognised as an explicit all-inclusive sentinel, identically to
`list_artifacts`. It is checked before enum validation and is never matched as a literal. `"all"`
is the only recognised sentinel. Omitting `status` means active-only, so archived artifacts are
excluded unless asked for — which is what FR-05 requires "by default" and what its wording already
permits to be overridden. The adr-2026-08-12-status-all-sentinel-convention ADR holds the rationale
and the cross-tool convention binding any future tool that exposes a `status` parameter.

**Example**

- Given a mix of active and archived artifacts matching the query, when `search_artifacts` is
  called without a `status` argument, then only active artifacts are returned.
- Given the same mix, when `search_artifacts` is called with `status="all"`, then both active and
  archived artifacts are returned.

**Why the sentinel is never matched as a literal:** `"all"` is not an `ArtifactStatus` member, so
filtering on the string would match no stored status and silently return zero results on every
call.

**Why `"all"` is accepted:** a caller holding an explicit "any status" filter —
`arkeology_studio`'s status facet, which defaults to `"all"` — could otherwise neither forward it
(search would error on the facet's own default) nor omit it (search would silently return
active-only results while the UI displays "All").

Source: FR-05, adr-2026-08-12-status-all-sentinel-convention

## 5. Rules — Query structure and re-fetch loop

### R8 — One combined query per iteration

`search_artifacts` issues **one** `query_vectors` call per iteration — not one per scope — using a
combined `$or` filter that covers own scope (unrestricted) and all foreign scopes (tier=3 +
visibility=shared). The filter for each call includes the user-provided metadata filters, the
status gate, and `artifact_id $nin already_seen_ids`, which excludes already-seen artifact IDs from
each subsequent iteration. Cross-scope filter structure per iteration:

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

- If `settings.read_prefixes_list` is empty, drop the `$or` wrapper entirely — use a plain
  `{"scope": {"$eq": settings.write_prefix}}` filter.
- On the first iteration, `seen_artifact_ids` is empty; omit the `$nin` clause entirely (the API
  requires a non-empty array; an empty seen set means no exclusions are needed).
- The `$nin` array grows each iteration. At 100 artifacts × ~60 chars each the payload is ~6 KB —
  well within service limits.

`$nin`, `$in`, `$eq`, `$ne`, `$and`, `$or`, and `$exists` are all confirmed supported by S3 Vectors
(source: AWS S3 Vectors metadata filtering documentation). No over-fetch fallback is needed.

**Why one combined query:** S3 Vectors supports `$or`, so the own-scope gate and all foreign-scope
gates can be expressed in one filter; this is simpler and makes fewer API calls.

### R9 — Section vectors are grouped by artifact

When the index returns multiple section vectors for the same artifact, they are grouped by
`artifact_id` and only the highest-scoring section's score is kept as the artifact score.

### R10 — The re-fetch loop stops early or at the iteration cap

The index contains many section vectors per artifact; the loop groups them by artifact and
collects the requested count without looping forever. When a full iteration produces zero new
artifact IDs, the loop stops early (index exhausted) rather than running to
`SEARCH_MAX_ITERATIONS`. When `SEARCH_MAX_ITERATIONS` is reached, `search_artifacts` returns
whatever artifacts have been collected so far — this is not an error.

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

**Example**

- Given `top_k=5` and `SEARCH_MAX_ITERATIONS=3`, when fewer than 5 matching artifacts exist across
  all iterations, then `search_artifacts` returns whatever it found (fewer than 5) and does not
  raise an error.
- Given `top_k=5` and the index is exhausted after iteration 2 (no new artifact IDs found), when
  `search_artifacts` returns, then exactly 2 iterations ran — the loop did not run to
  `SEARCH_MAX_ITERATIONS`.
- Given `top_k=5` and `SEARCH_MAX_ITERATIONS=2`, when 10 matching artifacts exist, then at most 2
  S3 Vectors query calls are made and up to 5 results are returned.

### R11 — Results are merged and re-ranked by score

When results span own scope and foreign scopes, all results are merged and re-ranked by score
descending before returning.

## 6. Rules — Response

### R12 — Each result carries metadata only, never content

When `search_artifacts` returns, each result includes: `artifact_id`, `score` (float), `type`,
`team`, `project`, `tier`, `date`, `status`, `title`, `visibility`, `tags`, `author_role` (null if
absent), `description`, `source_artifacts` (list of artifact IDs the result was synthesised from;
empty list for non-synthesis artifacts). Never `content`: search results never include full
artifact content, and any field derived from S3 object content is forbidden in the response.

Source: NFR-02

### R13 — Zero results are signalled, not an error

When the index returns zero results across all iterations, `search_artifacts` returns an empty
list with a `"zero_results"` signal field — distinguishable from a service error.

### R14 — Credential errors return a structured response

When a `CredentialError` is raised at any point, `search_artifacts` returns a structured error
response — never a raw exception.

## 7. Boundaries

**Always:**
- The tool function receives `settings`, `s3` (unused in this tool but injected for consistency),
  `vectors`, and `bedrock` as injected dependencies.

**Ask First:**
- None.

**Never:**
- Do not fetch S3 object content during search — all data returned must come from S3 Vectors
  metadata.
- Do not return more than 100 artifacts regardless of `top_k`.
- Do not expose the `scope` internal metadata field in the MCP response.

## 8. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_search.py` | Create | Written first (Red) |
| `src/arkeology/tools/search.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_search.py` | Create | Written before integration wiring |
| `src/arkeology/server.py` | Modify | Register `search_artifacts` tool on `_app` |

### Contracts

None.

### Testing Approach

**TDD cycle A (unit):** write `test_tools_search.py` first → fail → implement `tools/search.py` →
unit tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

**`test_tools_search.py` — unit tests (FakeVectorsClient + FakeBedrockClient):**

Seed the fake with a known set of vectors covering: own scope + foreign scope, tier 2 + tier 3,
shared + hidden visibility, multiple sections per artifact, active + archived.

Happy path (R1, R2, R11, R12):
- Query returns up to `top_k` distinct artifacts (no artifact appears twice).
- Results contain no `content` field.
- Score is a float; results are ordered by score descending.
- `artifact_id` in each result matches a key present in the fake index.

Metadata filters (R6, R7) — test each independently:
- `type` filter excludes wrong-type artifacts.
- `tags` filter: artifact must have the requested tag in its list.
- `team` filter excludes wrong-team artifacts.
- `project` filter excludes wrong-project artifacts.
- `tier` filter excludes wrong-tier artifacts.
- Default active-only gate: archived (`status="inactive"`) artifacts are excluded.

Cross-scope gate (R3, R4):
- Tier 2 foreign-scope artifact: absent from results regardless of query match.
- Tier 3 shared foreign-scope artifact: present in results when it matches.
- Tier 3 hidden foreign-scope artifact: absent from results.
- Own-scope tier 2 hidden artifact: present in results.

Re-fetch loop (R2, R8, R10) — the test tracks a single `query_vectors` call per iteration, not one
per scope:
- With `top_k=2` and 5 artifacts in fake: exactly 2 returned.
- Loop stops early when no new artifact IDs found in an iteration (exhaust the fake index by
  setting top_k very high on the fake, then verify iteration count via call tracking).
- `SEARCH_MAX_ITERATIONS=1` cap: only one round of queries, however many scopes.
- `top_k` defaults to `settings.search_default_top_k` when not provided.
- `top_k` capped at 100.

Zero results (R13):
- Empty fake → result list is empty; `zero_results` signal present in response.

Credential failure (R14):
- Bedrock credential failure (embed) → structured error, no vectors query attempted.
- Vectors credential failure → structured error.

**`test_tools_search.py` — integration tests (`@pytest.mark.integration`):**

Prerequisites: run after T7 integration tests have written known artifacts.
- Write three artifacts (via T7 tool or directly via clients); search with a semantically related
  query; verify at least one of the three appears in results.
- Metadata filter `type` reduces results correctly.
- Zero-result query (semantically unrelated query on a small index) returns empty list without
  error.
- Confirm the combined single-query approach works end-to-end: own-scope result and a
  foreign-scope tier 3 shared result both appear; a foreign-scope tier 2 result is absent.
