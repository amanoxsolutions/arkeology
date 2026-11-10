---
type: Spec
id: p9-t33c-install-script
title: T33c — Install Script
description: Spec for an idempotent bash install.sh that detects installed AI tools and applies the correct user-level wiring for OpenCode, Claude Code, and Copilot.
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
  at: 2026-11-09T16:52:42Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T33c — Install Script

## TL;DR

A single idempotent bash script (`install.sh`) at the repo root detects which AI tools are
installed and applies the correct user-level wiring for each: OpenCode (prints the plugin
snippet), Claude Code (registers marketplace + installs plugin + writes settings.json
pre-approval for `arkeology:plugin-sync`), and Copilot (via `gh skill install`, spec T33d).
The script always ends by printing a labelled session-refresh section that repeats the
OpenCode plugin lines verbatim, and running it twice produces the same state as running it once.

## 1. Problem Statement

Without an install script, operators must perform separate per-tool manual steps: look up
the OpenCode plugin snippet, run two Claude Code CLI commands, merge a JSON settings file.
These steps are error-prone, not in a runnable form, and not idempotent. A single script
that detects what is installed and applies the correct wiring eliminates manual burden,
makes the install reproducible, and ensures every operator ends in the same state.

All four stories this spec was written from are P1: single-command wiring (R1), idempotent re-run
(R8), session-refresh instructions always printed (R9), and Claude Code full wiring (R4, R5).

## 2. Rules — Detection

### R1 — One run wires every detected tool and skips the others

When `install.sh` is run, it detects the presence of `claude`, `opencode`, and `copilot` on PATH
and applies wiring only for detected tools. When a tool is not detected on PATH, the script skips
all wiring for that tool and prints an informational message. An Arkeology operator runs
`./install.sh` from the repo root and all their installed AI tools are wired in one step without
consulting per-tool documentation.

**Example**

- Given the operator has at least one supported tool installed (`claude`, `opencode`, or
  `copilot`), when they run `./install.sh`, then each detected tool is wired and a per-tool
  summary of what was done is printed; tools not detected are skipped with an informational
  message.

### R2 — With no supported tool detected, the script exits cleanly

When no supported tools are detected, the script prints a message and exits cleanly (no error).

## 3. Rules — Per-tool wiring

### R3 — OpenCode: the script prints both plugin lines and does not patch the config

When `opencode` is detected, the script prints both the SSH and HTTPS plugin line snippets for the
operator to add to `~/.config/opencode/opencode.jsonc` — the script does not patch the file
directly.

### R4 — Claude Code: the script registers the marketplace and installs the plugin

When `claude` is detected, the script runs
`claude plugin marketplace add git@github.com:amanoxsolutions/arkeology.git` and
`claude plugin install arkeology@arkeology`; both calls use `|| true` so a non-zero exit from an
already-registered marketplace or already-installed plugin does not abort the script. `|| true`
means a silent SSH failure (e.g. port 22 blocked by firewall) does not abort the script — the
session-refresh section mitigates this by printing the HTTPS alternative so the operator can re-run
manually if the automated step produced no result.

**Example**

- Given `claude` is detected on PATH, when `install.sh` runs, then
  `claude plugin marketplace add` and `claude plugin install arkeology@arkeology` have been run,
  and `~/.claude/settings.json` contains the pre-approval rule for `arkeology:plugin-sync`.

### R5 — Claude Code: the script merges the pre-approval rule into `~/.claude/settings.json` once

When `claude` is detected, the script merges the pre-approval rule `"Bash(git -C * pull)"` into
`~/.claude/settings.json` using an inline Python 3 script, creating the file if absent and merging
without touching unrelated entries if it exists. When the pre-approval rule is already present in
`~/.claude/settings.json`, the script does not add it a second time (idempotency).

### R6 — Copilot: the script applies the Copilot wiring specified in T33d

When `copilot` is detected, the script applies Copilot wiring as specified in T33d.

### R7 — No CLAUDE.md `@`-import step and no agent symlinks step

There is no CLAUDE.md `@`-import step and no agent symlinks step — Arkeology has no agents and its
AGENTS.md is server-setup documentation unsuitable for global injection.

Source: brainstorming-2026-06-08-skill-distribution D1

## 4. Rules — Re-runs and final output

### R8 — Re-running the script produces the same state

An Arkeology operator can re-run `./install.sh` at any time without side effects: running the
script twice produces the same state as running it once.

**Example**

- Given the operator has already run `install.sh` successfully, when they run it again, then the
  result is identical — no duplicate `settings.json` entries, no errors.

### R9 — The script always ends with a labelled session-refresh section

When all wiring is complete, the script prints a session-refresh section that:

- states the restart action for each wired tool;
- repeats both the SSH and HTTPS OpenCode plugin lines verbatim in this section;
- repeats both the SSH and HTTPS forms of `claude plugin marketplace add`, with the HTTPS form
  labelled "HTTPS alternative (if SSH / port 22 is blocked)".

An Arkeology operator always knows what to do after install completes — including what to run
manually if the automated SSH step failed silently.

**Example**

- Given `install.sh` has completed regardless of which tools were wired, when the script prints
  its final output, then a labelled section:
  - lists the session-refresh action for each wired tool;
  - repeats both the SSH and HTTPS OpenCode plugin lines verbatim;
  - repeats both the SSH and HTTPS forms of `claude plugin marketplace add` with the HTTPS
    form clearly labelled as the fallback for environments where outbound SSH is blocked.

## 5. Boundaries

**Always:**
- Bash only — no PowerShell, no Python wrapper (the JSON merge is an inline `python3 -`
  heredoc, not a separate script).
- User-level only — all config paths target `~/.claude/`, `~/.config/opencode/`, etc.
- Idempotent — every operation checks state before acting.
- `set -euo pipefail` at the top.
- `REPO_DIR` resolved via `"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`.
- SSH plugin URL uses a **forward slash** after the hostname:
  `git+ssh://git@github.com/amanoxsolutions/arkeology.git` — the SCP colon form is invalid
  in Node.js (see G1 in the brainstorming doc).
- The session-refresh summary at the bottom repeats both plugin lines (G7 — they scroll
  off during multi-tool installs).

**Ask First:**
- None.

**Never:**
- No CLAUDE.md `@`-import step (D1 — Arkeology AGENTS.md is server-setup documentation,
  not general engineering conventions).
- No agent symlinks loop (Arkeology has no agents).
- No interactive prompts — the script is fully non-interactive.
- No modification of the operator's existing tool configurations beyond the specific entries
  this script manages (settings.json pre-approval block).
- No Windows-native execution — WSL Ubuntu only on Windows.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `install.sh` | Create | Executable (`chmod +x`); sections: detect tools, OpenCode, Claude Code, Copilot (T33d logic), session-refresh |
| `README.md` | Modify | Add "Quick install" section (T33e) referencing `./install.sh` |
| `CONTRIBUTING.md` | Modify | Update tool setup section to reference `install.sh` as the primary setup path |

### Contracts

None.

### Testing Approach

Testing is manual smoke tests (no TDD for non-server files).

1. **Fresh install — all three tools:** Run `./install.sh` with `claude`, `opencode`, and
   `copilot` on PATH; verify each tool is wired; verify the session-refresh section lists
   all three tools and repeats the plugin lines verbatim.
2. **Partial tools — opencode only:** Run with only `opencode` detected; verify Claude Code
   and Copilot sections are skipped with informational messages; verify the OpenCode plugin
   lines are printed.
3. **Idempotency — settings.json:** Run `install.sh` twice; diff `~/.claude/settings.json`
   before and after the second run — no changes expected.
4. **No CLAUDE.md modification:** Confirm `~/.claude/CLAUDE.md` is not touched at any
   point during install.
5. **Session-refresh summary completeness:** Run with `opencode` and `claude` detected;
   scroll to the bottom of the output; confirm:
   - both SSH and HTTPS OpenCode plugin lines appear;
   - both SSH and HTTPS `claude plugin marketplace add` forms appear, with the HTTPS form
     clearly labelled as the SSH-blocked fallback.
6. **No tools detected:** Run with `claude`, `opencode`, and `copilot` all removed from
   PATH; verify the script prints a no-tools message and exits with code 0.
