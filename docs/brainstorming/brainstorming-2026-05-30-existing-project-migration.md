---
type: brainstorming
title: Existing Project Migration
description: Explores how a team adopting Arkeology would migrate accumulated project documentation (ADRs, specs, brainstorming files) into Arkeology, covering discovery, classification, metadata enrichment, import mechanism, and post-migration strategy.
tags: []
timestamp: 2026-05-30T00:00:00Z
okf_version: "0.1"
status: complete
references: []
authored:
  by: "analyst"
  date: "2026-05-30"
revised:
  by: ""
  date: ""
---

# Existing Project Migration

## Description

Arkeology is designed for new or ongoing agent sessions. But every team that adopts it starts
from an existing project — a repo with months or years of accumulated docs: ADRs in `docs/adr/`,
specs in `docs/specs/`, brainstorming session files, scratchpad notes, implementation notes
committed to the repo. This session explores how a team would actually get all of that into
Arkeology, and what the correct set of tools, workflows, and guidance looks like to make that
practical.

The migration problem has five distinct sub-problems: discovery (what to migrate), classification
(what type is this file?), metadata enrichment (where do descriptions and dates come from?),
import mechanism (who or what calls `write_artifact`?), and post-migration strategy (what happens
to the originals?).

---

## Session 2026-05-30

### Problem decomposition

A team adopting Arkeology on an existing project faces five separate challenges in sequence:

1. **Discovery** — identify which files in the repo are worth migrating
2. **Classification** — map each file to an Arkeology artifact type, tier, and visibility
3. **Metadata enrichment** — produce required fields that don't exist in most files (`description`, original `date`, `team`, `project`)
4. **Import** — actually call `write_artifact` for each selected file
5. **Post-migration** — decide what happens to the original files and what is the source of truth going forward

Each sub-problem has its own option space.

---

### Sub-problem 1 — Discovery: what to migrate

**Ideas — file selection strategies**

- **Allowlist by directory**: only migrate files under known documentation directories (`docs/adr/`, `docs/specs/`, `docs/brainstorming/`, `docs/planning-artifacts/`); everything else is ignored
- **Allowlist by filename pattern**: migrate all `*.md` files except known non-artifacts (`README.md`, `CHANGELOG.md`, `AGENTS.md`, `CONTRIBUTING.md`)
- **Explicit manifest**: user creates an ARKEOLOGY_IMPORT.yaml that explicitly lists files → metadata; nothing is inferred
- **Agent-guided sweep**: an agent walks the repo using `list_files` or directory traversal and makes judgment calls on each file using its understanding of the project
- **Git-history scan**: surface all `.md` files that have been modified by a human (not just auto-generated), using `git log` to exclude files never committed by a person
- **Gradual as-you-go**: no upfront migration; each time an agent session encounters a relevant repo file it reads it, writes it to Arkeology, and continues — coverage builds up naturally over time
- **Type-guided sweep**: for each Arkeology artifact type, identify the conventional directory for that type in the project and sweep it; skip anything that doesn't map to a type

**Selected direction**

The most practical starting approach is **allowlist by directory + agent judgment for edge cases**.
Canonical documentation directories (`docs/adr/`, `docs/specs/`, `docs/brainstorming/`,
`docs/planning-artifacts/`, `docs/notes/`) map cleanly to artifact types. Files outside these
directories are generally not artifacts. An agent doing the migration walk applies the final
judgment call on ambiguous files.

**What to explicitly exclude from migration**:

- `README.md`, `AGENTS.md`, `CONTRIBUTING.md` — repository metadata, not session artifacts
- `CHANGELOG.md` — version history belongs in git
- `pyproject.toml`, `.env.example`, any non-markdown file — not text artifacts
- Auto-generated docs (sphinx output, mkdocs output) — not hand-authored artifacts
- `.docs/` scratchpad — gitignored tier 1 ephemeral files; migrate selectively if valuable

---

### Sub-problem 2 — Classification: mapping files to artifact types

**Ideas — classification approaches**

- **Directory-convention mapping**: define a conventional directory → type mapping once, apply mechanically
  - `docs/adr/` or `docs/architecture/` → `adr`, tier 3
  - `docs/specs/` → `spec`, tier 3
  - `docs/brainstorming/` → `session-summary` or `research`, tier 2
  - `docs/planning-artifacts/` → split: `vision.md` → `spec`, `requirements.md` → `spec`, `plan.md` → `spec`, all tier 3
  - `docs/notes/` or `docs/impl-notes/` → `impl-note`, tier 2
  - `docs/code-reviews/` → `code-review`, tier 2
  - `docs/research/` → `research`, tier 2 or 3 depending on content
- **Filename pattern matching**: `session-summary-*.md` → `session-summary`; `adr-*.md` → `adr`; `cr-*.md` → `code-review`
- **Frontmatter parsing**: if files contain YAML frontmatter with a `type:` field, use it directly
- **Content-based LLM classification**: feed the first 300 words to an LLM with the Arkeology type catalogue (from MCP Resources) and ask it to classify — most reliable for ambiguous files
- **User-override manifest**: user provides the final mapping as YAML; tool uses it verbatim
- **Interactive agent dialog**: agent proposes a classification for each file, user confirms or corrects via conversational turns

**Tier assignment heuristics**:

| Type | Default tier | Rationale |
|---|---|---|
| `adr` | 3 | Permanent architectural decisions — living documents |
| `spec` | 3 | Specifications are living documents, updated as features evolve |
| `research` | 3 if explicitly canonical, 2 otherwise | Research can be historical record or reference |
| `session-summary` | 2 | Point-in-time records of what happened in a session |
| `impl-note` | 2 | Historical record of how and why something was implemented |
| `code-review` | 2 | Historical record of a review at a point in time |
| `issue-record` | 2 | Historical record of a bug or incident |
| `synthesis` | 3 | By definition a synthesised canonical summary |

**Selected direction**

**Directory-convention mapping is the primary signal; LLM classification handles ambiguous files.**
This means documenting a recommended directory layout for teams to adopt, and providing a
classification mapping that the migration workflow can apply mechanically. Files that don't match
any convention are sent to the LLM classifier or left for agent judgment.

---

### Sub-problem 3 — Metadata enrichment

**The hard fields**

`description` (≤280 chars) — The most critical field for search quality. Doesn't exist in most
existing files. Must be written or generated.

`date` — For tier 2 artifacts, date is part of the key. Using "today's date" for a 2-year-old
session summary would be semantically wrong and would create a key pointing to a migration event,
not the original event. The original creation date should be recovered.

`team` and `project` — Cannot be inferred from file content. Must be provided by the operator
at migration time (they apply uniformly to all files being migrated for a given project).

**Ideas — description generation**

- **H1 + first paragraph extraction**: use the first heading as title and the first non-empty
  paragraph as the description (trimmed to 280 chars). Fast, free, but often produces poor
  descriptions if the first paragraph is context-setting rather than summary.
- **LLM generation from content**: pass title + first 500 words to a LLM and ask for a
  ≤280-char description optimised for semantic search. Best quality, uses Bedrock API, small cost.
- **Frontmatter `description:` extraction**: many ADR templates include a description/context
  field; parse it if present.
- **Manual curation with agent assist**: agent proposes description, human reviews — best quality
  for high-value tier 3 artifacts that will persist permanently.
- **Null/empty and backfill later**: migrate with an empty description and add a second pass
  later to generate descriptions. Two-phase approach.

**Ideas — date recovery**

- **`git log` first commit date**: `git log --diff-filter=A --format="%ai" -- <file> | head -1`
  gives the date the file was first added to the repo — the best proxy for creation date.
- **Frontmatter `date:` extraction**: many ADR and session note templates include a date field.
- **Filename date extraction**: `session-summary-2024-11-15.md` → `2024-11-15`.
- **Current date fallback**: if git history is unavailable (repo transfer, squashed history),
  use today's date for tier 2 artifacts. Documents a "migrated on" date, not the original event.
- **Last modified date**: `git log --format="%ai" -1 -- <file>` — appropriate for tier 3 living
  documents (their date should reflect the last time they were updated, not created).

**Ideas — features and author_role**

- **Extract from frontmatter** if template includes feature tags.
- **LLM extraction from content** — ask the model to identify feature slugs mentioned.
- **Omit and search later** — optional fields; omitting them is valid and can always be searched
  by semantic query instead of metadata filter.

**Selected direction**

| Field | Migration strategy |
|---|---|
| `title` | H1 heading from markdown, fallback to filename cleaned up |
| `description` | LLM-generated from title + first 500 words via Bedrock (same model used by the server) |
| `date` | `git log` first commit for tier 2; last commit for tier 3; frontmatter override if present; current date as last resort |
| `team` | Provided once by operator for the whole project migration |
| `project` | Provided once by operator for the whole project migration |
| `tier` | Directory-convention mapping; manual override for ambiguous files |
| `visibility` | Default `shared`; `hidden` for files the operator explicitly flags |
| `features` | Omit unless frontmatter provides them; optional and not blocking |
| `author_role` | Omit (unknown for historical files) |
| `status` | `active` unless operator explicitly flags as superseded/archived |

---

### Sub-problem 4 — Import mechanism

**Ideas — how artifacts actually get written**

**Option A — Agent-led, file-by-file** (no new tooling needed)

The operator runs an agent session, provides the repo path, and instructs the agent to migrate.
The agent uses existing file-reading capabilities + `write_artifact` MCP tool for each file.
The agent classifies, generates descriptions, recovers dates, and writes.

- Pros: no new tooling, full agent judgment on each file, high description quality
- Cons: slow for large repos (100+ files = 100 agent turns), consumes significant context window
- Best for: small projects (< 30 files), high-value tier 3 artifacts only

**Option B — Manifest-driven Python migration script** (helper script in the repo)

A Python script (`tools/migrate_to_arkeology.py` or similar) that:
1. Reads an ARKEOLOGY_IMPORT.yaml manifest
2. Runs `git log` to recover dates per file
3. Calls Bedrock (same model) to generate descriptions for files missing them
4. Instantiates Arkeology clients directly and calls `write_artifact` logic
5. Reports what was imported, what failed, what was skipped

The manifest is either hand-written by the operator or generated by an agent in a preparation step.

- Pros: fast (bulk), automated, reliable, repeatable
- Cons: requires a script; agent is not in the loop during import; description quality depends on LLM prompt
- Best for: large migrations (50+ files), CI/CD-integrated migration

**Option C — New MCP tool: `import_artifact_from_path`** (server extension)

Add a new server tool that accepts a file path + partial metadata, reads the file content,
runs `git log` via subprocess to recover the date, generates a description via Bedrock, and
calls the write path internally.

- Pros: stays within MCP protocol; agent can call it in a loop
- Cons: adds a tool that is only useful during migration; `git` subprocess coupling is ugly;
  path access from the server implies server and repo are on the same machine
- Verdict: **probably the wrong place** to add this — migration is an operational concern,
  not a server tool concern. The server's job is to store and retrieve; migration preparation
  is a different concern.

**Option D — Frontmatter injection + direct write**

Before migrating, an agent adds YAML frontmatter to each file with pre-filled Arkeology metadata
(type, tier, team, project, description). Then a simple script reads frontmatter and calls
`write_artifact`. The frontmatter becomes the source of truth for metadata.

- Pros: metadata is visible in the file itself; no external manifest; idempotent on re-run
- Cons: pollutes source files with migration-specific metadata; frontmatter needs to be added
  to every file first (more work up front)

**Option E — Gradual as-you-go (no upfront migration)**

No batch migration at all. Agents encounter relevant repo files naturally during work, read
them, and write them to Arkeology as needed. Coverage builds up organically.

- Pros: zero migration effort; only relevant files get migrated
- Cons: patchy coverage; an agent starting a new session doesn't know which files have been
  migrated and which haven't; no single point of confidence

**Selected direction — Migration skill (SKILL.md) bundling migrate.py**

Migration is a **one-time operation**, not ongoing guidance. That rules out AGENTS.md — anything
placed there is loaded by every agent in every session, permanently. A skill is the correct
vehicle: the operator loads it once to perform the migration, then never needs it again.

SKILL.md is a cross-framework standard (https://agentskills.io/home) recognised by all major
agentic coding IDEs (Claude Code, Codex, Copilot, and others). It is not OpenCode-specific.
The D13 decision to reject a companion skill was about always-on general usage guidance — that
reasoning does not apply to a one-time operational skill.

**Structure of the migration skill (shipped with Arkeology)**:

```
skills/migration/
  SKILL.md          # Structured workflow for the agent
  migrate.py        # Mechanical bulk operations: git dates, Bedrock descriptions, bulk writes
  schema.yaml       # ARKEOLOGY_IMPORT.yaml manifest schema (for large migrations)
```

**Division of labour — skill vs. script:**

| Concern | Handled by |
|---|---|
| Discovery: which files to migrate | Skill instructs agent to apply directory allowlist + read ambiguous files |
| Classification: type + tier | Skill provides classification table; agent applies judgment on ambiguous files |
| Description generation: ambiguous/high-value files | Agent reads the file and writes a high-quality description in-context |
| Date recovery | `migrate.py` runs `git log` per file |
| Description generation: bulk clear-cut files | `migrate.py` calls Bedrock with a structured prompt |
| Bulk `write_artifact` calls | `migrate.py` calls Arkeology write path directly |
| Manifest generation (large migrations) | Agent produces the ARKEOLOGY_IMPORT.yaml, operator reviews |
| Verification | Skill instructs agent to call `list_artifacts` + run test searches |

**Two workflow paths within the skill:**

*Small migration (< 30 files) — agent-only*:
1. Load skill
2. Agent sweeps doc directories, classifies each file, reads ambiguous ones, generates descriptions in-context, calls `write_artifact` for each
3. Verify with `list_artifacts` and test searches

*Large migration (30+ files) — agent prepares manifest, script executes*:
1. Load skill
2. Agent reads all candidate files, produces ARKEOLOGY_IMPORT.yaml (path, type, tier, draft description for each)
3. Operator reviews and edits manifest
4. Agent runs `migrate.py` which handles git dates, Bedrock descriptions for bulk files, bulk writes
5. Verify with `list_artifacts` and test searches

---

### Sub-problem 5 — Post-migration strategy

**The tension**: the existing repo files are the current "source of truth". After migrating to
Arkeology, should they be removed? Left in place? What's the source of truth going forward?

**Ideas — treatment of original files post-migration**

- **Keep and leave**: files stay in the repo unchanged; Arkeology is an additional index; both
  exist; no single source of truth; risk of divergence
- **Keep and mark**: add a frontmatter flag `arkeology_id: <artifact_id>` to each migrated file;
  the file stays but it's clear it has been migrated; updating the file should also trigger a
  Arkeology re-write
- **Keep tier 3, remove tier 2**: ADRs and specs stay in the repo (they belong there too);
  tier 2 working documents (session summaries, code reviews, impl notes) are removed after
  migration since their value is now in Arkeology
- **Move to archive branch**: migrated tier 2 files are removed from main and archived in a
  historical branch; repo stays clean, history preserved
- **Remove all migrated files**: repo cleans up; Arkeology is the single source of truth for
  artifacts; risks: Arkeology unavailability = no access; new contributors may expect docs in repo
- **Dual-write going forward**: after migration, agents write all new artifacts to Arkeology
  AND commit a copy to the repo in the appropriate directory; redundant but portable

**Recommendation for each tier**

| Tier | Recommended post-migration treatment | Rationale |
|---|---|---|
| Tier 3 (ADRs, specs, plans) | **Keep in repo, dual-write going forward** | Tier 3 artifacts are canonical — engineers expect them in the repo; Arkeology adds semantic searchability, not replaces the repo |
| Tier 2 (session summaries, code reviews, impl notes) | **Remove from repo after migration** | These files pollute git history and the docs folder; their value is in being searchable, not in being in the repo |

This mirrors the three-tier model: code stays in git (tier 1/code), canonical decisions stay in
both git and Arkeology (tier 3 dual-write), working documents live only in Arkeology (tier 2
Arkeology only).

---

### Cross-cutting concerns

**Idempotency and re-runs**

Idempotent write semantics (D9, FR-08) mean the migration can be run multiple times safely.
For tier 3 artifacts (same type + title), re-migrating overwrites with the latest content —
correct, since they're living documents. For tier 2 artifacts (same type + title + date), if
the date comes from git log (creation date), re-running always produces the same key and
overwrites silently — also correct. The only risk is if the date strategy changes between runs
(e.g., first run uses git date, second run uses current date) — this would create a duplicate.
The migration manifest should record which date was used to prevent this.

**Git history availability**

If a repo has squashed history, a clean initial import commit, or was migrated from another
VCS, `git log` won't return meaningful creation dates. The fallback is current date for tier 2
(documents "when it was imported", not when it was originally written). This is acceptable —
search still works; the metadata just reflects migration time rather than original creation time.
The migration script should log when the date fallback was triggered.

**Description quality is the success criterion**

A migration that moves files into Arkeology with empty or low-quality descriptions is worse
than no migration. An agent searching for "authentication implementation decisions" that gets
back five results with descriptions like "Implementation notes for auth module" is not much
helped. The migration must invest in description quality — using LLM generation, not just
header extraction. Migrated descriptions should be reviewed for the highest-value tier 3 artifacts.

**Scale ceiling**

For very large projects (hundreds of markdown files), the Bedrock description generation cost
is still negligible (Titan Text Embeddings v2 per-call pricing). The bottleneck is agent
time (if agent-led) or script run time (if script-led). Script-based migration with async
Bedrock calls can process 100 files in under a minute.

**No new MCP server tools needed**

The existing `write_artifact` API is fully sufficient for migration — the question is entirely
about the workflow and tooling around it. Adding a migration-specific MCP tool would add
server complexity for a one-time operational concern. A skill + helper script is the right answer.

---

## Session 2026-05-30 — Decision record

Two corrections to the initial session that change the vehicle and structure of the migration
capability.

### C1 — SKILL.md is a cross-framework standard, not OpenCode-specific ✅

SKILL.md follows the https://agentskills.io/home standard and is recognised by all major
agentic coding IDEs: Claude Code, Codex, GitHub Copilot, and others. It is not tied to any
single tool. The initial session incorrectly framed skills as OpenCode-specific — this is
retracted. A migration skill ships without any framework lock-in.

### C2 — Migration is a one-time operation: AGENTS.md is the wrong vehicle ✅

AGENTS.md is loaded by every agent in every session. Placing migration instructions there would
permanently inject noise into all future sessions for a task that is done exactly once per
project. The candidate AGENTS.md snippet from the initial session is **withdrawn**.

A SKILL.md is the correct vehicle: the operator installs it, uses it once to perform the
migration, then uninstalls or ignores it. No permanent footprint in the project.

### Resolved decision — Migration skill ships with Arkeology ✅

The migration capability is delivered as a **skill bundled in the Arkeology repository**:

```
skills/migration/
  SKILL.md          # Structured workflow: discovery, classification, description, verification
  migrate.py        # Mechanical bulk operations: git dates, Bedrock descriptions, bulk writes
  schema.yaml       # ARKEOLOGY_IMPORT.yaml manifest schema
```

**Revised summary — key outputs for PM and architect**

| Concern | Recommended approach | Deliverable |
|---|---|---|
| Discovery | Skill instructs agent: directory allowlist + read ambiguous files | `SKILL.md` |
| Classification | Skill provides convention table; agent handles ambiguous files | `SKILL.md` |
| Description: ambiguous/high-value files | Agent reads file, writes description in-context | `SKILL.md` |
| Description: bulk clear-cut files | `migrate.py` calls Bedrock | `migrate.py` |
| Date recovery | `migrate.py` calls `git log` per file | `migrate.py` |
| Bulk `write_artifact` | `migrate.py` calls Arkeology write path directly | `migrate.py` |
| Manifest (large migrations) | Agent produces ARKEOLOGY_IMPORT.yaml, operator reviews | `SKILL.md` + `schema.yaml` |
| Verification | Skill instructs agent: `list_artifacts` + test searches | `SKILL.md` |
| AGENTS.md migration snippet | **Withdrawn** — wrong vehicle for a one-time operation | — |
| New MCP tools | None | No server changes |
| Post-migration: tier 3 | Keep in repo; open question on dual-write (see OQ3 below) | Policy in `SKILL.md` |
| Post-migration: tier 2 | Remove from repo after migration | Policy in `SKILL.md` |

**Resolved open questions**

### OQ1 — Skill installation: manual copy with per-IDE instructions ✅

Auto-detection of which IDE is in use is too fragile — skills folder locations change constantly
across Claude Code, Codex, Copilot, OpenCode, and others. The maintenance cost of a detection
script exceeds its value for a one-time installation.

Resolved approach: the Arkeology README documents the skills directory path for each supported
IDE in a single table, plus a simple `cp -r` one-liner. No detection script, no install command,
no breakage. A user installing a one-time migration skill can copy a folder once.

### OQ2 — migrate.py lives in `scripts/` inside the skill bundle ✅

Per the agentskills.io convention (https://agentskills.io/skill-creation/using-scripts),
bundled scripts live in a `scripts/` subdirectory of the skill and are referenced by relative
path from the skill root. The skill structure is:

```
skills/migration/
  SKILL.md
  scripts/
    migrate.py       # PEP 723 inline deps, run with: uv run scripts/migrate.py
  schema.yaml        # ARKEOLOGY_IMPORT.yaml manifest schema
```

`migrate.py` uses PEP 723 inline dependency declarations and is run with `uv run scripts/migrate.py`
— no separate install step, no venv management. This aligns with Arkeology's existing `uv` toolchain.

The script does not live in the Arkeology project repo itself — it lives only in the skill
bundle. Once the migration is done, the operator can uninstall the skill and the script goes
with it.

`migrate.py` follows agentskills.io script design guidelines:
- No interactive prompts — all inputs via CLI flags
- `--help` documents all flags and usage examples
- JSON structured output to stdout; progress and diagnostics to stderr
- `--dry-run` flag for preview before committing bulk writes
- Idempotent — safe to re-run; same manifest produces same artifact keys

### OQ3 — Post-migration: no deletion, no dual-write discipline ✅

Arkeology does not delete anything from the user's repo. The migration skill instructs the
agent to tell the operator which tier 2 files may be removed — the operator decides and acts.

After migration, the skill's final step updates the project's `AGENTS.md`: adding the
recommended Arkeology usage snippet (when to write artifacts, which types, how to write
descriptions) so that future agents use Arkeology going forward rather than committing docs
to the repo. This is the only post-migration write the skill makes to the project.

No dual-write discipline for tier 3 artifacts. Tier 3 files (ADRs, specs, plans) remain in the
repo as-is — they were already there and belong there. Arkeology adds searchability; it does
not replace the repo copy. The AGENTS.md guidance instructs future agents to write new tier 3
artifacts to Arkeology; updating existing tier 3 files in the repo is a separate human concern.

### OQ4 — V1 scope: migration skill ships with V1 ✅

Every new adopter faces this on their first day. The migration skill ships with V1 alongside
setup documentation.
