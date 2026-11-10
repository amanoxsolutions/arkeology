---
type: Spec
id: p3-t16-synthesise-artifacts
title: T16 — Synthesise Artifacts Tool
description: Feature spec for the synthesise_artifacts MCP tool that combines semantic search with batch content retrieval so an agent can assemble source artifacts for in-context synthesis in a single call.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-30T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T12:01:40Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T16 — Synthesise Artifacts Tool

## TL;DR

`synthesise_artifacts` collapses a semantic search and a batch read into a single call, returning full
content for the top-k results so an agent can synthesise knowledge across prior artifacts without one
`read_artifact` call per result. The server only retrieves and assembles source material under the same
cross-scope gate as search and read, bounded by a `top_k` count ceiling and a response-size budget; the
synthesis itself is always the agent's job.

## 1. Problem Statement

Search returns ranked metadata — enough to decide which artifacts matter, but not enough to act on them.
When an agent needs to synthesise knowledge across multiple prior artifacts (e.g. combine three ADRs
into a design recommendation, or distil five code reviews into a summary — such as the last five code
reviews on the auth module into a consolidated findings report), it currently has to issue one
`read_artifact` call per result and reassemble the content manually. `synthesise_artifacts` collapses
that into a single call: semantic search + batch read, returning full content for the top-k results in
one response. The agent performs the synthesis in-context and writes the result back using
`write_artifact` with `type="synthesis"` and `source_artifacts=[...]`. The server retrieves and
assembles; the synthesis is always the agent's job.

All four stories this spec covers are priority P1.

## 2. Rules — Retrieval

### R1 — One call searches, then fetches full content for each result

When `synthesise_artifacts` is called, the system performs a semantic search using the same logic as
`search_artifacts`, applying the cross-scope gate and any supplied metadata filters. When the search
returns results, the system fetches full content for each result via the same logic as `read_artifact`
— applying the cross-scope gate before fetching the S3 object.

**Example**

- Given several artifacts related to a topic, when `synthesise_artifacts` is called with a matching
  query, then the response contains full content for each of the top results, not just metadata.

Source: none

### R2 — The cross-scope gate is the same as search and read

The cross-scope gate is the same as `search_artifacts` and `read_artifact`; the synthesis tool adds no
new access rules.

**Example**

- Given a tier 2 artifact in a foreign scope, when `synthesise_artifacts` is called with a query that
  would match it, then the foreign-scope tier 2 artifact is absent from results.
- Given a tier 3 shared artifact in a foreign scope, when `synthesise_artifacts` is called, then the
  foreign-scope tier 3 shared artifact appears in results with full content.

Source: none

### R3 — An unreadable artifact is skipped, not fatal

When an individual artifact's content fetch fails (not-found or access-denied), the system skips that
artifact and continues fetching the remaining results. Individual S3 read failures per artifact are
swallowed (skip + log) so a single unreadable artifact does not abort the entire synthesis assembly.

Source: none

## 3. Rules — Bounds

### R4 — `top_k` defaults to 10 and is clamped to 100

When a `top_k` is provided, the system clamps it to `min(top_k, 100)`; when absent, the system uses 10
as the default. `top_k` is clamped to 100 (not rejected); the ceiling matches the `search_artifacts`
maximum.

**Example**

- Given `top_k=3`, when `synthesise_artifacts` is called, then at most 3 artifacts are returned
  regardless of how many match the query.
- Given `top_k` not provided, when `synthesise_artifacts` returns, then at most 10 artifacts are
  returned (default).
- Given `top_k=150` (above ceiling), when `synthesise_artifacts` is called, then it is clamped to 100 —
  not an error.

Source: none

### R5 — A response-size budget bounds total content

The `top_k` count ceiling bounds the number of results but not their total size, which could still
grow unboundedly with the ceiling raised. A configurable response-size (byte) budget sits on top of it —
`SYNTHESISE_MAX_RESPONSE_BYTES`, measured as the UTF-8-encoded byte length of each result's `content`
field. Results are assembled in rank order and assembly stops before adding any result that would push
the total response past the budget, even if the requested count has not yet been reached; when assembly
stops for this reason, the response adds `truncated: true` plus an `included: N` count of results
actually returned (both fields are omitted when no truncation occurs, so a normal ~10-artifact synthesis
is unaffected). The single exception: if the very first ranked candidate alone exceeds the budget, it is
included anyway (never return zero results for a single relevant oversized hit) with `truncated: true`
still set. The count ceiling (100) remains in force as a secondary, cheaper guard, not the primary
bound.

Source: none

### R6 — The response-size budget defaults to 1 MB

`SYNTHESISE_MAX_RESPONSE_BYTES` defaults to **1,000,000 bytes (1 MB)**.

Rationale for the 1 MB default: requirements.md FR-19 / NFR-02.

Source: FR-19, NFR-02

## 4. Rules — Response

### R7 — Each result carries full content and metadata

When all content has been assembled, the system returns a list of result objects, each containing:
`artifact_id`, `content`, `type`, `team`, `project`, `tier`, `date`, `status`, `title`, `visibility`,
`tags`, `author_role`, `description`.

Source: none

### R8 — No search results return an empty list

When the search returns no results, the system returns an empty list — not an error.

Source: none

### R9 — Credential errors return a structured error

When a `CredentialError` is raised — a credential failure during the embed call, search, or any read —
the system returns a structured error, never a raw exception.

Source: none

### R10 — The server returns source material and never synthesises

The system does not perform the synthesis itself; the response is source material only.

Source: none

## 5. Boundaries

**Always:**
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` as injected dependencies.
- The tool may be implemented by composing the search and read logic internally — it does not call the
  MCP tool functions directly; it uses the underlying client calls.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not perform the synthesis in the server — return source content; synthesis is the agent's
  responsibility.
- Do not return more than 100 artifacts regardless of caller input.
- Do not raise raw exceptions.
- Do not include `content` in search results for artifacts whose content fetch failed — skip the
  artifact entirely.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_synthesise.py` | Create | Written first (Red) |
| `src/arkeology/tools/synthesise.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_synthesise.py` | Create | Written before integration wiring |
| `src/arkeology/server.py` | Modify | Register `synthesise_artifacts` tool on `_app` |

### Contracts

None.

### Testing Approach

**TDD cycle A (unit):** write `test_tools_synthesise.py` first → fail → implement
`tools/synthesise.py` → unit tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

**`test_tools_synthesise.py` — unit tests (all three fakes: FakeS3, FakeVectors, FakeBedrock):**

Seed the fake vector index with several artifacts of different types and scopes (own-scope tier 2,
own-scope tier 3 shared, foreign-scope tier 2, foreign-scope tier 3 shared). Seed fake S3 with their
content. Seed fake Bedrock with fixed embedding vectors.

Happy path:
- Query with no filters → top results returned with full content.
- Each result dict contains: `artifact_id`, `content`, `type`, `team`, `project`, `tier`, `date`,
  `status`, `title`, `visibility`, `tags`, `author_role`, `description`.
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
- One artifact's S3 read fails (fake raises `KeyError`) → that artifact skipped; other results still
  returned.
- Search returns no results → empty list, no error.

Credential failures:
- Embed call raises `CredentialError` → structured error response.
- `query_vectors` raises `CredentialError` → structured error response.
- `get_object` raises `CredentialError` on first artifact → structured error response (credential
  errors are hard failures, unlike not-found which is skipped).

**`tests/integration/test_tools_synthesise.py` — integration tests (`@pytest.mark.integration`):**

Teardown: all artifacts written during the test must be deleted via `delete_artifact`.

- Write 3 artifacts; call `synthesise_artifacts` with matching query and `top_k=2` → 2 results with
  full content.
- Verify all required fields present in each result.
- `synthesise_artifacts` with non-matching query → empty list, no error.
