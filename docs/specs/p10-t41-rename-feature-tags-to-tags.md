---
type: Spec
id: p10-t41-rename-feature-tags-to-tags
title: "T41: Rename feature_tags → tags"
description: >
  Pure identifier rename of the feature_tags metadata field to tags across the entire
  Arkeology codebase — model, MCP API, S3/vector metadata keys, filters, tests, AGENTS.md,
  and skills — aligning with OKF vocabulary without semantic change.
tags: ["schema", "okf-alignment", "refactor"]
status: stable
okf_version: "0.2"
sources:
  - resource: docs/brainstorming/brainstorming-2026-06-15-okf-alignment.md
    title: OKF (Open Knowledge Format) Alignment for Arkeology
    last_modified: 2026-06-15T00:00:00Z
generated:
  by: "axians-pm/claude-sonnet-4.6"
  at: 2026-06-18T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T17:25:26Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T41: Rename `feature_tags` → `tags`

## TL;DR

Rename the `feature_tags` metadata field to `tags` across the entire Arkeology codebase —
model, tool parameters (public MCP API), S3 and vector metadata keys, filter clause keys,
tests, AGENTS.md, and skills. This is a pure identifier rename with no semantic change; it
aligns Arkeology's one cleanly OKF-equivalent field with the OKF `tags` vocabulary (brainstorming
D2, LOCKED). No live data migration is needed.

## 1. Problem Statement

The Arkeology artifact model uses `feature_tags` while OKF uses `tags` for the identical concept.
Brainstorming session D2 (LOCKED) identified this as the one field where OKF alignment is
clean — same concept, no semantic loss — and decided to rename internally. Until this rename
lands the public API and internal keys diverge from OKF vocabulary for no good reason, making
the future export adapter (B-2) slightly more complex and adding minor friction for users
already familiar with OKF.

All three user stories this spec covers — the MCP API uses `tags`, filtering on `tags` works
end-to-end, and the dual encoding is preserved under the new key name — are P1.

## 2. Rules — The `tags` field in storage and the MCP API

### R1 — `write_artifact` stores `tags` under the key `"tags"`, with the dual encoding unchanged

When `write_artifact` is called with a `tags` parameter, the system stores the value under the
key `"tags"` in S3 object metadata as a comma-joined string and under the key `"tags"` in vector
metadata as a `list[str]`. Only the key name changes — the encoding semantics (S3: comma-joined
string, vector: list[str]) are unchanged.

**Example**

- Given a caller writing an artifact with `tags=["auth", "security"]`, when `write_artifact` is
  called, then the artifact is stored with `tags` as the field name in both S3 object metadata
  (comma-joined string `"auth,security"`) and vector metadata (list `["auth", "security"]`).
- Given an artifact written with `tags=["auth", "security"]`, when S3 object metadata is
  inspected, then the key `"tags"` holds the comma-joined string `"auth,security"`; and when
  vector metadata is inspected, then the key `"tags"` holds the list `["auth", "security"]`.

### R2 — Tool responses name the field `"tags"`, not `"feature_tags"`

When any read, search, list, or synthesise tool returns artifact metadata, the system uses the
field name `"tags"` — not `"feature_tags"` — in the response dictionary. `tags` appears in
`write_artifact`, `read_artifact`, `list_artifacts`, and `search_artifacts` responses.

### R3 — The public MCP parameter is `tags` on all four tools

The public MCP parameter is renamed from `feature_tags` to `tags` in all four tools:
`write_artifact`, `search_artifacts`, `list_artifacts`, `synthesise_artifacts`.

### R4 — A `tags` filter builds one `{"tags": {"$eq": tag}}` clause per tag

When a filter clause is built for `tags`, the system constructs `{"tags": {"$eq": tag}}` for
each tag in the filter list, so filtering on `tags` works end-to-end.

**Example**

- Given artifacts stored with `tags=["payments"]`, when `list_artifacts(tags=["payments"])` or
  `search_artifacts(..., tags=["payments"])` is called, then only artifacts carrying
  `"payments"` in their `tags` list are returned.

### R5 — `reconcile_index` re-indexes the `"tags"` key

When `reconcile_index` re-indexes an S3 artifact, the system reads the `"tags"` key from S3
object metadata (comma-joined string) and writes it as `"tags"` (list[str]) into the vector
index.

### R6 — `write_artifacts` reads `"tags"` from a bulk descriptor

When `write_artifacts` parses a bulk descriptor, the system reads the `"tags"` key from the
descriptor dict.

## 3. Rules — Documentation, resources and skills

### R7 — Documentation and resource text name the field `tags`

When AGENTS.md and SERVER-REFERENCE.md describe conventions, they use `tags` everywhere
`feature_tags` was previously named — the AGENTS.md Conventions and High-Friction Areas
sections, SERVER-REFERENCE.md, and the `resources.py` schema table and guidance text.

### R8 — The setting-up-arkeology and migrating-to-arkeology skills name the field `tags`

When the setting-up-arkeology and migrating-to-arkeology skills reference the field, they use
`tags` — setting-up-arkeology (`agents-snippet.md`) and migrating-to-arkeology (`SKILL.md`).

## 4. Boundaries

**Always:**
- Rename the key name only — encoding semantics (S3: comma-joined string, vector: list[str]) are unchanged
- Rename the public MCP parameter in all four tools: `write_artifact`, `search_artifacts`, `list_artifacts`, `synthesise_artifacts`
- Rename filter clause keys (`{"tags": {"$eq": tag}}`)
- Rename in all unit and integration test fixtures, assertions, test names, and docstrings
- Update AGENTS.md Conventions and High-Friction Areas sections
- Update SERVER-REFERENCE.md, resources.py schema table and guidance text
- Update setting-up-arkeology (`agents-snippet.md`) and migrating-to-arkeology (`SKILL.md`)

**Ask First:**
- None.

**Never:**
- Change the dual-encoding scheme (S3 comma-joined string vs vector list[str])
- Add any data migration tooling — no live data exists
- Modify historical spec files in `docs/specs/` (completed task artefacts)
- Modify brainstorming docs in `docs/brainstorming/`
- Modify `docs/learnings.md`
- Modify `docs/architecture-decisions/` ADRs

## 5. For the developer agent

### Files to Touch

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

### Contracts

None.

### Testing Approach

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
