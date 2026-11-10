---
type: Spec
id: p9-t33d-copilot-adapter
title: T33d — Copilot Adapter
description: Spec for the GitHub Copilot install path in install.sh — using gh skill install with mandatory flags and a pre-commit validation guard for YAML compatibility.
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
  at: 2026-11-09T16:55:05Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T33d — Copilot Adapter

## TL;DR

When `copilot` is detected on PATH by `install.sh`, run `gh skill install` for each
directory under `skills/`, installing from the local clone at user scope for GitHub
Copilot, with all four mandatory flags always passed; if any install call fails the script stops
immediately and prints the error and the documentation link. A pre-commit `scripts/validate.py`
script ensures that no SKILL.md with an unquoted `: ` in its `description` can reach the main
branch — the Go YAML parser used by `gh skill install` rejects such values even when Python's
parser accepts them.

## 1. Problem Statement

`gh` is GitHub's general-purpose CLI, used for PRs, issues, releases, and many other
workflows — its presence on PATH says nothing about whether the engineer uses GitHub Copilot
as their AI coding tool. The correct Copilot-specific detection signal is `command -v copilot`.

When Copilot is confirmed, `gh skill install` is the native install mechanism. It must be
called non-interactively with all four mandatory flags. Any SKILL.md whose `description`
value contains the sequence `: ` (colon-space) without being double-quoted will cause
`gh skill install` to fail with a YAML parse error — Python's YAML parser accepts plain
scalars with `: ` but the Go parser used by `gh skill install` does not. This failure is
silent in the sense that there is no obvious link between the YAML error and the unquoted
description. A pre-commit validation script prevents this class of failure from ever
reaching the install path.

All five stories this spec was written from are P1: native Copilot install via
`gh skill install` (R3), hard failure with clear error (R4), idempotent on re-run (R5), `gh` not
available when `copilot` is (R2), and SKILL.md descriptions always `gh`-compatible (R6, R7).

## 2. Rules — Detection and prerequisites

### R1 — The Copilot wiring section is entered when `copilot` is on PATH

When `copilot` is detected on PATH, `install.sh` enters the Copilot wiring section. The detection
signal is `command -v copilot`, because the presence of `gh` on PATH says nothing about whether the
engineer uses GitHub Copilot.

### R2 — A missing `gh` or `gh skill` skips the Copilot wiring with a message

| Condition | Outcome |
|-----------|---------|
| `copilot` is detected but `gh` is not on PATH | The script prints an informational message ("gh CLI required for gh skill install — https://cli.github.com") and skips Copilot wiring. |
| `copilot` is detected but the `gh skill` subcommand is not available | The script prints an informational message and skips Copilot wiring. |

An Arkeology Copilot operator whose machine has `copilot` but not `gh` receives a clear message
telling them what to install.

**Example**

- Given `copilot` is on PATH but `gh` is not, when `install.sh` runs, then the script prints an
  informational message naming `gh` as a prerequisite with its install URL, and skips the Copilot
  wiring without error.

## 3. Rules — Installing the skills

### R3 — Each skill is installed with `gh skill install` and all four flags, without prompts

When `copilot` and `gh skill` are both available, the script iterates over each subdirectory of
`skills/` and calls
`gh skill install "$REPO_DIR" <skill-name> --from-local --agent github-copilot --scope user --force`.
Every `gh skill install` call always passes all four flags:

| Flag | Why |
|------|-----|
| `--agent github-copilot` | No interactive agent-selection prompt. |
| `--scope user` | Installs to the home directory, available in all projects. |
| `--from-local` | Installs from the local clone already on disk, no per-skill GitHub API calls. |
| `--force` | Overwrites on re-run without prompting. |

An Arkeology Copilot operator runs `./install.sh` and both skills are installed via
`gh skill install` without any interactive prompts.

**Example**

- Given `copilot` is on PATH and `gh` with `gh skill` is available, when the operator runs
  `./install.sh`, then each directory in `skills/` is processed by
  `gh skill install "$REPO_DIR" <skill-name> --from-local --agent github-copilot --scope user --force`,
  and the script prints a confirmation on success.
- The operator is never prompted to select an agent or scope.

### R4 — A failed `gh skill install` stops the run with the error and the documentation link

When any `gh skill install` call exits with a non-zero status, the script immediately stops
processing remaining skills, prints the error output, and prints
`https://cli.github.com/manual/gh_skill_install`. An Arkeology operator whose `gh skill install`
fails receives a clear error message and a documentation link rather than a silent partial install.

**Example**

- Given `gh skill install` returns a non-zero exit code for any skill, when the install script
  encounters the failure, then it stops immediately without processing further skills, prints the
  exact error output from `gh`, prints the URL to the `gh skill` documentation, and exits without
  attempting any fallback.

### R5 — Re-running the install produces no errors or duplicate installs

Re-running `install.sh` does not produce errors or duplicate installs for an Arkeology Copilot
operator.

**Example**

- Given both skills have already been installed, when the operator runs `install.sh` again, then
  the script completes without errors (`--force` handles existing installs).

## 4. Rules — SKILL.md description validation

### R6 — `scripts/validate.py` rejects an unquoted `: ` in a SKILL.md `description`

When `scripts/validate.py` is run, it checks every `skills/*/SKILL.md` frontmatter and reports an
error for any `description` value that contains `: ` but is not wrapped in double quotes. When a
`description` value containing `: ` is properly double-quoted, it passes the check. When
`scripts/validate.py` finds no errors it exits 0; when it finds any error it exits 1 and prints
actionable messages.

### R7 — A pre-commit hook runs `scripts/validate.py` on every commit

When `.pre-commit-config.yaml` is updated, a hook is added that runs `python3 scripts/validate.py`
on every commit so description quoting cannot regress: an unquoted `: ` in a SKILL.md `description`
value is caught at commit time, not at install time.

**Example**

- Given a SKILL.md with `description: Installing arkeology: the MCP server` (unquoted colon), when
  the contributor runs `git commit`, then the pre-commit hook calls `python3 scripts/validate.py`
  and the commit is blocked with an actionable error message.
- Given all `description` values are correctly quoted, when the contributor commits, the hook
  passes and the commit proceeds.

## 5. Boundaries

**Always:**
- Detection signal is `command -v copilot` — not `command -v gh`.
- `gh` and `gh skill --help` are prerequisites checked inside the Copilot section.
- All four flags (`--from-local`, `--agent github-copilot`, `--scope user`, `--force`) are
  always passed — never omit any of them.
- Fail hard on any `gh skill install` error — stop immediately, print error, print docs
  URL.
- All `description` values in `skills/*/SKILL.md` that contain `: ` must be double-quoted;
  `scripts/validate.py` enforces this at commit time.
- `scripts/validate.py` checks SKILL.md files only (Arkeology has no agents directory).

**Ask First:**
- None.

**Never:**
- No fallback path — no symlinks, no file copies if `gh skill install` fails.
- No silent skip of a failed `gh skill install` call.
- No interactive agent-selection prompt — `--agent github-copilot` is always explicit.
- No use of `command -v gh` as the Copilot detection signal.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `install.sh` | Modify | Detection: `command -v copilot`; section: check `gh` + `gh skill` prerequisites; loop with all four mandatory flags; error path stops and prints docs URL |
| `scripts/validate.py` | Create | Checks every `skills/*/SKILL.md` `description` value for unquoted `: `; exits 0 on pass, 1 on fail; actionable error messages naming the file and the problem |
| `.pre-commit-config.yaml` | Modify | Add a `local` repo hook that runs `python3 scripts/validate.py` on every commit; stage-type `manual` or `commit` as appropriate |
| `skills/setting-up-arkeology/SKILL.md` | Verify/fix | Confirm `description` value is double-quoted if it contains `: `; fix if not |
| `skills/migrating-to-arkeology/SKILL.md` | Verify/fix | Same |

### Contracts

None.

### Testing Approach

Testing is manual smoke tests (no TDD for non-server files), plus the automated
`scripts/validate.py` which is verifiable via direct invocation.

1. **Successful loop:** Run `./install.sh` with `copilot` and `gh` on PATH; verify each
   skill in `skills/` is installed at user scope for GitHub Copilot; verify Copilot
   discovers the skills in a new VS Code session.
2. **Failure path:** Temporarily corrupt a skill dir (empty `SKILL.md`); verify the script
   stops after the first failure, prints the error output, and prints the docs URL; verify
   the second skill is not processed.
3. **Idempotency:** Run `./install.sh` twice; verify the second run completes without errors.
4. **No `copilot` on PATH:** Run `./install.sh` without `copilot` in PATH; verify the
   Copilot section is skipped with an informational message and the rest continues normally.
5. **`copilot` present but `gh` absent:** Remove `gh` from PATH; verify the prerequisite
   message is printed and the section is skipped without error.
6. **No interactive prompt:** Confirm `gh skill install` never produces an agent-selection
   or scope-selection prompt during the install loop.
7. **validate.py — unquoted colon:** Run `python3 scripts/validate.py` on a test SKILL.md
   with `description: Foo: bar` (unquoted); confirm exit code 1 and an actionable message.
8. **validate.py — quoted colon:** Run `python3 scripts/validate.py` with
   `description: "Foo: bar"` (quoted); confirm exit code 0.
9. **validate.py — no colon:** Run on a description with no `: `; confirm exit code 0.
10. **Pre-commit hook fires:** Stage a SKILL.md change with an unquoted `: ` in description;
    run `git commit`; verify the commit is blocked.
