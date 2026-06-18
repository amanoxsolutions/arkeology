---
type: spec
title: T16 — Synthesise Artifacts Tool
description: Feature spec for the synthesise_artifacts MCP tool that combines semantic search with batch content retrieval so an agent can assemble source artifacts for in-context synthesis in a single call.
tags: []
timestamp: 2026-05-30T00:00:00Z
okf_version: "0.1"
feature: p3-t16-synthesise-artifacts
status: ready
phase: 3
task: 16
references: []
authored:
  by: "architect"
  date: "2026-05-30"
revised:
  by: ""
  date: ""
---

# T16 — Synthesise Artifacts Tool

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Search returns ranked metadata — enough to decide which artifacts matter, but not enough to
act on them. When an agent needs to synthesise knowledge across multiple prior artifacts
(e.g. combine three ADRs into a design recommendation, or distil five code reviews into a
summary), it currently has to issue one `read_artifact` call per result and reassemble the
content manually. `synthesise_artifacts` collapses that into a single call: semantic search
+ batch read, returning full content for the top-k results in one response. The agent
performs the synthesis in-context and writes the result back using `write_artifact` with
`type="synthesis"` and `source_artifacts=[...]`. The server retrieves and assembles; the
synthesis is always the agent's job.

## User Stories

### Story 1 — Agent assembles source content in a single call (P1)

An agent wants to synthesise the last five code reviews on the auth module into a
consolidated findings report.

**Acceptance criteria:**
- Given several artifacts related to a topic, when `synthesise_artifacts` is called with a
  matching query, then the response contains full content for each of the top results, not
  just metadata.
- Each entry in the response includes: `artifact_id`, `type`, `team`, `project`, `tier`,
  `date`, `status`, `title`, `visibility`, `tags`, `author_role`, `description`,
  and `content`.
- The number of results is bounded by the `top_k` parameter (default 10, ceiling 100).

### Story 2 — Cross-scope gate is enforced (P1)

The same gate that applies to `search_artifacts` and `read_artifact` applies here.

**Acceptance criteria:**
- Given a tier 2 artifact in a foreign scope, when `synthesise_artifacts` is called with a
  query that would match it, then the foreign-scope tier 2 artifact is absent from results.
- Given a tier 3 shared artifact in a foreign scope, when `synthesise_artifacts` is called,
  then the foreign-scope tier 3 shared artifact appears in results with full content.

### Story 3 — Response is bounded by top_k ceiling (P1)

**Acceptance criteria:**
- Given `top_k=3`, when `synthesise_artifacts` is called, then at most 3 artifacts are
  returned regardless of how many match the query.
- Given `top_k` not provided, when `synthesise_artifacts` returns, then at most 10
  artifacts are returned (default).
- Given `top_k=150` (above ceiling), when `synthesise_artifacts` is called, then it is
  clamped to 100 — not an error.

### Story 4 — Credential errors return structured responses (P1)

**Acceptance criteria:**
- Given a credential failure during the embed call, search, or any read, when
  `synthesise_artifacts` returns, then a structured error is returned — not a raw exception.

## Requirements

- WHEN `synthesise_artifacts` is called THE SYSTEM SHALL perform a semantic search using
  the same logic as `search_artifacts`, applying the cross-scope gate and any supplied
  metadata filters.
- WHEN a `top_k` is provided THE SYSTEM SHALL clamp it to `min(top_k, 100)`; when absent
  THE SYSTEM SHALL use 10 as the default.
- WHEN the search returns results THE SYSTEM SHALL fetch full content for each result via
  the same logic as `read_artifact` — applying the cross-scope gate before fetching the S3
  object.
- WHEN an individual artifact's content fetch fails (not-found or access-denied) THE SYSTEM
  SHALL skip that artifact and continue fetching the remaining results.
- WHEN all content has been assembled THE SYSTEM SHALL return a list of result objects,
  each containing: `artifact_id`, `content`, `type`, `team`, `project`, `tier`, `date`,
  `status`, `title`, `visibility`, `tags`, `author_role`, `description`.
- WHEN the search returns no results THE SYSTEM SHALL return an empty list — not an error.
- WHEN a CredentialError is raised THE SYSTEM SHALL return a structured error — never a raw
  exception.
- THE SYSTEM SHALL NOT perform the synthesis itself; the response is source material only.

## Boundaries

**Always:**
- The cross-scope gate is the same as `search_artifacts` and `read_artifact`; the synthesis
  tool adds no new access rules.
- `top_k` is clamped to 100 (not rejected); the ceiling matches `search_artifacts` maximum.
- Individual S3 read failures per artifact are swallowed (skip + log) so a single
  unreadable artifact does not abort the entire synthesis assembly.
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` as injected dependencies.
- The tool may be implemented by composing the search and read logic internally — it does
  not call the MCP tool functions directly; it uses the underlying client calls.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not perform the synthesis in the server — return source content; synthesis is the
  agent's responsibility.
- Do not return more than 100 artifacts regardless of caller input.
- Do not raise raw exceptions.
- Do not include `content` in search results for artifacts whose content fetch failed —
  skip the artifact entirely.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_synthesise.py` | Create | Written first (Red) |
| `src/cairn_mcp/tools/synthesise.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_synthesise.py` | Create | Written before integration wiring |
| `src/cairn_mcp/server.py` | Modify | Register `synthesise_artifacts` tool on `_app` |

## Testing Approach

**TDD cycle A (unit):** write `test_tools_synthesise.py` first → fail → implement
`tools/synthesise.py` → unit tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

---

**`test_tools_synthesise.py` — unit tests (all three fakes: FakeS3, FakeVectors, FakeBedrock):**

Seed the fake vector index with several artifacts of different types and scopes (own-scope
tier 2, own-scope tier 3 shared, foreign-scope tier 2, foreign-scope tier 3 shared). Seed
fake S3 with their content. Seed fake Bedrock with fixed embedding vectors.

Happy path:
- Query with no filters → top results returned with full content.
- Each result dict contains: `artifact_id`, `content`, `type`, `team`, `project`, `tier`,
  `date`, `status`, `title`, `visibility`, `tags`, `author_role`, `description`.
- `tags` is a list, not a comma-separated string.
- `content` matches the content written in fake S3.

top_k:
- `top_k=2` → at most 2 results.
- `top_k` absent → at most 10 results.
- `top_k=150` → clamped to 100; no error.

Cross-scope gate:
- Foreign-scope tier 2 artifact → excluded from results.
- Foreign-scope tier 3 shared → included with full content.
- Foreign-scope tier 3 hidden → excluded.

Resilience:
- One artifact's S3 read fails (fake raises `KeyError`) → that artifact skipped; other
  results still returned.
- Search returns no results → empty list, no error.

Credential failures:
- Embed call raises `CredentialError` → structured error response.
- `query_vectors` raises `CredentialError` → structured error response.
- `get_object` raises `CredentialError` on first artifact → structured error response
  (credential errors are hard failures, unlike not-found which is skipped).

**`tests/integration/test_tools_synthesise.py` — integration tests (`@pytest.mark.integration`):**

Teardown: all artifacts written during the test must be deleted via `delete_artifact`.

- Write 3 artifacts; call `synthesise_artifacts` with matching query and `top_k=2` → 2
  results with full content.
- Verify all required fields present in each result.
- `synthesise_artifacts` with non-matching query → empty list, no error.

## Open Questions

*(none — all constraints are defined)*
