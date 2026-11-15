---
type: Spec
id: p12-t53-reference-backfill-skill
title: T53 — Reference-Backfill Cleanup Skill (optional, decoupled, dry-run-first)
description: An optional, skippable-by-default skill that content-scans artifacts against the migration path→identifier map, presents a dry-run batch report of proposed references backfills for operator review, and applies confirmed backfills via link_metadata. Never rewrites stored content; never mutates metadata without confirmation. Resolves OQ1-cleanup with a batch-approval UX.
tags: []
status: deprecated
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
    title: Artifact Cross-Referencing — First-Class references Field, Migration Rewrite, and referenced_by Warning
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/specs/p12-t49-link-metadata.md
    title: T49 — link_metadata Tool (generalizes and supersedes link_commit)
    last_modified: 2026-09-06T00:00:00Z
  - resource: docs/specs/p12-t51-migration-reference-rewrite.md
    title: T51 — Migration Frontmatter Reference Rewriting + arkeology:// Content Rewrite
    last_modified: 2026-08-13T00:00:00Z
  - resource: docs/specs/p10-t40-migration-skill-commit-refs-backfill.md
    title: T40 — Migration Skill commit_refs Backfill Options
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
generated:
  by: "axians-architect/claude-opus-4.8"
  at: 2026-07-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T17:44:06Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T53 — Reference-Backfill Cleanup Skill (optional, decoupled, dry-run-first)

## TL;DR

Ship an optional, skippable-by-default skill that backfills the structured `references` field onto
already-written artifacts whose references could not be resolved inline at migration time (targets
absent from the original batch, references discovered later). It content-scans own-scope artifacts
against the migration path→identifier map, presents a **single dry-run batch report** of proposed
`references` backfills for operator review, and applies confirmed backfills via `link_metadata`
(T49). It never rewrites stored content and never mutates metadata without confirmation. (FR-58,
AC-63; resolves OQ1-cleanup.)

## 1. Problem Statement

The migration rewrite (T51) resolves references at first-write time, but a reference can only be
backfilled once its target exists and is resolvable — targets absent from the original batch, or
references discovered after a write, cannot be resolved inline
(adr-2026-07-03-artifact-cross-referencing D10). Mirroring the existing commit-refs backfill pattern
(p10-t40), a decoupled post-hoc skill is the right vehicle: it runs when the operator chooses,
resolves what is now resolvable, and applies it through the safe, embedding-free `link_metadata`
primitive without touching stored content or tier-2 append-only content rules
(adr-2026-07-03-artifact-cross-referencing D8).

All three stories are P1: dry-run batch report before any write (P1); confirmed backfills route
through link_metadata (P1); skippable by default, declining changes nothing (P1).

## 2. Rules — Discovery

### R1 — Discovery scans own-scope active artifacts against the migration path→identifier map

When the skill runs, it discovers candidates by enumerating own-scope active artifacts
(`list_artifacts`), reading each artifact's content (`read_artifact`), and matching repo-relative
path references — frontmatter `references:` first — against the migration path→identifier map (T51
helpers). In-body links are advisory-only: surfaced for the operator, never auto-applied. The skill
operates on the deployment's own artifacts only.

Source: OQ1-cleanup — the discovery-scan part

### R2 — A resolved target not already referenced is proposed as a backfill candidate

When a matched target resolves to an `artifact_id` not already present in the artifact's
`references`, the skill proposes it as a backfill candidate.

## 3. Rules — Review and apply

### R3 — A single dry-run batch report precedes any write

When discovery completes, the skill presents a single dry-run batch report listing, per artifact,
the proposed `references` additions (target path → resolved `artifact_id`), and makes NO metadata
write until the operator confirms. Reviewing the report, the operator may approve the whole batch,
or edit/remove individual proposed entries before applying.

**Why:** Recommendation (adopted in this spec): *batch approval* — a single consolidated dry-run
report of all proposed backfills, which the operator approves wholesale or edits/removes entries
from before applying, rather than a per-artifact prompt loop (lower operator friction, matches the
dry-run-first commit-refs backfill precedent in p10-t40). Confirm this UX with the operator before
implementation if a per-artifact review is preferred.

Source: AC-63; OQ1-cleanup

### R4 — Confirmed backfills are applied only through `link_metadata`, never by rewriting content

When the operator confirms, the skill applies the backfills via `link_metadata(references=…)`, with
the resolved `references` per artifact — `link_metadata` being the embedding-free, dual-write
primitive (T49) — and never rewrites stored content: content is fixed after first write.

Source: AC-63; adr-2026-07-03-artifact-cross-referencing D8 — the content-is-fixed part

### R5 — Re-running the skill does not duplicate references

Given `link_metadata` is idempotent, re-running the skill does not duplicate references.

### R6 — Skippable by default; declining or skipping changes nothing

When the operator skips or declines the skill, every artifact is left unchanged.

Source: AC-63

## 4. Rules — Distribution

### R7 — The skill needs no per-skill wiring

When the skill is distributed, it requires no per-skill wiring: placing `SKILL.md` in a new
directory under `plugins/arkeology/skills/` is sufficient for all three channels — the OpenCode JS
plugin registers the whole `plugins/arkeology/skills` directory into `config.skills.paths`, the
Claude Code plugin is declared once in `plugins/arkeology/.claude-plugin/plugin.json`, and
`install.sh` loops `plugins/arkeology/skills/*/` for `gh skill install`.

### R8 — The skill's offline snippets are held to the server by T51's drift test

The skill documents two offline `python3` snippets — the full-key computation and the frontmatter
`references:` extraction — because it must compute both before the server is reachable. Each stays
behaviourally identical to the server's `generate_artifact_id` (composed into the full key) and
`extract_references_list`, and both are covered by the parameterised drift test T51 owns: a change
to either snippet that diverges from the server, or a snippet the test can no longer locate, fails
the unit suite.

Source: p12-t51-migration-reference-rewrite R10, R11, R12

## 5. Boundaries

**Always:**
- Dry-run first; operator confirmation before any write (AC-63).
- Backfill is applied only via `link_metadata` — the embedding-free, dual-write primitive (T49).
- Own-scope only — the skill operates on the deployment's own artifacts.
- Consistent with existing skill style and length conventions (≤ ~500 lines, cross-IDE, no
  IDE-specific tool references in the body).

**Ask First:**
- Any metadata mutation — never applied without explicit operator confirmation of the batch.

**Never:**
- Do not rewrite stored artifact content (adr-2026-07-03-artifact-cross-referencing D8 — content is
  fixed after first write).
- Do not auto-apply in-body-link matches — surface them for the operator only.
- Do not add server code — this is a skill-only deliverable (ruff + mypy unaffected).

## 6. For the developer agent

### Files to Touch

Skills live directly at `plugins/arkeology/skills/<name>/SKILL.md` — one canonical copy, no
top-level `skills/` directory, no symlinks.

| File | Action | Notes |
|------|--------|-------|
| `plugins/arkeology/skills/backfilling-references/SKILL.md` | Create | The skill, and the only file it needs: discovery scan → dry-run batch report → confirm → apply via `link_metadata` |
| `.opencode/plugins/arkeology.js` | Verify | No change — the plugin pushes the whole `plugins/arkeology/skills` directory onto `config.skills.paths`; new subdirectories are picked up automatically |
| `plugins/arkeology/.claude-plugin/plugin.json` | Verify | No change — the manifest declares the plugin, not individual skills; Claude Code discovers `skills/*/` beneath it |
| `install.sh` | Verify | No change — the Copilot branch already loops `plugins/arkeology/skills/*/` and runs `gh skill install` per directory; confirm the new skill appears in the run output |
| `README.md` | Modify | Add the skill to the skills table / brief mention (optional cleanup step) |

### Contracts

None.

### Testing Approach

Skill-only — no unit tests written as part of this task (ruff + mypy unaffected). Validate
against the plan's done-condition manually: the skill presents a dry-run batch report before any
write; confirmed backfills route through `link_metadata`; declining leaves all artifacts
unchanged; no stored content is rewritten; skill text is consistent with existing skill style;
the skill is discoverable through each plugin channel.

The skill's two offline snippets (R8) are covered by T51's `tests/unit/test_skill_artifact_id_drift.py`,
which runs both of `backfilling-references/SKILL.md`'s documented snippets against the server; a
change to either snippet is checked there, not by a test of this task.
