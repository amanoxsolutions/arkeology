---
type: feature-spec
feature: p9-t34-sync-cairn-plugin
phase: 9
task: 34
status: ready
references:
  - docs/planning-artifacts/prd.md
  - docs/specs/p9-t33a-opencode-js-plugin.md
  - docs/specs/p9-t33b-claude-code-plugin.md
authored:
  by: "architect"
  date: "2026-06-10"
revised:
  by: ""
  date: ""
---

# T34 — sync-cairn-plugin

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add a single `sync-cairn-plugin` skill that engineers invoke on any supported tool
(OpenCode, Claude Code, Copilot) to pull the latest cairn-mcp skill content. The skill
detects the running tool and applies the correct update action for each. It replaces the
existing `plugin-sync` Claude-Code-only skill, which is removed as part of this task.

## Problem Statement

Engineers currently need tool-specific knowledge to keep their cairn-mcp skills current:
OpenCode users must clear Bun's plugin cache manually, Claude Code users must know about
`/cairn:plugin-sync`, and Copilot users must re-run `install.sh`. There is no single
command that works everywhere, and the OpenCode path has no skill-based entry point at
all. A single tool-aware `sync-cairn-plugin` skill closes all three gaps and reduces the
`cairn:` Claude Code namespace from two overlapping update commands to one.

## User Stories

### Story 1 — OpenCode update (P1)

As a cairn-mcp operator using OpenCode, I invoke `sync-cairn-plugin` and receive the
exact command to clear the Bun plugin cache, then restart OpenCode to pull the latest
skills.

**Acceptance criteria:**
- Given I am in an OpenCode session and invoke the skill, when the skill completes, then
  I have run `rm -rf ~/.cache/opencode/packages/cairn-mcp@git+*` and restarted OpenCode
  and the latest skill content is active.

### Story 2 — Claude Code update (P1)

As a cairn-mcp operator using Claude Code, I invoke `/cairn:sync-cairn-plugin` and the
skill performs `git pull` on the plugin clone and then `/reload-plugins`.

**Acceptance criteria:**
- Given I am in a Claude Code session and invoke the skill, when the skill completes,
  then `git -C ~/.claude/plugins/cairn-mcp pull` has run, `/reload-plugins` has been
  called, and the updated skills are active in the same session.

### Story 3 — Copilot update (P1)

As a cairn-mcp operator using Copilot, I invoke `sync-cairn-plugin` and receive clear
instructions to re-run `install.sh`, which calls `gh skill install --force` for all
skills.

**Acceptance criteria:**
- Given I am in a Copilot session and invoke the skill, when the skill completes, then I
  have re-run `./install.sh` from the cairn-mcp repo and reloaded VS Code to pick up the
  updated skills.

### Story 4 — Unknown tool fallback (P2)

As a cairn-mcp operator using an unrecognised tool, I invoke `sync-cairn-plugin` and
receive an explanation of all three update paths so I can apply the correct one manually.

**Acceptance criteria:**
- Given the agent cannot determine the running tool, when the skill completes, then the
  engineer has been presented with all three update paths with enough detail to act
  independently.

## Requirements

- WHEN the skill is invoked in an OpenCode session THE SYSTEM SHALL instruct the agent
  to run `rm -rf ~/.cache/opencode/packages/cairn-mcp@git+*` and then restart OpenCode.
- WHEN the skill is invoked in a Claude Code session THE SYSTEM SHALL execute
  `git -C ~/.claude/plugins/cairn-mcp pull` and then run `/reload-plugins`.
- WHEN the skill is invoked in a Copilot session THE SYSTEM SHALL instruct the engineer
  to re-run `./install.sh` from the cairn-mcp repo directory and then reload VS Code.
- WHEN the tool cannot be determined THE SYSTEM SHALL present all three update paths and
  ask the engineer to identify their tool.
- WHEN the `plugin-sync` skill directory is removed THE SYSTEM SHALL have a symlink for
  `sync-cairn-plugin` in its place under `plugins/cairn-mcp/skills/` so the skill appears
  as `/cairn:sync-cairn-plugin` in Claude Code.

## Boundaries

**Always:**
- `sync-cairn-plugin` lives in `skills/sync-cairn-plugin/SKILL.md` (shared skills
  directory) — it is not Claude-Code-specific.
- The Claude Code plugin uses a symlink
  `plugins/cairn-mcp/skills/sync-cairn-plugin → ../../../skills/sync-cairn-plugin`,
  identical to the pattern used for `setting-up-cairn` and `migrating-to-cairn`.
- `plugin-sync` (`plugins/cairn-mcp/skills/plugin-sync/`) is deleted entirely as part of
  this task — it is not kept as an alias or redirect.
- No Python source changes. No `pyproject.toml` changes. No server code changes.

**Never:**
- Do not update `install.sh` — it already loops over `skills/*/` and will pick up
  `sync-cairn-plugin` automatically on the next run.
- Do not add any detection logic to `cairn.js` — tool detection is the agent's
  responsibility at runtime; the skill file provides the branching instructions.

---

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/sync-cairn-plugin/SKILL.md` | Create | ~35 lines; tool-detection preamble followed by three labelled step blocks (OpenCode / Claude Code / Copilot) and a fallback block |
| `plugins/cairn-mcp/skills/sync-cairn-plugin` | Create (symlink) | Points to `../../../skills/sync-cairn-plugin`; same pattern as `setting-up-cairn` and `migrating-to-cairn` symlinks |
| `plugins/cairn-mcp/skills/plugin-sync/` | Delete | Entire directory including `SKILL.md`; replaced by `sync-cairn-plugin` |

## Testing Approach

No server code changes — testing is manual smoke tests only (same convention as T33a–T33e).

1. **OpenCode path:** Invoke the skill in an OpenCode session; confirm the agent prints
   the `rm -rf` command and restart instruction without error.
2. **Claude Code path:** Invoke `/cairn:sync-cairn-plugin` in a Claude Code session;
   confirm `git pull` runs on `~/.claude/plugins/cairn-mcp` and `/reload-plugins` is
   called; confirm updated skill content is active.
3. **Copilot path:** Invoke the skill in a Copilot session; confirm the agent instructs
   re-running `install.sh` and reloading VS Code.
4. **plugin-sync removed:** Confirm `/cairn:plugin-sync` no longer appears as a slash
   command in Claude Code after reloading plugins.
5. **Symlink resolution:** Confirm the Claude Code symlink resolves correctly and the
   SKILL.md content is identical to `skills/sync-cairn-plugin/SKILL.md`.

## Open Questions

None.
