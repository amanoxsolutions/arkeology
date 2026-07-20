---
type: spec
title: T10 — List Artifacts Tool
description: Feature spec for the list_artifacts MCP tool that provides metadata-only browsing of the artifact store with filter-driven retrieval and cross-scope gate enforcement.
tags: []
timestamp: 2026-05-30T00:00:00Z
okf_version: "0.1"
feature: p3-t10-list-artifacts
status: ready
phase: 3
task: 10
references: []
authored:
  by: "architect"
  date: "2026-05-30"
revised:
  by: "developer"
  date: "2026-07-05"
---

# T10 — List Artifacts Tool

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Semantic search is query-driven: an agent must already know what to ask for. But when
starting a new task or doing housekeeping, the agent may need to browse what exists — all
artifacts for a project, everything tagged with a feature, all archived docs from last month.
The list tool provides a metadata-only view across the artifact store with filter-driven
retrieval and no semantic ranking. It applies the same cross-scope gate as search and read:
own-scope artifacts are unrestricted; foreign-scope artifacts are limited to tier 3 shared.

## User Stories

### Story 1 — Agent browses all active artifacts for a project (P1)

An agent starting a session wants to see everything stored for the current project before
deciding where to focus.

**Acceptance criteria:**
- Given several active artifacts written with the same `project`, when `list_artifacts` is
  called with `project` filter, then all matching artifacts appear in the response with their
  metadata and description — no content.
- Given a mix of active and archived artifacts in the same project, when `list_artifacts` is
  called without a `status` override, then only active artifacts are returned.
- Given the same project with archived artifacts, when `list_artifacts` is called with
  `status="inactive"`, then only inactive artifacts are returned.

### Story 2 — Agent filters by type and feature tags (P1)

An agent reviewing the authentication module wants only code reviews tagged with `auth`.

**Acceptance criteria:**
- Given artifacts of various types and tags, when `list_artifacts` is called with
  `type="code_review"` and `tags=["auth"]`, then only artifacts matching both
  constraints are returned.
- Given no artifacts matching the combined filter, when `list_artifacts` returns, then an
  empty list is returned — not an error.

### Story 3 — Foreign-scope tier 3 shared artifacts are included (P1)

A microservices team subscribes to the platform scope. They should see platform ADRs in
their listing.

**Acceptance criteria:**
- Given a tier 3 shared artifact in a foreign scope, when `list_artifacts` is called without
  scope filters, then the artifact appears in the response.
- Given a tier 2 artifact in a foreign scope, when `list_artifacts` is called, then the
  artifact is excluded from results.
- Given a tier 3 hidden artifact in a foreign scope, when `list_artifacts` is called,
  then the artifact is excluded from results.

### Story 4 — Credential errors return structured responses (P1)

**Acceptance criteria:**
- Given a credential failure during the vector scan, when `list_artifacts` returns, then a
  structured error is returned — not a raw exception.

## Requirements

- WHEN `list_artifacts` is called THE SYSTEM SHALL query the vector index for all artifacts
  matching the supplied filters (type, tags, team, project, tier, status); if no
  filters are supplied THE SYSTEM SHALL return all active artifacts visible to this
  deployment.
- WHEN no `status` filter is provided THE SYSTEM SHALL default to `status="active"` (exclude
  archived artifacts).

> **Revised (2026-07-05).** `status="all"` is now recognised as an
> explicit all-inclusive sentinel: the status clause is omitted entirely, so both active and
> inactive own-scope (and eligible foreign-scope) artifacts are returned. This closed a bug in
> `cairn_studio`'s browser UI, where the "All" status filter option sent `value=""`, which
> `loadList` then omitted from the call arguments — falling through to the server's
> `status="active"` default and making "All" unreachable. Any other literal value (including
> the default `"active"`) still filters normally; `"all"` is the only recognised sentinel.
- WHEN filters are applied THE SYSTEM SHALL evaluate them server-side using the metadata
  stored in the vector index; no S3 reads are required for the list operation.
- WHEN cross-scope results are assembled THE SYSTEM SHALL include foreign-scope artifacts
  only if `tier=3` AND `visibility="shared"`; own-scope artifacts are never gated.

> **Forward-pointer note (2026-07-06, not yet shipped).** This spec predates the first-class
> `references` field (added by `p12-t46`) and its return in each `list_artifacts` entry. Once
> `references` is present in the response, a foreign-scope entry's `references` list must drop any
> entry the requesting reader could not independently read (i.e. not itself tier 3 shared) — batched
> into a single additional query across the whole result page rather than one lookup per
> artifact per reference, to avoid an N×M cost. Own-scope entries are never filtered. Full
> requirements: `docs/specs/review-followup-2026-07-06-design-fixes.md` ("Cross-Scope Reference
> Filtering" section) and ADR-012's "Cross-scope reference visibility" section.
- WHEN multiple section vectors for the same artifact match the filter THE SYSTEM SHALL
  deduplicate by `artifact_id` and return exactly one record per artifact.
- WHEN `list_artifacts` returns successfully THE SYSTEM SHALL return for each artifact:
  `artifact_id`, `type`, `team`, `project`, `tier`, `date`, `status`, `title`,
  `visibility`, `tags`, `author_role`, `description`. No `content` field.
- WHEN a CredentialError is raised THE SYSTEM SHALL return a structured error — never a
  raw exception.

## Boundaries

**Always:**
- Results contain metadata and description only — no full content (NFR-02).
- `status` defaults to `"active"` when not supplied; the caller must explicitly pass
  `status="inactive"` to see archived artifacts.
- Cross-scope gate uses the same `startswith(scope + "/")` logic as read and search.
- All metadata required for the list response is available in vector metadata; no S3 calls
  are needed for the list operation itself.
- The tool receives `settings`, `s3` (unused), `vectors`, and `bedrock` (unused) as
  injected dependencies.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not fetch S3 object content or S3 object metadata for the list response — all needed
  data is in vector metadata.
- Do not return more than one record per `artifact_id` even if multiple section vectors
  match the filter.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_list.py` | Create | Written first (Red) |
| `src/cairn_mcp/tools/list.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_list.py` | Create | Written before integration wiring |
| `src/cairn_mcp/server.py` | Modify | Register `list_artifacts` tool on `_app` |

## Testing Approach

**TDD cycle A (unit):** write `test_tools_list.py` first → fail → implement `tools/list.py`
→ unit tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

---

**`test_tools_list.py` — unit tests (FakeVectorsClient, no S3 or Bedrock calls):**

Seed the fake vector index with vectors covering: own-scope active tier 2, own-scope active
tier 3 shared, own-scope inactive tier 2, own-scope active tier 2 with type `code_review`
and feature tag `auth`, foreign-scope active tier 3 shared, foreign-scope active tier 2,
foreign-scope active tier 3 hidden. Each artifact has multiple section vectors to
verify deduplication.

Default behaviour:
- No filters → only own-scope and foreign-scope tier 3 shared active artifacts returned.
- `status` defaults to `"active"` → inactive artifacts absent from results.
- `status="inactive"` override → only inactive artifacts returned.

Filter combinations:
- `type="code_review"` → only code reviews.
- `tags=["auth"]` → only artifacts with `"auth"` tag.
- `type="code_review"` + `tags=["auth"]` → intersection.
- `team="platform"` → only platform artifacts.
- `project="infra"` → only infra project artifacts.
- `tier=3` → only tier 3 artifacts.
- No matching artifacts → empty list returned, no error.

Deduplication:
- Two section vectors for the same `artifact_id` → one record in results.
- Correct fields present: artifact_id, type, team, project, tier, date, status, title,
  visibility, tags, author_role, description. No `content` field.
- `tags` in response is a list, not a comma-separated string.

Cross-scope gate:
- Foreign-scope tier 3 shared → included.
- Foreign-scope tier 2 → excluded.
- Foreign-scope tier 3 hidden → excluded.

Credential failure:
- `list_vectors_by_metadata` raises `CredentialError` → structured error response.
- `get_vectors` raises `CredentialError` → structured error response.

**`tests/integration/test_tools_list.py` — integration tests (`@pytest.mark.integration`):**

- Write 2 artifacts; list with no filters → both appear.
- Write artifact then archive it; list with default filter → archived artifact absent; list
  with `status="inactive"` → archived artifact present.
- Write artifacts with different types; list with type filter → correct subset returned.
- Non-existent filter → empty list, no error.

## Open Questions

*(none — all constraints are defined)*
