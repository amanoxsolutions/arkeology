---
type: brainstorming
title: "Visibility Reframing: `confidential` → `hidden`"
description: Catalogues all occurrences of the misleading `confidential` visibility value across code, tests, specs, PRD, and brainstorming files, and makes the case for replacing it with `hidden` to accurately describe the cross-scope visibility gate rather than implying a security boundary.
tags: []
timestamp: 2026-05-31T00:00:00Z
okf_version: "0.1"
status: complete
references: []
authored:
  by: "analyst"
  date: "2026-05-31"
revised:
  by: ""
  date: ""
techniques_used: []
assumptions_challenged: []
---

# Visibility Reframing: `confidential` → `hidden`

## Description

The `visibility` field uses the value `"confidential"` to mark artifacts that should not be
accessible across scope boundaries. This is a misleading name: the MCP server enforces
**visibility** (whether an artifact appears to other scopes), not **confidentiality** (whether
content is truly secure from unauthorized access). True confidentiality can only be enforced at
the AWS IAM layer. Using the word "confidential" creates a false sense of security and should be
replaced throughout with `"hidden"` — which accurately describes what the feature does.

The user has already made the first correction in the README. This document catalogues every
remaining occurrence across code, tests, specs, PRD, and brainstorming files so the PM can
produce a complete, ordered plan for the developer and tech-writer agents.

---

## Session 2026-05-31

### Why this matters

The current vocabulary creates a dangerous misunderstanding:

| What the word implies | What the feature actually does |
|---|---|
| `"confidential"` → the content is secure | Artifacts with `visibility="confidential"` are not returned by cross-scope queries — but any AWS principal with S3 read access can still access them directly |
| "confidentiality gate" → security boundary | It is a **visibility gate** — a soft filter in application code, not an IAM permission boundary |
| "confidential tier 2 documents" → protected | These artifacts are hidden from cross-scope discovery; they are NOT protected from an operator who has S3 bucket access |

The correct vocabulary:

| Old term | New term | Rationale |
|---|---|---|
| `"confidential"` (visibility value) | `"hidden"` | Describes the behaviour: the artifact is hidden from cross-scope visibility |
| "confidentiality gate" | "visibility gate" | The gate controls visibility, not access security |
| "confidential artifact" | "hidden artifact" | Consistent with the value name |
| "confidentiality" (as a concept for this feature) | "visibility control" | The feature is about controlling visibility, not security |
| Remaining uses of "confidential" in prose | Rephrase or remove | Avoid the word entirely in this codebase |

**Exception:** The README note `"True access control has to happen at the AWS IAM layer to handle
confidentiality"` uses "confidentiality" as a security concept in a meta-explanatory sentence.
This should also be rephrased to avoid the word: e.g. `"True access restriction (keeping content
private from unauthorized AWS principals) requires IAM permissions."` This keeps the meaning without
reintroducing the dangerous word.

---

### Vocabulary mapping

```
"confidential"  (string value)    →  "hidden"
"confidential"  (adjective, docs) →  "hidden"
"confidentiality" (noun, docs)    →  "visibility control" or rephrase
```

The cross-scope gate logic in code (`meta.get("visibility") != "shared"`, `visibility == "shared"`)
is **already correct and does not need to change** — it never checked for `"confidential"` by name.
The only functional code change is the validator in `artifact.py`.

---

### Inventory of all occurrences

#### Category A — Source code (developer task, functional impact)

These are the only changes with runtime behaviour impact:

| File | Line | Change |
|---|---|---|
| `src/arkeology/artifact.py` | 155 | Docstring: `"shared"`` or ``"confidential"` → `"shared"`` or ``"hidden"`` |
| `src/arkeology/artifact.py` | 192 | Validator set: `{"shared", "confidential"}` → `{"shared", "hidden"}` |
| `src/arkeology/artifact.py` | 193 | Error message: `"must be 'shared' or 'confidential'"` → `"must be 'shared' or 'hidden'"` |
| `src/arkeology/tools/write.py` | 139 | Docstring: `"shared"`` or ``"confidential"` → `"shared"`` or ``"hidden"`` |

No other source files have functional occurrences of `"confidential"`. All cross-scope gate
checks use `== "shared"` (not `!= "confidential"`), so they require no change.

---

#### Category B — Unit tests (developer task, must land simultaneously with Category A)

These changes must be delivered in the **same commit** as the Category A validator change.
If `artifact.py` accepts only `"shared"` or `"hidden"` but the tests still pass `"confidential"`,
**every test that seeds fixture data with `"confidential"` will fail** the validator.

**`tests/unit/test_artifact.py`**

| Element | Change |
|---|---|
| Function `test_artifact_visibility_confidential_valid` | Rename → `test_artifact_visibility_hidden_valid` |
| Docstring | `"visibility='confidential' → accepted"` → `"visibility='hidden' → accepted"` |
| String value `"confidential"` (line 413) | → `"hidden"` |
| Assertion `"confidential"` (line 415) | → `"hidden"` |
| Add new test | `test_artifact_visibility_confidential_invalid` — verifies that `visibility="confidential"` now raises `ValidationError` (previously valid, now must be rejected) |

> **Important:** The new test `test_artifact_visibility_confidential_invalid` is necessary because
> `"confidential"` was a valid value before this change. After the change, passing it must produce
> a `ValidationError`. This test guards against accidental reversion.

**`tests/unit/test_tools_read.py`**

| Element | Change |
|---|---|
| Comment `# own-scope tier 2 confidential` | → `# own-scope tier 2 hidden` |
| Fixture key `"artifacts/t2-confidential"` | → `"artifacts/t2-hidden"` |
| Metadata value `"confidential"` (tier 2 own-scope) | → `"hidden"` |
| Comment `# own-scope tier 3 confidential` | → `# own-scope tier 3 hidden` |
| Fixture key `"artifacts/t3-confidential"` | → `"artifacts/t3-hidden"` |
| Metadata value `"confidential"` (tier 3 own-scope) | → `"hidden"` |
| Comment `# foreign-scope tier 3 confidential` | → `# foreign-scope tier 3 hidden` |
| Fixture key `"other-team/t3-foreign-confidential"` | → `"other-team/t3-foreign-hidden"` |
| Metadata value `"confidential"` (tier 3 foreign) | → `"hidden"` |
| Function `test_own_scope_tier3_confidential_returned` | Rename → `test_own_scope_tier3_hidden_returned` |
| Docstring for above | `"own-scope tier 3 confidential → returned (no gate on own scope)"` → `"hidden"` |
| Artifact_id in above | `"artifacts/t3-confidential"` → `"artifacts/t3-hidden"` |
| Function `test_foreign_tier3_confidential_access_denied` | Rename → `test_foreign_tier3_hidden_access_denied` |
| Docstring for above | `"foreign-scope tier 3 confidential → access-denied error"` → `"hidden"` |
| Artifact_id in above | `"other-team/t3-foreign-confidential"` → `"other-team/t3-foreign-hidden"` |

**`tests/unit/test_tools_list.py`**

| Element | Change |
|---|---|
| Comment `# foreign-scope active tier 3 confidential — DENIED` | → `# foreign-scope active tier 3 hidden — DENIED` |
| Fixture key `"other-team/t3-foreign-confidential-adr#summary"` | → `"other-team/t3-foreign-hidden-adr#summary"` |
| Vector metadata `artifact_id` `"other-team/t3-foreign-confidential-adr"` | → `"other-team/t3-foreign-hidden-adr"` |
| Vector metadata `visibility` `"confidential"` | → `"hidden"` |
| Function `test_foreign_tier3_confidential_excluded` | Rename → `test_foreign_tier3_hidden_excluded` |
| Docstring for above | `"Foreign-scope tier 3 confidential artifact is excluded from results."` → `"hidden"` |
| Assertion artifact_id `"other-team/t3-foreign-confidential-adr"` | → `"other-team/t3-foreign-hidden-adr"` |

**`tests/unit/test_tools_search.py`**

| Element | Change |
|---|---|
| Comment `# own-scope tier 2 confidential` | → `# own-scope tier 2 hidden` |
| Fixture key `f"{write_prefix}/t2-confidential-review#summary"` | → `f"{write_prefix}/t2-hidden-review#summary"` |
| Vector metadata `artifact_id` `f"{write_prefix}/t2-confidential-review"` | → `f"{write_prefix}/t2-hidden-review"` |
| Vector metadata `visibility` `"confidential"` (own-scope) | → `"hidden"` |
| Comment `# foreign-scope tier 3 confidential — SHOULD NOT appear` | → `# foreign-scope tier 3 hidden — SHOULD NOT appear` |
| Fixture key `"other-team/t3-foreign-confidential-adr"` | → `"other-team/t3-foreign-hidden-adr"` |
| Vector metadata `artifact_id` (foreign) | → `"other-team/t3-foreign-hidden-adr"` |
| Vector metadata `visibility` `"confidential"` (foreign) | → `"hidden"` |
| Title `"Foreign tier 3 confidential ADR"` | → `"Foreign tier 3 hidden ADR"` |
| Function `test_foreign_tier3_confidential_absent` | Rename → `test_foreign_tier3_hidden_absent` |
| Docstring for above | update to `"hidden"` |
| Assertion artifact_id `"other-team/t3-foreign-confidential-adr"` | → `"other-team/t3-foreign-hidden-adr"` |
| Function `test_own_scope_tier2_confidential_present` | Rename → `test_own_scope_tier2_hidden_present` |
| Docstring for above | update to `"hidden"` |
| Assertion artifact_id `f"{write_prefix}/t2-confidential-review"` | → `f"{write_prefix}/t2-hidden-review"` |

**`tests/unit/test_tools_synthesise.py`**

| Element | Change |
|---|---|
| Comment `# foreign-scope tier 3 confidential — should be EXCLUDED` | → `# foreign-scope tier 3 hidden — should be EXCLUDED` |
| S3 fixture key `"other-team/t3-confidential-foreign"` | → `"other-team/t3-hidden-foreign"` |
| S3 metadata `visibility` `"confidential"` | → `"hidden"` |
| Vector key `"other-team/t3-confidential-foreign#summary"` | → `"other-team/t3-hidden-foreign#summary"` |
| Vector metadata `artifact_id` `"other-team/t3-confidential-foreign"` | → `"other-team/t3-hidden-foreign"` |
| Vector metadata `visibility` `"confidential"` | → `"hidden"` |
| Function `test_synthesise_foreign_tier3_confidential_excluded` | Rename → `test_synthesise_foreign_tier3_hidden_excluded` |
| Docstring for above | `"Foreign-scope tier 3 confidential artifact excluded from results."` → `"hidden"` |
| Assertion artifact_id `"other-team/t3-confidential-foreign"` | → `"other-team/t3-hidden-foreign"` |

---

#### Category C — README (user has already partially fixed; one remaining occurrence)

| File | Location | Change |
|---|---|---|
| `README.md` | Line 50, last sentence of the note | `"True access control has to happen at the AWS IAM layer to handle confidentiality."` → `"True access restriction (keeping content private from unauthorized AWS principals) requires IAM permissions."` |

---

#### Category D — Spec files (tech-writer task, no code impact)

All spec files use `"confidential"` only in test case descriptions, problem statements, and
boundary rules — no executable code. These are editorial changes.

**`docs/specs/p2-t8-search-artifacts.md`**

| Location | Change |
|---|---|
| Story 2 AC, line 50 | `"tier 3 confidential artifact in a subscribed foreign scope"` → `"tier 3 hidden artifact..."` |
| Test seeding line 164 | `"shared + confidential visibility"` → `"shared + hidden visibility"` |
| Cross-scope gate test line 183 | `"Tier 3 confidential foreign-scope artifact: absent from results"` → `"Tier 3 hidden..."` |
| Own-scope gate test line 184 | `"Own-scope tier 2 confidential artifact: present in results"` → `"Own-scope tier 2 hidden..."` |

**`docs/specs/p2-t9-read-artifact.md`**

| Location | Change |
|---|---|
| Problem Statement line 21 | `"confidential tier 2 documents simply by knowing their identifier"` → `"hidden tier 2 documents..."` |
| Story 2 title | `"Foreign-scope tier 2 artifacts are rejected"` — keep, no mention of confidential |
| Story 3 AC line 59 | `visibility="confidential"` → `visibility="hidden"` |
| Boundaries "Never" line 119 | `"Do not silently downgrade a confidential foreign artifact to 'not found'"` → `"Do not silently downgrade a hidden foreign artifact..."` |
| Test seeding line 146-147 | `"own-scope tier 3 confidential, foreign-scope tier 3 confidential"` → `"hidden"` throughout |
| Happy path line 152 | `"Own-scope tier 3 confidential artifact returned (no gate on own scope)"` → `"hidden"` |
| Access control line 161 | `"Foreign-scope tier 3 confidential → access-denied error"` → `"hidden"` |

**`docs/specs/p3-t10-list-artifacts.md`**

| Location | Change |
|---|---|
| Story 3 AC line 60 | `"tier 3 confidential artifact in a foreign scope"` → `"tier 3 hidden artifact..."` |
| Test seeding line 135 | `"foreign-scope active tier 3 confidential"` → `"hidden"` |
| Cross-scope gate line 161 | `"Foreign-scope tier 3 confidential → excluded"` → `"Foreign-scope tier 3 hidden → excluded"` |

**`docs/specs/p3-t12-delete-artifact.md`**

| Location | Change |
|---|---|
| Problem Statement line 18 | `"a confidential draft — permanent removal is the correct remedy"` → `"a hidden artifact — permanent removal..."` |

**`docs/specs/p3-t16-synthesise-artifacts.md`**

| Location | Change |
|---|---|
| Cross-scope gate line 152 | `"Foreign-scope tier 3 confidential → excluded"` → `"Foreign-scope tier 3 hidden → excluded"` |

---

#### Category E — PRD (tech-writer task)

| File | Location | Change |
|---|---|---|
| `docs/planning-artifacts/prd.md` | FR-01 (line 154) | `"visibility (shared or confidential)"` → `"visibility (shared or hidden)"` |

All other PRD occurrences of `"shared"` (in cross-scope gate descriptions, AC-06, AC-07, etc.)
are already correct and do not mention `"confidential"`.

---

#### Category F — Brainstorming files (tech-writer task, low priority)

These are historical exploration documents. Changes are low priority but keep the terminology
consistent for any future reader.

| File | Location | Change |
|---|---|---|
| `docs/brainstorming/brainstorming-existing-project-migration-2026-05-30.md` | Line 161 | `"confidential" for files the operator explicitly flags` → `"hidden" for files the operator explicitly flags` |
| `docs/brainstorming/brainstorming-delete-artifact-2026-05-30.md` | Line 89 | `"remove all confidential artifacts before a team offboards"` → `"remove all hidden artifacts before a team offboards"` |

---

### Critical implementation notes for the PM

#### 1 — Categories A and B must land in the same commit

The validator in `artifact.py` (Category A) and the test fixture data in unit tests (Category B)
are coupled. Once the validator only accepts `{"shared", "hidden"}`, any test that passes
`"confidential"` as a metadata value will fail — not with a clean assertion error, but because
the fixture data itself is invalid. Both categories must be updated atomically.

**Suggested developer task scope:** Category A (4 file locations) + Category B (5 test files) +
Category C README fix. One commit, all tests green after.

**Verification gate:** `uv run pytest tests/unit/ -q -m 'not integration'` must pass.

#### 2 — No existing stored data needs migration

All cross-scope gate checks in the server (`read.py`, `search.py`, `list.py`, `synthesise.py`)
check `visibility == "shared"`. They never check for `"confidential"` by name. This means:

- Existing stored artifacts with `visibility="confidential"` will continue to behave correctly
  (they will not appear in cross-scope results, exactly as before).
- No S3 data migration script is needed.
- The only user-facing change: agents that pass `visibility="confidential"` to `write_artifact`
  will receive a validation error after the code change. They must switch to `"hidden"`.

#### 3 — The "frozen after approval" note in spec files

All feature specs contain `<!-- SCOPE BLOCK — frozen after approval -->`. This terminology
change is not a scope change — it is a correction to naming used in test case descriptions
and problem statements. The tech-writer should treat these as editorial corrections and does
not need PM re-approval of the frozen scope.

#### 4 — Spec files are complete and implemented; changes are documentation-only

Phases 1–3 are fully implemented. The spec changes are retrospective corrections to historical
documentation. They do not change behaviour, acceptance criteria, or implementation guidance —
only the names used for test fixtures and the labels used in text. The developer does not need
to re-run or re-verify the spec tests after the tech-writer changes the spec documents.

#### 5 — The new `test_artifact_visibility_confidential_invalid` test

This is a new unit test the developer must add to `test_artifact.py`. It must assert that
`Artifact(visibility="confidential", ...)` raises `ValidationError`. This test did not exist
before (there was no reason to test an invalid value that was previously valid). It is
important because it makes the rename permanent and detectable if anyone tries to revert
the validator accidentally.

---

### Suggested work breakdown for PM

| Task | Assigned to | Scope | Verification |
|---|---|---|---|
| **D-task: Code + Tests + README** | Developer agent | Category A (source) + Category B (unit tests) + Category C (README) | `uv run pytest tests/unit/ -q -m 'not integration'` passes; `uv run mypy src/` clean; `uv run ruff check src/ tests/` clean |
| **TW-task: Spec files** | Tech-writer agent | Category D (5 spec files) | Human review; no automated verification needed |
| **TW-task: PRD** | Tech-writer agent | Category E (1 occurrence in prd.md) | Human review |
| **TW-task: Brainstorming** | Tech-writer agent (low priority) | Category F (2 brainstorming files) | Human review; can be deferred |

The developer task must complete first. Tech-writer tasks can run in parallel with each other and
after the developer task.

---

### Open questions

None. The decisions are clear:

- `"confidential"` → `"hidden"` everywhere (value, variable names, test names, prose)
- `"confidentiality"` (as a concept for this feature) → `"visibility control"` or rephrase
- Gate logic (`== "shared"`) is already correct — no logic changes needed
- No data migration — existing stored artifacts continue to work correctly
