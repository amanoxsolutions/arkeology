---
type: feature-spec
feature: p9-t33b-claude-code-plugin
phase: 9
task: 33b
status: complete
references:
  - docs/brainstorming/brainstorming-2026-06-08-skill-distribution.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-06-09"
revised:
  by: "tech-writer"
  date: "2026-06-10"
---

# T33b — Claude Code Plugin

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add a `.claude-plugin/marketplace.json` marketplace manifest and a `plugins/cairn-mcp/`
plugin directory to the repo so Claude Code engineers install both cairn-mcp skills via
two `claude plugin` commands. Skills become available as `cairn:<name>` slash commands
(`/cairn:installing-cairn`, `/cairn:migrating-to-cairn`), and the `cairn:plugin-sync`
skill handles future updates to the skill plugin clone without a full reinstall.

Both SSH and HTTPS forms of `claude plugin marketplace add` are documented — the SSH form
is primary; the HTTPS form is the fallback for environments where outbound SSH (port 22)
is blocked by a corporate firewall.

No global CLAUDE.md `@`-import is written — cairn-mcp's `AGENTS.md` contains server-setup
documentation specific to the codebase, not conventions applicable in every session. The
per-project AGENTS.md snippet written by `installing-cairn` already provides the right
context within each project.

## Problem Statement

Claude Code engineers currently have no namespaced, self-updating way to install cairn-mcp
skills. Claude Code's private marketplace system allows a git repo to act as a
self-installing plugin: two `claude plugin` commands give the engineer both skills under
the `cairn:` namespace and provide a `plugin-sync` skill so future updates are a
one-command operation. The `cairn:` prefix prevents collision with any other installed
plugin.

## User Stories

### Story 1 — Two-command install via SSH (P1)

As a cairn-mcp Claude Code operator, I run two commands and both cairn-mcp skills are
available in every subsequent Claude Code session as namespaced slash commands.

**Acceptance criteria:**
- Given the engineer has `claude` on PATH and SSH access to GitHub, when they run
  `claude plugin marketplace add git@github.com:amanoxsolutions/cairn-mcp.git` then
  `claude plugin install cairn@cairn-mcp`, then `/cairn:installing-cairn` and
  `/cairn:migrating-to-cairn` appear as slash commands.

### Story 4 — Two-command install via HTTPS (P1)

As a cairn-mcp Claude Code operator whose outbound SSH is blocked by a corporate firewall,
I can use the HTTPS form of `claude plugin marketplace add` and the install works
identically.

**Acceptance criteria:**
- Given the engineer has `claude` on PATH but cannot use SSH (port 22 blocked), when they
  run `claude plugin marketplace add https://github.com/amanoxsolutions/cairn-mcp.git` then
  `claude plugin install cairn@cairn-mcp`, then `/cairn:installing-cairn` and
  `/cairn:migrating-to-cairn` appear as slash commands, identical to the SSH path.

### Story 2 — One-command skill update (P1)

As a cairn-mcp Claude Code operator, I run `/cairn:plugin-sync` to pull updated skills
into the Claude Code plugin clone without reinstalling.

**Acceptance criteria:**
- Given the plugin is installed, when the engineer runs `/cairn:plugin-sync`, then the skill
  performs `git pull` on `~/.claude/plugins/cairn-mcp/` and calls `/reload-plugins`.
- The skill's notes section states that the server clone requires a separate `git pull` +
  `uv sync` + restart — `plugin-sync` only updates the skill plugin clone.

### Story 3 — Permission-free sync (P1)

As a cairn-mcp Claude Code operator, running `/cairn:plugin-sync` does not trigger
permission prompts.

**Acceptance criteria:**
- Given `install.sh` has run and written the pre-approval rule to `~/.claude/settings.json`,
  when the engineer invokes `/cairn:plugin-sync`, then `git pull` executes without a
  per-call approval prompt.

## Requirements

- WHEN the plugin is installed via `claude plugin install` THE SYSTEM SHALL make both skills
  in `plugins/cairn-mcp/skills/` available as `cairn:<skill-name>` slash commands.
- WHEN `plugins/cairn-mcp/skills/<name>` is resolved THE SYSTEM SHALL be a symlink to
  `../../../skills/<name>` so edits to the root `skills/` are immediately reflected.
- WHEN the engineer runs `/cairn:plugin-sync` THE SYSTEM SHALL perform `git pull` on
  `~/.claude/plugins/cairn-mcp/` and then execute `/reload-plugins`.
- WHEN `install.sh` runs the Claude Code section THE SYSTEM SHALL merge the pre-approval
  rule `"Bash(git -C * pull)"` into `~/.claude/settings.json`, creating the file if absent
  and merging without overwriting unrelated entries if it exists.
- WHEN the pre-approval rule is already present in `~/.claude/settings.json` THE SYSTEM
  SHALL not duplicate it (idempotency).
- WHEN the README and install.sh session-refresh section document the Claude Code install
  THE SYSTEM SHALL show both:
  - SSH primary: `claude plugin marketplace add git@github.com:amanoxsolutions/cairn-mcp.git`
  - HTTPS fallback: `claude plugin marketplace add https://github.com/amanoxsolutions/cairn-mcp.git`
  The HTTPS fallback is clearly labelled for environments where outbound SSH is blocked.

## Boundaries

**Always:**
- Skills inside `plugins/cairn-mcp/skills/` are symlinks to `../../../skills/<name>` — no
  file copies.
- `plugins/cairn-mcp/` contains only a `.claude-plugin/` directory and a `skills/`
  directory — no `agents/` directory (cairn-mcp has no agents).
- The marketplace manifest `source` field uses the relative path `"./plugins/cairn-mcp"` —
  a bare `"path"` key is not a valid source type and causes install to fail.
- `marketplace.json` must include `$schema`, `name`, `owner: {name: ...}` and the plugin
  entry must include `name`, `description`, `author`, `source`, and `homepage` — all fields
  are required for Claude Code compatibility; missing `owner` or `$schema` causes silent
  failures. The `$schema` value must be exactly
  `"https://anthropic.com/claude-code/marketplace.schema.json"` — Claude Code uses this URL
  to select its source-type parser; an invented or alternative URL (e.g. `claude.ai/schemas/…`)
  causes "This plugin uses a source type your Claude Code version does not support" at install
  time. The `author` field inside `plugins[0]` must be an object (`{"name": "…"}`), not a
  plain string. The top-level `description` field should also be present.
- `marketplace.json` has **two distinct `name` fields** that must not be confused:
  the top-level `"name": "cairn-mcp"` is the marketplace identifier (the `@cairn-mcp`
  part of `claude plugin install cairn@cairn-mcp`); the plugin entry's
  `"plugins[0].name": "cairn"` is the plugin lookup key (the `cairn@` part of the same
  command). Claude Code searches the `plugins` array for an entry whose `name` matches
  the install-command identifier — using the marketplace name for the plugin entry causes
  "Plugin 'cairn' not found in marketplace 'cairn-mcp'" at install time.
- `plugin.json` must **omit the `version` field** — a pinned static version prevents
  `claude plugin update` from picking up new pushes; Claude Code uses the commit SHA
  automatically when `version` is absent.
- `cairn:plugin-sync` lives exclusively in `plugins/cairn-mcp/skills/plugin-sync/SKILL.md`;
  it must **not** appear in the root `skills/` directory (it is Claude Code-specific and
  irrelevant to other tools).
- Pre-approval is scoped narrowly to `"Bash(git -C * pull)"` — no blanket bash access.
- No global CLAUDE.md `@`-import is written or required (D1 — see brainstorming doc).

**Never:**
- No file copies inside `plugins/cairn-mcp/skills/` — symlinks only.
- No agents directory inside `plugins/cairn-mcp/` — cairn-mcp has no agents.
- No `version` field in `plugin.json`.
- No `@`-import prepended to `~/.claude/CLAUDE.md`.

---

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `.claude-plugin/marketplace.json` | Create | Top-level `name: cairn-mcp` (marketplace ID); `owner: {name: Amanox}`; `$schema`; `plugins[0].name: cairn` (plugin lookup key — **must match the `cairn@` identifier in the install command, not the marketplace name**); `plugins[0].source: "./plugins/cairn-mcp"`; see Boundaries for required fields |
| `plugins/cairn-mcp/.claude-plugin/plugin.json` | Create | `name: cairn`, `description` only — **no `version` field** |
| `plugins/cairn-mcp/skills/installing-cairn` | Create | Symlink → `../../../skills/installing-cairn` |
| `plugins/cairn-mcp/skills/migrating-to-cairn` | Create | Symlink → `../../../skills/migrating-to-cairn` |
| `plugins/cairn-mcp/skills/plugin-sync/SKILL.md` | Create | `cairn:plugin-sync` skill; runs `git -C ~/.claude/plugins/cairn-mcp pull` + `/reload-plugins`; notes section warns that the server clone requires a separate update |
| `README.md` | Modify | Add the two `claude plugin` commands to the Quick Install section added by T33e |
| `CONTRIBUTING.md` | Modify | Update Claude Code setup section to reference the two plugin commands |

## Testing Approach

Testing is manual smoke tests (no TDD for non-server files).

1. **Plugin install — SSH:** Run `claude plugin marketplace add <repo-ssh-url>` then
   `claude plugin install cairn@cairn-mcp`; verify `/cairn:installing-cairn` and
   `/cairn:migrating-to-cairn` appear as slash commands.
2. **Plugin install — HTTPS:** Substitute the HTTPS URL in `claude plugin marketplace add`;
   run `claude plugin install cairn@cairn-mcp`; verify the same two slash commands appear —
   confirms the HTTPS path works for SSH-blocked environments.
2. **Symlink integrity:** Edit `skills/installing-cairn/SKILL.md` (add a comment); run
   `/reload-plugins`; confirm the change is reflected — proving symlinks are live, not
   copies.
3. **No agents directory:** Confirm `plugins/cairn-mcp/agents/` does not exist.
4. **plugin-sync not in root skills:** Confirm `skills/plugin-sync/` does not exist at
   the repo root.
5. **`plugin.json` has no version:** Confirm the file contains only `name` and
   `description`; run `claude plugin update cairn` after pushing a change; confirm the
   update is detected.
6. **Permission-free sync:** After `install.sh` has run, invoke `/cairn:plugin-sync`;
   confirm `git pull` executes without a per-call permission prompt.
7. **Idempotency:** Run `install.sh` twice; verify no duplicate entries in
   `~/.claude/settings.json`.

## Open Questions

None.
