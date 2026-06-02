---
name: migrating-to-cairn
description: Migrate existing repository documentation into cairn-mcp — one-time bulk import for projects adopting cairn-mcp on an existing codebase with accumulated docs.
---

# Migrating to cairn-mcp

This skill guides you through a one-time migration of existing repository
documentation into cairn-mcp. Use it when adopting cairn-mcp on a project that
already has months or years of accumulated docs (in `docs/`, `documentation/`, or wherever the project organises its documentation).

The skill supports three execution paths:

- **1–4 files (agent-only, sequential):** You read each file, generate descriptions
  in-context, and call `write_artifact` for each. No extra tooling needed.
- **5–9 files (manifest + script):** You produce a `CAIRN_IMPORT.yaml`
  manifest, the operator reviews it, then `migrate.py` executes bulk writes
  with Bedrock-generated descriptions and git-recovered dates.
- **≥ 10 files (agent-only, parallel via sub-agents):** You enrich all files
  first, then dispatch batches of 4–5 to sub-agents via the `task` tool for
  concurrent `write_artifact` calls.

## Workflow

1. **Pre-migration health check** — verify cairn-mcp is reachable and all components return `"status": "ok"`.
2. **Discovery** — declare the ADR strategy (git only vs cairn-mcp only), then scan the repo for migration candidates using the two-pass classification system.
3. **Classification table** — present the proposed type/tier/visibility mapping per file; wait for operator confirmation.
4. **Metadata enrichment** — resolve title, date, description, team, and project for each confirmed file.
5. **Two-path gate** — 1–4 files: agent writes directly via `write_artifact`; 5–9 files: produce `CAIRN_IMPORT.yaml`, dry-run, then execute with `migrate.py`; 10 or more files: agent enriches all files then dispatches batches of 4–5 to sub-agents.
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

Scan the repository for migration candidates. Classify every `.md` file found using
the two passes below, in order. If the operator chose **git only** for ADRs, apply
the classification first and then exclude files that resolved to `adr`.

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

## Step 5 — Three-path decision gate

Count the files confirmed in Step 3.

### Path A — Agent-only, sequential (1–4 files)

For each file:
1. Read the file content.
2. Generate a ≤ 280-character description in-context.
3. Run the `git log` commands from Step 4 to recover the date.
4. Call `write_artifact` with all fields populated.
5. Check the response for `artifact_id`. If the response contains `"error"`,
   log the filename and error, then continue with the next file.

After all files: skip to Step 6.

### Path C — Agent-only, parallel (≥ 10 files via sub-agents)

When the confirmed file count is 10 or more, use a two-phase parallel approach
to avoid long single-context write loops:

**Phase 1 — Enrich all files first (sequential, in this agent):**
For every confirmed file, gather all metadata in this context window without
writing:
1. Read the file content.
2. Generate a ≤ 280-character description in-context.
3. Run `git log` commands to recover the date.
4. Record the enriched metadata (title, date, description, type, tier, etc.)
   for every file before writing any of them.

**Phase 2 — Confirm parallelism, then write:**

Before spawning any sub-agents, present the operator with the two parallelism
knobs and their combined effect. Compute the default agent count from the file
count (ceil(N / 5), capped at 5). Example for 12 files:

> I'm ready to start writing. Before I begin, please confirm the parallelism
> settings (or give me different numbers):
>
> | What | Proposed | Default |
> |---|---|---|
> | Parallel agents | 3 agents (4–5 files each) | 3 |
> | Sections embedded at the same time per file | 5 | 5 |
> | Combined parallel AI calls | 15 | 15 |
>
> ⚠️ Keep parallel agents × sections per file ≤ 15 to stay within Bedrock
> quota. To change "sections per file", you need to restart the cairn-mcp
> server with a different `SECTION_CONCURRENCY` value before proceeding.
>
> Reply **confirm** to use these values, or give me updated numbers.

Wait for the operator's reply before spawning anything. If the operator
provides a different agent count, recompute the files-per-agent split and
confirm the new combined call count stays ≤ 15.

**Write in parallel batches (sub-agents via `task` tool):**
Split the enriched list into equal batches, one per agent. For each batch,
spawn a sub-agent using the `task` tool with explicit instructions:
- Pass all enriched metadata for the batch in the task prompt (do not ask the
  sub-agent to re-read files or re-generate descriptions).
- Instruct the sub-agent to call `write_artifact` once per file in sequence.
- Ask the sub-agent to return a JSON array of results with `artifact_id` and
  any `error`.

**Fallback if `write_artifact` is unavailable to sub-agents:**
If the sub-agent reports that `write_artifact` is not available in its tool
set, fall back to writing all files sequentially in this agent context. Report
this fallback to the operator.

**After all batches complete:** collect results from all sub-agents, log any
errors, then proceed to Step 6.

### Path B — Manifest + script (5–9 files)

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

Before running, present the operator with the two parallelism knobs and
their combined effect. Example for 7 files:

> The dry run looks good. Before I start writing, please confirm the
> parallelism settings (or give me different numbers):
>
> | What | Proposed | Default |
> |---|---|---|
> | Files written at the same time | 3 | 3 |
> | Sections embedded at the same time per file | 5 | 5 |
> | Combined parallel AI calls | 15 | 15 |
>
> ⚠️ Keep files at a time × sections per file ≤ 15 to stay within Bedrock
> quota. To change "sections per file", you need to restart the cairn-mcp
> server with a different `SECTION_CONCURRENCY` value before proceeding.
>
> Reply **confirm** to use these values, or give me updated numbers.

Wait for the operator's reply, then run with the confirmed values:

```bash
MIGRATE_CONCURRENCY=<confirmed_files_at_a_time> uv run skills/migrating-to-cairn/scripts/migrate.py \
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
