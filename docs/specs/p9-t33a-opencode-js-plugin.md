---
type: feature-spec
feature: p9-t33a-opencode-js-plugin
phase: 9
task: 33a
status: draft
references:
  - docs/brainstorming/brainstorming-2026-06-08-skill-distribution.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-06-09"
revised:
  by: ""
  date: ""
---

# T33a — OpenCode JS Plugin

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add a `package.json` and `.opencode/plugins/cairn.js` to the repo so it becomes a
self-installing OpenCode plugin. Engineers make both cairn-mcp skills (`installing-cairn`,
`migrating-to-cairn`) discoverable in any OpenCode session by adding one line to their
global `~/.config/opencode/opencode.jsonc` — no file copying, no env vars.

## Problem Statement

Engineers who adopt cairn-mcp currently have to manually locate the `skills/` path and add
it to `config.skills.paths` in their OpenCode config. The OpenCode JS plugin system —
specifically the `config` hook and Bun's git package resolver — allows the repo itself to
self-register: one line in the global config installs and activates both skills, and
OpenCode's Bun plugin manager handles caching and update checks on restart.

## User Stories

### Story 1 — One-line install (P1)

As a cairn-mcp operator, I add one line to `~/.config/opencode/opencode.jsonc` and both
cairn-mcp skills are available to the agent in my next OpenCode session.

**Acceptance criteria:**
- Given the plugin line is present in `opencode.jsonc` and OpenCode has been restarted,
  when the engineer invokes the `skill` tool, then both `installing-cairn` and
  `migrating-to-cairn` appear and are loadable.

### Story 2 — Automatic updates on restart (P1)

As a cairn-mcp operator, after a new skill release I get the updated skill without any
manual action other than restarting OpenCode.

**Acceptance criteria:**
- Given the plugin line is already present in `opencode.jsonc`, when the engineer restarts
  OpenCode after a new release has been pushed, then the updated skill content is active.

### Story 3 — HTTPS alternative (P1)

As a cairn-mcp operator without SSH configured for GitHub, I can use `git+https://` instead
of `git+ssh://` and the plugin installs and works identically.

**Acceptance criteria:**
- Given the engineer substitutes `git+https://` for `git+ssh://` in the plugin line, when
  they start a new OpenCode session, then both skills are loadable by the agent.

## Requirements

- WHEN the plugin is loaded by OpenCode THE SYSTEM SHALL register the absolute path to
  `skills/` in `config.skills.paths` using the `config` hook.
- WHEN the plugin resolves the `skills/` directory path THE SYSTEM SHALL derive it relative
  to the plugin file itself via `import.meta.url` — never a hardcoded absolute path — so
  the plugin works regardless of Bun's cache location.
- WHEN the `config` hook encounters an error THE SYSTEM SHALL catch the exception, log it to
  `stderr`, and return without throwing — a hook error must never crash the OpenCode session.
- WHEN Bun installs the plugin via `git+https://` THE SYSTEM SHALL work identically to
  `git+ssh://`.

## Boundaries

**Always:**
- Plugin file is ESM format (`"type": "module"` in `package.json`).
- `package.json` is at the repo root with `"name": "cairn-mcp"` and
  `"main": ".opencode/plugins/cairn.js"`.
- The git+ssh URL uses a **forward slash** after the hostname:
  `git+ssh://git@github.com/amanoxsolutions/cairn-mcp.git` — the SCP colon form
  (`git+ssh://git@github.com:...`) is invalid in Node.js and causes the plugin to
  silently never install.
- Plugin registers `skills/` only — cairn-mcp has no agents directory.
- Installation is user-level: the plugin line goes in `~/.config/opencode/opencode.jsonc`.

**Never:**
- No hardcoded absolute paths inside the plugin file.
- No `experimental.chat.messages.transform` bootstrap injection.
- No Windows-native install path — engineers on Windows use WSL Ubuntu.

---

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `package.json` | Create | Repo root; `name: cairn-mcp`, `version` kept in sync with `pyproject.toml`, `type: module`, `main: .opencode/plugins/cairn.js`, `description` |
| `.opencode/plugins/cairn.js` | Create | ESM module; default export function; `config` hook pushes `skills/` into `config.skills.paths`; path resolved via `import.meta.url` (`../../skills` relative to plugin file); errors caught and logged to stderr |
| `README.md` | Modify | Add OpenCode plugin line (SSH primary, HTTPS alternative) to the Quick Install section added by T33e |
| `CONTRIBUTING.md` | Modify | Reference the plugin line and `install.sh` for OpenCode setup |

## Testing Approach

Testing is manual smoke tests (no TDD for non-server files).

1. **Plugin loads:** Add a local `file://` or `git+ssh://` plugin line to a test
   `opencode.jsonc`; start OpenCode; invoke the `skill` tool and verify both
   `installing-cairn` and `migrating-to-cairn` are loadable.
2. **Path resolution:** Confirm the plugin works correctly when Bun resolves it to its cache
   directory (different from the repo clone path).
3. **HTTPS path:** Substitute `git+https://` in the plugin line; restart OpenCode; confirm
   both skills are loadable.
4. **No crash on hook error:** Introduce a deliberate error in the config hook (wrong path
   type); verify OpenCode starts without crashing and logs to stderr.
5. **Idempotency:** Restart OpenCode twice in a row; verify skills are not duplicated.

## Open Questions

None.
