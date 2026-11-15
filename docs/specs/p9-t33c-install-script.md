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
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/specs/p9-t34-sync-arkeology-plugin.md
    title: T34 — sync-arkeology-plugin
    last_modified: 2026-11-15T19:07:16Z
  - resource: https://code.claude.com/docs/en/permissions
    title: Claude Code — Configure permissions
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

# T33c — Install Script

## TL;DR

A single idempotent bash script (`install.sh`) at the repo root detects which AI tools are
installed and applies the correct user-level wiring for each: OpenCode (prints the plugin
snippet), Claude Code (registers and updates the marketplace, installs the plugin, and pre-approves
in `settings.json` the one exact command the `sync-arkeology-plugin` skill runs, printing that
rule), and Copilot (via `gh skill install`, spec T33d).
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

When `claude` is detected, the script runs, in order,
`claude plugin marketplace add git@github.com:amanoxsolutions/arkeology.git`,
`claude plugin marketplace update arkeology` and `claude plugin install arkeology@arkeology`; a
non-zero exit from any of the three — as an already-registered marketplace or an already-installed
plugin returns — does not abort the script.
After the three calls, the script checks whether the plugin is installed: `claude plugin list` lists
`arkeology`. When it does not, the script prints one line saying the Claude Code plugin was not
installed, followed by the HTTPS form of the two commands (`claude plugin marketplace add
https://github.com/amanoxsolutions/arkeology.git`, then `claude plugin install arkeology@arkeology`),
labelled for networks where SSH (port 22) is blocked; Claude Code then counts as not wired in the
session-refresh section (R9).

**Example**

- Given `claude` is detected on PATH, when `install.sh` runs, then
  `claude plugin marketplace add`, `claude plugin marketplace update arkeology` and
  `claude plugin install arkeology@arkeology` have been run, and `~/.claude/settings.json` contains
  R5's pre-approval rule.
- Given a network that blocks outbound port 22, when `install.sh` runs with `claude` on PATH, then
  the calls fail, `claude plugin list` does not list `arkeology`, and the script prints that the
  Claude Code plugin was not installed, followed by the two HTTPS commands.
- Given the plugin is already installed, when `install.sh` runs again, then any non-zero exit from
  the three calls is passed over, the check finds `arkeology` listed, and no not-installed line or
  HTTPS command is printed.

**Why:** the tolerance that lets a re-run pass an already-registered marketplace also discards a
real failure; without the check the script ends exactly as after a successful install, and the
engineer learns only on restarting Claude Code that no skill was installed.

### R5 — Claude Code: the script pre-approves exactly the sync skill's pull, once, and prints the rule

⚠️ Hard to reverse: the rule lands in the engineer's user-level settings, outside this repository,
and applies in every Claude Code session on that machine; a rule written broader than the one
command stays in force on every machine that ran the script until something removes it.

When `claude` is detected, the script merges into the `permissions.allow` list of
`~/.claude/settings.json` the one pre-approval rule
`"Bash(git -C ~/.claude/plugins/marketplaces/arkeology pull)"` — character for character the
command the `sync-arkeology-plugin` skill runs in Claude Code to pull the plugin clone, with no `*`
anywhere in it — using an inline Python 3 script, creating the file if absent and merging without
touching unrelated entries if it exists. When the rule is already present, the script does not add
it a second time (idempotency). Either way it prints the rule it manages, as one of:

- `Pre-approval rule added to ~/.claude/settings.json: Bash(git -C ~/.claude/plugins/marketplaces/arkeology pull)`
- `Pre-approval rule already present in ~/.claude/settings.json: Bash(git -C ~/.claude/plugins/marketplaces/arkeology pull)`

In the same merge, when `permissions.allow` holds the exact string `Bash(git -C * pull)` — the
wildcard rule earlier versions of this script wrote — the script removes that entry, and only that
one, and prints:

- `Pre-approval rule removed from ~/.claude/settings.json: Bash(git -C * pull)`

Any other entry, including another rule that mentions `git`, stays untouched; when the wildcard rule
is absent the script prints nothing about it.

**Example**

- Given `~/.claude/settings.json` without the rule, when `install.sh` runs with `claude` on PATH,
  then `permissions.allow` holds the string
  `Bash(git -C ~/.claude/plugins/marketplaces/arkeology pull)`, every other entry of the file is
  unchanged, and the output shows the "added" line above.
- Given the script has run, when the `sync-arkeology-plugin` skill runs
  `git -C ~/.claude/plugins/marketplaces/arkeology pull` in a Claude Code session, then it runs
  without a permission prompt; when the agent is asked to run `git -C ~/code/another-repo pull`, then
  Claude Code prompts for it.
- Given `~/.claude/settings.json` whose `permissions.allow` holds `Bash(git -C * pull)` and
  `Bash(git status)`, when `install.sh` runs with `claude` on PATH, then `permissions.allow` holds
  `Bash(git status)` and the exact-command rule but not `Bash(git -C * pull)`, and the output shows
  the "removed" line above.

**Why:** Claude Code matches a Bash rule against the command text the agent writes, and a rule with
no `*` matches that one command only. The `~` is part of that text and is expanded by the shell, to
the engineer's own home, only when the command runs, so the rule names one directory on each
machine; a rule with the home path expanded at install time would not match the command as the
skill writes it. A `*` in place of the path would let `git -C <any path> pull` — any repository on
disk, on an instruction read from any file, page or artifact — run unprompted, with whatever hooks
that repository carries. Adding the exact rule does not take the wildcard away, so the script
removes the wildcard entry it wrote itself on every machine that ran an earlier version; it matches
that exact string only, so a rule the engineer wrote is never touched.

Source: FR-35; p9-t34-sync-arkeology-plugin R2; the script removes the wildcard rule it wrote (Operator, 2026-11-15)

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
- repeats the SSH form of `claude plugin marketplace add`; and, only when R4's check found the
  Claude Code plugin not installed, repeats the not-installed line and the HTTPS form, labelled
  "HTTPS alternative (if SSH / port 22 is blocked)", in place of a Claude Code restart action.

An Arkeology operator always knows what to do after install completes — including, when the
Claude Code install did not take, that it did not and what to run instead.

**Example**

- Given `install.sh` has completed regardless of which tools were wired, when the script prints
  its final output, then a labelled section:
  - lists the session-refresh action for each wired tool;
  - repeats both the SSH and HTTPS OpenCode plugin lines verbatim;
  - repeats the SSH form of `claude plugin marketplace add`.
- Given R4's check found the Claude Code plugin not installed, when the script prints its final
  output, then the section holds no Claude Code restart action, and instead says the plugin was
  not installed and repeats the HTTPS form, clearly labelled as the fallback for environments
  where outbound SSH is blocked.

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
- No CLAUDE.md `@`-import step (brainstorming-2026-06-08-skill-distribution D1 — Arkeology AGENTS.md
  is server-setup documentation, not general engineering conventions).
- No agent symlinks loop (Arkeology has no agents).
- No interactive prompts — the script is fully non-interactive.
- No modification of the operator's existing tool configurations beyond the specific entries
  this script manages (R5's one pre-approval rule in `settings.json`, and the removal of the
  `Bash(git -C * pull)` entry earlier versions of the script wrote).
- No pre-approval rule other than R5's exact command, and no `*` in it.
- No Windows-native execution — WSL Ubuntu only on Windows.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `install.sh` | Create | Executable (`chmod +x`); sections: detect tools, OpenCode, Claude Code, Copilot (T33d logic), session-refresh |
| `install.sh` | Modify | Claude Code section: after the three tolerated calls, check `claude plugin list` for `arkeology`; when absent, print the not-installed line and the HTTPS commands and leave Claude Code out of the wired tools (R4). Session refresh: print the HTTPS `claude plugin marketplace add` form only after a failed check (R9) |
| `install.sh` | Modify | Pre-approval merge (the inline `python3 -` heredoc): the rule string becomes `Bash(git -C ~/.claude/plugins/marketplaces/arkeology pull)`, and both outcomes print the rule with the file, in R5's wording. The same merge removes the exact string `Bash(git -C * pull)` from `permissions.allow` when present and prints R5's "removed" line; no other entry is matched or removed |
| `README.md` | Modify | Add "Quick install" section (T33e) referencing `./install.sh` |
| `CONTRIBUTING.md` | Modify | Update tool setup section to reference `install.sh` as the primary setup path |

### Contracts

None — the installer wires AI tools to the skills; it touches no server interface.

### Testing Approach

Testing is manual smoke tests (no TDD for non-server files).

1. **Fresh install — all three tools:** Run `./install.sh` with `claude`, `opencode`, and
   `copilot` on PATH; verify each tool is wired; verify the session-refresh section lists
   all three tools and repeats the plugin lines verbatim.
2. **Partial tools — opencode only:** Run with only `opencode` detected; verify Claude Code
   and Copilot sections are skipped with informational messages; verify the OpenCode plugin
   lines are printed.
3. **Idempotency — settings.json:** Run `install.sh` twice; diff `~/.claude/settings.json`
   before and after the second run — no changes expected; the second run prints the "already
   present" line with the rule.
3a. **Earlier wildcard rule removed:** Put `Bash(git -C * pull)` and one unrelated entry into
   `permissions.allow`, then run `install.sh`; confirm the wildcard entry is gone, the unrelated
   entry and the exact-command rule are present, and the "removed" line is printed. Run again;
   confirm no "removed" line is printed (R5).
4. **No CLAUDE.md modification:** Confirm `~/.claude/CLAUDE.md` is not touched at any
   point during install.
5. **Session-refresh summary completeness:** Run with `opencode` and `claude` detected;
   scroll to the bottom of the output; confirm:
   - both SSH and HTTPS OpenCode plugin lines appear;
   - the SSH `claude plugin marketplace add` form appears, and after a successful Claude Code
     install the HTTPS form does not.
6. **No tools detected:** Run with `claude`, `opencode`, and `copilot` all removed from
   PATH; verify the script prints a no-tools message and exits with code 0.
7. **Claude Code install not taken:** Run with `claude` on PATH and outbound port 22 blocked
   (or the SSH marketplace URL unreachable); confirm the script prints that the Claude Code
   plugin was not installed followed by the two HTTPS commands, and that the session-refresh
   section repeats them, labelled as the SSH-blocked fallback, with no Claude Code restart
   action.
8. **Exact-command pre-approval (R5):** Confirm the rule string in `install.sh` is character for
   character `Bash(` + the command in the Claude Code block of
   `plugins/arkeology/skills/sync-arkeology-plugin/SKILL.md` + `)`, and contains no `*`. After a
   run, invoke `/arkeology:sync-arkeology-plugin` in Claude Code and confirm the pull runs without
   a prompt; ask the agent to run `git -C <another repository> pull` and confirm Claude Code
   prompts.
