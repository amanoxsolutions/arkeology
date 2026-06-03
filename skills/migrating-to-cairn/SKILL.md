---
name: migrating-to-cairn
description: Migrate existing repository documentation into cairn-mcp — one-time bulk import for projects adopting cairn-mcp on an existing codebase with accumulated docs.
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
2. **Discovery** — scope the migration, declare ADR strategy, classify files.
3. **Classification table** — operator confirms type/tier/visibility per file and provides team/project; file count determines the path.
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
`sessions`, `notes`, `reviews`, `runbooks`, `planning`, `brainstorming`, etc.
Do **not** descend into source code directories (`src/`, `lib/`, `app/`, `tests/`,
`node_modules/`, `.git/`, build outputs, etc.).

Present the candidate folder list to the operator and ask them to:
1. Confirm which folders to include.
2. Add any folders you missed.
3. Name any files or subdirectories within those folders to exclude
   (e.g. auto-generated files, WIP drafts, files already migrated).

**Do not proceed to 2c until the operator has confirmed the scope.**

---

### 2c — ADR strategy

Before scanning for migration candidates, the operator must declare their ADR storage strategy.
This is a binary, one-time decision. Keeping ADRs in two systems creates a sync problem; choose
one authoritative home and commit to it.

| Strategy | What this means for migration |
|----------|-------------------------------|
| **Git only** | ADRs stay in git. Skip all `adr`-type files in the scan — do not migrate them into cairn-mcp. The git file is the single source of truth. |
| **cairn-mcp only** | Migrate ADRs into cairn-mcp. cairn-mcp becomes the single source of truth. After migration you may remove the git files. |

Ask the operator which strategy they want, without suggesting one over the other.
This choice must be recorded in the project's `AGENTS.md` — Step 5 provides the correct snippet
for each option.

**Wait for the operator to confirm their ADR strategy before continuing.**

---

### 2d — Scan and classify

Scan only the directories and files confirmed in 2b. Classify each `.md` file using
the two passes below, in order. Apply the exclusion list the operator provided, plus
the always-skip rules at the bottom of this section. If the operator chose **git only**
for ADRs, exclude any file that resolves to type `adr`.

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
- The `.docs/` scratchpad directory (agent scratch space, not canonical docs)
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

Also ask the operator for:
- **team** — team identifier (e.g. `platform`, `backend`)
- **project** — project identifier (e.g. `cairn-mcp`, `billing`)

Wait for operator confirmation of both the table and team/project before continuing.

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
| `team` | from operator (Step 3) |
| `project` | from operator (Step 3) |
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

Call `migrate_artifacts` with `dry_run=False` and the full descriptor list.
Since all descriptions are agent-provided, the server writes them as-is.

If any entry in the response carries `error`:
- Report the failed entries (title + error) to the operator.
- Re-call `migrate_artifacts(dry_run=False)` with only the failed entries
  (re-read file contents from disk before retrying).
- Repeat until all entries show `written: true`.

→ Proceed to **Step 4 — Verification**.

---

## Step 3.B — > 10 files

> When no description is provided, the server generates one automatically.
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

Present the generated `CAIRN_IMPORT.yaml` to the operator. Ask them to:
- Verify types, tiers, and dates.
- Add `description_override` for any entry where they want to supply the
  description and skip server-side generation.
- Correct any `date_override` values where git history was unavailable.

Wait for operator confirmation before continuing.

### 3.B3 — Read files and preview descriptions

For every `status: pending` entry, read the file at `path`. Build a descriptor:

| Field | Source |
|-------|--------|
| `type`, `tier`, `visibility` | manifest entry |
| `team`, `project` | manifest `global` section |
| `title` | extracted H1 or cleaned filename |
| `date` | `date_override` from manifest, else git log |
| `content` | **full file text — must not be empty** |
| `feature_tags` | manifest entry, if set |
| `description` | `description_override` if set, else **leave empty** |

> **Checkpoint before calling `migrate_artifacts`:**
> Every descriptor must have a non-empty `content`. If any is missing,
> go back and read that file now.

Call `migrate_artifacts` with `dry_run=True` and this descriptor list.

The response contains enriched descriptors with server-generated descriptions clipped
to ≤ 280 chars. For every entry that did not already have a `description_override`,
write the server-generated description back into `CAIRN_IMPORT.yaml` as
`description_override`.

### 3.B4 — Operator review

This is the final opportunity for the operator to review descriptions before any
writes occur. Instruct the operator to open `CAIRN_IMPORT.yaml` and review every
`description_override` value. The operator may edit any entry freely.

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

Call `migrate_artifacts` with `dry_run=False` and this descriptor list.

After the call, update `CAIRN_IMPORT.yaml` for every entry:
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
| `adr` | **Depends on your ADR strategy (chosen in Step 2).** If you chose **cairn-mcp only**: yes, remove the git files — cairn-mcp is now the single source of truth. If you chose **git only**: you should not have migrated ADRs at all (Step 2 told you to skip them). |
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
