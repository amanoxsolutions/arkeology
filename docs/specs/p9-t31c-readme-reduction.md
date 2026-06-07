---
type: feature-spec
feature: p9-t31c-readme-reduction
status: ready
phase: 9
task: 31c
references:
  - docs/brainstorming/brainstorming-2026-06-02-installing-cairn-skill.md
  - docs/specs/p9-t31a-installing-cairn-skill.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-06-07"
revised:
  by: "architect"
  date: "2026-06-07"
---

# T31c — README Reduction

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Slim `README.md` further by removing the remaining operational sections that have moved
into the `installing-cairn` skill (`## Connecting to an MCP client` and
`## Recommended AGENTS.md Snippet`), and update the `## Key Features` section to
reflect the generalised exclusion model. The `## AWS Provisioning` section, the
provisioning IAM policy, and the `.env` installation step have already been removed
from the README as part of the scope-correction for T31. Replace each removed section
with a one-sentence pointer to the skill. The target line count after all T31 changes
is approximately 330 lines (higher than originally estimated because the promoted
`## Minimum IAM Policy` section and the retained `## Using the Migration Skill`
section together account for ~97 lines not included in the original projection).

## Problem Statement

The README still contains two large sections (`## Connecting to an MCP client` and
`## Recommended AGENTS.md Snippet`) that belong in the `installing-cairn` skill rather
than in the README. Keeping them risks drift as the skill evolves and adds content that
is operationally redundant once the skill exists. Removing them and replacing with
pointers completes the README's transformation into a focused discovery document.

## User Stories

### Story 1 — A new operator discovers cairn-mcp and understands what it is (P1)

**Acceptance criteria:**
- Given a developer reading the README for the first time, when they reach the end,
  then they understand what cairn-mcp does, whether it suits their project, and exactly
  what to do next to get started (run the `installing-cairn` skill).
- Given a developer scanning for the configuration reference, when they find it in the
  README, then every environment variable is documented with its default and a brief
  description.

### Story 2 — The README stays current with the skill (P2)

**Acceptance criteria:**
- Given the `installing-cairn` skill evolves, when the README is reviewed, then the
  README contains no duplicated operational steps that could drift — only concept
  content and config reference that are stable.

### Story 3 — Key Features reflects the generalised exclusion model (P1)

The `## Key Features` bullet that previously described only the ADR strategy now
describes the full permanent-exclusion capability.

**Acceptance criteria:**
- Given the updated README `## Key Features` section, when the "Flexible ADR &
  document strategy" bullet is read, then it conveys that teams can keep ADRs, specs,
  plans, or any folder in git and that the decision is recorded once in `AGENTS.md`.
- Given the updated bullet, when it is compared to the old "Flexible ADR strategy"
  text, then it no longer implies ADRs are the only type of document that can stay
  in git.

## Requirements

- WHEN the README is updated THE SYSTEM SHALL remove `## Connecting to an MCP client`
  (including both IDE sub-sections) and `## Recommended AGENTS.md Snippet` (including
  `### Declare your ADR strategy first` and the full snippet body from
  `### cairn-mcp — Persistent Artifact Memory` to end of snippet), replacing each with
  a one-sentence pointer: "See the `installing-cairn` skill for interactive
  step-by-step guidance."
- WHEN the README is updated THE SYSTEM SHALL update the `## Key Features` bullet
  currently titled "Flexible ADR strategy" to read "Flexible ADR & document strategy"
  with a description that conveys: teams can designate ADRs, specs, plans, or any
  folder as git-only during installation; the decision is recorded once in `AGENTS.md`
  and respected by every future agent session and the migration skill automatically.
- WHEN the README is updated THE SYSTEM SHALL retain without modification: all
  marketing/concept sections (`## The pain point`, `## Key Features` except the one
  updated bullet, `### cairn-mcp vs. other approaches`, `## Who this is for`,
  `## Why AWS`, `## How it works`, `## Status`), the `## Using the Migration Skill`
  section, the `## Prerequisites` section, the `## Minimum IAM Policy` section,
  the `## Installation` section, the `## Configuration` table, the
  `## Running the server` section, and the `## Development` section.
- WHEN complete THE SYSTEM SHALL produce a README of approximately 330 lines (±25). The higher-than-originally-estimated line count accounts for the `## Minimum IAM Policy` section (promoted to top-level, ~56 lines) and `## Using the Migration Skill` (~41 lines) both being retained in full.

## Boundaries

**Always:**
- The `## AWS Provisioning` section, the provisioning IAM policy block, the `.env`
  installation step, and the `.env` Configuration intro are already removed from the
  README (done as part of the T31 scope-correction). This spec covers only the
  remaining two sections to remove.
- Every removed section gets a one-sentence pointer to `installing-cairn`.
- The `## Prerequisites`, `## Minimum IAM Policy`, and `## Installation` sections are
  retained — they were updated as part of the T31 scope-correction and should not be
  modified again here.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not remove the configuration table — stable reference for operators.
- Do not remove the Development section — needed by contributors.
- Do not add new content beyond the Key Features bullet update and pointer sentences.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `README.md` | Modify | Remove ~345 lines of operational content; add pointer sentences |

## Testing Approach

Pure documentation update — no Python source files or unit tests. Verification by
inspection against the checklist below.

**Key Features update:**
- [ ] The bullet previously titled "Flexible ADR strategy" now reads
  "**Flexible ADR & document strategy**"
- [ ] The bullet description mentions ADRs, specs, plans, or any folder as examples
  of content that can be designated git-only
- [ ] The bullet description mentions that the decision is recorded in `AGENTS.md`
  and respected by agent sessions and the migration skill

**Removed sections (these two remain as of T31 task start):**
- [ ] `## Connecting to an MCP client` and both IDE sub-sections are absent
- [ ] `## Recommended AGENTS.md Snippet` and `### Declare your ADR strategy first`
  are absent
- [ ] The full AGENTS.md snippet body (`### cairn-mcp — Persistent Artifact Memory`
  through to the end of the snippet) is absent

**Already removed before this task (verify not re-introduced):**
- [ ] `## AWS Provisioning` section is absent
- [ ] Both IAM policy JSON blocks (`### Minimum IAM Policy` old location inside
  Provisioning, `#### Provisioning IAM policy`) are absent from their old location
- [ ] No `cp .env.example .env` or `# Edit .env` in `## Installation`
- [ ] `## Configuration` intro does not reference `.env`

**Pointer sentences present:**
- [ ] A pointer to `installing-cairn` appears where `## Connecting to an MCP client`
  was
- [ ] A pointer to `installing-cairn` appears where `## Recommended AGENTS.md Snippet`
  was

**Retained sections intact:**
- [ ] `## The pain point: the artifact gap` — unchanged
- [ ] `## Key Features` — all bullets unchanged except the one updated bullet
- [ ] `### cairn-mcp vs. other approaches` — unchanged
- [ ] `## Who this is for` — unchanged
- [ ] `## Why AWS, and why this stack?` — unchanged
- [ ] `## How it works` — unchanged
- [ ] `## Status` — unchanged
- [ ] `## Using the Migration Skill` — unchanged
- [ ] `## Prerequisites` — retained (updated in T31 scope-correction; do not modify)
- [ ] `## Minimum IAM Policy` — retained (promoted from AWS Provisioning in
  T31 scope-correction; do not modify)
- [ ] `## Installation` — retained (updated in T31 scope-correction; do not modify)
- [ ] `## Configuration` table — all env vars present with defaults and descriptions
- [ ] `## Running the server` — unchanged
- [ ] `## Development` — unchanged
- [ ] `## License` — unchanged

**Quality checks:**
- [ ] `wc -l` reports approximately 330 lines (310–360 acceptable)
- [ ] `## Minimum IAM Policy` is present and contains `YOUR-*` placeholder values —
  these are intentional template values for operators to substitute; do not remove them
- [ ] README reads coherently top-to-bottom with no orphaned headings or broken prose

## Open Questions

*(none — all constraints are defined)*
