---
type: brainstorming
title: Add `brainstorming` Artifact Type
description: Makes the case for adding `brainstorming` as a first-class tier 2 artifact type to distinguish ideation outputs from session outcomes, restoring search precision for projects that produce both document kinds.
tags: []
timestamp: 2026-06-01T00:00:00Z
okf_version: "0.1"
status: complete
references: []
authored:
  by: "analyst"
  date: "2026-06-01"
revised:
  by: ""
  date: ""
techniques_used: []
assumptions_challenged: []
---

# Add `brainstorming` Artifact Type

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add `brainstorming` as a first-class tier 2 artifact type. Brainstorming documents
capture options explored and directions considered during ideation — they are
structurally and semantically distinct from session summaries, which record what was
decided and done. The migration skill currently maps `docs/brainstorming/` to
`session_summary`, conflating two meaningfully different document kinds and degrading
search precision for projects that produce both.

## Problem Statement

`session_summary` conflates two distinct document kinds: (1) session outcomes — what
was decided, implemented, or discovered — and (2) brainstorming outputs — options
explored, trade-offs weighed, directions considered but not yet resolved. When a user
runs the migration skill on a project that has both `docs/brainstorming/` and
`docs/sessions/` directories, all of them become `session_summary` artifacts. Semantic
search that filters by `type=session_summary` then returns brainstorming noise when
the user wants session outcomes, and vice versa. Giving brainstorming its own type
restores that distinction and lets agents filter cleanly.

## User Stories

### Story 1 — Write brainstorming as a distinct type (P1)

An agent completing an ideation session wants to write the brainstorming output with
`type=brainstorming` so it is stored and indexed as a distinct document kind.

**Acceptance criteria:**
- Given a valid `write_artifact` call with `type="brainstorming"`, when the tool runs,
  then the artifact is written to S3 and indexed without error.
- Given an artifact written with `type="brainstorming"`, when `search_artifacts` is
  called with `type="brainstorming"`, then the artifact appears in results.
- Given an artifact written with `type="session_summary"`, when `search_artifacts` is
  called with `type="brainstorming"`, then the session summary does not appear.

### Story 2 — Migration skill detects brainstorming by directory convention (P1)

An operator running the migration skill on a project with a `docs/brainstorming/`
directory wants files in that directory classified as `brainstorming`, not `session_summary`.

**Acceptance criteria:**
- Given a project with `docs/brainstorming/` files, when the migration skill runs Step 2,
  then files in that directory are mapped to `type=brainstorming`, `tier=2`.
- Given a project with `docs/sessions/` or `docs/notes/` files, when the migration skill
  runs Step 2, then files in those directories remain mapped to `type=session_summary`, `tier=2`.

### Story 3 — Schema resources reflect the new type (P1)

A connected agent reading Arkeology's MCP resources sees `brainstorming` in the type
catalogue and artifact schema.

**Acceptance criteria:**
- Given a call to `arkeology://schema/types`, when the resource is read, then `brainstorming`
  appears with a usage description.
- Given a call to `arkeology://schema/artifact`, when the resource is read, then `brainstorming`
  is listed as a valid type value.
- Given a call to `arkeology://schema/tiers`, when the resource is read, then `brainstorming`
  appears in the tier 2 "Use for" guidance.

## Requirements

- WHEN `write_artifact` is called with `type="brainstorming"` THE SYSTEM SHALL accept the
  type and proceed normally.
- WHEN `write_artifact` is called with `type="brainstorming"` THE SYSTEM SHALL treat the
  artifact as tier 2 in guidance (the tier parameter is still caller-controlled, but the
  type catalogue documents it as tier 2).
- WHEN `arkeology://schema/types` is read THE SYSTEM SHALL include a description for
  `brainstorming`.
- WHEN `arkeology://schema/tiers` is read THE SYSTEM SHALL list `brainstorming` alongside
  other tier 2 types in the "Use for" guidance.
- WHEN the migration skill Step 2 directory scan encounters `docs/brainstorming/` THE
  SYSTEM SHALL map it to `type=brainstorming`, `tier=2` (not `session_summary`).

## Boundaries

**Always:**
- `brainstorming` is tier 2 — point-in-time, date-anchored, immutable after write.
- `ARTIFACT_TYPES` in `artifact.py` is the single source of truth; no other file
  duplicates the type set.
- `resources.py` reads `ARTIFACT_TYPES` at call-time; no hardcoded count anywhere.
- Migration skill directory mapping for `docs/sessions/` and `docs/notes/` remains
  `session_summary` — only `docs/brainstorming/` changes.

**Ask First:** Nothing ambiguous — scope is fully defined.

**Never:**
- Do not modify existing artifacts, tool logic, search logic, or any stored data.
- Do not add tier 3 support for `brainstorming` — it is tier 2 only per approved scope.
- Do not change any other existing type's description, tier assignment, or removal guidance.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Modify | Add `"brainstorming"` to parametrized type list; update docstring "All 8" → "All 9" |
| `src/arkeology/artifact.py` | Modify | Add `"brainstorming"` to `ARTIFACT_TYPES`; update docstring "eight" → "nine" |
| `src/arkeology/resources.py` | Modify | Add `"brainstorming"` entry to `_descriptions` in `types_schema_content()`; add `brainstorming` to "Use for" line in `tiers_schema_content()` |
| `README.md` | Modify | Add `brainstorming` row to the artifact type table in the AGENTS.md snippet; add `brainstorming` to the tier 2 list in the Tier selection section |
| `skills/migrating-to-arkeology/SKILL.md` | Modify | Split `docs/brainstorming/` into its own row mapping to `brainstorming` tier 2; add `brainstorming` row to Step 7 removal guidance table |
| `skills/migrating-to-arkeology/schema.yaml` | Modify | Add `brainstorming` to the inline type comment listing the valid `ARTIFACT_TYPES` values |

## Testing Approach

This project uses TDD. Each test file is listed before the implementation file it gates.

**Red — write the failing test first:**

1. `tests/unit/test_artifact.py` — add `"brainstorming"` to `@pytest.mark.parametrize`
   list in `test_artifact_all_valid_types_accepted`; update docstring "All 8" → "All 9".
   This test fails until `ARTIFACT_TYPES` contains `"brainstorming"`.

**Green — implement to make the test pass:**

2. `src/arkeology/artifact.py` — add `"brainstorming"` to `ARTIFACT_TYPES`; update
   docstring on `Artifact` class from "eight valid artifact types" to "nine valid
   artifact types". The parametrized test now passes.

**Documentation (no failing test gates these, update after green):**

3. `src/arkeology/resources.py` — add `brainstorming` description entry; update tier 2
   "Use for" line. Verified by existing `test_resources.py` dynamic iteration over
   `ARTIFACT_TYPES` (no new test needed — the loop already covers every type in the set).

4. `README.md` — add `brainstorming` row; update tier 2 list.

5. `skills/migrating-to-arkeology/SKILL.md` — split directory mapping row; add step 7 row.

6. `skills/migrating-to-arkeology/schema.yaml` — add type to comment.

**Verify after all changes:**

```bash
uv run pytest tests/unit/test_artifact.py -q -m 'not integration'
uv run pytest tests/unit/test_resources.py -q -m 'not integration'
uv run pytest tests/unit/ -q -m 'not integration'
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

## Open Questions

None — scope is fully defined and approved.
