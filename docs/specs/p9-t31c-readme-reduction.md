---
type: Spec
id: p9-t31c-readme-reduction
title: T31c — README Reduction
description: Spec to slim the README by removing operational sections moved into the setting-up-arkeology skill and replacing them with pointers.
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

# T31c — README Reduction

## TL;DR

Slim `README.md` further by removing the remaining operational sections that have moved
into the `setting-up-arkeology` skill (`## Connecting to an MCP client` and
`## Recommended AGENTS.md Snippet`), replacing each removed section with a one-sentence pointer
to the skill, and update the `## Key Features` section to reflect the generalised exclusion
model. The `## AWS Provisioning` section, the provisioning IAM policy, and the `.env`
installation step have already been removed from the README as part of the scope-correction for
T31. The target line count after all T31 changes is approximately 330 lines.

## 1. Problem Statement

The README still contains two large sections (`## Connecting to an MCP client` and
`## Recommended AGENTS.md Snippet`) that belong in the `setting-up-arkeology` skill rather
than in the README. Keeping them risks drift as the skill evolves and adds content that
is operationally redundant once the skill exists. Removing them and replacing with
pointers completes the README's transformation into a focused discovery document.

The user stories behind R3 and R5 are P1; the one behind R2 is P2.

## 2. Rules — Removed operational sections

### R1 — Two operational sections are removed, each replaced by a one-sentence pointer

When the README is updated, `## Connecting to an MCP client` (including both IDE sub-sections)
and `## Recommended AGENTS.md Snippet` (including `### Declare your ADR strategy first` and the
full snippet body from `### arkeology — Persistent Artifact Memory` to end of snippet) are
removed, each replaced with a one-sentence pointer: "See the `setting-up-arkeology` skill for
interactive step-by-step guidance."

Source: none

### R2 — The README holds no operational steps that could drift from the skill

The README stays current with the skill: it contains no duplicated operational steps that could
drift — only concept content and config reference that are stable.

**Example**

- Given the `setting-up-arkeology` skill evolves, when the README is reviewed, then the README
  contains no duplicated operational steps that could drift — only concept content and config
  reference that are stable.

Source: none

## 3. Rules — Key Features

### R3 — The ADR-strategy bullet becomes "Flexible ADR & document strategy"

When the README is updated, the `## Key Features` bullet currently titled "Flexible ADR
strategy" is updated to read "Flexible ADR & document strategy", with a description that
conveys: teams can designate ADRs, specs, plans, or any folder as git-only during installation;
the decision is recorded once in `AGENTS.md` and respected by every future agent session and the
migration skill automatically. The bullet that previously described only the ADR strategy now
describes the full permanent-exclusion capability.

**Example**

- Given the updated README `## Key Features` section, when the "Flexible ADR & document
  strategy" bullet is read, then it conveys that teams can keep ADRs, specs, plans, or any
  folder in git and that the decision is recorded once in `AGENTS.md`.
- Given the updated bullet, when it is compared to the old "Flexible ADR strategy" text, then
  it no longer implies ADRs are the only type of document that can stay in git.

Source: none

## 4. Rules — Retained content and size

### R4 — The named sections are retained without modification

When the README is updated, the following are retained without modification: all
marketing/concept sections (`## The pain point`, `## Key Features` except the one updated
bullet, `### arkeology vs. other approaches`, `## Who this is for`, `## Why AWS`,
`## How it works`, `## Status`), the `## Using the Migration Skill` section, the
`## Prerequisites` section, the `## Minimum IAM Policy` section, the `## Installation` section,
the `## Configuration` table, the `## Running the server` section, and the `## Development`
section. The `YOUR-*` placeholder values in `## Minimum IAM Policy` are intentional template
values for operators to substitute and stay.

Source: none

### R5 — A first-time reader knows what Arkeology is and what to do next

A new operator discovers Arkeology from the README and understands what it is.

**Example**

- Given a developer reading the README for the first time, when they reach the end, then they
  understand what Arkeology does, whether it suits their project, and exactly what to do next to
  get started (run the `setting-up-arkeology` skill).
- Given a developer scanning for the configuration reference, when they find it in the README,
  then every environment variable is documented with its default and a brief description.

Source: none

### R6 — The finished README is about 330 lines

When complete, the README is approximately 330 lines (±25).

**Why:** the line count is higher than originally estimated because the `## Minimum IAM Policy`
section (promoted to top-level, ~56 lines) and `## Using the Migration Skill` (~41 lines) are
both retained in full — together ~97 lines not included in the original projection.

Source: none

## 5. Boundaries

**Always:**
- The `## AWS Provisioning` section, the provisioning IAM policy block, the `.env`
  installation step, and the `.env` Configuration intro are already removed from the
  README (done as part of the T31 scope-correction). This spec covers only the
  remaining two sections to remove.
- Every removed section gets a one-sentence pointer to `setting-up-arkeology`.
- The `## Prerequisites`, `## Minimum IAM Policy`, and `## Installation` sections are
  retained — they were updated as part of the T31 scope-correction and should not be
  modified again here.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not remove the configuration table — stable reference for operators.
- Do not remove the Development section — needed by contributors.
- Do not add new content beyond the Key Features bullet update and pointer sentences.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `README.md` | Modify | Remove ~345 lines of operational content; add pointer sentences |

### Contracts

None.

### Testing Approach

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
- [ ] The full AGENTS.md snippet body (`### arkeology — Persistent Artifact Memory`
  through to the end of the snippet) is absent

**Already removed before this task (verify not re-introduced):**
- [ ] `## AWS Provisioning` section is absent
- [ ] Both IAM policy JSON blocks (`### Minimum IAM Policy` old location inside
  Provisioning, `#### Provisioning IAM policy`) are absent from their old location
- [ ] No `cp .env.example .env` or `# Edit .env` in `## Installation`
- [ ] `## Configuration` intro does not reference `.env`

**Pointer sentences present:**
- [ ] A pointer to `setting-up-arkeology` appears where `## Connecting to an MCP client`
  was
- [ ] A pointer to `setting-up-arkeology` appears where `## Recommended AGENTS.md Snippet`
  was

**Retained sections intact:**
- [ ] `## The pain point: the artifact gap` — unchanged
- [ ] `## Key Features` — all bullets unchanged except the one updated bullet
- [ ] `### arkeology vs. other approaches` — unchanged
- [ ] `## Who this is for` — unchanged
- [ ] `## Why AWS, and why this stack?` — unchanged
- [ ] `## How it works` — unchanged
- [ ] `## Status` — unchanged
- [ ] `## Using the Migration Skill` — unchanged
- [ ] `## Prerequisites` — retained (updated in T31 scope-correction; do not modify)
- [ ] `## Minimum IAM Policy` — retained (promoted from AWS Provisioning in
  T31 scope-correction; do not modify)
- [ ] `## Installation` — retained (updated in T31 scope-correction; do not modify)- [ ] `## Configuration` table — all env vars present with defaults and descriptions
- [ ] `## Running the server` — unchanged
- [ ] `## Development` — unchanged
- [ ] `## License` — unchanged

**Quality checks:**
- [ ] `wc -l` reports approximately 330 lines (310–360 acceptable)
- [ ] `## Minimum IAM Policy` is present and contains `YOUR-*` placeholder values —
  these are intentional template values for operators to substitute; do not remove them
- [ ] README reads coherently top-to-bottom with no orphaned headings or broken prose
