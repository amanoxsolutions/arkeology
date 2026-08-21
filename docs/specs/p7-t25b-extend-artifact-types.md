---
type: spec
title: Extend Artifact Type Vocabulary (+5 Types) and Flexible Migration Docs Root
description: Adds five new artifact types (prd, plan, runbook, changelog, postmortem) to expand the vocabulary from 9 to 14 types, and fixes the migration skill to discover the project's docs root dynamically instead of assuming docs/.
tags: []
timestamp: 2026-06-01T00:00:00Z
okf_version: "0.1"
feature: p7-t25b-extend-artifact-types
phase: 7
task: 25b
status: ready
references: []
authored:
  by: "architect"
  date: "2026-06-01"
revised:
  by: ""
  date: ""
---

# Extend Artifact Type Vocabulary (+5 types) and Flexible Migration Docs Root

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add five new first-class artifact types (`prd`, `plan`, `runbook`, `changelog`,
`postmortem`) to bring the vocabulary from 9 to 14 types — separating product and
planning documents from feature specs, and adding operational and incident knowledge.
Simultaneously fix the migration skill to discover the project's docs root dynamically
rather than assuming `docs/`.

> **Follow-up (2026-06-15):** a fifteenth type, `learning` (tier 3, date-independent),
> was added later to back the `capturing-learnings` skill's living `learnings.md`. The
> change is additive and follows the same pattern as the five types below: 14 → 15 types,
> the `Artifact` class docstring note moves from "fourteen" → "fifteen", `resources.py`
> gains a `learning` description and tier 3 "Use for" entry, the migration skill gains
> Pass 1 / Pass 2 classification rows and a Step 5 removal-guidance row, and one
> parametrized test case is added in `test_artifact.py`.

> **Follow-up (2026-08-21):** the `prd` type is removed and replaced by two new types,
> `vision` and `requirements` (15 → 16 types — one type removed, two added), mirroring
> the amanox planning-artifact convention this project itself
> follows: the old single `prd.md` is now split into `vision.md` (problem statement,
> users, journeys, differentiator) + `requirements.md` (FR/NFR/AC/Constraints). Splitting
> preserves type-filtered search granularity — an agent can ask for "the vision" or "the
> requirements" separately — which a single merged type would have cost. A legacy
> single-document `prd.md`/`product-requirements.md` (pre-split convention) classifies
> to `requirements`, since its content is predominantly requirements-shaped and
> "requirements" is part of the name; the smaller vision-framing portion such a document
> typically carries is an acceptable, judgment-call-documented simplification.
> `resources.py`'s `prd` description entry is replaced by two new description entries;
> the tier 3 "Use for" line drops `prd` and gains `vision`, `requirements`; the migration
> skill's Pass 1 filename-stem row is split into two rows accordingly; and the Step 7
> removal-guidance row is replaced by two rows. See `p7-t25c`'s matching follow-up for
> the exact table change.

## Problem Statement

Two independent gaps are resolved together because they share the same affected files
(migration skill, README, resources) and a single implementation pass is cheaper than two.

**Gap 1 — type vocabulary:** `spec` conflates four semantically distinct document kinds
(feature spec, PRD, project plan, and technical specification). Three further document
kinds common in software teams — operational runbooks, release changelogs, and
post-incident analyses — have no home in the vocabulary, forcing agents to misclassify
them as `implementation_note`, `session_summary`, or `spec`. Misclassification silently
partitions search results and degrades retrieval precision.

**Gap 2 — migration skill hardcodes `docs/`:** Every directory pattern in the migration
skill's Step 2 mapping uses a `docs/` prefix. Projects that organise documentation under
`documentation/`, `doc/`, `wiki/`, or directly in the repo root cannot use the skill's
directory convention mapping without manual correction of every row.

## User Stories

### Story 1 — Write the five new types (P1)

An agent wants to write a PRD, project plan, runbook, changelog entry, or postmortem
and have it stored and indexed under the correct type.

**Acceptance criteria:**
- Given a valid `write_artifact` call with `type="prd"`, when the tool runs, then the
  artifact is written to S3 and indexed without error.
- Given a valid `write_artifact` call with `type="plan"`, when the tool runs, then the
  artifact is written to S3 and indexed without error.
- Given a valid `write_artifact` call with `type="runbook"`, when the tool runs, then
  the artifact is written to S3 and indexed without error.
- Given a valid `write_artifact` call with `type="changelog"`, when the tool runs, then
  the artifact is written to S3 and indexed without error.
- Given a valid `write_artifact` call with `type="postmortem"`, when the tool runs, then
  the artifact is written to S3 and indexed without error.
- Given a `write_artifact` call with any of the five new types, when `search_artifacts`
  is called with that same type filter, then only artifacts of that type appear.

### Story 2 — Schema resources reflect all 14 types (P1)

A connected agent reading Arkeology's MCP resources sees all 14 types in the catalogue
and artifact schema.

**Acceptance criteria:**
- Given a call to `arkeology://schema/types`, when the resource is read, then each of the
  five new types appears with a usage description.
- Given a call to `arkeology://schema/artifact`, when the resource is read, then all five
  new types are listed as valid type values.
- Given a call to `arkeology://schema/tiers`, when the resource is read, then `prd`, `plan`,
  and `runbook` appear in the tier 3 "Use for" guidance; `changelog` and `postmortem`
  appear in the tier 2 "Use for" guidance.

### Story 3 — Migration skill discovers the docs root (P1)

An operator running the migration skill on a project whose documentation lives under
`documentation/` (not `docs/`) sees the correct directory-to-type mapping applied
without needing to manually edit every row.

**Acceptance criteria:**
- Given a project with documentation under a non-`docs/` root (e.g. `documentation/`),
  when the migration skill runs Step 2, then the agent discovers the actual docs root
  first and applies subdirectory patterns relative to that root.
- Given a project with no recognisable docs root, when the migration skill runs Step 2,
  then the agent scans the repo root for Markdown files and asks the operator to confirm
  the classification before proceeding.
- Given a project with a `docs/` root (existing behaviour), when the migration skill runs
  Step 2, then the behaviour is unchanged — `docs/adr/` still maps to `adr`, etc.

### Story 4 — Migration skill maps new types by directory convention (P1)

An operator migrating a project that has runbook, changelog, or postmortem directories
sees those directories mapped to the correct new types automatically.

**Acceptance criteria:**
- Given a project with a directory matching `runbooks/`, `runbook/`, or `ops/` under the
  docs root, when the migration skill runs Step 2, then files in that directory are
  mapped to `type=runbook`, `tier=3`.
- Given a project with a directory matching `changelogs/` or `releases/` under the docs
  root, when the migration skill runs Step 2, then files in that directory are mapped to
  `type=changelog`, `tier=2`.
- Given a project with a directory matching `postmortems/` or `incidents/` under the
  docs root, when the migration skill runs Step 2, then files in that directory are
  mapped to `type=postmortem`, `tier=2`.
- Given a `planning-artifacts/` or `planning/` directory, when the migration skill
  encounters `prd.md` or `plan.md` within it, then those files map to `type=prd` and
  `type=plan` respectively; other files in the same directory map to `type=spec`.

## Requirements

- WHEN `write_artifact` is called with `type="prd"` THE SYSTEM SHALL accept the type and
  proceed normally.
- WHEN `write_artifact` is called with `type="plan"` THE SYSTEM SHALL accept the type
  and proceed normally.
- WHEN `write_artifact` is called with `type="runbook"` THE SYSTEM SHALL accept the type
  and proceed normally.
- WHEN `write_artifact` is called with `type="changelog"` THE SYSTEM SHALL accept the
  type and proceed normally.
- WHEN `write_artifact` is called with `type="postmortem"` THE SYSTEM SHALL accept the
  type and proceed normally.
- WHEN `arkeology://schema/types` is read THE SYSTEM SHALL include a description for each of
  the five new types.
- WHEN `arkeology://schema/tiers` is read THE SYSTEM SHALL list `prd`, `plan`, `runbook`
  under tier 3 "Use for" guidance and `changelog`, `postmortem` under tier 2 "Use for"
  guidance.

## Boundaries

**Always:**
- `ARTIFACT_TYPES` in `artifact.py` is the single source of truth; no other file
  duplicates the type set.
- `resources.py` reads `ARTIFACT_TYPES` at call-time; no hardcoded type count anywhere.
- The existing 9 types (`adr`, `brainstorming`, `bug_report`, `code_review`,
  `decision_note`, `implementation_note`, `session_summary`, `spec`, `synthesis`) are
  unchanged — no description, tier assignment, or removal guidance is altered.
- Tier recommendations in the type catalogue are guidance only; the `tier` parameter
  remains caller-controlled.
- Migration skill Step 2 docs-root discovery presents its finding to the operator and
  waits for confirmation before proceeding — the agent must not silently assume a root.

**Ask First:** Nothing ambiguous — scope is fully defined.

**Never:**
- Do not modify tool logic, search logic, vector client code, or any stored data.
- Do not add a catch-all or generic fallback type.
- Do not remove or rename any existing type.
- Do not hardcode a new `docs/` prefix in the migration skill — the whole point of this
  change is to make the prefix dynamic.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Modify | Add 5 new types to parametrized list; update "All 9" → "All 14"; update docstring count |
| `src/arkeology/artifact.py` | Modify | Add 5 types to `ARTIFACT_TYPES`; update Artifact class docstring "nine" → "fourteen" |
| `src/arkeology/resources.py` | Modify | Add 5 entries to `_descriptions` in `types_schema_content()`; update both "Use for" lines in `tiers_schema_content()` |
| `README.md` | Modify | Add 5 rows to artifact type table; update tier 2 and tier 3 type lists |
| `skills/migrating-to-arkeology/SKILL.md` | Modify | (1) Add docs-root discovery sub-step to Step 2; (2) change directory mapping table to subdirectory patterns; (3) add new type rows; (4) fix `planning-artifacts/` to split prd/plan/spec; (5) add 5 new types to Step 7 removal guidance |
| `skills/migrating-to-arkeology/schema.yaml` | Modify | Add 5 new types to the inline `ARTIFACT_TYPES` comment |

## Testing Approach

This project uses TDD. Test file is listed before the implementation file it gates.

**Red — write the failing test first:**

1. `tests/unit/test_artifact.py` — add `"changelog"`, `"plan"`, `"postmortem"`,
   `"prd"`, `"runbook"` to the `@pytest.mark.parametrize` list in
   `test_artifact_all_valid_types_accepted`; update the docstring from "All 9" to
   "All 14". These five parametrize cases fail until `ARTIFACT_TYPES` contains the
   new values.

**Green — implement to make the tests pass:**

2. `src/arkeology/artifact.py` — add `"changelog"`, `"plan"`, `"postmortem"`, `"prd"`,
   `"runbook"` to `ARTIFACT_TYPES`; update the `Artifact` class docstring from "nine
   valid artifact types" to "fourteen valid artifact types". All five parametrized
   cases now pass.

**Documentation (no failing test gates these — update after green):**

3. `src/arkeology/resources.py` — add description entries for the five new types to
   `_descriptions`; update `tiers_schema_content()` tier 2 "Use for" line to include
   `changelog` and `postmortem`; update tier 3 "Use for" line to include `plan`, `prd`,
   `runbook`. Existing `test_resources.py` iterates `ARTIFACT_TYPES` dynamically — no
   new test needed; the loop already covers every type in the set.

   Descriptions to use (≤ one line each):
   - `prd`: "Product Requirements Document — defines what to build, user needs, goals,
     and non-goals. Tier 3, shared."
   - `plan`: "Project or sprint plan — ordered task breakdown, milestones, and
     dependencies. Tier 3."
   - `runbook`: "Operational runbook — step-by-step procedures for deployment, rollback,
     and incident response. Tier 3."
   - `changelog`: "Changelog entry — records features shipped, bugs fixed, and breaking
     changes for a release. Tier 2."
   - `postmortem`: "Post-incident analysis — timeline, root cause, customer impact,
     remediation, and follow-up actions. Tier 2."

4. `README.md` — add 5 rows to the artifact type table (one per new type); update the
   tier 2 type list to include `changelog` and `postmortem`; update the tier 3 type list
   to include `plan`, `prd`, `runbook`.

5. `skills/migrating-to-arkeology/SKILL.md` — the following changes are all in Step 2 and
   Step 7:

   **Step 2 — docs-root discovery sub-step** (insert before the directory mapping table):

   > Before applying the mapping below, discover the project's documentation root:
   > 1. Check for these candidates in order: `docs/`, `documentation/`, `doc/`, `wiki/`.
   > 2. If exactly one exists, use it as the docs root. Announce it to the operator.
   > 3. If multiple exist, list them and ask the operator which is the primary docs root.
   > 4. If none exist, treat the repo root as the docs root and note this to the operator.
   > 5. All subdirectory patterns in the table below are relative to the confirmed docs root.

   **Step 2 — directory mapping table** — replace current hardcoded-path table with
   subdirectory-pattern table (paths are relative to confirmed docs root):

   | Subdirectory pattern | Default type | Default tier |
   |---|---|---|
   | `adr/`, `architecture/` | `adr` | 3 |
   | `specs/` | `spec` | 3 |
   | `planning-artifacts/`, `planning/` | see note below | 3 |
   | `brainstorming/` | `brainstorming` | 2 |
   | `sessions/`, `notes/` | `session_summary` | 2 |
   | `code-reviews/` | `code_review` | 2 |
   | `implementation-notes/`, `impl-notes/` | `implementation_note` | 2 |
   | `runbooks/`, `runbook/`, `ops/` | `runbook` | 3 |
   | `changelogs/`, `releases/` | `changelog` | 2 |
   | `postmortems/`, `incidents/` | `postmortem` | 2 |

   > **Note for `planning-artifacts/` and `planning/`:** classify by filename within the
   > directory — `prd.md` → `type=prd`; `plan.md` → `type=plan`; all other files →
   > `type=spec`.

   **Step 7 — removal guidance** — add rows for the 5 new types:

   | Type | Safe to remove from repo |
   |---|---|
   | `changelog` | Judgment call — keep if the changelog is actively referenced in release PRs; remove old entries already captured in Arkeology |
   | `plan` | Judgment call — keep if the plan file is actively updated in the repo; remove if Arkeology is now the live version |
   | `postmortem` | Yes — point-in-time incident records; Arkeology is the right home |
   | `prd` | Judgment call — keep if the PRD is referenced in active development; remove once the feature is shipped and the Arkeology copy is the archive |
   | `runbook` | Judgment call — keep if the team needs runbooks reachable outside Arkeology (e.g. via git during an incident); remove if Arkeology is the agreed operational home |

6. `skills/migrating-to-arkeology/schema.yaml` — update the inline `ARTIFACT_TYPES` comment
   to list all types alphabetically (16 after the `learning` and `vision`/`requirements`
   follow-ups):
   `adr, brainstorming, bug_report, changelog, code_review, decision_note,`
   `implementation_note, learning, plan, postmortem, requirements, runbook,`
   `session_summary, spec, synthesis, vision`

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
