---
type: Spec
id: p9-t33b-claude-code-plugin
title: T33b — Claude Code Plugin
description: Spec to add a Claude Code marketplace manifest and plugin directory so both Arkeology skills are installable via two claude plugin commands.
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
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/specs/p9-t34-sync-arkeology-plugin.md
    title: T34 — sync-arkeology-plugin
    last_modified: 2026-11-15T19:07:16Z
  - resource: docs/specs/p9-t33c-install-script.md
    title: T33c — Install Script
    last_modified: 2026-11-15T19:07:16Z
generated:
  by: "axians-architect/unknown"
  at: 2026-06-09T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:19:59Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T33b — Claude Code Plugin

## TL;DR

Add a `.claude-plugin/marketplace.json` marketplace manifest and a `plugins/arkeology/`
plugin directory to the repo so Claude Code engineers install both Arkeology skills via
two `claude plugin` commands. Skills become available as `arkeology:<name>` slash commands
(`/arkeology:setting-up-arkeology`, `/arkeology:migrating-to-arkeology`); later updates come from
the `sync-arkeology-plugin` skill, without a full reinstall.

## 1. Problem Statement

Claude Code engineers currently have no namespaced, self-updating way to install Arkeology
skills. Claude Code's private marketplace system allows a git repo to act as a
self-installing plugin: two `claude plugin` commands give the engineer both skills under
the `arkeology:` namespace. The `arkeology:` prefix prevents collision with any other installed
plugin.

This spec covers the Claude Code plugin's packaging and installation. Updating the installed
skills is the `sync-arkeology-plugin` skill's, specified in T34 for every supported tool; the one
pre-approval rule that lets its Claude Code pull run without a permission prompt is written by
`install.sh` and specified in T33c R5. This spec states neither.

The stories this spec was written from are P1: two-command install via SSH (R1) and two-command
install via HTTPS (R2).

## 2. Rules — Installation

### R1 — Two commands install both skills as namespaced slash commands

When the plugin is installed via `claude plugin install`, both skills in
`plugins/arkeology/skills/` are available as `arkeology:<skill-name>` slash commands: an
Arkeology Claude Code operator runs two commands and both Arkeology skills are available in every
subsequent Claude Code session as namespaced slash commands.

**Example**

- Given the engineer has `claude` on PATH and SSH access to GitHub, when they run
  `claude plugin marketplace add git@github.com:amanoxsolutions/arkeology.git` then
  `claude plugin install arkeology@arkeology`, then `/arkeology:setting-up-arkeology` and
  `/arkeology:migrating-to-arkeology` appear as slash commands.

### R2 — The HTTPS form of `claude plugin marketplace add` installs identically

An Arkeology Claude Code operator whose outbound SSH is blocked by a corporate firewall can use the
HTTPS form of `claude plugin marketplace add` and the install works identically.

**Example**

- Given the engineer has `claude` on PATH but cannot use SSH (port 22 blocked), when they
  run `claude plugin marketplace add https://github.com/amanoxsolutions/arkeology.git` then
  `claude plugin install arkeology@arkeology`, then `/arkeology:setting-up-arkeology` and
  `/arkeology:migrating-to-arkeology` appear as slash commands, identical to the SSH path.

### R3 — The install documentation shows both forms, SSH primary and HTTPS fallback

When the README documents the Claude Code install, it shows both:

- SSH primary: `claude plugin marketplace add git@github.com:amanoxsolutions/arkeology.git`
- HTTPS fallback: `claude plugin marketplace add https://github.com/amanoxsolutions/arkeology.git`

The SSH form is primary; the HTTPS fallback is clearly labelled for environments where outbound
SSH (port 22) is blocked by a corporate firewall. `install.sh` prints the HTTPS form only when its
Claude Code install did not take (T33c R4, R9).

### R4 — Each skill is a real directory under `plugins/arkeology/skills/`, its only copy

Each skill lives in `plugins/arkeology/skills/<name>/` as a real directory holding its
`SKILL.md` — the only copy of the skill, from which the Claude Code plugin and `install.sh`'s
Copilot loop (T33d R3) both install. There is no top-level `skills/` directory and no symlink.

### R5 — No global CLAUDE.md `@`-import is written

No global CLAUDE.md `@`-import is written — Arkeology's `AGENTS.md` contains server-setup
documentation specific to the codebase, not conventions applicable in every session. The
per-project AGENTS.md snippet written by `setting-up-arkeology` already provides the right
context within each project.

Source: brainstorming-2026-06-08-skill-distribution D1

## 3. Boundaries

**Always:**
- Skills live only in `plugins/arkeology/skills/<name>/` — no top-level `skills/` directory,
  no symlinks, no second copy.
- `plugins/arkeology/` contains only a `.claude-plugin/` directory and a `skills/`
  directory — no `agents/` directory (Arkeology has no agents).
- The marketplace manifest `source` field uses the relative path `"./plugins/arkeology"` —
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
  the top-level `"name": "arkeology"` is the marketplace identifier (the `@arkeology`
  part of `claude plugin install arkeology@arkeology`); the plugin entry's
  `"plugins[0].name": "arkeology"` is the plugin lookup key (the `arkeology@` part of the same
  command). Claude Code searches the `plugins` array for an entry whose `name` matches
  the install-command identifier — using the marketplace name for the plugin entry causes
  "Plugin 'Arkeology' not found in marketplace 'Arkeology'" at install time.
- `plugin.json` must **omit the `version` field** — a pinned static version prevents
  `claude plugin update` from picking up new pushes; Claude Code uses the commit SHA
  automatically when `version` is absent.
- The plugin needs no pre-approval of its own: the only one the install writes is T33c R5's single
  rule for the update skill's exact pull command — no wildcard, no other git command, no blanket
  bash access.
- No global CLAUDE.md `@`-import is written or required (brainstorming-2026-06-08-skill-distribution D1).

**Ask First:**
- None.

**Never:**
- No second copy of a skill outside `plugins/arkeology/skills/`, and no symlink into it.
- No agents directory inside `plugins/arkeology/` — Arkeology has no agents.
- No `version` field in `plugin.json`.
- No `@`-import prepended to `~/.claude/CLAUDE.md`.

## 4. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `.claude-plugin/marketplace.json` | Create | Top-level `name: arkeology` (marketplace ID); `owner: {name: Amanox}`; `$schema`; `plugins[0].name: arkeology` (plugin lookup key — **must match the `arkeology@` identifier in the install command, not the marketplace name**); `plugins[0].source: "./plugins/arkeology"`; see Boundaries for required fields |
| `plugins/arkeology/.claude-plugin/plugin.json` | Create | `name: arkeology`, `description` only — **no `version` field** |
| `plugins/arkeology/skills/setting-up-arkeology/` | Create | The skill's only copy, a real directory (R4) |
| `plugins/arkeology/skills/migrating-to-arkeology/` | Create | The skill's only copy, a real directory (R4) |
| `README.md` | Modify | Add the two `claude plugin` commands to the Quick Install section added by T33e |
| `CONTRIBUTING.md` | Modify | Update Claude Code setup section to reference the two plugin commands |

### Contracts

None — plugin packaging and install commands only; no server interface.

### Testing Approach

Testing is manual smoke tests (no TDD for non-server files).

1. **Plugin install — SSH:** Run `claude plugin marketplace add <repo-ssh-url>` then
   `claude plugin install arkeology@arkeology`; verify `/arkeology:setting-up-arkeology` and
   `/arkeology:migrating-to-arkeology` appear as slash commands.
2. **Plugin install — HTTPS:** Substitute the HTTPS URL in `claude plugin marketplace add`;
   run `claude plugin install arkeology@arkeology`; verify the same two slash commands appear —
   confirms the HTTPS path works for SSH-blocked environments.
3. **Skill layout:** Confirm every entry under `plugins/arkeology/skills/` is a real
   directory holding a `SKILL.md`, none is a symlink, and the repository has no top-level
   `skills/` directory.
4. **No agents directory:** Confirm `plugins/arkeology/agents/` does not exist.
5. **`plugin.json` has no version:** Confirm the file contains only `name` and
   `description`; run `claude plugin update arkeology` after pushing a change; confirm the
   update is detected.
