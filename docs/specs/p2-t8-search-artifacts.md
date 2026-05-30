---
type: feature-spec
feature: p2-t8-search-artifacts
created: 2026-05-30
status: ready
phase: 2
task: 8
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
- Given a tier 3 confidential artifact in a subscribed foreign scope, when `search_artifacts`
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
- Given `feature_tags=["payments"]` filter and artifacts with various tags, when
  `search_artifacts` is called, then all returned artifacts have `"payments"` in their
  `feature_tags`.
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
  metadata filters (type, feature_tags, team, project, tier), a `status="active"` gate
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
  `feature_tags`, `author_role` (null if absent), `description`. Never `content`.
- WHEN a CredentialError is raised at any point THE SYSTEM SHALL return a structured error
  response — never a raw exception.
- WHEN the index returns zero results across all iterations THE SYSTEM SHALL return an empty
  list with a `"zero_results"` signal field — distinguishable from a service error.

## Boundaries

**Always:**
- Queries run independently per scope in each iteration: one S3 Vectors call for the own
  scope, one per READ_PREFIXES entry. The cross-scope gate is applied as an additional
  metadata filter on each READ_PREFIXES query, not as post-processing.
- The `$nin` filter on `artifact_id` excludes already-seen artifact IDs from each subsequent
  iteration. If S3 Vectors does not support `$nin`, use the over-fetch fallback (see Open
  Questions).
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
3, shared + confidential visibility, multiple sections per artifact, active + archived.

Happy path:
- Query returns up to `top_k` distinct artifacts (no artifact appears twice).
- Results contain no `content` field.
- Score is a float; results are ordered by score descending.
- `artifact_id` in each result matches a key present in the fake index.

Metadata filters (test each independently):
- `type` filter excludes wrong-type artifacts.
- `feature_tags` filter: artifact must have the requested tag in its list.
- `team` filter excludes wrong-team artifacts.
- `project` filter excludes wrong-project artifacts.
- `tier` filter excludes wrong-tier artifacts.
- Default active-only gate: archived (`status="inactive"`) artifacts are excluded.

Cross-scope gate:
- Tier 2 foreign-scope artifact: absent from results regardless of query match.
- Tier 3 shared foreign-scope artifact: present in results when it matches.
- Tier 3 confidential foreign-scope artifact: absent from results.
- Own-scope tier 2 confidential artifact: present in results.

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
- **Integration checkpoint:** Verify S3 Vectors supports `$nin` operator on the `artifact_id`
  field. If not supported, fall back to over-fetch strategy and record in `plan.md` under
  Learnings.
- Zero-result query (semantically unrelated query on a small index) returns empty list
  without error.

## Open Questions

- [ ] S3 Vectors `$nin` support on `artifact_id` metadata field: **must be verified in
  integration tests before implementing the re-fetch loop**. If `$nin` is not supported,
  use the over-fetch fallback: multiply `SEARCH_FETCH_TOP_K` by the current iteration number
  on each call and deduplicate client-side. Document which approach is used.
- [ ] Per-scope vs single combined query: does querying the shared index once with a combined
  own-scope + foreign-scope filter perform better than separate per-scope queries? Start with
  per-scope queries (simpler to reason about the cross-scope gate); optimise only if
  integration tests reveal unacceptable latency.
- [ ] Multi-scope result merging: when own-scope and foreign-scope queries return results in
  the same iteration, should they be merged before deduplication or after? Merge after
  deduplication within each scope result set, then re-rank globally.
