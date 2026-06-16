---
type: spec
title: T33d — Copilot Adapter
description: Spec for the GitHub Copilot install path in install.sh — using gh skill install with mandatory flags and a pre-commit validation guard for YAML compatibility.
tags: []
timestamp: 2026-06-09T00:00:00Z
okf_version: "0.1"
feature: p9-t33d-copilot-adapter
phase: 9
task: 33d
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

# T33d — Copilot Adapter

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

When `copilot` is detected on PATH by `install.sh`, run `gh skill install` for each
directory under `skills/`, installing from the local clone at user scope for GitHub
Copilot. All four flags are mandatory and always passed: `--from-local`,
`--agent github-copilot`, `--scope user`, `--force`. If any install call fails the
script stops immediately and prints the error and the documentation link. A pre-commit
`scripts/validate.py` script ensures that no SKILL.md with an unquoted `: ` in its
`description` can reach the main branch — the Go YAML parser used by `gh skill install`
rejects such values even when Python's parser accepts them.

## Problem Statement

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

## User Stories

### Story 1 — Native Copilot install via `gh skill install` (P1)

As a cairn-mcp Copilot operator, I run `./install.sh` and both skills are installed via
`gh skill install` without any interactive prompts.

**Acceptance criteria:**
- Given `copilot` is on PATH and `gh` with `gh skill` is available, when the operator runs
  `./install.sh`, then each directory in `skills/` is processed by
  `gh skill install "$REPO_DIR" <skill-name> --from-local --agent github-copilot --scope user --force`,
  and the script prints a confirmation on success.
- The operator is never prompted to select an agent or scope.

### Story 2 — Hard failure with clear error (P1)

As a cairn-mcp operator, if `gh skill install` fails I receive a clear error message and
a documentation link rather than a silent partial install.

**Acceptance criteria:**
- Given `gh skill install` returns a non-zero exit code for any skill, when the install
  script encounters the failure, then it stops immediately without processing further
  skills, prints the exact error output from `gh`, prints the URL to the `gh skill`
  documentation, and exits without attempting any fallback.

### Story 3 — Idempotent on re-run (P1)

As a cairn-mcp Copilot operator, re-running `install.sh` does not produce errors or
duplicate installs.

**Acceptance criteria:**
- Given both skills have already been installed, when the operator runs `install.sh` again,
  then the script completes without errors (`--force` handles existing installs).

### Story 4 — `gh` not available when `copilot` is (P1)

As a cairn-mcp Copilot operator whose machine has `copilot` but not `gh`, I receive a
clear message telling me what to install.

**Acceptance criteria:**
- Given `copilot` is on PATH but `gh` is not, when `install.sh` runs, then the script
  prints an informational message naming `gh` as a prerequisite with its install URL, and
  skips the Copilot wiring without error.

### Story 5 — SKILL.md descriptions are always `gh`-compatible (P1)

As a cairn-mcp contributor, an unquoted `: ` in a SKILL.md `description` value is caught
at commit time, not at install time.

**Acceptance criteria:**
- Given a SKILL.md with `description: Installing cairn: the MCP server` (unquoted colon),
  when the contributor runs `git commit`, then the pre-commit hook calls
  `python3 scripts/validate.py` and the commit is blocked with an actionable error message.
- Given all `description` values are correctly quoted, when the contributor commits, the
  hook passes and the commit proceeds.

## Requirements

- WHEN `copilot` is detected on PATH THE SYSTEM SHALL enter the Copilot wiring section.
- WHEN `copilot` is detected but `gh` is not on PATH THE SYSTEM SHALL print an
  informational message ("gh CLI required for gh skill install — https://cli.github.com")
  and skip Copilot wiring.
- WHEN `copilot` is detected but `gh skill` subcommand is not available THE SYSTEM SHALL
  print an informational message and skip Copilot wiring.
- WHEN `copilot` and `gh skill` are both available THE SYSTEM SHALL iterate over each
  subdirectory of `skills/` and call
  `gh skill install "$REPO_DIR" <skill-name> --from-local --agent github-copilot --scope user --force`.
- WHEN calling `gh skill install` THE SYSTEM SHALL always pass `--agent github-copilot` —
  no interactive agent-selection prompt.
- WHEN calling `gh skill install` THE SYSTEM SHALL always pass `--scope user` — installs
  to home directory, available in all projects.
- WHEN calling `gh skill install` THE SYSTEM SHALL always pass `--from-local` — installs
  from the local clone already on disk, no per-skill GitHub API calls.
- WHEN calling `gh skill install` THE SYSTEM SHALL always pass `--force` — overwrites on
  re-run without prompting.
- WHEN any `gh skill install` call exits with a non-zero status THE SYSTEM SHALL
  immediately stop processing remaining skills, print the error output, and print
  `https://cli.github.com/manual/gh_skill_install`.
- WHEN `scripts/validate.py` is run THE SYSTEM SHALL check every `skills/*/SKILL.md`
  frontmatter and report an error for any `description` value that contains `: ` but is
  not wrapped in double quotes.
- WHEN a `description` value containing `: ` is properly double-quoted THE SYSTEM SHALL
  pass the check.
- WHEN `scripts/validate.py` finds no errors THE SYSTEM SHALL exit 0; when it finds any
  error THE SYSTEM SHALL exit 1 and print actionable messages.
- WHEN `.pre-commit-config.yaml` is updated THE SYSTEM SHALL add a hook that runs
  `python3 scripts/validate.py` on every commit so description quoting cannot regress.

## Boundaries

**Always:**
- Detection signal is `command -v copilot` — not `command -v gh`.
- `gh` and `gh skill --help` are prerequisites checked inside the Copilot section.
- All four flags (`--from-local`, `--agent github-copilot`, `--scope user`, `--force`) are
  always passed — never omit any of them.
- Fail hard on any `gh skill install` error — stop immediately, print error, print docs
  URL.
- All `description` values in `skills/*/SKILL.md` that contain `: ` must be double-quoted;
  `scripts/validate.py` enforces this at commit time.
- `scripts/validate.py` checks SKILL.md files only (cairn-mcp has no agents directory).

**Never:**
- No fallback path — no symlinks, no file copies if `gh skill install` fails.
- No silent skip of a failed `gh skill install` call.
- No interactive agent-selection prompt — `--agent github-copilot` is always explicit.
- No use of `command -v gh` as the Copilot detection signal.

---

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `install.sh` | Modify | Detection: `command -v copilot`; section: check `gh` + `gh skill` prerequisites; loop with all four mandatory flags; error path stops and prints docs URL |
| `scripts/validate.py` | Create | Checks every `skills/*/SKILL.md` `description` value for unquoted `: `; exits 0 on pass, 1 on fail; actionable error messages naming the file and the problem |
| `.pre-commit-config.yaml` | Modify | Add a `local` repo hook that runs `python3 scripts/validate.py` on every commit; stage-type `manual` or `commit` as appropriate |
| `skills/setting-up-cairn/SKILL.md` | Verify/fix | Confirm `description` value is double-quoted if it contains `: `; fix if not |
| `skills/migrating-to-cairn/SKILL.md` | Verify/fix | Same |

## Testing Approach

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

## Open Questions

None.
