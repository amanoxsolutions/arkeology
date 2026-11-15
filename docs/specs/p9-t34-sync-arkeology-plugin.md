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
  - resource: docs/specs/p9-t33d-copilot-adapter.md
    title: T33d — Copilot Adapter
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/specs/p9-t31a-setting-up-arkeology-skill.md
    title: T31a — Setting-Up-Arkeology Skill
    last_modified: 2026-11-15T19:07:16Z
  - resource: docs/specs/p9-t33c-install-script.md
    title: T33c — Install Script
    last_modified: 2026-11-15T19:07:16Z
  - resource: install.sh
    title: Arkeology install script
  - resource: https://code.claude.com/docs/en/permissions
    title: Claude Code — Configure permissions
generated:
  by: "axians-architect/unknown"
  at: 2026-06-10T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:19:59Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T34 — sync-arkeology-plugin

## TL;DR

Add a single `sync-arkeology-plugin` skill that engineers invoke on any supported tool
(OpenCode, Claude Code, Copilot) to pull the latest Arkeology skill content. The skill
detects the running tool and applies the correct update action for each, then gives the separate
update action for the Arkeology server, which no skill update touches. It also checks the
project's copy of the Arkeology `AGENTS.md` snippet against the shipped one, offering to replace an
out-of-date copy — last in Claude Code and Copilot, and in OpenCode first, before the cache clear
removes the shipped copy. It replaces the existing `plugin-sync` Claude-Code-only skill, which is removed
as part of this task.

## 1. Problem Statement

Engineers currently need tool-specific knowledge to keep their Arkeology skills current:
OpenCode users must clear Bun's plugin cache manually, Claude Code users must know about
`/arkeology:plugin-sync`, and Copilot users must re-run `install.sh`. There is no single
command that works everywhere, and the OpenCode path has no skill-based entry point at
all. A single tool-aware `sync-arkeology-plugin` skill closes all three gaps and reduces the
`arkeology:` Claude Code namespace from two overlapping update commands to one.

The skill also checks the project's copy of the Arkeology `AGENTS.md` snippet; the snippet's
markers, its stamp and the refresh it offers are specified with the setup skill (T31a), and the
migration skill's Step 5 makes the same check (T31b). The pre-approval that lets the Claude Code
pull run without a prompt is `install.sh`'s (T33c R5).

Of the four stories this spec was written from, three are P1 — OpenCode update (R1), Claude Code
update (R2) and Copilot update (R3) — and one is P2: unknown tool fallback (R4).

## 2. Rules — Update action per tool

### R1 — OpenCode: clear the Bun plugin cache, then restart OpenCode

When the skill is invoked in an OpenCode session, it instructs the agent — after the project
snippet check, which in OpenCode runs first (R8) — to run
`rm -rf ~/.cache/opencode/packages/arkeology@git+*` and then restart OpenCode. An Arkeology
operator using OpenCode invokes `sync-arkeology-plugin` and receives the exact command to clear the
Bun plugin cache, then restarts OpenCode to pull the latest skills.

**Example**

- Given I am in an OpenCode session and invoke the skill, when the skill completes, then I have
  run `rm -rf ~/.cache/opencode/packages/arkeology@git+*` and restarted OpenCode and the latest
  skill content is active.

### R2 — Claude Code: pull the plugin clone, then reload plugins

When the skill is invoked in a Claude Code session, it executes
`git -C ~/.claude/plugins/marketplaces/arkeology pull` and then runs `/reload-plugins`. The
directory is the clone of the Arkeology repository that `claude plugin marketplace add` creates. The
command is written exactly so, with the `~` unexpanded: `install.sh` pre-approves this text and no
other, so a differently written command — an expanded home path, a trailing option — stops at a
permission prompt. An Arkeology operator using Claude Code invokes
`/arkeology:sync-arkeology-plugin` and the skill performs `git pull` on the plugin clone and then
`/reload-plugins`.

**Example**

- Given I am in a Claude Code session after `install.sh` has run, and invoke the skill, when the
  skill completes, then `git -C ~/.claude/plugins/marketplaces/arkeology pull` has run without a
  permission prompt, `/reload-plugins` has been called, and the updated skills are active in the
  same session.

Source: p9-t33c-install-script R5

### R3 — Copilot: pull the Arkeology clone, re-run `install.sh`, then reload VS Code

When the skill is invoked in a Copilot session, it instructs the engineer to run, in order,
`git -C <path to their Arkeology clone> pull`, then `./install.sh` from that clone, then reload
VS Code. `install.sh` installs the skills from the clone on disk (`gh skill install --from-local
--force`, T33d R3), so the pull is what brings in the latest skill content; without it the re-install
puts back the skills already installed.

**Example**

- Given I am in a Copilot session and invoke the skill, when the skill completes, then I have
  pulled my Arkeology clone, re-run `./install.sh` from it and reloaded VS Code, and the skills
  active are those of the clone's latest commit.

### R4 — Unknown tool: present all three update paths

When the tool cannot be determined, the skill presents all three update paths and asks the
engineer to identify their tool. An Arkeology operator using an unrecognised tool invokes
`sync-arkeology-plugin` and receives an explanation of all three update paths so they can apply
the correct one manually.

**Example**

- Given the agent cannot determine the running tool, when the skill completes, then the engineer
  has been presented with all three update paths with enough detail to act independently.

### R7 — Every path gives the server's own update action after the skills'

After the update action for the detected tool (R1–R3), or the three paths for an unknown tool (R4),
the skill states that it updated the skills only, not the Arkeology server, and gives the server's
update action: in the Arkeology clone the server runs from, `git pull` and then `uv sync`, then
restart the MCP client so that it starts the updated server.

**Example**

- Given I am in a Claude Code session and invoke the skill, when the skill completes, then besides
  pulling the plugin clone and reloading plugins it has told me to run `git pull` and `uv sync` in
  my server clone and restart the client.

**Why:** the skills and the server ship from the same repository and change together, so skills
newer than the server can call a tool or pass an input the older server does not support; a skill
update alone leaves the server where it was.

Source: none

### R8 — Every path checks the project's Arkeology snippet against the shipped one

When the `AGENTS.md` of the project the skill runs in holds the Arkeology snippet, the skill
compares the stamp in the snippet's opening marker — the release version of the shipped snippet it
was copied from (T31a R36) — with the stamp of a shipped snippet, and applies the table below. Where
the shipped snippet is read, and so when the check runs, depends on the tool:

- **Claude Code and Copilot** — after the update action and the server's (R7), against the snippet
  in the Arkeology copy the update action pulled: the plugin clone in Claude Code; the engineer's
  Arkeology clone in Copilot, once the engineer says the pull is done.
- **OpenCode** — before the cache clear (R1), against the snippet of the skills OpenCode is
  running, those its last restart loaded; the check, and any replacement, ends before the skill
  gives the cache-clear command. The skill then says that a newer snippet the coming restart brings
  is checked at the next sync.

| The project's snippet | The skill |
|---|---|
| Stamp equal to the shipped one | Says in one line that the project's snippet is current, and changes nothing |
| Stamp different from the shipped one, or no markers at all | Offers the refresh: names both stamps, or says the project's has none; says replacing discards any edit made between the markers; replaces the snippet in place only on the operator's yes, and on no leaves `AGENTS.md` unchanged (T31a R37) |
| Absent from `AGENTS.md`, or no `AGENTS.md` | Says nothing about the snippet, and changes nothing |

**Example**

- Given a project whose snippet carries a stamp older than the one in the plugin clone after the
  pull, when the skill finishes in Claude Code, then it has named both stamps and asked whether to
  replace the snippet; when the operator answers no, then `AGENTS.md` is byte for byte unchanged.
- Given a project set up before the snippet carried markers, when the skill finishes, then it says
  the project's snippet has no stamp and offers the refresh.
- Given an OpenCode session whose running skills ship the snippet stamped `0.8.0` and a project
  snippet stamped `0.7.1`, when the skill is invoked, then it names both stamps and asks whether to
  replace the snippet before it gives the `rm -rf` command, and after that command says a newer
  snippet the restart brings is checked at the next sync.

**Why:** the snippet reaches a project as a copy made once, at setup; without this check a project
keeps instructing its agents with tool names and parameters the server has since changed or
removed. In OpenCode the cache clear removes the only shipped snippet on disk, and OpenCode fetches
the new package only when it restarts, so the check runs while the running skills' snippet is still
there: no second run of the skill and no clone path to ask for, at the cost of one sync's delay
before a snippet the restart brings is offered.

Source: FR-45; p9-t31a-setting-up-arkeology-skill R36, R37; in OpenCode the check runs before the cache clear (Operator, 2026-11-15)

## 3. Rules — Packaging

### R5 — The skill appears as `/arkeology:sync-arkeology-plugin` in Claude Code from the plugin's skills directory

The skill lives in `plugins/arkeology/skills/sync-arkeology-plugin/` — its only copy, a real
directory, not a symlink — so it appears as `/arkeology:sync-arkeology-plugin` in Claude Code and
is installed for Copilot by `install.sh`'s loop over that directory (T33d R3).

### R6 — `sync-arkeology-plugin` replaces `plugin-sync`

The `sync-arkeology-plugin` skill replaces the existing `plugin-sync` Claude-Code-only skill, which
is removed, reducing the `arkeology:` Claude Code namespace from two overlapping update commands to
one.

## 4. Boundaries

**Always:**
- `sync-arkeology-plugin` lives in `plugins/arkeology/skills/sync-arkeology-plugin/SKILL.md`,
  the one skills directory every tool installs from — it is not Claude-Code-specific. There is
  no top-level `skills/` directory and no symlink.
- `plugin-sync` (`plugins/arkeology/skills/plugin-sync/`) is deleted entirely as part of
  this task — it is not kept as an alias or redirect.
- No Python source changes. No `pyproject.toml` changes. No server code changes.

**Ask First:**
- None.

**Never:**
- Do not update `install.sh` — it already loops over `plugins/arkeology/skills/*/` and will
  pick up `sync-arkeology-plugin` automatically on the next run.
- Do not add any detection logic to `arkeology.js` — tool detection is the agent's
  responsibility at runtime; the skill file provides the branching instructions.

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `plugins/arkeology/skills/sync-arkeology-plugin/SKILL.md` | Create | ~35 lines; tool-detection preamble followed by three labelled step blocks (OpenCode / Claude Code / Copilot), a fallback block, and the server update note (R7) |
| `plugins/arkeology/skills/sync-arkeology-plugin/SKILL.md` | Modify | Copilot block: `git -C <clone> pull` before `./install.sh` (R3). Notes: end with restarting the MCP client rather than "the Arkeology server process", since the client starts the server (R7) |
| `plugins/arkeology/skills/plugin-sync/` | Delete | Entire directory including `SKILL.md`; replaced by `sync-arkeology-plugin` |
| `plugins/arkeology/skills/sync-arkeology-plugin/SKILL.md` | Verify | Claude Code block: the command is exactly `git -C ~/.claude/plugins/marketplaces/arkeology pull`, the text `install.sh` pre-approves (R2) — the shipped block already reads so; any edit to it is an edit to T33c R5's rule too |
| `plugins/arkeology/skills/sync-arkeology-plugin/SKILL.md` | Modify | Add a final "Project snippet check" section after the server note (R8): find the markers in the project's `AGENTS.md`; read the shipped snippet's stamp from `plugins/arkeology/skills/setting-up-arkeology/references/agents-snippet.md` in the copy just pulled (Claude Code: under `~/.claude/plugins/marketplaces/arkeology/`; Copilot: under the engineer's clone); apply R8's table and, on a yes, the setup skill's replacement (T31a R37). OpenCode block: the same check runs first, before the `rm -rf` command, reading the shipped snippet from the package OpenCode is running under `~/.cache/opencode/packages/arkeology@git+*/` (flag: confirm the snippet's path inside the cached package), and ends with the line that a newer snippet the restart brings is checked at the next sync |

### Contracts

None — the skill updates skill copies and the `AGENTS.md` snippet; it calls no server tool.

### Testing Approach

No server code changes — testing is manual smoke tests only (same convention as T33a–T33e).

1. **OpenCode path:** Invoke the skill in an OpenCode session; confirm the agent prints
   the `rm -rf` command and restart instruction without error. In a project whose snippet carries
   an older stamp than the running skills', confirm the refresh is offered before the `rm -rf`
   command is given (R8).
2. **Claude Code path:** Invoke `/arkeology:sync-arkeology-plugin` in a Claude Code session;
   confirm `git -C ~/.claude/plugins/marketplaces/arkeology pull` runs without a permission
   prompt and `/reload-plugins` is called; confirm updated skill content is active.
3. **Copilot path:** Invoke the skill in a Copilot session; confirm the agent instructs, in
   order, pulling the Arkeology clone, re-running `install.sh` from it and reloading VS Code.
4. **plugin-sync removed:** Confirm `/arkeology:plugin-sync` no longer appears as a slash
   command in Claude Code after reloading plugins.
5. **Skill location:** Confirm `plugins/arkeology/skills/sync-arkeology-plugin/` is a real
   directory, not a symlink, and that the repository has no top-level `skills/` directory.
6. **Server update note:** On each of the three paths and the unknown-tool fallback, confirm
   the skill gives `git pull` + `uv sync` in the server clone and a client restart.
7. **Project snippet check (R8):** In a project whose `AGENTS.md` snippet carries an older stamp,
   then in one set up before the snippet had markers, then in one whose stamp is current, and in one
   with no snippet, invoke the skill in Claude Code; confirm R8's outcome for each, that a "no"
   leaves `AGENTS.md` byte for byte unchanged, and that a "yes" replaces only the text between the
   markers.
