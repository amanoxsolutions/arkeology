---
name: migrating-to-cairn
description: Migrate existing repository documentation into cairn-mcp — one-time bulk import for projects adopting cairn-mcp on an existing codebase with accumulated docs.
---

# Migrating to cairn-mcp

This skill guides you through a one-time migration of existing repository
documentation into cairn-mcp. Use it when adopting cairn-mcp on a project that
already has months or years of accumulated docs in `docs/`.

The skill supports two execution paths:

- **< 30 files (agent-only):** You read each file, generate descriptions
  in-context, and call `write_artifact` for each. No extra tooling needed.
- **≥ 30 files (manifest + script):** You produce a `CAIRN_IMPORT.yaml`
  manifest, the operator reviews it, then `migrate.py` executes bulk writes
  with Bedrock-generated descriptions and git-recovered dates.

## Workflow

1. **Pre-migration health check** — verify cairn-mcp is reachable and all components return `"status": "ok"`.
2. **Discovery** — declare the ADR strategy (git only vs cairn-mcp only), then scan the repo for migration candidates using the directory mapping.
3. **Classification table** — present the proposed type/tier/visibility mapping per file; wait for operator confirmation.
4. **Metadata enrichment** — resolve title, date, description, team, and project for each confirmed file.
5. **Two-path gate** — fewer than 30 files: agent writes directly via `write_artifact`; 30 or more: produce `CAIRN_IMPORT.yaml`, dry-run, then execute with `migrate.py`.
6. **Verification** — confirm all artifacts appear in `list_artifacts` and are semantically discoverable via `search_artifacts`.
7. **Post-migration cleanup** — remove migrated files from git (per type guidance) and append the cairn-mcp usage snippet with the correct ADR variant to the project's `AGENTS.md`.

---

## Step 1 — Pre-migration health check

Before touching any files, verify cairn-mcp is configured and reachable.

Call the `health_check` MCP tool (no arguments). Examine the response:

- If every component shows `"status": "ok"` → proceed to Step 2.
- If any component shows `"status": "error"` → **stop here**. Report the
  failing component and its error message to the operator. Do not proceed
  until the configuration is fixed and `health_check` returns all-ok.

---

## Step 2 — Discovery

### ADR strategy — decide before cataloguing files

Before scanning for migration candidates, the operator must declare their ADR storage strategy.
This is a binary, one-time decision. Keeping ADRs in two systems creates a sync problem that is
not acceptable; choose one authoritative home and commit to it.

**The deciding question:** Does your team use pull request review as the approval mechanism
for ADRs?

| Answer | Strategy | What this means for migration |
|--------|----------|-------------------------------|
| **Yes — PR merge is the approval act** | **Git only** | ADRs stay in git. **Skip all `adr`-type files in the discovery scan below** — do not migrate them into cairn-mcp. The git file is the single source of truth; the PR discussion is part of the approval record and cannot be replicated in cairn-mcp. |
| **No — no formal PR-based approval** | **cairn-mcp only** | Migrate ADRs into cairn-mcp. cairn-mcp becomes the single source of truth. After migration you may remove the git files. |

This choice must be recorded in the project's `AGENTS.md` — Step 7 provides the correct snippet
for each option.

**Wait for the operator to confirm their ADR strategy before continuing.**

---

Scan the repository for migration candidates. Apply the directory convention
mapping below. When a directory listed here exists in the repo, enumerate all
`.md` files inside it (recursive). If the operator chose **git only** for ADRs,
exclude ADR directories from the scan entirely.

### Directory → type mapping

| Directory | Default type | Default tier |
|-----------|-------------|-------------|
| `docs/adr/`, `docs/architecture/` | `adr` | 3 |
| `docs/specs/` | `spec` | 3 |
| `docs/planning-artifacts/` | `spec` | 3 (prd.md, plan.md → spec tier 3) |
| `docs/brainstorming/`, `docs/sessions/`, `docs/notes/` | `session_summary` | 2 |
| `docs/code-reviews/` | `code_review` | 2 |
| `docs/implementation-notes/`, `docs/impl-notes/` | `implementation_note` | 2 |

### Exclusion list — always skip these

- `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `CHANGELOG.md` (root-level docs)
- Non-markdown files (`.txt`, `.rst`, `.html`, etc.)
- Auto-generated documentation (anything under `docs/_build/`, `site/`, `dist/`)
- The `.docs/` scratchpad directory (agent scratch space, not canonical docs)
- Files the operator explicitly asks to exclude

### Ambiguous files

For any file that does not match the directory convention (wrong directory,
mixed content, unclear purpose), read the file and use judgment to assign a
type and tier. Default to `visibility=shared` unless the content is clearly
team-internal or sensitive.

---

## Step 3 — Classification table

After discovery, present a classification table to the operator showing the
proposed mapping for every candidate file. The operator may correct any row
before you proceed.

Example table format:

| File | Type | Tier | Visibility | Notes |
|------|------|------|-----------|-------|
| docs/adr/001-use-s3.md | adr | 3 | shared | |
| docs/specs/search.md | spec | 3 | shared | |
| docs/sessions/2026-01-sprint.md | session_summary | 2 | hidden | internal notes |

Wait for operator confirmation before proceeding to Step 4.

---

## Step 4 — Metadata enrichment

For each file in the confirmed classification table, determine:

### Title
1. Extract the first `# H1` heading from the file content.
2. If no H1, clean the filename: strip path, extension, date prefixes; replace
   hyphens/underscores with spaces; title-case.

### Date
- **Tier 2:** first commit date (when the file was originally created in git).
- **Tier 3:** last commit date (when the canonical version was last updated).
- Override with `date:` frontmatter field if present (takes precedence over git log and filename).
- Override with a `YYYY-MM-DD` pattern in the filename if present (takes precedence over git log).
- Fall back to git log when neither frontmatter nor filename provides a date.
- Fallback to today's date (log a warning to stderr).

Priority order used by `migrate.py`:
1. `date_override` in manifest entry
2. frontmatter `date:` field
3. `YYYY-MM-DD` pattern in filename
4. `git log` (first commit for tier 2, last commit for tier 3)
5. today's date (fallback, logged to stderr)

In the agent-only path (< 30 files), recover dates by running:
```bash
# Tier 2 — first commit date
git log --diff-filter=A --format="%ad" --date=short -- <file> | head -1

# Tier 3 — last commit date
git log --format="%ad" --date=short -1 -- <file>
```

### Description
- **Agent-only path:** generate a ≤ 280-character search-optimised description
  in-context from the file's title and first ~500 words.
- **Manifest path:** `migrate.py` generates descriptions via Amazon Nova Lite
  (Bedrock) for entries without a `description_override` in the manifest.
- Good description: specific, mentions the decision/outcome/scope. Avoid "This
  document describes..." preamble.

### team and project
Provided once by the operator at the start of this step. Apply to all files.

### feature_tags
Omit unless the file's frontmatter provides them explicitly. Do not invent tags.

### author_role
Omit for historical files (unknown at migration time).

---

## Step 5 — Two-path decision gate

Count the files confirmed in Step 3.

### Path A — Agent-only (< 30 files)

For each file:
1. Read the file content.
2. Generate a ≤ 280-character description in-context.
3. Run the `git log` commands from Step 4 to recover the date.
4. Call `write_artifact` with all fields populated.
5. Check the response for `artifact_id`. If the response contains `"error"`,
   log the filename and error, then continue with the next file.

After all files: skip to Step 6.

### Path B — Manifest + script (≥ 30 files)

**5a — Produce the manifest**

Generate `CAIRN_IMPORT.yaml` in the repo root. See `schema.yaml` for the
full manifest format. For each file in the classification table, add an entry:

```yaml
global:
  team: "<team>"
  project: "<project>"
  visibility: "shared"

artifacts:
  - path: "docs/adr/001-use-s3.md"
    type: "adr"
    tier: 3
  - path: "docs/specs/search.md"
    type: "spec"
    tier: 3
    # description_override: "Optional verbatim description — skip Bedrock if set"
    # date_override: "2024-11-15"
    # feature_tags: ["search", "vectors"]
```

**5b — Operator review**

Present the generated `CAIRN_IMPORT.yaml` to the operator. Ask them to:
- Verify types and tiers are correct.
- Add `description_override` for any file with unusual content.
- Add `date_override` for any file where git history is unavailable.

**5c — Dry run**

Run the preview:

```bash
uv run skills/migrating-to-cairn/scripts/migrate.py \
  --manifest CAIRN_IMPORT.yaml \
  --dry-run
```

Show the JSON output to the operator. Each entry shows the resolved
`artifact_id`, `title`, `type`, `tier`, `date`, `date_source`,
`description`, and `sections_count`. This is the operator's last chance to
correct the manifest before any writes occur.

**5d — Execute**

After operator confirmation, run the full import:

```bash
uv run skills/migrating-to-cairn/scripts/migrate.py \
  --manifest CAIRN_IMPORT.yaml
```

The script outputs a JSON array with one object per artifact. Each object
includes `written: true` on success or `error: "<message>"` on failure.
Re-running the same manifest is safe — the same `artifact_id` values overwrite
silently (idempotent via S3 and S3 Vectors upsert semantics).

---

## Step 6 — Verification

After all writes (either path), verify the migration succeeded:

1. Call `list_artifacts` with `team=<team>` and `project=<project>` to confirm
   all expected artifacts appear in the listing.
2. Run 2–3 test searches using `search_artifacts` to confirm migrated artifacts
   are semantically discoverable. Choose queries that would naturally find key
   ADRs, specs, or summaries in the migrated set.
3. If any artifact is missing from `list_artifacts`, check the write output for
   errors and re-run that entry.

---

## Step 7 — Post-migration cleanup

### Tier 2 file removal guidance

The following types are now the **canonical store** for this project's history.
Once verified in cairn-mcp, the operator may remove these files from the repo:

| Type | Safe to remove from repo |
|------|--------------------------|
| `session_summary` | Yes — ephemeral session records; cairn-mcp is the right home |
| `code_review` | Yes — point-in-time review records; no need in git history |
| `implementation_note` | Yes — non-code context; cairn-mcp is the right home |
| `bug_report` | Yes — if the bug is resolved and the ticket is closed |
| `adr` | **Depends on your ADR strategy (chosen in Step 2).** If you chose **cairn-mcp only**: yes, remove the git files — cairn-mcp is now the single source of truth. If you chose **git only**: you should not have migrated ADRs at all (Step 2 told you to skip them). |
| `spec` | Judgment call — keep specs that are actively referenced in code PRs; remove old, completed specs |
| `decision_note` | Judgment call — keep if referenced by other docs; otherwise remove |

Before removing any file, confirm with the operator which files they are
comfortable removing.

### AGENTS.md update

Append the cairn-mcp usage snippet to the project's `AGENTS.md`. Start from the
README's "Recommended AGENTS.md Snippet" section. Then, based on the ADR strategy
confirmed in Step 2, insert the appropriate ADR guidance block — **Variant A** for
**git only**, **Variant B** for **cairn-mcp only** — under the artifact type selection
table in the snippet. Confirm with the operator before writing.

**Variant A — git only (team uses PR-based ADR approval)**

```markdown
**ADRs:** This project keeps ADRs in git. Do NOT write `type=adr` artifacts to
cairn-mcp. When you create or update an ADR, commit it to the project's ADR
directory in git. Git is the single source of truth for ADRs.
```

**Variant B — cairn-mcp only (no formal PR-based ADR approval)**

```markdown
**ADRs:** This project stores ADRs in cairn-mcp only. Write ADRs using
`write_artifact` (type=adr, tier=3, visibility=shared). Do NOT commit ADR files
to git — cairn-mcp is the single source of truth. Draft ADRs use `visibility=hidden`
until approved.
```

Confirm with the operator before writing to `AGENTS.md`.
