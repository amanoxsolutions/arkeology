---
type: spec
title: T33e — README Quick Install Section
description: Spec to add a Quick Install section to the README with copy-paste-ready OpenCode and Claude Code install commands and a namespace coexistence note.
tags: []
timestamp: 2026-06-09T00:00:00Z
okf_version: "0.1"
feature: p9-t33e-readme-quick-install
phase: 9
task: 33e
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

# T33e — README Quick Install Section

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add a "Quick install" section to the README that gives operators the one-line OpenCode
snippet (SSH primary, HTTPS alternative) and the two-command Claude Code install, plus a
short coexistence note confirming cairn-mcp's `cairn:` namespace does not collide with
other installed plugins. This replaces the four-layer composability model from the
reference project — cairn-mcp is a specific tool, not a personal engineering baseline, so
the composability framing adds no value here.

## Problem Statement

The README currently documents the server setup in detail but gives no quick-start for
wiring the cairn-mcp skills into AI tools. Engineers who clone the repo to run the server
also need to know how to make the skills discoverable. The quick install section provides
that in under 10 lines of content — enough for an engineer to be up and running without
reading the full setup documentation, and short enough to sit at the top of the README
before the detailed sections.

## User Stories

### Story 1 — Engineer gets wired in under two minutes (P1)

As a cairn-mcp operator who has already provisioned the AWS resources and started the
server, I read the Quick Install section and wire the skills into my AI tools without
consulting any other documentation.

**Acceptance criteria:**
- Given the operator has the repo cloned and their AI tool(s) installed, when they follow
  the Quick Install section verbatim, then skills are discoverable in their next session.
- All commands in the section are copy-paste-ready — no placeholders, no invented syntax.

### Story 2 — Coexistence with other plugins is clear (P1)

As an operator who already has another AI plugin installed (e.g. from a shared engineering
plugin set), I confirm from the README that adding cairn-mcp's plugin does not break
anything already installed.

**Acceptance criteria:**
- Given the operator reads the Quick Install section, when they reach the coexistence note,
  then they understand that `cairn:` is a distinct namespace that does not shadow or collide
  with skills from other installed plugins.

## Requirements

- WHEN an engineer reads the Quick Install section THE SYSTEM SHALL provide:
  - The one-line OpenCode plugin snippet, SSH primary:
    `"plugin": ["cairn-mcp@git+ssh://git@github.com/amanoxsolutions/cairn-mcp.git"]`
  - The HTTPS alternative clearly labelled (no SSH key required):
    `"plugin": ["cairn-mcp@git+https://github.com/amanoxsolutions/cairn-mcp.git"]`
  - A note that the snippet goes in `~/.config/opencode/opencode.jsonc`.
  - The Claude Code install, SSH primary:
    ```
    claude plugin marketplace add git@github.com:amanoxsolutions/cairn-mcp.git
    claude plugin install cairn@cairn-mcp
    ```
  - The Claude Code HTTPS alternative clearly labelled (for environments where outbound
    SSH / port 22 is blocked):
    ```
    claude plugin marketplace add https://github.com/amanoxsolutions/cairn-mcp.git
    claude plugin install cairn@cairn-mcp
    ```
  - A note to run `./install.sh` to handle all wiring automatically (including GitHub
    Copilot via `gh skill install`).
  - A coexistence note: the `cairn:` namespace does not collide with skills from other
    plugins; both can be active simultaneously.
- WHEN the section is rendered THE SYSTEM SHALL not require any placeholder substitution —
  all commands are literal and copy-paste-ready.

## Boundaries

**Always:**
- Section lives in `README.md`, placed before the full server setup section so it is
  reachable without scrolling past configuration details.
- All URLs use the **forward slash** after the hostname
  (`git+ssh://git@github.com/amanoxsolutions/cairn-mcp.git`) — the SCP colon form is
  invalid in Node.js and causes the plugin to silently never install.
- The HTTPS alternative is always shown alongside the SSH form — not only in a footnote.
- Commands match exactly what T33a, T33b, T33c specify — no invented or speculative syntax.

**Never:**
- No four-layer composability model — cairn-mcp is a specific tool, not a personal
  engineering baseline (D4).
- No invented plugin registry URLs — all examples use the `git+ssh://` / `git+https://`
  pattern pointing at the real repo.
- No content about Codex or Cursor — not in T33 scope.

---

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `README.md` | Modify | Add "Quick install" section before the server setup / configuration section; content: OpenCode snippet (SSH + HTTPS), Claude Code two-command install, `./install.sh` note, coexistence paragraph |

## Testing Approach

1. **Copy-paste check — OpenCode:** Add the printed plugin line verbatim to a test
   `opencode.jsonc`; restart OpenCode; confirm both skills are loadable.
2. **Copy-paste check — Claude Code SSH:** Run the two printed `claude plugin` commands
   using the SSH URL verbatim; confirm `/cairn:setting-up-cairn` and
   `/cairn:migrating-to-cairn` appear.
3. **Copy-paste check — Claude Code HTTPS:** Run the two printed `claude plugin` commands
   using the HTTPS URL verbatim; confirm the same two slash commands appear — confirms the
   HTTPS alternative is correct for SSH-blocked environments.
4. **URL format:** Confirm all SSH URLs in the README use a forward slash after the
   hostname (not a colon); confirm HTTPS URLs use `https://github.com/` (not a git+https
   prefix — `claude plugin marketplace add` takes a plain git URL, not an npm specifier).
4. **No placeholders:** Review the section for any `YOUR-*`, `<placeholder>`, or
   `example.com` strings — none should be present.
5. **Coexistence note accuracy:** If another plugin is installed (e.g. a shared engineering
   plugin), confirm that adding the cairn-mcp plugin line alongside it and restarting
   OpenCode makes both plugin's skills simultaneously available without error.

## Open Questions

None.
