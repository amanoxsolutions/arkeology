---
name: migrating-to-cairn
description: Migrate existing repository documentation into cairn-mcp — run the setting-up-cairn skill first. One-time bulk import for projects adopting cairn-mcp on an existing codebase.
---

# Migrating to cairn-mcp

This skill guides you through a one-time migration of existing repository
documentation into cairn-mcp. Use it when adopting cairn-mcp on a project that
already has months or years of accumulated docs (in `docs/`, `documentation/`, or wherever the project organises its documentation).

`migrate_artifacts` is the only migration tool. After the shared discovery and
classification steps, the file count determines which path to follow:

- **Step 3.A — ≤ 10 files:** agent generates descriptions in-context, presents them
  to the operator, then calls `migrate_artifacts(dry_run=False)` directly — Nova
  Lite is never called.
- **Step 3.B — > 10 files:** agent produces `CAIRN_IMPORT.yaml` for progress
  tracking, previews with `migrate_artifacts(dry_run=True)` so the operator can
  review server-generated descriptions before committing, then executes with `dry_run=False`.

## Workflow

1. **Health check** — verify cairn-mcp is reachable.
2. **Discovery** — check cairn-mcp installation record, check for existing manifest, scope the migration, classify files (honouring `local_only_paths` and `local_only_types` from the config block).
3. **Classification table** — operator confirms type/tier/visibility per file; file count determines the path.
   - → **Step 3.A (≤ 10 files):** build descriptors with in-context descriptions → present to operator → execute.
   - → **Step 3.B (> 10 files):** produce manifest → operator review → read files + dry-run preview → execute.
4. **Verification** — confirm artifacts appear in `list_artifacts` and `search_artifacts`.
5. **Post-migration cleanup** — remove migrated files from git (per type guidance) and update `AGENTS.md`.

---

## Step 1 — Health check

Before touching any files, verify cairn-mcp is configured and reachable.

Call the `health_check` MCP tool (no arguments). Examine the response:

- If every component shows `"status": "ok"` → proceed to Step 2.
- If any component shows `"status": "error"` → **stop here**. Report the
  failing component and its error message to the operator. Do not proceed
  until the configuration is fixed and `health_check` returns all-ok.

---

## Step 2 — Discovery

### Pre-flight — Check for cairn-mcp installation record

Before scanning the repository, check whether the project `AGENTS.md` contains a `<!-- cairn-mcp:config` block.

- **Block found** → parse `team`, `project`, `local_only_types`, and `local_only_paths` from its YAML content. Carry all four values through the rest of the skill — never ask the operator for team or project again.
- **Block not found** → **stop here**. cairn-mcp does not appear to be configured for this project. Run the `setting-up-cairn` skill first, then return here.

---

### 2a — Check for existing manifest

Before scanning the repository, check whether `CAIRN_IMPORT.yaml` exists in the repo root.

- **No manifest found** → continue to 2b.
- **All entries `status: written`** → a previous run completed successfully. Skip to Step 4 — Verification.
- **All entries `status: pending`** → the manifest was produced but the dry-run preview has not run yet. Ask the operator: continue from 3.B3, or discard the manifest and restart from scratch?
- **Mix of `status: written` / `status: pending` / `status: failed`** → migration is in progress or partially failed. Present a summary (X written, Y pending, Z failed). Skip to 3.B3 with only the `pending` and `failed` entries.

**Do not proceed further until the operator has confirmed how to continue.**

---

### 2b — Scope the migration

Scan the repository's directory tree (one level at a time, top-down) and identify
folders that are likely to contain documentation artifacts. Look for names such as
`docs`, `documentation`, `adr`, `adrs`, `specs`, `spec`, `decisions`, `architecture`,
`sessions`, `notes`, `reviews`, `runbooks`, `planning`, `brainstorming`, etc. — and
their **dot-prefix equivalents** (e.g. `.docs/`, `.documentation/`). Dot-prefix
directories are hidden but may contain real documentation; include them in the candidate
list if their name matches a documentation pattern. If a dot-prefix directory is
gitignored, note that next to it — git date recovery will not be available for files
inside it and today's date will be used as the fallback.
Do **not** descend into source code directories (`src/`, `lib/`, `app/`, `tests/`,
`node_modules/`, `.git/`, build outputs, etc.).

Present the candidate folder list to the operator and ask them to:
1. Confirm which folders to include.
2. Add any folders you missed.
3. Name any files or subdirectories within those folders to exclude
   (e.g. auto-generated files, WIP drafts, files already migrated).

Files and directories listed in `local_only_paths` (from the `cairn-mcp:config` block) are automatically excluded from this scan — never read, classified, or presented to the operator. Path matching uses prefix semantics: an entry ending in `/` (e.g. `docs/adr/`) excludes the entire directory tree; an entry without a trailing `/` (e.g. `docs/internal/private-note.md`) excludes only that exact file.

**Do not proceed to 2c until the operator has confirmed the scope.**

---

### 2c — Scan and classify

Scan only the directories and files confirmed in 2b. Classify each `.md` file using
the two passes below, in order. Apply the exclusion list the operator provided, plus
the always-skip rules at the bottom of this section. After classification, discard any
file whose resolved type is listed in `local_only_types` from the `cairn-mcp:config` block.

### Pass 1 — Filename rules (highest priority)

Match on the file's stem (filename without extension), case-insensitive, exact match.
Applies regardless of where the file sits in the repo. If a rule matches, **stop —
do not consult Pass 2**.

| Filename stems (exact, case-insensitive) | Type | Tier |
|---|---|---|
| `prd`, `product-requirements`, `requirements` | `prd` | 3 |
| `plan`, `planning`, `project-plan`, `roadmap` | `plan` | 3 |
| `changelog`, `change-log`, `changes`, `release-notes` | `changelog` | 2 |
| `runbook`, `run-book`, `playbook` | `runbook` | 3 |
| `postmortem`, `post-mortem`, `incident-report` | `postmortem` | 2 |

### Pass 2 — Path segment rules

If no filename rule matched, check every **directory segment** of the file's path,
case-insensitive. The `**/pattern` notation means the segment can appear at any depth —
`docs/brainstorming/`, `_bmad-output/brainstorming/`, and `work/project/brainstorming/`
all match `**/brainstorming`. Use the **first matching row**.

| Path segment pattern(s) | Type | Tier |
|---|---|---|
| `**/brainstorming`, `**/brainstorm`, `**/research`, `**/ideas`, `**/investigation`, `**/investigations`, `**/explore`, `**/exploration` | `brainstorming` | 2 |
| `**/adr`, `**/adrs`, `**/architecture`, `**/architectural-decisions`, `**/decisions` | `adr` | 3 |
| `**/specs`, `**/spec`, `**/specifications`, `**/specification` | `spec` | 3 |
| `**/planning-artifacts`, `**/planning`, `**/plans` | `spec` | 3 |
| `**/sessions`, `**/session-notes`, `**/notes`, `**/logs` | `session_summary` | 2 |
| `**/code-reviews`, `**/code_reviews`, `**/reviews`, `**/review` | `code_review` | 2 |
| `**/implementation-notes`, `**/impl-notes`, `**/implementation`, `**/dev-notes` | `implementation_note` | 2 |
| `**/runbooks`, `**/runbook`, `**/ops`, `**/operations`, `**/procedures`, `**/playbooks` | `runbook` | 3 |
| `**/changelogs`, `**/changelog`, `**/releases`, `**/release-notes` | `changelog` | 2 |
| `**/postmortems`, `**/postmortem`, `**/incidents`, `**/incident-reports` | `postmortem` | 2 |

### Pass 3 — Judgment fallback

If neither pass matched, read the file content and use judgment to assign a type and
tier. Default to `visibility=shared` unless the content is clearly team-internal or
sensitive.

### Exclusion list — always skip these

- `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `CHANGELOG.md` (root-level docs)
- Non-markdown files (`.txt`, `.rst`, `.html`, etc.)
- Auto-generated documentation (anything under `docs/_build/`, `site/`, `dist/`)
- Files the operator explicitly asks to exclude

---

## Step 3 — Classification table and path selection

Present a classification table to the operator showing the proposed mapping for
every candidate file. The operator may correct any row before you proceed.

| File | Type | Tier | Visibility | Notes |
|------|------|------|-----------|-------|
| docs/adr/001-use-s3.md | adr | 3 | shared | |
| docs/specs/search.md | spec | 3 | shared | |
| docs/sessions/2026-01-sprint.md | session_summary | 2 | hidden | internal notes |

Wait for operator confirmation of the table before continuing.

**Count the confirmed files.**
- ≤ 10 files → follow **Step 3.A** below.
- > 10 files → follow **Step 3.B** below.

---

## Step 3.A — ≤ 10 files

> Agent generates descriptions in-context.
> No manifest is produced. The only `migrate_artifacts` call is `dry_run=False`.

### 3.A1 — Build descriptors

For each file, read its full content and build a descriptor:

| Field | How to populate |
|-------|----------------|
| `type` | from classification table |
| `tier` | from classification table |
| `team` | from `cairn-mcp:config` block in AGENTS.md (Step 2 pre-flight) |
| `project` | from `cairn-mcp:config` block in AGENTS.md (Step 2 pre-flight) |
| `visibility` | from classification table |
| `title` | first `# H1` heading; if none, clean the filename (strip path/extension/date prefix, replace hyphens with spaces, title-case) |
| `date` | frontmatter `date:` field → `YYYY-MM-DD` in filename → `git log` (tier 2: first commit; tier 3: last commit) → today as fallback |
| `content` | **full file text — must not be empty** |
| `feature_tags` | from frontmatter only; omit if not present |
| `description` | **write in-context, ≤ 280 chars** — be specific, mention decision/outcome/scope; avoid "This document describes…" preamble |

Git date commands:
```bash
# Tier 2 — first commit date
git log --diff-filter=A --format="%ad" --date=short -- <file> | head -1
# Tier 3 — last commit date
git log --format="%ad" --date=short -1 -- <file>
```

### 3.A2 — Operator confirmation

Present the complete list to the operator — one row per file showing title,
date, and description. Wait for explicit confirmation.

> **Checkpoint before calling `migrate_artifacts`:**
> Every descriptor must have a non-empty `content` **and** a non-empty
> `description`. If any field is missing, go back and fill it now.

### 3.A3 — Execute

Compute `artifact_concurrency = min(file_count, 15)`. Explain to the operator: this
controls both how many artifacts write concurrently server-side and how many descriptors
are sent per call (for ≤ 10 files this is typically the full list in one call). Note the
Bedrock ~100 req/s Titan ceiling. Ask the operator to confirm or supply their own value.
Use the confirmed value in the call.

Call `migrate_artifacts` with `dry_run=False`, `artifact_concurrency=<confirmed_value>`,
and the full descriptor list.
Since all descriptions are agent-provided, the server writes them as-is.

If any entry in the response carries `error`:
- Report the failed entries (title + error) to the operator.
- Re-call `migrate_artifacts(dry_run=False)` with only the failed entries
  (re-read file contents from disk before retrying).
- Repeat until all entries show `written: true`.

→ Proceed to **Step 4 — Verification**.

---

## Step 3.B — > 10 files

> When no description is provided, the server generates one automatically using
> the `BEDROCK_TEXT_MODEL` configured in the MCP server entry. **If
> `BEDROCK_TEXT_MODEL` is not configured, call `health_check` — if the
> `bedrock_text_model` component is absent or errored, stop here and ask the
> operator to add `BEDROCK_TEXT_MODEL: amazon.nova-lite-v1:0` to the MCP server
> environment in their project config, then restart the MCP client.**
> A `CAIRN_IMPORT.yaml` manifest tracks progress across runs. The operator
> reviews server-generated descriptions via a dry-run before any writes occur.

### 3.B1 — Produce the manifest

For each file in the classification table, extract:
- **title** — first `# H1` heading; if none, clean the filename.
- **date** — frontmatter `date:` → `YYYY-MM-DD` in filename → `git log` (tier 2: first commit; tier 3: last commit) → today as fallback.

Git date commands:
```bash
# Tier 2 — first commit date
git log --diff-filter=A --format="%ad" --date=short -- <file> | head -1
# Tier 3 — last commit date
git log --format="%ad" --date=short -1 -- <file>
```

Generate `CAIRN_IMPORT.yaml` in the repo root (see `schema.yaml` for the full
format). Set every entry to `status: pending`. Leave `description` empty.
Populate `global.team` and `global.project` from the `cairn-mcp:config` block parsed in Step 2.

```yaml
global:
  team: "<team>"
  project: "<project>"
  visibility: "shared"

artifacts:
  - path: "docs/adr/001-use-s3.md"
    type: "adr"
    tier: 3
    status: pending
    date_override: "2024-03-15"

  - path: "docs/specs/search.md"
    type: "spec"
    tier: 3
    status: pending
    date_override: "2024-11-20"
    # description_override: "Optional — supply your own description; skips server-side generation"
    # feature_tags: ["search", "vectors"]
```

### 3.B2 — Operator review of manifest

Tell the operator: "CAIRN_IMPORT.yaml has been written to the repo root with X entries.
Please open it in your editor and review:
- Types and tiers are correct for each file
- Dates look right
- Add `description_override` for any entry where you want to supply the description yourself
- Remove any entries you do not want migrated"

Do **not** print the file content to the terminal.

Wait for operator confirmation before continuing.

### 3.B3 — Read files and preview descriptions

> **For the dry-run phase, read only the first 150 lines of each file.** This is enough
> to extract the H1 title and give Nova Lite sufficient context to generate an accurate
> description. Full file content will be read in 3.B5 for S3 storage.

Compute `artifact_concurrency = min(file_count, 15)`. Explain to the operator: this
controls how many Nova Lite description calls run concurrently per batch AND how many
descriptors are sent per call — so `artifact_concurrency=15` means 15 descriptions
generated concurrently in each batch, and you will receive a progress update after every
15 files. Note the Bedrock ~100 req/s Titan ceiling. Ask the operator to confirm or
supply their own value.

**Wait for the operator's answer before continuing. Do not proceed to the batch loop until a value is confirmed.**

Process `status: pending` entries in batches of `artifact_concurrency`. **Read files
within each batch — do not read all files upfront.** For each batch:

1. For each file in the batch, read the first 150 lines. Build a descriptor:

| Field | Source |
|-------|--------|
| `type`, `tier`, `visibility` | manifest entry |
| `team`, `project` | manifest `global` section |
| `title` | first `# H1` heading in the file; if none, clean the filename |
| `date` | `date_override` from manifest, else git log |
| `content` | **first 150 lines of the file — must not be empty** |
| `feature_tags` | manifest entry, if set |
| `description` | `description_override` if set, else **leave empty** |

2. Verify every descriptor in the batch has non-empty `content`. If any is missing,
   re-read that file before continuing.

3. Call `migrate_artifacts(dry_run=True, artifact_concurrency=<confirmed_value>, descriptors=<batch>)`.

4. Report progress only as a count — e.g. "Described 15 of 98 files". Do **not** print
   file contents, descriptor details, or any CAIRN_IMPORT.yaml content to the terminal.

After all batches complete, write all returned `description_override` values back to
`CAIRN_IMPORT.yaml` in one update pass. Do **not** print the file content.

### 3.B4 — Operator review

This is the final opportunity for the operator to review descriptions before any
writes occur. Tell the operator to open `CAIRN_IMPORT.yaml` in their editor and review
every `description_override` value. The operator may edit any entry freely.

Do **not** print the CAIRN_IMPORT.yaml content to the terminal.

Wait for the operator to confirm before proceeding.

Before moving to 3.B5, validate that every `status: pending` entry has all required
fields populated. Run from the repo root (where `CAIRN_IMPORT.yaml` lives):

```bash
uv run skills/migrating-to-cairn/scripts/validate_manifest.py
```

If the script reports errors, show them to the operator and wait for the manifest to
be corrected before re-running. Do not proceed to 3.B5 until the script exits clean.

### 3.B5 — Execute

Re-read `CAIRN_IMPORT.yaml`. For every `status: pending` entry, read the file at
`path` and build a descriptor using the same field mapping as 3.B3 — the
`description_override` field is now populated for every entry, so server-side
generation is not triggered.

Compute `artifact_concurrency = min(file_count, 15)`. Explain to the operator: in the
write phase each concurrent artifact also runs up to `SECTION_CONCURRENCY` (default 5)
Titan embedding calls, so `artifact_concurrency=15` at default settings means up to 75
concurrent Bedrock embedding calls — 25% headroom under the 100 req/s ceiling. Batching
by this value means a progress update after every `artifact_concurrency` files written.
Ask the operator to confirm or supply a lower value if concerned about quota.

**Wait for the operator's answer before continuing. Do not proceed to the batch loop until a value is confirmed.**

Split the pending descriptor list into batches of `artifact_concurrency`. For each batch:
call `migrate_artifacts(dry_run=False, artifact_concurrency=<confirmed_value>, descriptors=batch)`,
update `CAIRN_IMPORT.yaml` statuses (written/failed), and report progress as a count only
(e.g. "Written 15 of 98 files"). Do **not** print file contents or CAIRN_IMPORT.yaml
content to the terminal. Continue until all batches are processed.

After all batches, update `CAIRN_IMPORT.yaml` for every entry:
- `written: true` in the response → set `status: written`
- `error` in the response → set `status: failed` and record the error in an
  `error:` field on that manifest entry

If any entries have `status: failed`:
- Report every failed entry (path + error) to the operator.
- On next run, re-read those files, rebuild their descriptors with content,
  and call `migrate_artifacts(dry_run=False)` with only those entries.
- Repeat until all entries carry `status: written`.

→ Proceed to **Step 4 — Verification**.

---

## Step 4 — Verification

After all writes (either path), verify the migration succeeded:

1. Call `list_artifacts` with `team=<team>` and `project=<project>` to confirm
   all expected artifacts appear in the listing.
2. Run 2–3 test searches using `search_artifacts` to confirm migrated artifacts
   are semantically discoverable. Choose queries that would naturally find key
   ADRs, specs, or summaries in the migrated set.
3. If any artifact is missing from `list_artifacts`, check the write output for
   errors and re-run that entry.

---

## Step 5 — Post-migration cleanup

### Tier 2 file removal guidance

The following types are now the **canonical store** for this project's history.
Once verified in cairn-mcp, the operator may remove these files from the repo:

| Type | Safe to remove from repo |
|------|--------------------------|
| `brainstorming` | Yes — ideation records; cairn-mcp is the right home |
| `session_summary` | Yes — ephemeral session records; cairn-mcp is the right home |
| `code_review` | Yes — point-in-time review records; no need in git history |
| `implementation_note` | Yes — non-code context; cairn-mcp is the right home |
| `bug_report` | Yes — if the bug is resolved and the ticket is closed |
| `adr` | **Depends on the `adr_strategy` in your `cairn-mcp:config` block in AGENTS.md.** If `git-only`: ADRs were not migrated. If `cairn-mcp-only`: yes, remove — cairn-mcp is now the source of truth. |
| `spec` | Judgment call — keep specs that are actively referenced in code PRs; remove old, completed specs |
| `decision_note` | Judgment call — keep if referenced by other docs; otherwise remove |
| `changelog` | Judgment call — keep if the changelog is actively referenced in release PRs; remove old entries already captured in cairn-mcp |
| `plan` | Judgment call — keep if the plan file is actively updated in the repo; remove if cairn-mcp is now the live version |
| `postmortem` | Yes — point-in-time incident records; cairn-mcp is the right home |
| `prd` | Judgment call — keep if the PRD is referenced in active development; remove once the feature is shipped and the cairn-mcp copy is the archive |
| `runbook` | Judgment call — keep if the team needs runbooks reachable outside cairn-mcp (e.g. via git during an incident); remove if cairn-mcp is the agreed operational home |

Before removing any file, confirm with the operator which files they are
comfortable removing.

### AGENTS.md update

Verify that the project `AGENTS.md` already contains both:
1. A `<!-- cairn-mcp:config` block (written by the `setting-up-cairn` skill)
2. The cairn-mcp narrative usage snippet (also written by `setting-up-cairn`)

If either is absent, ask the operator to run the `setting-up-cairn` skill to write them before proceeding.
