---
type: code_review
title: Review Fix 20 — Minor Documentation Cleanup
description: Code review spec for three documentation gaps — unexplained snake_case aliases in config.py, HTML comment placeholder in README License section, and template placeholder clone URL.
tags: []
timestamp: 2026-05-31T00:00:00Z
okf_version: "0.1"
status: ready
references: []
authored:
  by: "developer"
  date: "2026-05-31"
revised:
  by: ""
  date: ""
---
# Review Fix 20 — Minor Documentation Cleanup

## Problem Statement

Three documentation gaps leave the project in a misleading state: 80 lines of
snake_case property aliases in `config.py` have no explanation, making maintainers
wonder if `alias_generator` was overlooked; `README.md` has an HTML comment placeholder
in the License section that renders as blank to readers; and the quick-start clone URL
is a template placeholder that will confuse new users. No source or test changes are
needed — all three are documentation-only fixes.

## User Stories

### Story 1 — README shows an unambiguous license statement (P3)

**Acceptance criteria:**
- Given a user opens `README.md` and navigates to the License section, when they read
  the section, then they see either an actual license statement or an explicit human-
  readable "TBD — contact maintainers" note — not an HTML comment.

### Story 2 — Quick-start clone URL is clearly labelled (P3)

**Acceptance criteria:**
- Given a user follows the quick-start guide, when they reach the `git clone` command,
  then they see either the real repository URL or a clearly labelled
  `<YOUR_REPO_URL>` placeholder with an inline comment directing them to substitute it.

### Story 3 — Config alias boilerplate is explained (P3)

**Acceptance criteria:**
- Given a maintainer reads the snake_case alias block in `config.py`, when they see the
  comment block above it, then they understand why `alias_generator` was not used and
  what trade-off was made.

## Requirements

- WHEN a user reads `README.md` THE SYSTEM SHALL show an actual license statement or an
  explicit `<!-- TODO: replace with license text — see AGENTS.md -->` visible note, not
  a silent HTML comment placeholder.
- WHEN a user reads the quick-start section THE SYSTEM SHALL see a real repository URL
  or a clearly labelled `<YOUR_REPO_URL>` placeholder with a human-readable comment.
- WHEN a maintainer reads the alias block in `config.py` THE SYSTEM SHALL find a comment
  explaining the ergonomic trade-off and noting that `alias_generator` was considered
  and rejected for explicit IDE autocomplete.

## Boundaries

**Never:**
- Add a `LICENSE` file in this spec without explicit user approval of the license type.
- Commit an actual license text until the user confirms the license type.

**Decisions (2026-05-31):**
- **License:** Apache 2.0. Rationale: provides an explicit patent grant (important for
  AWS-adjacent open-source code), is widely accepted in enterprise settings, and is the
  licence used by Amazon for most of its own open-source tooling. A `LICENSE` file with
  the Apache 2.0 text must be created in the repo root and the README updated accordingly.
- **Repository URL:** `https://github.com/amanoxsolutions/cairn-mcp`. Replace the
  `your-org/cairn-mcp` placeholder with this URL.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `LICENSE` | Create | Apache 2.0 full text (SPDX: `Apache-2.0`); copyright line: `Copyright 2026 Amanox Solutions` |
| `README.md` | Modify | Replace `<!-- TODO -->` License placeholder with Apache 2.0 badge/statement; replace `your-org/cairn-mcp` clone URL with `https://github.com/amanoxsolutions/cairn-mcp` |
| `src/cairn_mcp/config.py` | Modify | Add comment block above the snake_case alias section explaining the `alias_generator` trade-off |

## Testing Approach

Documentation-only changes — no source code or test files are modified.

**Verification (no automated tests):**
- Open `README.md` and confirm the License section is readable without an HTML comment
  blocker.
- Open `README.md` and confirm the `git clone` URL is either real or clearly labelled.
- Open `src/cairn_mcp/config.py` and confirm the comment block is present above the
  alias block.
- Run `uv run ruff check src/` and `uv run mypy src/` to confirm the comment addition
  in `config.py` did not introduce any lint or type errors.

## Open Questions

- **License — RESOLVED (2026-05-31):** Apache 2.0. Create `LICENSE` file and update README.
- **Repository URL — RESOLVED (2026-05-31):** `https://github.com/amanoxsolutions/cairn-mcp`.
  Replace `your-org/cairn-mcp` placeholder.
