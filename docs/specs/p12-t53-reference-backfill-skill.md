---
type: spec
title: T53 — Reference-Backfill Cleanup Skill (optional, decoupled, dry-run-first)
description: An optional, skippable-by-default skill that content-scans artifacts against the migration path→identifier map, presents a dry-run batch report of proposed references backfills for operator review, and applies confirmed backfills via link_metadata. Never rewrites stored content; never mutates metadata without confirmation. Resolves OQ1-cleanup with a batch-approval UX.
tags: []
timestamp: 2026-07-03T00:00:00Z
okf_version: "0.1"
feature: p12-t53-reference-backfill-skill
status: ready
phase: 12
task: 53
references:
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/specs/p12-t49-link-metadata.md
  - docs/specs/p12-t51-migration-reference-rewrite.md
  - docs/specs/p10-t40-migration-skill-commit-refs-backfill.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-07-03"
revised:
  by: "architect"
  date: "2026-08-13"
---

# T53 — Reference-Backfill Cleanup Skill (optional, decoupled, dry-run-first)

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Ship an optional, skippable-by-default skill that backfills the structured `references` field onto
already-written artifacts whose references could not be resolved inline at migration time (targets
absent from the original batch, references discovered later). It content-scans own-scope artifacts
against the migration path→identifier map, presents a **single dry-run batch report** of proposed
`references` backfills for operator review, and applies confirmed backfills via `link_metadata`
(T49). It never rewrites stored content and never mutates metadata without confirmation. (FR-58,
AC-63; resolves OQ1-cleanup.)

## Problem Statement

The migration rewrite (T51) resolves references at first-write time, but a reference can only be
backfilled once its target exists and is resolvable — targets absent from the original batch, or
references discovered after a write, cannot be resolved inline (ADR-012 D10). Mirroring the existing
commit-refs backfill pattern (p10-t40), a decoupled post-hoc skill is the right vehicle: it runs
when the operator chooses, resolves what is now resolvable, and applies it through the safe,
embedding-free `link_metadata` primitive without touching stored content or tier-2 append-only
content rules (ADR-012 D8).

## User Stories

### Story 1 — Dry-run batch report before any write (P1)

**Acceptance criteria:**
- Given the skill is run, when it completes discovery then it presents a single batch report listing,
  per artifact, the proposed `references` additions (target path → resolved `artifact_id`) and makes
  NO write until the operator confirms. (AC-63)
- Given the operator reviews the report, then they may approve the whole batch, or edit/remove
  individual proposed entries before applying.

### Story 2 — Confirmed backfills route through link_metadata (P1)

**Acceptance criteria:**
- Given the operator confirms, when the skill applies backfills then it calls `link_metadata` with
  the resolved `references` per artifact — no stored content is rewritten. (AC-63)
- Given `link_metadata` is idempotent, then re-running the skill does not duplicate references.

### Story 3 — Skippable by default; declining changes nothing (P1)

**Acceptance criteria:**
- Given the operator skips or declines the skill, then no artifact is changed. (AC-63)

## Requirements

- WHEN the skill runs THE SYSTEM SHALL discover candidates by enumerating own-scope active artifacts
  (`list_artifacts`), reading each artifact's content (`read_artifact`), and matching repo-relative
  path references (frontmatter `references:` first; in-body links are advisory-only, surfaced for
  the operator, never auto-applied) against the migration path→identifier map (T51 helpers).
- WHEN a matched target resolves to an `artifact_id` not already present in the artifact's
  `references` THE SYSTEM SHALL propose it as a backfill candidate.
- WHEN discovery completes THE SYSTEM SHALL present a single dry-run batch report and SHALL make no
  metadata write until the operator confirms.
- WHEN the operator confirms THE SYSTEM SHALL apply the backfills via `link_metadata(references=…)`
  and SHALL NOT rewrite stored content.
- WHEN the operator declines or skips THE SYSTEM SHALL leave every artifact unchanged.
- WHEN the skill is distributed THE SYSTEM SHALL require no per-skill wiring: placing
  `SKILL.md` in a new directory under `plugins/arkeology/skills/` is sufficient for all three
  channels — the OpenCode JS plugin registers the whole `plugins/arkeology/skills` directory into
  `config.skills.paths`, the Claude Code plugin is declared once in
  `plugins/arkeology/.claude-plugin/plugin.json`, and `install.sh` loops
  `plugins/arkeology/skills/*/` for `gh skill install`. *(Corrected 2026-08-12 — the original
  wording described the retired top-level `skills/` + symlink layout.)*

## Boundaries

**Always:**
- Dry-run first; operator confirmation before any write (AC-63).
- Backfill is applied only via `link_metadata` — the embedding-free, dual-write primitive (T49).
- Own-scope only — the skill operates on the deployment's own artifacts.
- Consistent with existing skill style and length conventions (≤ ~500 lines, cross-IDE, no
  IDE-specific tool references in the body).

**Ask First:**
- Any metadata mutation — never applied without explicit operator confirmation of the batch.

**Never:**
- Do not rewrite stored artifact content (ADR-012 D8 — content is fixed after first write).
- Do not auto-apply in-body-link matches — surface them for the operator only.
- Do not add server code — this is a skill-only deliverable (ruff + mypy unaffected).

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

> **Layout correction 2026-08-12 (tech-writer).** The original table described the
> pre-consolidation layout: a top-level `skills/backfilling-references/` directory plus a symlink
> at `plugins/arkeology/skills/backfilling-references` pointing into it. That layout no longer
> exists. Skills live **directly** at `plugins/arkeology/skills/<name>/SKILL.md` — one canonical
> copy, no top-level `skills/` directory, no symlinks anywhere. Verified against the working tree
> on 2026-08-12.

| File | Action | Notes |
|------|--------|-------|
| `plugins/arkeology/skills/backfilling-references/SKILL.md` | Create | The skill, and the only file it needs: discovery scan → dry-run batch report → confirm → apply via `link_metadata` |
| `.opencode/plugins/arkeology.js` | Verify | No change — the plugin pushes the whole `plugins/arkeology/skills` directory onto `config.skills.paths`; new subdirectories are picked up automatically |
| `plugins/arkeology/.claude-plugin/plugin.json` | Verify | No change — the manifest declares the plugin, not individual skills; Claude Code discovers `skills/*/` beneath it |
| `install.sh` | Verify | No change — the Copilot branch already loops `plugins/arkeology/skills/*/` and runs `gh skill install` per directory; confirm the new skill appears in the run output |
| `README.md` | Modify | Add the skill to the skills table / brief mention (optional cleanup step) |

## Testing Approach

Skill-only — no unit tests written as part of this task (ruff + mypy unaffected). Validate
against the plan's done-condition manually: the skill presents a dry-run batch report before any
write; confirmed backfills route through `link_metadata`; declining leaves all artifacts
unchanged; no stored content is rewritten; skill text is consistent with existing skill style;
the skill is discoverable through each plugin channel.

> **Note (2026-08-13, architect).** This skill's two offline snippets — ID computation and
> frontmatter `references:` extraction — are covered, but by a drift-guard suite owned by T51,
> not by this task: `tests/unit/test_skill_artifact_id_drift.py` executes both of
> `backfilling-references/SKILL.md`'s documented snippets against the server's
> `generate_artifact_id` and `extract_references_list` (see
> `docs/specs/p12-t51-migration-reference-rewrite.md`, Story 5 and Story 6). No action is needed
> here; noted so "no unit tests written as part of this task" isn't misread as "this skill has no
> test coverage at all."

## Open Questions

- **OQ1-cleanup (resolved):** Per-artifact vs batch approval, and discovery-scan specifics.
  **Recommendation (adopted in this spec):** *batch approval* — a single consolidated dry-run report
  of all proposed backfills, which the operator approves wholesale or edits/removes entries from
  before applying, rather than a per-artifact prompt loop (lower operator friction, matches the
  dry-run-first commit-refs backfill precedent in p10-t40). Discovery scan = enumerate own-scope
  active artifacts via `list_artifacts`, read each via `read_artifact`, match **frontmatter**
  `references:` paths against the T51 path→id map to propose resolved additions; in-body links are
  surfaced advisory-only, never auto-applied. Confirm this UX with the operator before implementation
  if a per-artifact review is preferred.
