---
type: spec
title: T31b — Migration Skill Exclusion Gate and ADR Gate Removal
description: Spec to add an arkeology:config pre-flight check to the migration skill, remove the ADR strategy gate, and source exclusions from the config block.
tags: []
timestamp: 2026-06-07T00:00:00Z
okf_version: "0.1"
feature: p9-t31b-migration-skill-exclusion-gate
status: complete
phase: 9
task: 31b
references:
  - docs/brainstorming/brainstorming-2026-06-02-setting-up-arkeology-skill.md
  - docs/brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md
  - docs/specs/p9-t31a-setting-up-arkeology-skill.md
  - docs/planning-artifacts/requirements.md
authored:
  by: "architect"
  date: "2026-06-07"
revised:
  by: "tech-writer"
  date: "2026-06-10"
---

# T31b — Migration Skill: Exclusion Gate and ADR Gate Removal

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Modify `skills/migrating-to-arkeology/SKILL.md` to: (1) add a pre-flight check at the
start of Step 2 that reads the `arkeology:config` block from AGENTS.md and hard-stops
if it is absent; (2) remove Step 2c (ADR strategy gate) entirely — exclusions now come
from the config block; (3) update Step 2d to source `local_only_paths` and
`local_only_types` from the block; (4) update Step 5 to remove the ADR variant
copy-paste and instead instruct the agent to confirm the AGENTS.md snippet is already
in place from the installation skill.

## Problem Statement

The migration skill currently asks the operator for their ADR strategy (Step 2c) and
appends an ADR-variant snippet to AGENTS.md (Step 5). Both actions are now owned by
the installation skill: the operator declares exclusions during `setting-up-arkeology` and
the decisions are recorded in the `arkeology:config` block. Asking again during
migration re-opens a settled decision and risks inconsistency. The config block also
serves as the installation sentinel — if it is absent, the operator has not completed
setup and migration should not proceed.

## User Stories

### Story 1 — Migration halts when installation has not run (P1)

An operator who skips the installation skill and goes straight to migration is redirected.

**Acceptance criteria:**
- Given AGENTS.md has no `arkeology:config` block, when the migration skill reaches the
  pre-flight check, then it stops immediately and tells the operator to run the
  `setting-up-arkeology` skill first before returning to migration.
- Given AGENTS.md has a `arkeology:config` block, when the migration skill reaches
  the pre-flight check, then it proceeds without any ADR or exclusion questions.

### Story 2 — Paths in local_only_paths are never seen by the migration scan (P1)

**Acceptance criteria:**
- Given `local_only_paths: [docs/adr/]` in the config block, when the scan in Step 2b
  runs, then no file under `docs/adr/` appears in the candidate list or the
  classification table.
- Given `local_only_paths: [docs/internal/private-design.md]` in the config block,
  when the scan runs, then that exact file is not presented to the operator.

### Story 3 — Types in local_only_types are excluded after classification (P1)

**Acceptance criteria:**
- Given `local_only_types: [adr, spec]` in the config block, when a file is classified
  as `adr` or `spec`, then it is removed from the candidate list before the
  classification table is presented.
- Given `local_only_types` is an empty list, when classification runs, then no types
  are excluded by the config block (the operator may still exclude individual files
  via Step 2b's manual exclusion list).

### Story 4 — Step 5 no longer re-asks ADR strategy or re-writes AGENTS.md snippet (P1)

**Acceptance criteria:**
- Given the migration skill reaches Step 5, then it does not ask the operator for their
  ADR strategy.
- Given the migration skill reaches Step 5, then the AGENTS.md update section instructs
  the agent to verify (not write) that the `arkeology:config` block and narrative
  snippet are present, referring the operator to `setting-up-arkeology` if they are absent.

## Requirements

- WHEN Step 2 starts THE SYSTEM SHALL check AGENTS.md for a `<!-- arkeology:config`
  block before any other Step 2 action.
- WHEN the block is absent THE SYSTEM SHALL stop immediately with the message:
  "Arkeology does not appear to be configured for this project. Run the
  `setting-up-arkeology` skill first, then return here."
- WHEN the block is present THE SYSTEM SHALL parse `local_only_paths` and
  `local_only_types` from its YAML content and carry both lists through the remainder
  of the workflow.
- WHEN Step 2b scans the repository THE SYSTEM SHALL skip any file whose path starts
  with a value from `local_only_paths` (trailing `/` = directory tree; no trailing `/`
  = exact file match).
- WHEN Step 2d classifies files THE SYSTEM SHALL discard any file whose resolved type
  is in `local_only_types`.
- WHEN Step 5 runs THE SYSTEM SHALL NOT ask the operator for ADR strategy and SHALL
  NOT write ADR variant text to AGENTS.md.
- WHEN Step 5 runs THE SYSTEM SHALL verify the `arkeology:config` block and the
  narrative snippet are present in AGENTS.md; if either is absent, instruct the
  operator to run `setting-up-arkeology` to write them.

## Boundaries

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

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/migrating-to-arkeology/SKILL.md` | Modify | Pre-flight check; remove Step 2c; update Step 2d → 2c; update Step 5 AGENTS.md section |

## Testing Approach

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

## Open Questions

*(none — all constraints are defined)*
