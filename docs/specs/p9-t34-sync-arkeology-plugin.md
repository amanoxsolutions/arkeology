---
type: Spec
id: p9-t34-sync-arkeology-plugin
title: T34 — sync-arkeology-plugin
description: Spec for a single tool-aware sync-arkeology-plugin skill that updates Arkeology skill content across OpenCode, Claude Code, and Copilot with the correct action for each.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/specs/p9-t33a-opencode-js-plugin.md
    title: T33a — OpenCode JS Plugin
    last_modified: 2026-06-10T00:00:00Z
  - resource: docs/specs/p9-t33b-claude-code-plugin.md
    title: T33b — Claude Code Plugin
    last_modified: 2026-06-10T00:00:00Z
generated:
  by: "axians-architect/unknown"
  at: 2026-06-10T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T16:58:18Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T34 — sync-arkeology-plugin

## TL;DR

Add a single `sync-arkeology-plugin` skill that engineers invoke on any supported tool
(OpenCode, Claude Code, Copilot) to pull the latest Arkeology skill content. The skill
detects the running tool and applies the correct update action for each. It replaces the
existing `plugin-sync` Claude-Code-only skill, which is removed as part of this task.

## 1. Problem Statement

Engineers currently need tool-specific knowledge to keep their Arkeology skills current:
OpenCode users must clear Bun's plugin cache manually, Claude Code users must know about
`/arkeology:plugin-sync`, and Copilot users must re-run `install.sh`. There is no single
command that works everywhere, and the OpenCode path has no skill-based entry point at
all. A single tool-aware `sync-arkeology-plugin` skill closes all three gaps and reduces the
`arkeology:` Claude Code namespace from two overlapping update commands to one.

Of the four stories this spec was written from, three are P1 — OpenCode update (R1), Claude Code
update (R2) and Copilot update (R3) — and one is P2: unknown tool fallback (R4).

## 2. Rules — Update action per tool

### R1 — OpenCode: clear the Bun plugin cache, then restart OpenCode

When the skill is invoked in an OpenCode session, it instructs the agent to run
`rm -rf ~/.cache/opencode/packages/arkeology@git+*` and then restart OpenCode. An Arkeology
operator using OpenCode invokes `sync-arkeology-plugin` and receives the exact command to clear the
Bun plugin cache, then restarts OpenCode to pull the latest skills.

**Example**

- Given I am in an OpenCode session and invoke the skill, when the skill completes, then I have
  run `rm -rf ~/.cache/opencode/packages/arkeology@git+*` and restarted OpenCode and the latest
  skill content is active.

### R2 — Claude Code: pull the plugin clone, then reload plugins

When the skill is invoked in a Claude Code session, it executes
`git -C ~/.claude/plugins/arkeology pull` and then runs `/reload-plugins`. An Arkeology operator
using Claude Code invokes `/arkeology:sync-arkeology-plugin` and the skill performs `git pull` on
the plugin clone and then `/reload-plugins`.

**Example**

- Given I am in a Claude Code session and invoke the skill, when the skill completes, then
  `git -C ~/.claude/plugins/arkeology pull` has run, `/reload-plugins` has been called, and the
  updated skills are active in the same session.

### R3 — Copilot: re-run `install.sh`, then reload VS Code

When the skill is invoked in a Copilot session, it instructs the engineer to re-run `./install.sh`
from the Arkeology repo directory and then reload VS Code. An Arkeology operator using Copilot
invokes `sync-arkeology-plugin` and receives clear instructions to re-run `install.sh`, which calls
`gh skill install --force` for all skills.

**Example**

- Given I am in a Copilot session and invoke the skill, when the skill completes, then I have
  re-run `./install.sh` from the Arkeology repo and reloaded VS Code to pick up the updated skills.

### R4 — Unknown tool: present all three update paths

When the tool cannot be determined, the skill presents all three update paths and asks the
engineer to identify their tool. An Arkeology operator using an unrecognised tool invokes
`sync-arkeology-plugin` and receives an explanation of all three update paths so they can apply
the correct one manually.

**Example**

- Given the agent cannot determine the running tool, when the skill completes, then the engineer
  has been presented with all three update paths with enough detail to act independently.

## 3. Rules — Packaging

### R5 — The skill appears as `/arkeology:sync-arkeology-plugin` in Claude Code through a symlink

When the `plugin-sync` skill directory is removed, a symlink for `sync-arkeology-plugin` is in its
place under `plugins/arkeology/skills/` so the skill appears as `/arkeology:sync-arkeology-plugin`
in Claude Code.

### R6 — `sync-arkeology-plugin` replaces `plugin-sync`

The `sync-arkeology-plugin` skill replaces the existing `plugin-sync` Claude-Code-only skill, which
is removed, reducing the `arkeology:` Claude Code namespace from two overlapping update commands to
one.

## 4. Boundaries

**Always:**
- `sync-arkeology-plugin` lives in `skills/sync-arkeology-plugin/SKILL.md` (shared skills
  directory) — it is not Claude-Code-specific.
- The Claude Code plugin uses a symlink
  `plugins/arkeology/skills/sync-arkeology-plugin → ../../../skills/sync-arkeology-plugin`,
  identical to the pattern used for `setting-up-arkeology` and `migrating-to-arkeology`.
- `plugin-sync` (`plugins/arkeology/skills/plugin-sync/`) is deleted entirely as part of
  this task — it is not kept as an alias or redirect.
- No Python source changes. No `pyproject.toml` changes. No server code changes.

**Ask First:**
- None.

**Never:**
- Do not update `install.sh` — it already loops over `skills/*/` and will pick up
  `sync-arkeology-plugin` automatically on the next run.
- Do not add any detection logic to `arkeology.js` — tool detection is the agent's
  responsibility at runtime; the skill file provides the branching instructions.

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/sync-arkeology-plugin/SKILL.md` | Create | ~35 lines; tool-detection preamble followed by three labelled step blocks (OpenCode / Claude Code / Copilot) and a fallback block |
| `plugins/arkeology/skills/sync-arkeology-plugin` | Create (symlink) | Points to `../../../skills/sync-arkeology-plugin`; same pattern as `setting-up-arkeology` and `migrating-to-arkeology` symlinks |
| `plugins/arkeology/skills/plugin-sync/` | Delete | Entire directory including `SKILL.md`; replaced by `sync-arkeology-plugin` |

### Contracts

None.

### Testing Approach

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
