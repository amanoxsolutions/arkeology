---
type: feature-spec
feature: p4-t20-migration-skill
status: ready
phase: 4
task: 20
references: []
authored:
  by: "architect"
  date: "2026-05-31"
revised:
  by: ""
  date: ""
---

# T20 — Migration Skill

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Every team adopting cairn-mcp on an existing project starts with months or years of
accumulated documentation in their repo — ADRs, specs, session notes, implementation
records. Without a migration path, they either start from zero (losing all prior knowledge
as searchable context) or migrate files one by one with no structure. The migration skill
provides a one-time, structured workflow bundled with the cairn-mcp repository. It covers
discovery, classification, metadata enrichment (descriptions, git dates), and two execution
paths: agent-only for small projects (< 30 files) and manifest-plus-script for large ones.
A bundled `migrate.py` script handles bulk operations using the same AWS env vars as the
server without importing the `cairn_mcp` package. Following the agentskills.io standard,
the skill is usable by any MCP-compatible agentic IDE without framework lock-in.

## User Stories

### Story 1 — Operator migrates a small project (< 30 files) using agent only (P1)

An operator on a project with 15 documentation files loads the migration skill. The agent
sweeps the documentation directories, classifies each file by type and tier using the
convention table, generates a quality description in-context, recovers the original date
from `git log`, and calls `write_artifact` for each — with no extra tooling required.

**Acceptance criteria:**
- Given the agent follows the SKILL.md agent-only workflow, then all identified artifacts
  are written to cairn-mcp and immediately searchable.
- The SKILL.md workflow covers discovery, classification, description generation, and
  post-migration AGENTS.md update without gaps.

### Story 2 — Operator migrates a large project (≥ 30 files) using manifest + script (P1)

An operator on a project with 50 documentation files uses the agent to produce a
`CAIRN_IMPORT.yaml` manifest, reviews it, then runs `migrate.py` to execute bulk writes.

**Acceptance criteria:**
- Given a valid `CAIRN_IMPORT.yaml`, when `uv run skills/migration/scripts/migrate.py` is
  run, then all listed artifacts are written and immediately searchable.
- Re-running the same manifest produces no duplicate artifacts and no errors.
- When a file has no git history (squashed repo, transferred history), the date fallback
  (current date for tier 2, current date for tier 3) is logged to stderr and the import
  continues.

### Story 3 — Operator previews migration before committing writes (P1)

**Acceptance criteria:**
- Given a valid `CAIRN_IMPORT.yaml`, when `--dry-run` is passed to `migrate.py`, then
  structured JSON is output to stdout listing every artifact that would be imported —
  resolved `artifact_id`, resolved date, generated description, section count — with no
  writes to S3 or S3 Vectors.

### Story 4 — Post-migration: AGENTS.md updated, tier 2 removal guidance given (P1)

**Acceptance criteria:**
- Given a completed migration, when the SKILL.md post-migration step is followed, then
  the operator's project `AGENTS.md` has the cairn-mcp usage snippet appended (the same
  snippet from T19).
- The SKILL.md explicitly identifies which tier 2 files may be removed from the repo and
  instructs the operator on when it is safe to do so.

### Story 5 — Skill is installable in any MCP-compatible IDE (P2)

**Acceptance criteria:**
- Given the README "Using the Migration Skill" section, when an operator reads it, then
  they find the skills directory path for their IDE (Claude Code, Codex, GitHub Copilot,
  OpenCode) and a `cp -r` one-liner to install the skill.

## Requirements

- THE SKILL SHALL ship as three files: `skills/migration/SKILL.md`,
  `skills/migration/scripts/migrate.py`, and `skills/migration/schema.yaml`.
- THE `SKILL.md` SHALL cover a complete, sequential workflow: (1) pre-migration
  check (cairn-mcp configured and reachable via `health_check`), (2) discovery (directory
  allowlist + exclusion list), (3) classification table (directory-to-type-and-tier
  mapping), (4) metadata enrichment strategy, (5) two-path decision gate (< 30 files →
  agent-only; ≥ 30 files → manifest + script), (6) post-migration file removal guidance,
  (7) `AGENTS.md` update step (append the T19 snippet).
- THE `migrate.py` script SHALL use PEP 723 inline dependency declarations (boto3, pyyaml)
  and be run with `uv run skills/migration/scripts/migrate.py`; it SHALL NOT import from
  the `cairn_mcp` package.
- THE `migrate.py` script SHALL implement the same write path as `write_artifact`: parse
  `##` sections from content, embed each section via Bedrock (fallback to single
  document-level embed if no sections), put the S3 object with metadata, put a section
  vector per section with the same `{artifact_key}#{section_slug}` key format.
- THE `migrate.py` script SHALL compute `artifact_id` using the same deterministic slug
  logic as the server: tier 2 → `{type_slug}-{date}-{title_slug}`, tier 3 →
  `{type_slug}-{title_slug}`.
- THE `migrate.py` script SHALL recover original dates via `git log`: first commit date
  for tier 2 artifacts, last commit date for tier 3 artifacts; frontmatter `date:` field
  and filename-embedded date take precedence; fall back to current date if git history is
  unavailable, logging the fallback to stderr.
- THE `migrate.py` script SHALL support `--dry-run`: output a JSON array to stdout with
  one object per manifest entry — `artifact_id`, `title`, `type`, `tier`, `date`,
  `description`, `sections_count` — without any writes.
- THE `migrate.py` script SHALL generate Bedrock descriptions for entries without a
  `description_override` using the same embedding model configured in the env vars;
  in `--dry-run` mode, descriptions SHALL still be generated (or shown as preview) so the
  operator can review quality before committing.
- THE `migrate.py` script SHALL output only structured JSON to stdout; all progress,
  warnings, and diagnostics go to stderr.
- THE `migrate.py` script SHALL be idempotent: re-running the same manifest produces the
  same `artifact_id` values, which overwrite silently via the server's upsert semantics.
- THE `schema.yaml` SHALL document the `CAIRN_IMPORT.yaml` manifest format: global fields
  (`team`, `project`, `aws_region`, `bedrock_model`, `bedrock_dimensions`) and per-entry
  fields (`path`, `type`, `tier`, `visibility`, `title`, `description_override` [optional],
  `date_override` [optional], `feature_tags` [optional]).
- THE README SHALL gain a "Using the Migration Skill" section with a table showing the
  skills directory path for Claude Code, Codex, GitHub Copilot, and OpenCode, plus a
  `cp -r` one-liner to install the skill from the repo.

## Boundaries

**Always:**
- `migrate.py` calls AWS APIs directly via boto3 — it does not import from `cairn_mcp`
  to avoid creating a source dependency from the skill bundle into the server package.
- `migrate.py` uses the same env vars as the server (`ARTIFACT_BUCKET`, `VECTORS_BUCKET`,
  `VECTORS_INDEX`, `AWS_REGION`, `BEDROCK_EMBEDDING_MODEL`, `BEDROCK_EMBEDDING_DIMENSIONS`)
  so no additional configuration is needed.
- The migration skill is a one-time operational resource — it is NOT added to
  `cairn-mcp/AGENTS.md` (which would inject migration guidance into every session).
- `migrate.py` does not delete, move, or modify any files in the operator's repo — it
  only writes to cairn-mcp.
- All CLI inputs to `migrate.py` are via flags; no interactive prompts.
- `migrate.py --help` documents all flags and usage examples.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not import from `cairn_mcp` in `migrate.py`.
- Do not write anything to stdout from `migrate.py` except the structured JSON result.
- Do not make `migrate.py` interactive — all inputs must be CLI flags.
- Do not add the migration skill to `cairn-mcp/AGENTS.md`.
- Do not delete files from the operator's repository.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/migration/SKILL.md` | Create | Structured workflow document (agentskills.io format) |
| `skills/migration/scripts/migrate.py` | Create | PEP 723 script — boto3 inline dep, `--dry-run`, `--help` |
| `skills/migration/schema.yaml` | Create | CAIRN_IMPORT.yaml manifest format documentation |
| `README.md` | Modify | Add "Using the Migration Skill" section with IDE skills table and `cp -r` one-liner |

## Testing Approach

`migrate.py` is a standalone script outside the `cairn_mcp` package; standard unit tests
do not apply. Verification is integration-level and manual:

**Script verification (requires real AWS in `.env`):**
1. Author a minimal `CAIRN_IMPORT.yaml` with 2–3 real markdown files from this repo's
   `docs/` directory.
2. Run `uv run skills/migration/scripts/migrate.py --dry-run --manifest test.yaml` →
   verify JSON output contains `artifact_id`, `title`, `type`, `tier`, `date`,
   `description`, `sections_count` for each entry; confirm no S3 writes occurred.
3. Run without `--dry-run` → verify each artifact appears in `search_artifacts` and
   `list_artifacts` results immediately.
4. Re-run the same manifest → verify no duplicate artifacts appear in listing or search.
5. Test date fallback: provide an entry whose file has no git history (create a temp file
   not tracked by git) → verify a warning is logged to stderr and current date is used.
6. Clean up all written test artifacts via `delete_artifact`.

**`SKILL.md` verification (human review):**
- Load the skill in an MCP client; follow the workflow on a test project with 3–5
  documentation files; verify all artifacts are written and searchable; verify the
  `AGENTS.md` update step appends the correct snippet without error.

**`schema.yaml` verification (human review):**
- Review against CAIRN_IMPORT.yaml fields used in step 2–3 above to confirm all fields
  are documented.

## Open Questions

*(none — all constraints are defined)*
