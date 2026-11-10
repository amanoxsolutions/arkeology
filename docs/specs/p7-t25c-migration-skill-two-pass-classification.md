---
type: Spec
id: p7-t25c-migration-skill-two-pass-classification
title: Migration Skill — Two-Pass File Classification
description: Replaces the fragile docs-root discovery and single-level subdirectory matching in the migration skill with a two-pass system — filename stem rules first, then path-segment pattern rules — to correctly classify files in non-standard directory layouts.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-06-01T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T15:56:54Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# Migration Skill — Two-Pass File Classification

## TL;DR

Replace the fragile docs-root discovery + single-level subdirectory matching in the migration
skill's Step 2 with a two-pass classification system: (1) filename stem rules that fire regardless
of directory location, then (2) path segment pattern rules (`**/pattern` style) that match at any
depth in the repo tree. This fixes misclassification of files in non-standard directory layouts
(e.g. `_bmad-output/brainstorming/`) for operators migrating a project.

## 1. Problem Statement

The migration skill's Step 2 discovery tries to find a docs root (`docs/`, `documentation/`,
`doc/`, `wiki/`) before applying directory patterns. When documentation lives under a
non-standard prefix (e.g. `_bmad-output/`), none of the candidates match and the skill falls back
to treating the repo root as the docs root. From that point every directory pattern fails —
`brainstorming/` does not match `_bmad-output/brainstorming/` relative to the repo root — and all
files are treated as ambiguous, falling to unreliable judgment. The result: brainstorming files
are classified as `session_summary`, `prd.md` is classified as `spec`, and the operator must
manually correct every row. The filename-level rule (`prd.md` → `prd`) was also buried in a note
below the directory table and was never reached via the ambiguous path.

All three user stories this spec states are P1: files in non-standard directory prefixes classify
correctly, filename rules fire before directory rules, and path segment patterns match at any
depth.

## 2. Rules — Two-pass classification

### R1 — Step 2 classifies every Markdown file in passes, in order

Step 2 scans the repository for migration candidates and classifies every `.md` file found using
the passes below, in order, so an operator whose docs live under a non-standard prefix such as
`_bmad-output/` sees correct automatic classification without needing to correct every row:

1. **Pass 1 — filename rules.** When a file's stem exactly matches a filename rule
   (case-insensitive), the skill assigns that type and tier and skips Pass 2.
2. **Pass 2 — path segment rules.** When no filename rule matches, the skill checks every
   directory segment in the file's path against the path segment table (case-insensitive, any
   depth).
3. **Pass 3 — judgment.** When no path segment rule matches, the skill falls back to judgment.

**Example**

- Given a file at `_bmad-output/brainstorming/brainstorming-V1.md`, when Step 2 classification
  runs, then the file is proposed as `type=brainstorming`, `tier=2`.
- Given a file at `_bmad-output/planning-artifacts/prd.md`, when Step 2 classification runs, then
  the file is proposed as `type=prd`, `tier=3`.
- Given a file at `_bmad-output/planning-artifacts/implementation-readiness.md`, when Step 2
  classification runs, then the file is proposed as `type=spec`, `tier=3`.

Source: —

### R2 — Pass 1 assigns the type by filename stem

Pass 1 matches on the file's stem (filename without extension), case-insensitive, exact match,
regardless of where the file sits in the repo, so a `prd.md` or `plan.md` inside any folder gets
the correct type assigned by filename, regardless of the parent directory name. If a rule
matches, classification stops and Pass 2 is not consulted.

| Filename stems (exact, case-insensitive) | Type | Tier |
|---|---|---|
| `vision` | `vision` | 3 |
| `prd`, `product-requirements`, `requirements` | `requirements` | 3 |
| `plan`, `planning`, `project-plan`, `roadmap` | `plan` | 3 |
| `changelog`, `change-log`, `changes`, `release-notes` | `changelog` | 2 |
| `runbook`, `run-book`, `playbook` | `runbook` | 3 |
| `postmortem`, `post-mortem`, `incident-report` | `postmortem` | 2 |
| `learnings`, `learning`, `lessons-learned` | `learning` | 3 |

There is no `prd` type: `vision` and `requirements` replace it, mirroring the amanox
planning-artifact convention this project itself now follows (`vision.md` + `requirements.md` in
place of a single `prd.md`). The stems `prd`, `product-requirements` and `requirements` (the
legacy single-document convention, still common in migrated projects) map to `requirements` —
its content is predominantly requirements-shaped, and "requirements" is literally part of the
name, so this is the closer content match of the two new types. See `p7-t25b`'s matching
follow-up for the `resources.py` and Step 7 table changes.

**Example**

- Given `any-folder/prd.md`, when Step 2 classification runs, then the file is proposed as
  `type=prd`, `tier=3` — not `type=spec`.
- Given `any-folder/plan.md`, when Step 2 classification runs, then the file is proposed as
  `type=plan`, `tier=3`.
- Given `any-folder/changelog.md`, when Step 2 classification runs, then the file is proposed as
  `type=changelog`, `tier=2`.

Source: —

### R3 — Pass 2 assigns the type by path segment, at any depth

When no filename rule matched, Pass 2 checks every directory segment of the file's path,
case-insensitive. The `**/pattern` notation means the segment can appear at any depth —
`docs/brainstorming/`, `_bmad-output/brainstorming/`, and `work/project/brainstorming/` all match
`**/brainstorming`. The first matching row is used. An operator with `brainstorm/` nested two
levels deep still gets correct classification without a docs-root discovery step.

| Path segment pattern(s) | Type | Tier |
|---|---|---|
| `**/brainstorming`, `**/brainstorm`, `**/research`, `**/ideas`, `**/investigation`, `**/investigations`, `**/explore`, `**/exploration` | `brainstorming` | 2 |
| `**/adr`, `**/adrs`, `**/architecture`, `**/architectural-decisions`, `**/decisions` | `adr` | 3 |
| `**/specs`, `**/spec`, `**/specifications`, `**/specification` | `spec` | 3 |
| `**/planning-artifacts`, `**/planning`, `**/plans` | `spec` | 3 |
| `**/sessions`, `**/session-notes`, `**/notes`, `**/logs` | `session_summary` | 2 |
| `**/code-reviews`, `**/code_reviews`, `**/reviews`, `**/review` | `code_review` | 2 |
| `**/implementation-notes`, `**/impl-notes`, `**/implementation`, `**/dev-notes` | `implementation_note` | 2 |
| `**/runbooks`, `**/runbook`, `**/ops`, `**/operations`, `**/procedures`, `**/playbooks` | `runbook` | 3 |
| `**/changelogs`, `**/changelog`, `**/releases`, `**/release-notes` | `changelog` | 2 |
| `**/postmortems`, `**/postmortem`, `**/incidents`, `**/incident-reports` | `postmortem` | 2 |
| `**/learnings`, `**/lessons-learned` | `learning` | 3 |

When a path segment matches `**/planning-artifacts`, `**/planning`, or `**/plans`, the skill
assigns `type=spec` — but Pass 1 fires first, so `prd.md` and `plan.md` inside those directories
still resolve to `prd` and `plan` respectively.

**Example**

- Given `project/work/brainstorm/ideas.md`, when Step 2 classification runs, then the file is
  proposed as `type=brainstorming`, `tier=2`.
- Given `docs/reviews/pr-123.md`, when Step 2 classification runs, then the file is proposed as
  `type=code_review`, `tier=2`.
- Given `src/docs/specifications/auth.md`, when Step 2 classification runs, then the file is
  proposed as `type=spec`, `tier=3`.

Source: —

### R4 — Pass 3 falls back to judgment

If neither pass matched, the skill reads the file content and uses judgment to assign a type and
tier. It defaults to `visibility=shared` unless the content is clearly team-internal or
sensitive.

Source: —

### R5 — No docs-root discovery

When no docs root is found, the skill does not fall back to treating the repo root as a fixed
docs root — the two-pass system makes docs-root detection unnecessary.

Source: —

### R6 — The ADR git-only exclusion applies after classification

If the operator chose **git only** for ADRs, the skill applies the classification first and then
excludes files that resolved to `adr` — classify first, then exclude.

Source: —

## 3. Boundaries

**Always:**

- Pass 1 (filename) has higher priority than Pass 2 (path segment) — a filename match terminates
  classification; Pass 2 is never consulted.
- Matching is case-insensitive for both stems and path segments.
- The ADR exclusion rule (skip `adr` files when operator chose git-only strategy) applies after
  classification, not before — classify first, then exclude.
- Step 7 removal guidance, Step 3 table format, and all other steps are unchanged.

**Ask First:**

- None — nothing is ambiguous; scope is fully defined.

**Never:**

- Do not add a docs-root discovery step back — the two-pass system replaces it entirely.
- Do not change any step other than Step 2's classification section.
- Do not modify Python source code, tests, or any file outside the skill.

## 4. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/migrating-to-arkeology/SKILL.md` | Modify | Replace the docs-root discovery sub-step and the old directory table with the two-pass system described below |

### Exact replacement

**Remove**: everything from `"Scan the repository for migration candidates…"` through the end of
the `### Ambiguous files` section (inclusive).

**Replace with** the following content (preserve the `---` separator before Step 3):

---

```
Scan the repository for migration candidates. Classify every `.md` file found using
the two passes below, in order. If the operator chose **git only** for ADRs, apply
the classification first and then exclude files that resolved to `adr`.

### Pass 1 — Filename rules (highest priority)

Match on the file's stem (filename without extension), case-insensitive, exact match.
Applies regardless of where the file sits in the repo. If a rule matches, **stop —
do not consult Pass 2**.

| Filename stems (exact, case-insensitive) | Type | Tier |
|---|---|---|
| `vision` | `vision` | 3 |
| `prd`, `product-requirements`, `requirements` | `requirements` | 3 |
| `plan`, `planning`, `project-plan`, `roadmap` | `plan` | 3 |
| `changelog`, `change-log`, `changes`, `release-notes` | `changelog` | 2 |
| `runbook`, `run-book`, `playbook` | `runbook` | 3 |
| `postmortem`, `post-mortem`, `incident-report` | `postmortem` | 2 |
| `learnings`, `learning`, `lessons-learned` | `learning` | 3 |

### Pass 2 — Path segment rules

If no filename rule matched, check every **directory segment** of the file's path,
case-insensitive. The `**/pattern` notation means the segment can appear at any depth —
`docs/brainstorming/`, `_bmad-output/brainstorming/`, and `work/project/brainstorming/`
all match `**/brainstorming`. Use the **first matching row**.

| Path segment pattern(s) | Type | Tier |
|---|---|---|
| `**/brainstorming`, `**/brainstorm`, `**/research`, `**/ideas`, `**/investigation`, `**/investigations`, `**/explore`, `**/exploration` | `brainstorming` | 2 |
| `**/adr`, `**/adrs`, `**/architecture`, `**/architectural-decisions`, `**/decisions` | `adr` | 3 |
| `**/specs`, `**/spec`, `**/specifications`, `**/specification` | `spec` | 3 |
| `**/planning-artifacts`, `**/planning`, `**/plans` | `spec` | 3 |
| `**/sessions`, `**/session-notes`, `**/notes`, `**/logs` | `session_summary` | 2 |
| `**/code-reviews`, `**/code_reviews`, `**/reviews`, `**/review` | `code_review` | 2 |
| `**/implementation-notes`, `**/impl-notes`, `**/implementation`, `**/dev-notes` | `implementation_note` | 2 |
| `**/runbooks`, `**/runbook`, `**/ops`, `**/operations`, `**/procedures`, `**/playbooks` | `runbook` | 3 |
| `**/changelogs`, `**/changelog`, `**/releases`, `**/release-notes` | `changelog` | 2 |
| `**/postmortems`, `**/postmortem`, `**/incidents`, `**/incident-reports` | `postmortem` | 2 |
| `**/learnings`, `**/lessons-learned` | `learning` | 3 |

### Pass 3 — Judgment fallback

If neither pass matched, read the file content and use judgment to assign a type and
tier. Default to `visibility=shared` unless the content is clearly team-internal or
sensitive.
```

---

### Contracts

None.

### Testing Approach

This is a pure skill (markdown) update — no Python source files or unit tests are involved.
Verification is by inspection:

1. Read the updated `skills/migrating-to-arkeology/SKILL.md` Step 2 section and confirm:
   - The docs-root discovery sub-step (the 5-bullet list) is gone
   - Pass 1 filename table is present and matches the spec exactly
   - Pass 2 path segment table is present with all aliases from the spec
   - Pass 3 judgment fallback text is present
   - The old `### Directory → type mapping` table and the `### Ambiguous files` section are gone
   - All other sections (Steps 1, 3–7) are untouched
2. Verify the three non-standard-prefix scenarios of R1 mentally against the new rules:
   - `_bmad-output/brainstorming/brainstorming-V1.md` → stem `brainstorming-v1` no filename
     match → path has segment `brainstorming` → `brainstorming` tier 2 ✓
   - `_bmad-output/planning-artifacts/prd.md` → stem `prd` → filename rule → `prd`
     tier 3 ✓
   - `_bmad-output/planning-artifacts/implementation-readiness.md` → no filename match → path
     has segment `planning-artifacts` → `spec` tier 3 ✓
