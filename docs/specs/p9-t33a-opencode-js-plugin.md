---
type: Spec
id: p9-t33a-opencode-js-plugin
title: T33a — OpenCode JS Plugin
description: Spec to add a package.json and OpenCode JS plugin file so Arkeology becomes a self-installing OpenCode plugin with one-line install.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/brainstorming/brainstorming-2026-06-08-skill-distribution.md
    title: Phase 9 — Skill Distribution via Native Plugin Mechanisms
    last_modified: 2026-06-10T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
generated:
  by: "axians-architect/unknown"
  at: 2026-06-09T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T16:49:20Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T33a — OpenCode JS Plugin

## TL;DR

Add a `package.json` and `.opencode/plugins/arkeology.js` to the repo so it becomes a
self-installing OpenCode plugin. Engineers make both Arkeology skills (`setting-up-arkeology`,
`migrating-to-arkeology`) discoverable in any OpenCode session by adding one line to their
global `~/.config/opencode/opencode.jsonc` — no file copying, no env vars.

## 1. Problem Statement

Engineers who adopt Arkeology currently have to manually locate the `skills/` path and add
it to `config.skills.paths` in their OpenCode config. The OpenCode JS plugin system —
specifically the `config` hook and Bun's git package resolver — allows the repo itself to
self-register: one line in the global config installs and activates both skills, and
OpenCode's Bun plugin manager handles caching and update checks on restart.

All three stories this spec was written from are P1: one-line install (R1), automatic updates on
restart (R3), and the HTTPS alternative (R2).

## 2. Rules — Installation

### R1 — One line in the global OpenCode config makes both skills available

When an Arkeology operator adds one line to `~/.config/opencode/opencode.jsonc`, both Arkeology
skills are available to the agent in their next OpenCode session.

**Example**

- Given the plugin line is present in `opencode.jsonc` and OpenCode has been restarted, when the
  engineer invokes the `skill` tool, then both `setting-up-arkeology` and `migrating-to-arkeology`
  appear and are loadable.

### R2 — Installing via `git+https://` works identically to `git+ssh://`

When Bun installs the plugin via `git+https://`, the plugin works identically to `git+ssh://`: an
Arkeology operator without SSH configured for GitHub can use `git+https://` instead of
`git+ssh://` and the plugin installs and works identically.

**Example**

- Given the engineer substitutes `git+https://` for `git+ssh://` in the plugin line, when they
  start a new OpenCode session, then both skills are loadable by the agent.

### R3 — A restart after a release activates the updated skills

After a new skill release, an Arkeology operator gets the updated skill without any manual action
other than restarting OpenCode.

**Example**

- Given the plugin line is already present in `opencode.jsonc`, when the engineer restarts
  OpenCode after a new release has been pushed, then the updated skill content is active.

## 3. Rules — Plugin behaviour

### R4 — The plugin registers `skills/` through the `config` hook

When the plugin is loaded by OpenCode, it registers the absolute path to `skills/` in
`config.skills.paths` using the `config` hook.

### R5 — The `skills/` path is derived from the plugin file's own location

When the plugin resolves the `skills/` directory path, it derives it relative to the plugin file
itself via `import.meta.url` — never a hardcoded absolute path — so the plugin works regardless of
Bun's cache location.

### R6 — A `config` hook error never crashes the OpenCode session

When the `config` hook encounters an error, the plugin catches the exception, logs it to `stderr`,
and returns without throwing — a hook error must never crash the OpenCode session.

## 4. Boundaries

**Always:**
- Plugin file is ESM format (`"type": "module"` in `package.json`).
- `package.json` is at the repo root with `"name": "arkeology"` and
  `"main": ".opencode/plugins/arkeology.js"`.
- The git+ssh URL uses a **forward slash** after the hostname:
  `git+ssh://git@github.com/amanoxsolutions/arkeology.git` — the SCP colon form
  (`git+ssh://git@github.com:...`) is invalid in Node.js and causes the plugin to
  silently never install.
- Plugin registers `skills/` only — Arkeology has no agents directory.
- Installation is user-level: the plugin line goes in `~/.config/opencode/opencode.jsonc`.
- The plugin default export must follow the **named-hook pattern**: the outer function
  receives the OpenCode context `{ project, client, $, directory, worktree }` and returns
  an object with a `config` method — `export default function(context) { return { config: (cfg) => { … } } }`.
  The `config` method receives the live config object and mutates `cfg.skills.paths` directly.
  Do **not** treat the first argument as the config object and do **not** return the config
  from the default export — OpenCode silently ignores that shape and no skills are registered.
  Use `amanox-ai-agents/.opencode/plugins/amanox.js` as the canonical reference.
- OpenCode **never auto-updates** the plugin cache (`~/.cache/opencode/packages/arkeology@git+*/`).
  Once installed, the cache entry is reused on every restart without checking for new commits
  (upstream limitation: opencode#6159, unresolved). `install.sh` must delete
  `~/.cache/opencode/packages/arkeology@git+*` so the next restart re-fetches from GitHub.

**Ask First:**
- None.

**Never:**
- No hardcoded absolute paths inside the plugin file.
- No `experimental.chat.messages.transform` bootstrap injection.
- No Windows-native install path — engineers on Windows use WSL Ubuntu.

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `package.json` | Create | Repo root; `name: arkeology`, `version` kept in sync with `pyproject.toml`, `type: module`, `main: .opencode/plugins/arkeology.js`, `description` |
| `.opencode/plugins/arkeology.js` | Create | ESM module; named-hook pattern: `export default function(context) { return { config: (cfg) => { … } } }`; mutates `cfg.skills.paths`; path resolved via `fileURLToPath(new URL('.', import.meta.url))` + `path.resolve(__dirname, '../../skills')`; errors caught and logged via `console.error`, never thrown |
| `README.md` | Modify | Add OpenCode plugin line (SSH primary, HTTPS alternative) to the Quick Install section added by T33e |
| `CONTRIBUTING.md` | Modify | Reference the plugin line and `install.sh` for OpenCode setup |

### Contracts

None.

### Testing Approach

Testing is manual smoke tests (no TDD for non-server files).

1. **Plugin loads:** Add a local `file://` or `git+ssh://` plugin line to a test
   `opencode.jsonc`; start OpenCode; invoke the `skill` tool and verify both
   `setting-up-arkeology` and `migrating-to-arkeology` are loadable.
2. **Path resolution:** Confirm the plugin works correctly when Bun resolves it to its cache
   directory (different from the repo clone path).
3. **HTTPS path:** Substitute `git+https://` in the plugin line; restart OpenCode; confirm
   both skills are loadable.
4. **No crash on hook error:** Introduce a deliberate error in the config hook (wrong path
   type); verify OpenCode starts without crashing and logs to stderr.
5. **Idempotency:** Restart OpenCode twice in a row; verify skills are not duplicated.
