---
type: Spec
id: p9-t31b-migration-skill-exclusion-gate
title: T31b — Migration Skill Exclusion Gate and ADR Gate Removal
description: Spec to add an arkeology:config pre-flight check to the migration skill, remove the ADR strategy gate, and source exclusions from the config block.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/brainstorming/brainstorming-2026-06-02-setting-up-arkeology-skill.md
    title: Setting-Up-Arkeology Skill
    last_modified: 2026-06-07T00:00:00Z
  - resource: docs/brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md
    title: Multi-team / Multi-project Configuration
    last_modified: 2026-06-08T00:00:00Z
  - resource: docs/specs/p9-t31a-setting-up-arkeology-skill.md
    title: T31a — Setting-Up-Arkeology Skill
    last_modified: 2026-08-12T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
generated:
  by: "axians-architect/unknown"
  at: 2026-06-07T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T16:41:18Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T31b — Migration Skill: Exclusion Gate and ADR Gate Removal

## TL;DR

Modify `skills/migrating-to-arkeology/SKILL.md` to: (1) add a pre-flight check at the
start of Step 2 that reads the `arkeology:config` block from AGENTS.md and hard-stops
if it is absent; (2) remove Step 2c (ADR strategy gate) entirely — exclusions now come
from the config block; (3) update Step 2d to source `local_only_paths` and
`local_only_types` from the block; (4) update Step 5 to remove the ADR variant
copy-paste and instead instruct the agent to confirm the AGENTS.md snippet is already
in place from the installation skill.

## 1. Problem Statement

The migration skill currently asks the operator for their ADR strategy (Step 2c) and
appends an ADR-variant snippet to AGENTS.md (Step 5). Both actions are now owned by
the installation skill: the operator declares exclusions during `setting-up-arkeology` and
the decisions are recorded in the `arkeology:config` block. Asking again during
migration re-opens a settled decision and risks inconsistency. The config block also
serves as the installation sentinel — if it is absent, the operator has not completed
setup and migration should not proceed.

All four user stories behind these rules are P1.

## 2. Rules — Step 2 pre-flight

### R1 — Step 2 starts by checking for the `arkeology:config` block, and hard-stops without it

When Step 2 starts, the skill checks AGENTS.md for a `<!-- arkeology:config` block before any
other Step 2 action. When the block is absent, the skill stops immediately with the message:
"Arkeology does not appear to be configured for this project. Run the
`setting-up-arkeology` skill first, then return here." When the block is present, the skill
parses `local_only_paths` and `local_only_types` from its YAML content, carries both lists
through the remainder of the workflow, and proceeds without any ADR or exclusion questions.

**Example**

- Given AGENTS.md has no `arkeology:config` block, when the migration skill reaches the
  pre-flight check, then it stops immediately and tells the operator to run the
  `setting-up-arkeology` skill first before returning to migration.
- Given AGENTS.md has a `arkeology:config` block, when the migration skill reaches the
  pre-flight check, then it proceeds without any ADR or exclusion questions.

**Why:** the config block serves as the installation sentinel — an operator who skips the
installation skill and goes straight to migration is redirected, because without the block the
operator has not completed setup and migration should not proceed.

Source: none

## 3. Rules — Exclusions from the config block

### R2 — The Step 2b scan never sees a path in `local_only_paths`

When Step 2b scans the repository, the skill skips any file whose path starts with a value from
`local_only_paths` (trailing `/` = directory tree; no trailing `/` = exact file match).

**Example**

- Given `local_only_paths: [docs/adr/]` in the config block, when the scan in Step 2b runs,
  then no file under `docs/adr/` appears in the candidate list or the classification table.
- Given `local_only_paths: [docs/internal/private-design.md]` in the config block, when the
  scan runs, then that exact file is not presented to the operator.

Source: none

### R3 — A file whose type is in `local_only_types` is discarded after classification

When Step 2d classifies files, the skill discards any file whose resolved type is in
`local_only_types` — it is removed from the candidate list before the classification table is
presented.

**Example**

- Given `local_only_types: [adr, spec]` in the config block, when a file is classified as `adr`
  or `spec`, then it is removed from the candidate list before the classification table is
  presented.
- Given `local_only_types` is an empty list, when classification runs, then no types are
  excluded by the config block (the operator may still exclude individual files via Step 2b's
  manual exclusion list).

Source: none

## 4. Rules — Step 5

### R4 — Step 5 verifies the config block and snippet instead of asking and writing

When Step 5 runs, the skill does not ask the operator for ADR strategy and does not write ADR
variant text to AGENTS.md. Instead it verifies that the `arkeology:config` block and the
narrative snippet are present in AGENTS.md; if either is absent, it instructs the operator to run
`setting-up-arkeology` to write them. Step 5's AGENTS.md update section instructs the agent to
verify (not write) the config block and snippet.

**Why:** both actions are now owned by the installation skill; asking again during migration
re-opens a settled decision and risks inconsistency.

Source: none

## 5. Boundaries

**Always:**
- The pre-flight config block check is the very first action in Step 2 — before the
  existing manifest check (Step 2a). Update the Step 2 header and opening prose to
  reflect the new order: config check → manifest check → scope → classify.
- Path matching in Step 2b uses prefix matching: a `local_only_paths` entry of
  `docs/adr/` excludes any file whose path starts with `docs/adr/`; an entry of
  `docs/internal/private-design.md` excludes only that exact file.
- Type exclusion in Step 2d is applied after both Pass 1 and Pass 2 classification —
  the file is classified first, then checked against `local_only_types`.
- The operator's manual exclusion list (Step 2b, item 3) is additive to `local_only_paths`
  — the operator can still exclude additional files per-migration.
- Step 2c is removed entirely — no remnant text, no "see installation skill" note in
  its place. The numbered steps are renumbered: current 2d becomes 2c.
- The ADR removal guidance row in Step 5's tier 2 file removal table is updated to
  read: "Depends on the `adr_strategy` in your `arkeology:config` block."

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not add an inline fallback that re-asks exclusion questions if the config block is
  absent — always hard-stop and redirect to `setting-up-arkeology`.
- Do not change any other step (Steps 1, 3.A, 3.B, 4) — only Steps 2 and 5 are in scope.
- Do not change the two-pass classification logic or the always-skip rules.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/migrating-to-arkeology/SKILL.md` | Modify | Pre-flight check; remove Step 2c; update Step 2d → 2c; update Step 5 AGENTS.md section |

### Contracts

None.

### Testing Approach

Pure skill (markdown) update — no Python source files or unit tests. Verification by
inspection against the checklist below.

**Step 2 — pre-flight and discovery:**
- [ ] Step 2 opens with a config block check section before Step 2a (manifest check)
- [ ] Hard-stop message names `setting-up-arkeology` explicitly
- [ ] Step 2a (manifest check) is unchanged and follows the pre-flight check
- [ ] Step 2b (scope) applies `local_only_paths` exclusions during scan — described
  explicitly with prefix-matching semantics
- [ ] Step 2c (old ADR strategy gate) is completely absent — no heading, no table,
  no reference to the two-strategy decision
- [ ] What was Step 2d is now renumbered Step 2c and references `local_only_types`
  for post-classification exclusion
- [ ] Step 2 workflow summary at the top of the skill is updated to reflect the new
  sub-step order

**Step 5 — post-migration:**
- [ ] No ADR strategy question in Step 5
- [ ] Variant A and Variant B markdown blocks are removed
- [ ] The AGENTS.md update section instructs the agent to verify (not write) the
  config block and snippet and refers the operator to `setting-up-arkeology` if absent
- [ ] ADR row in the tier 2 file removal table references `adr_strategy` in the
  config block rather than "your strategy chosen in Step 2"

**Regression check:**
- [ ] Steps 1, 3.A, 3.B, 4 are unchanged — diff shows no edits outside Steps 2 and 5
- [ ] Always-skip exclusion list is unchanged
- [ ] Two-pass classification tables are unchanged
