---
type: spec
title: "B-3 / T41: Rename feature_tags → tags"
description: >
  Pure identifier rename of the feature_tags metadata field to tags across the entire
  Arkeology codebase — model, MCP API, S3/vector metadata keys, filters, tests, AGENTS.md,
  and skills — aligning with OKF vocabulary without semantic change.
tags: ["schema", "okf-alignment", "refactor"]
timestamp: 2026-06-18T00:00:00Z
okf_version: "0.1"
feature: "B-3"
status: ready
references:
  - docs/brainstorming/brainstorming-2026-06-15-okf-alignment.md
authored:
  by: pm
  date: "2026-06-18"
revised:
  by: ""
  date: ""
---

# B-3 / T41: Rename `feature_tags` → `tags`

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Rename the `feature_tags` metadata field to `tags` across the entire Arkeology codebase —
model, tool parameters (public MCP API), S3 and vector metadata keys, filter clause keys,
tests, AGENTS.md, and skills. This is a pure identifier rename with no semantic change; it
aligns Arkeology's one cleanly OKF-equivalent field with the OKF `tags` vocabulary (brainstorming
D2, LOCKED). No live data migration is needed.

## Problem Statement

The Arkeology artifact model uses `feature_tags` while OKF uses `tags` for the identical concept.
Brainstorming session D2 (LOCKED) identified this as the one field where OKF alignment is
clean — same concept, no semantic loss — and decided to rename internally. Until this rename
lands the public API and internal keys diverge from OKF vocabulary for no good reason, making
the future export adapter (B-2) slightly more complex and adding minor friction for users
already familiar with OKF.

## User Stories

**P1 — MCP API uses `tags`**
- Given a caller writing an artifact with `tags=["auth", "security"]`
- When `write_artifact` is called
- Then the artifact is stored with `tags` as the field name in both S3 object metadata
  (comma-joined string `"auth,security"`) and vector metadata (list `["auth", "security"]`);
  `tags` appears in `write_artifact`, `read_artifact`, `list_artifacts`, and
  `search_artifacts` responses.

**P1 — Filter on `tags` works end-to-end**
- Given artifacts stored with `tags=["payments"]`
- When `list_artifacts(tags=["payments"])` or `search_artifacts(..., tags=["payments"])` is
  called
- Then only artifacts carrying `"payments"` in their `tags` list are returned.

**P1 — Dual encoding preserved under the new key name**
- Given an artifact written with `tags=["auth", "security"]`
- When S3 object metadata is inspected
- Then the key `"tags"` holds the comma-joined string `"auth,security"`.
- And when vector metadata is inspected
- Then the key `"tags"` holds the list `["auth", "security"]`.

## Requirements

- WHEN `write_artifact` is called with a `tags` parameter, THE SYSTEM SHALL store the value
  under the key `"tags"` in S3 object metadata as a comma-joined string and under the key
  `"tags"` in vector metadata as a `list[str]`.
- WHEN any read, search, list, or synthesise tool returns artifact metadata, THE SYSTEM SHALL
  use the field name `"tags"` — not `"feature_tags"` — in the response dictionary.
- WHEN a filter clause is built for `tags`, THE SYSTEM SHALL construct
  `{"tags": {"$eq": tag}}` for each tag in the filter list.
- WHEN `reconcile_index` re-indexes an S3 artifact, THE SYSTEM SHALL read the `"tags"` key
  from S3 object metadata (comma-joined string) and write it as `"tags"` (list[str]) into
  the vector index.
- WHEN `write_artifacts` parses a bulk descriptor, THE SYSTEM SHALL read the `"tags"` key
  from the descriptor dict.
- WHEN AGENTS.md and SERVER-REFERENCE.md describe conventions, THE SYSTEM SHALL use `tags`
  everywhere `feature_tags` was previously named.
- WHEN the setting-up-arkeology and migrating-to-arkeology skills reference the field, THE SYSTEM
  SHALL use `tags`.

## Boundaries

| Category | Entry |
|---|---|
| **Always** | Rename the key name only — encoding semantics (S3: comma-joined string, vector: list[str]) are unchanged |
| **Always** | Rename the public MCP parameter in all four tools: `write_artifact`, `search_artifacts`, `list_artifacts`, `synthesise_artifacts` |
| **Always** | Rename filter clause keys (`{"tags": {"$eq": tag}}`) |
| **Always** | Rename in all unit and integration test fixtures, assertions, test names, and docstrings |
| **Always** | Update AGENTS.md Conventions and High-Friction Areas sections |
| **Always** | Update SERVER-REFERENCE.md, resources.py schema table and guidance text |
| **Always** | Update setting-up-arkeology (`agents-snippet.md`) and migrating-to-arkeology (`SKILL.md`) |
| **Never** | Change the dual-encoding scheme (S3 comma-joined string vs vector list[str]) |
| **Never** | Add any data migration tooling — no live data exists |
| **Never** | Modify historical spec files in `docs/specs/` (completed task artefacts) |
| **Never** | Modify brainstorming docs in `docs/brainstorming/` |
| **Never** | Modify `docs/learnings.md` |
| **Never** | Modify `docs/architecture-decisions/` ADRs |

---

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|---|---|---|
| `src/arkeology/artifact.py` | Rename field | `feature_tags: list[str]` → `tags: list[str]`; update Field docstring |
| `src/arkeology/server.py` | Rename params | Four tool registrations: `write_artifact`, `search_artifacts`, `list_artifacts`, `synthesise_artifacts` — param `feature_tags` → `tags` in both signature and pass-through call |
| `src/arkeology/tools/write.py` | Rename throughout | Function params in `_build_section_embedding_text`, `_build_document_embedding_text`, `write_artifact`; S3 metadata key `"feature_tags"` → `"tags"`; vector metadata key `"feature_tags"` → `"tags"`; internal normalisation variable rename |
| `src/arkeology/tools/read.py` | Rename throughout | S3 metadata parse key; response field key |
| `src/arkeology/tools/list.py` | Rename throughout | Function param; filter clause key `{"tags": {"$eq": tag}}`; response field; deserialization key |
| `src/arkeology/tools/search.py` | Rename throughout | Same pattern as list.py |
| `src/arkeology/tools/synthesise.py` | Rename throughout | Same pattern as list.py |
| `src/arkeology/tools/reconcile.py` | Rename throughout | S3 parse key; vector metadata key; Artifact constructor kwarg |
| `src/arkeology/tools/write_artifacts.py` | Rename key access | `descriptor.get("feature_tags")` → `descriptor.get("tags")` |
| `src/arkeology/resources.py` | Rename throughout | Schema table row; guidance text references |
| `tests/unit/test_artifact.py` | Rename | Fixture key; assertion field; test name/docstring |
| `tests/unit/test_tools_write.py` | Rename | All fixture dicts; test names (`test_vector_metadata_feature_tags_is_list` → `test_vector_metadata_tags_is_list`, `test_s3_metadata_feature_tags_…` → `test_s3_metadata_tags_…`); all assertions |
| `tests/unit/test_tools_read.py` | Rename | S3 fixture key; assertion field; test name/docstring |
| `tests/unit/test_tools_list.py` | Rename | All fixture dicts; filter param; assertions; test names |
| `tests/unit/test_tools_search.py` | Rename | Same pattern as test_tools_list.py |
| `tests/unit/test_tools_synthesise.py` | Rename | All fixture dicts; assertions; test name |
| `tests/unit/test_tools_reconcile.py` | Rename | Fixture key |
| `tests/unit/test_tools_archive.py` | Rename | Fixture keys (S3 and vector fixtures) |
| `tests/unit/test_tools_delete.py` | Rename | Fixture keys |
| `tests/unit/test_tools_purge.py` | Rename | Fixture keys |
| `tests/unit/test_tools_freshness.py` | Rename | Fixture key |
| `tests/unit/test_tools_propose_commit_links.py` | Rename | Fixture key |
| `tests/unit/test_tools_link_commit.py` | Rename | Fixture key |
| `tests/unit/test_resources.py` | Rename | Optional fields list entry `"feature_tags"` → `"tags"`; test name and assertion that checks `"tags"` appears in query strategy content |
| `tests/integration/test_tools_read.py` | Rename | Fixture keys; assertion field |
| `tests/integration/test_tools_synthesise.py` | Rename | Fixture field |
| `AGENTS.md` | Rename | Conventions section (comma-join list note); High-Friction Areas section |
| `SERVER-REFERENCE.md` | Rename | Tool signature lines for `search_artifacts` and `list_artifacts` |
| `skills/setting-up-arkeology/references/agents-snippet.md` | Rename | Tool call example `feature_tags=` → `tags=` |
| `skills/migrating-to-arkeology/SKILL.md` | Rename | Field mapping guidance references |

## Testing Approach

This project uses TDD. Because this is a pure rename refactor, the TDD sequence is a
**red → green sweep**: update test files first so each test fails because the production
key name has not changed yet, then update implementation files to satisfy each failing group.

**Phase 1 — Red (update all test files; run suite → expect failures on renamed fields)**

Update these files in the order listed, running
`uv run pytest tests/unit/ -q -m 'not integration'` after each group to confirm expected
failures before moving on:

1. `tests/unit/test_artifact.py` — gates `artifact.py`
2. `tests/unit/test_tools_write.py` — gates `tools/write.py`
3. `tests/unit/test_tools_read.py` — gates `tools/read.py`
4. `tests/unit/test_tools_list.py` — gates `tools/list.py` + `server.py` (list_artifacts)
5. `tests/unit/test_tools_search.py` — gates `tools/search.py` + `server.py` (search_artifacts)
6. `tests/unit/test_tools_synthesise.py` — gates `tools/synthesise.py` + `server.py` (synthesise_artifacts)
7. `tests/unit/test_tools_reconcile.py` — gates `tools/reconcile.py`
8. Fixture-only files (no new impl gate): `test_tools_archive.py`, `test_tools_delete.py`,
   `test_tools_purge.py`, `test_tools_freshness.py`, `test_tools_propose_commit_links.py`,
   `test_tools_link_commit.py`
9. `tests/unit/test_resources.py` — gates `resources.py`

**Phase 2 — Green (update implementation files; run suite → expect all tests pass)**

Update implementation files in the same order as their gating tests:

1. `artifact.py` → then `server.py` (all four tool params) → then `tools/write.py`
2. `tools/read.py`
3. `tools/list.py`
4. `tools/search.py`
5. `tools/synthesise.py`
6. `tools/reconcile.py`
7. `tools/write_artifacts.py` (no dedicated test gate — part of write pipeline)
8. `resources.py`

After all Phase 2 changes: `uv run pytest tests/unit/ -q -m 'not integration'` must be
fully green. Then: `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`,
`uv run mypy src/`.

**Phase 3 — Documentation and skills (no test gate)**

Update `AGENTS.md`, `SERVER-REFERENCE.md`,
`skills/setting-up-arkeology/references/agents-snippet.md`, `skills/migrating-to-arkeology/SKILL.md`.

## Open Questions

None — scope is fully specified by brainstorming D2 (LOCKED) and confirmed by PM.
