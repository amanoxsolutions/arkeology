---
type: spec
title: T34 — sync-arkeology-plugin
description: Spec for a single tool-aware sync-arkeology-plugin skill that updates Arkeology skill content across OpenCode, Claude Code, and Copilot with the correct action for each.
tags: []
timestamp: 2026-06-10T00:00:00Z
okf_version: "0.1"
feature: p9-t34-sync-arkeology-plugin
phase: 9
task: 34
status: ready
references:
  - docs/planning-artifacts/requirements.md
  - docs/specs/p9-t33a-opencode-js-plugin.md
  - docs/specs/p9-t33b-claude-code-plugin.md
authored:
  by: "architect"
  date: "2026-06-10"
revised:
  by: ""
  date: ""
---

# T34 — sync-arkeology-plugin

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add a single `sync-arkeology-plugin` skill that engineers invoke on any supported tool
(OpenCode, Claude Code, Copilot) to pull the latest Arkeology skill content. The skill
detects the running tool and applies the correct update action for each. It replaces the
existing `plugin-sync` Claude-Code-only skill, which is removed as part of this task.

## Problem Statement

Engineers currently need tool-specific knowledge to keep their Arkeology skills current:
OpenCode users must clear Bun's plugin cache manually, Claude Code users must know about
`/arkeology:plugin-sync`, and Copilot users must re-run `install.sh`. There is no single
command that works everywhere, and the OpenCode path has no skill-based entry point at
all. A single tool-aware `sync-arkeology-plugin` skill closes all three gaps and reduces the
`arkeology:` Claude Code namespace from two overlapping update commands to one.

## User Stories

### Story 1 — OpenCode update (P1)

As an Arkeology operator using OpenCode, I invoke `sync-arkeology-plugin` and receive the
exact command to clear the Bun plugin cache, then restart OpenCode to pull the latest
skills.

**Acceptance criteria:**
- Given I am in an OpenCode session and invoke the skill, when the skill completes, then
  I have run `rm -rf ~/.cache/opencode/packages/arkeology@git+*` and restarted OpenCode
  and the latest skill content is active.

### Story 2 — Claude Code update (P1)

As an Arkeology operator using Claude Code, I invoke `/arkeology:sync-arkeology-plugin` and the
skill performs `git pull` on the plugin clone and then `/reload-plugins`.

**Acceptance criteria:**
- Given I am in a Claude Code session and invoke the skill, when the skill completes,
  then `git -C ~/.claude/plugins/arkeology pull` has run, `/reload-plugins` has been
  called, and the updated skills are active in the same session.

### Story 3 — Copilot update (P1)

As an Arkeology operator using Copilot, I invoke `sync-arkeology-plugin` and receive clear
instructions to re-run `install.sh`, which calls `gh skill install --force` for all
skills.

**Acceptance criteria:**
- Given I am in a Copilot session and invoke the skill, when the skill completes, then I
  have re-run `./install.sh` from the Arkeology repo and reloaded VS Code to pick up the
  updated skills.

### Story 4 — Unknown tool fallback (P2)

As an Arkeology operator using an unrecognised tool, I invoke `sync-arkeology-plugin` and
receive an explanation of all three update paths so I can apply the correct one manually.

**Acceptance criteria:**
- Given the agent cannot determine the running tool, when the skill completes, then the
  engineer has been presented with all three update paths with enough detail to act
  independently.

## Requirements

- WHEN the skill is invoked in an OpenCode session THE SYSTEM SHALL instruct the agent
  to run `rm -rf ~/.cache/opencode/packages/arkeology@git+*` and then restart OpenCode.
- WHEN the skill is invoked in a Claude Code session THE SYSTEM SHALL execute
  `git -C ~/.claude/plugins/arkeology pull` and then run `/reload-plugins`.
- WHEN the skill is invoked in a Copilot session THE SYSTEM SHALL instruct the engineer
  to re-run `./install.sh` from the Arkeology repo directory and then reload VS Code.
- WHEN the tool cannot be determined THE SYSTEM SHALL present all three update paths and
  ask the engineer to identify their tool.
- WHEN the `plugin-sync` skill directory is removed THE SYSTEM SHALL have a symlink for
  `sync-arkeology-plugin` in its place under `plugins/arkeology/skills/` so the skill appears
  as `/arkeology:sync-arkeology-plugin` in Claude Code.

## Boundaries

**Always:**
- `sync-arkeology-plugin` lives in `skills/sync-arkeology-plugin/SKILL.md` (shared skills
  directory) — it is not Claude-Code-specific.
- The Claude Code plugin uses a symlink
  `plugins/arkeology/skills/sync-arkeology-plugin → ../../../skills/sync-arkeology-plugin`,
  identical to the pattern used for `setting-up-arkeology` and `migrating-to-arkeology`.
- `plugin-sync` (`plugins/arkeology/skills/plugin-sync/`) is deleted entirely as part of
  this task — it is not kept as an alias or redirect.
- No Python source changes. No `pyproject.toml` changes. No server code changes.

**Never:**
- Do not update `install.sh` — it already loops over `skills/*/` and will pick up
  `sync-arkeology-plugin` automatically on the next run.
- Do not add any detection logic to `arkeology.js` — tool detection is the agent's
  responsibility at runtime; the skill file provides the branching instructions.

---

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/sync-arkeology-plugin/SKILL.md` | Create | ~35 lines; tool-detection preamble followed by three labelled step blocks (OpenCode / Claude Code / Copilot) and a fallback block |
| `plugins/arkeology/skills/sync-arkeology-plugin` | Create (symlink) | Points to `../../../skills/sync-arkeology-plugin`; same pattern as `setting-up-arkeology` and `migrating-to-arkeology` symlinks |
| `plugins/arkeology/skills/plugin-sync/` | Delete | Entire directory including `SKILL.md`; replaced by `sync-arkeology-plugin` |

## Testing Approach

No server code changes — testing is manual smoke tests only (same convention as T33a–T33e).

1. **OpenCode path:** Invoke the skill in an OpenCode session; confirm the agent prints
   the `rm -rf` command and restart instruction without error.
2. **Claude Code path:** Invoke `/arkeology:sync-arkeology-plugin` in a Claude Code session;
   confirm `git pull` runs on `~/.claude/plugins/arkeology` and `/reload-plugins` is
   called; confirm updated skill content is active.
3. **Copilot path:** Invoke the skill in a Copilot session; confirm the agent instructs
   re-running `install.sh` and reloading VS Code.
4. **plugin-sync removed:** Confirm `/arkeology:plugin-sync` no longer appears as a slash
   command in Claude Code after reloading plugins.
5. **Symlink resolution:** Confirm the Claude Code symlink resolves correctly and the
   SKILL.md content is identical to `skills/sync-arkeology-plugin/SKILL.md`.

## Open Questions

None.
