---
type: feature-spec
feature: p9-t33c-install-script
phase: 9
task: 33c
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

# T33c — Install Script

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

A single idempotent bash script (`install.sh`) at the repo root detects which AI tools are
installed and applies the correct user-level wiring for each: OpenCode (prints the plugin
snippet), Claude Code (registers marketplace + installs plugin + writes settings.json
pre-approval for `cairn:plugin-sync`), and Copilot (via `gh skill install`, spec T33d).
The script always ends by printing a labelled session-refresh section that repeats the
OpenCode plugin lines verbatim. Running the script twice produces the same state as
running it once.

There is no CLAUDE.md `@`-import step and no agent symlinks step — cairn-mcp has no
agents and its AGENTS.md is server-setup documentation unsuitable for global injection
(decision D1, documented in the brainstorming doc).

## Problem Statement

Without an install script, operators must perform separate per-tool manual steps: look up
the OpenCode plugin snippet, run two Claude Code CLI commands, merge a JSON settings file.
These steps are error-prone, not in a runnable form, and not idempotent. A single script
that detects what is installed and applies the correct wiring eliminates manual burden,
makes the install reproducible, and ensures every operator ends in the same state.

## User Stories

### Story 1 — Single-command wiring (P1)

As a cairn-mcp operator, I run `./install.sh` from the repo root and all my installed AI
tools are wired in one step without consulting per-tool documentation.

**Acceptance criteria:**
- Given the operator has at least one supported tool installed (`claude`, `opencode`, or
  `copilot`), when they run `./install.sh`, then each detected tool is wired and a per-tool
  summary of what was done is printed; tools not detected are skipped with an informational
  message.

### Story 2 — Idempotent re-run (P1)

As a cairn-mcp operator, I can re-run `./install.sh` at any time without side effects.

**Acceptance criteria:**
- Given the operator has already run `install.sh` successfully, when they run it again,
  then the result is identical — no duplicate `settings.json` entries, no errors.

### Story 3 — Session-refresh instructions always printed (P1)

As a cairn-mcp operator, I always know what to do after install completes — including
what to run manually if the automated SSH step failed silently.

**Acceptance criteria:**
- Given `install.sh` has completed regardless of which tools were wired, when the script
  prints its final output, then a labelled section:
  - lists the session-refresh action for each wired tool;
  - repeats both the SSH and HTTPS OpenCode plugin lines verbatim;
  - repeats both the SSH and HTTPS forms of `claude plugin marketplace add` with the HTTPS
    form clearly labelled as the fallback for environments where outbound SSH is blocked.

### Story 4 — Claude Code full wiring (P1)

As a cairn-mcp Claude Code operator, `install.sh` handles all Claude Code setup steps.

**Acceptance criteria:**
- Given `claude` is detected on PATH, when `install.sh` runs, then
  `claude plugin marketplace add` and `claude plugin install cairn@cairn-mcp` have been run,
  and `~/.claude/settings.json` contains the pre-approval rule for `cairn:plugin-sync`.

## Requirements

- WHEN `install.sh` is run THE SYSTEM SHALL detect presence of `claude`, `opencode`, and
  `copilot` on PATH and apply wiring only for detected tools.
- WHEN `opencode` is detected THE SYSTEM SHALL print both the SSH and HTTPS plugin line
  snippets for the operator to add to `~/.config/opencode/opencode.jsonc` — the script does
  not patch the file directly.
- WHEN `claude` is detected THE SYSTEM SHALL run
  `claude plugin marketplace add git@github.com:amanoxsolutions/cairn-mcp.git` and
  `claude plugin install cairn@cairn-mcp`; both calls use `|| true` so a non-zero exit from
  an already-registered marketplace or already-installed plugin does not abort the script.
  Note: `|| true` means a silent SSH failure (e.g. port 22 blocked by firewall) does not
  abort the script — the session-refresh section mitigates this by printing the HTTPS
  alternative so the operator can re-run manually if the automated step produced no result.
- WHEN `claude` is detected THE SYSTEM SHALL merge the pre-approval rule
  `"Bash(git -C * pull)"` into `~/.claude/settings.json` using an inline Python 3 script,
  creating the file if absent and merging without touching unrelated entries if it exists.
- WHEN the pre-approval rule is already present in `~/.claude/settings.json` THE SYSTEM
  SHALL not add it a second time (idempotency).
- WHEN `copilot` is detected THE SYSTEM SHALL apply Copilot wiring as specified in T33d.
- WHEN a tool is not detected on PATH THE SYSTEM SHALL skip all wiring for that tool and
  print an informational message.
- WHEN all wiring is complete THE SYSTEM SHALL print a session-refresh section that:
  - states the restart action for each wired tool;
  - repeats both the SSH and HTTPS OpenCode plugin lines verbatim in this section;
  - repeats both the SSH and HTTPS forms of `claude plugin marketplace add`, with the
    HTTPS form labelled "HTTPS alternative (if SSH / port 22 is blocked)".
- WHEN no supported tools are detected THE SYSTEM SHALL print a message and exit cleanly
  (no error).

## Boundaries

**Always:**
- Bash only — no PowerShell, no Python wrapper (the JSON merge is an inline `python3 -`
  heredoc, not a separate script).
- User-level only — all config paths target `~/.claude/`, `~/.config/opencode/`, etc.
- Idempotent — every operation checks state before acting.
- `set -euo pipefail` at the top.
- `REPO_DIR` resolved via `"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`.
- SSH plugin URL uses a **forward slash** after the hostname:
  `git+ssh://git@github.com/amanoxsolutions/cairn-mcp.git` — the SCP colon form is invalid
  in Node.js (see G1 in the brainstorming doc).
- The session-refresh summary at the bottom repeats both plugin lines (G7 — they scroll
  off during multi-tool installs).

**Never:**
- No CLAUDE.md `@`-import step (D1 — cairn-mcp AGENTS.md is server-setup documentation,
  not general engineering conventions).
- No agent symlinks loop (cairn-mcp has no agents).
- No interactive prompts — the script is fully non-interactive.
- No modification of the operator's existing tool configurations beyond the specific entries
  this script manages (settings.json pre-approval block).
- No Windows-native execution — WSL Ubuntu only on Windows.

---

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `install.sh` | Create | Executable (`chmod +x`); sections: detect tools, OpenCode, Claude Code, Copilot (T33d logic), session-refresh |
| `README.md` | Modify | Add "Quick install" section (T33e) referencing `./install.sh` |
| `CONTRIBUTING.md` | Modify | Update tool setup section to reference `install.sh` as the primary setup path |

## Testing Approach

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

## Open Questions

None.
