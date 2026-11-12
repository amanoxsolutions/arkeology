---
type: Spec
id: p9-t31a-setting-up-arkeology-skill
title: T31a — Setting-Up-Arkeology Skill
description: Spec for a 6-step agent-driven skill that validates AWS resources, writes the Arkeology MCP config entry for the chosen client, and records the setup in AGENTS.md.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/brainstorming/brainstorming-2026-06-02-setting-up-arkeology-skill.md
    title: Setting-Up-Arkeology Skill
    last_modified: 2026-06-07T00:00:00Z
  - resource: docs/brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md
    title: Multi-team / Multi-project Configuration
    last_modified: 2026-06-08T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
  - resource: https://code.claude.com/docs/en/mcp
  - resource: https://opencode.ai/docs/mcp-servers/
  - resource: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers
  - resource: https://learn.chatgpt.com/docs/extend/mcp?surface=cli
  - resource: docs/specs/p3-t15-partial-write-failure-log.md
    title: T15 — Partial Write Failure Log
    last_modified: 2026-11-10T17:12:26Z
  - resource: .docs/reviews/architecture-review-2026-11-10-arkeology.md
    title: Architecture review — Arkeology (whole design record)
    last_modified: 2026-11-10T11:21:17Z
  - resource: docs/architecture-decisions/adr-2026-05-29-aws-backend-selection.md
    title: AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend
    last_modified: 2026-11-12T13:11:40Z
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-index-mode.html
    title: Amazon S3 User Guide — Changing a vector index's mode
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_GetIndex.html
    title: Amazon S3 API Reference — GetIndex
  - resource: docs/specs/p15-t90-store-migration.md
    title: T90 — Store Migration Skill and Command
    last_modified: 2026-11-12T10:00:13Z
  - resource: docs/planning-artifacts/vision.md
    title: "Arkeology — Persistent Artifact Memory"
  - resource: .docs/reviews/architecture-review-2026-11-10-arkeology-recheck.md
    title: "Architecture review — Arkeology (whole design record), re-check of C-1 to C-3"
    last_modified: 2026-11-10T16:49:29Z
  - resource: .docs/review-fixes/calibration-2026-11-12.md
    title: "Calibration: is a filtered, paged QueryVectors (ENHANCED) an exhaustive per-artifact lookup?"
generated:
  by: "axians-architect/unknown"
  at: 2026-06-07T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-12T21:20:24Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T31a — Setting-Up-Arkeology Skill

## TL;DR

Create `skills/setting-up-arkeology/SKILL.md` — a 6-step agent-driven workflow that assumes all
required AWS resources are already provisioned externally, validates their reachability and that the
vector index runs in `ENHANCED` mode, writes a
complete and project-scoped Arkeology server entry into the correct MCP configuration file for the
chosen client (Claude Code, opencode, GitHub Copilot CLI, or OpenAI Codex), runs a health check,
and writes a machine-readable `arkeology:config` block plus a narrative usage snippet to the
project AGENTS.md. No Python code, no bundled scripts, no `.env` file, no AWS resource creation, no
IAM policy generation. The spec also covers how the throwaway probe objects that the skill's Step 2
connectivity check writes into the deployment's own `WRITE_PREFIX` are named, tagged and cleaned up, and
the orphan-scan exclusion in `src/arkeology/tools/reconcile.py` that keeps one from being mistaken
for an artifact.

## 1. Problem Statement

First-time Arkeology setup currently requires an operator to read README ops content,
manually substitute placeholders, and copy configuration into multiple files — with no
validation between steps and no record of the decisions made. A skill replaces that with
an agent-driven workflow that collects all resource identifiers upfront, validates that
every declared resource is actually reachable, writes the MCP client configuration, and
ends with two artefacts written to AGENTS.md: the `arkeology:config` block
(machine-readable, consumed by the migration skill and future agent sessions) and the
narrative usage snippet.

AWS resource creation, IAM policy generation, and IAM policy application are all
**out of scope** — the operator handles these using their existing AWS tooling and the
README's policy reference before running the skill. The skill's responsibility is
connection and configuration, not provisioning or access management.

Every user story behind these rules is P1, except re-running the skill to replace the
`arkeology:config` block in place (R20), which is P2.

## 2. Rules — Workflow

### R1 — Six steps; a failed step can be fixed and re-run without repeating earlier steps

The skill is a workflow of exactly 6 numbered steps, each a `##` section of `SKILL.md`. An
operator on a new project runs the skill and reaches a working Arkeology instance without
consulting the README. When a step fails (e.g. wrong region) and the operator fixes it and re-runs
that step, the skill continues without re-executing earlier steps.

**Example**

- Given a fresh environment where all required AWS resources are already provisioned, when the
  operator follows every skill step, then all declared resources are confirmed reachable, the
  Arkeology server entry with all env vars is written into the correct MCP config file for the
  chosen client, and `health_check` returns `"status": "ok"` for all components.

Source: none

## 3. Rules — Step 1: client detection and parameter collection

### R2 — Step 1 detects the MCP client from the project's existing config files

When the skill starts, before prompting for the client choice, it scans the project root for
recognised MCP client config files (`.mcp.json`, `.mcp.jsonc`, `opencode.json`,
`.codex/config.toml`, `.vscode/mcp.json`):

| Files found in the project root | The skill |
|---|---|
| Exactly one (e.g. `.mcp.json`) | Presents it as the detected client — the file and its associated client as the default — and asks the operator to confirm, rather than presenting an open-ended choice |
| Multiple (e.g. both `opencode.json` and `.vscode/mcp.json`) | Lists each detected file with its associated client name and asks the operator to select one |
| None | Presents the full list of supported clients with a brief description and asks the operator to choose |

When `.mcp.json` is detected, the skill notes that it is compatible with both Claude Code and
GitHub Copilot CLI simultaneously.

**Why:** an operator running the skill should not need to know which config file format their
client uses — the skill detects it from what is already in the project.

Source: none

### R3 — Step 1 collects every remaining parameter before any action

When the skill starts, it collects all remaining required parameters before any action is taken:
AWS region, S3 artifact bucket name, S3 Vectors bucket name, S3 Vectors index name, embedding
model (default `amazon.titan-embed-text-v2:0`), embedding dimension (default 1024), AWS profile,
team name, project name, and optional `READ_PREFIXES`. Step 1 lists every remaining required
parameter with its default where applicable; no IAM principal ARN is collected (no provisioning
or IAM steps).

Source: none

## 4. Rules — Steps 2 and 3: pre-flight and install

### R4 — Step 2 confirms every declared resource is reachable, and any failure is a hard stop

The skill validates that every declared resource is reachable before writing any configuration
file. When Step 2 runs, it validates five things: AWS credentials are active
(`aws sts get-caller-identity`), `uv` is installed, the declared S3 bucket is reachable
(`s3api head-bucket`), the declared Vectors index is reachable (`s3vectors get-index`), and
the declared Bedrock embedding model is accessible (`bedrock invoke-model` with a minimal
payload). When any Step 2 check fails, the skill stops immediately with a message identifying
which resource is unreachable — no subsequent steps are executed. When all declared resources are
reachable, Step 2 completes and the skill proceeds to Step 3. Step 2 contains no AWS resource
creation commands.

**Example**

- Given a declared S3 bucket that does not exist or is inaccessible, when Step 2 runs, then the
  skill stops and tells the operator which resource failed and why — no config file is written.
- Given a declared Vectors index that does not exist, when Step 2 runs, then the skill stops with
  a clear error identifying the missing index.
- Given an embedding model that is not enabled in the operator's region, when Step 2 runs, then
  the skill stops and instructs the operator to enable the model in the Bedrock console before
  proceeding.

Source: none

### R5 — Step 3 is clone and `uv sync` only

Step 3 is clone and `uv sync` only — no IAM policy step follows it.

Source: none

### R27 — Step 2 also confirms the vector index runs in `ENHANCED` mode, and stops with the switch command when it does not

When Step 2 checks the declared Vectors index, it also reads the index's mode from the same response
(`aws s3vectors get-index --vector-bucket-name <bucket> --index-name <index>`, field `indexMode`).
When the mode is not `ENHANCED` — `CLASSIC`, or not reported — Step 2 fails like any other Step 2
check: the skill stops before writing any configuration file and shows the Admin
`aws s3vectors update-index-mode --vector-bucket-name <bucket> --index-name <index> --index-mode ENHANCED`,
stating that the switch takes effect in place with no re-ingestion and no additional charge, that
an index other teams share changes for their servers too, and that it must not be switched back
while any server uses it. The skill does not run the command itself — Step 2 contains no command
that changes an AWS resource — and the Admin re-runs Step 2 once the switch is made. When the
operator is about to create a new index, the skill states that a vector bucket created on or after
30 September 2026 creates `ENHANCED` indexes, and that an index created in an older bucket starts
`CLASSIC` unless the bucket's default index mode has been set to `ENHANCED`.

**Why (The server refuses a `CLASSIC` index):** The server's scoped searches and its store-shape
check are filtered queries, which find what their filters match only on an `ENHANCED` index —
measured on real AWS, filtered queries on `CLASSIC` lost vectors even for artifacts of 10 or fewer
vectors — so the server refuses to start on any other (`p1-t5-startup-validation-sequence.md` R12).
Catching the mode here gives the operator the fix before a config entry is written, rather than a
server that will not start at Step 5.

**Example**

- Given a declared Vectors index in `CLASSIC` mode, when Step 2 runs, then the skill stops, names
  the index and its mode, shows the `update-index-mode` command, and writes no config file.
- Given a declared Vectors index in `ENHANCED` mode, when Step 2 runs, then the mode check passes
  and the remaining Step 2 checks run.

Source: NFR-03; adr-2026-05-29-aws-backend-selection; the calibration of 2026-11-12 (`.docs/review-fixes/calibration-2026-11-12.md`)

### R30 — For a new deployment, Step 2 has the Admin apply the write-fence statement before the probe's first write

WHEN Step 2 runs for a deployment set up on this release — a write prefix no server has written
yet, as the operator confirms — THE SYSTEM SHALL, before the annotation probe writes, show the
Admin the write-fence statement T90 R39 defines, built from the `ARTIFACT_BUCKET` and `WRITE_PREFIX`
collected in Step 1, with T90 R39's instruction to add this prefix's resource to an existing
statement with the same `Sid` rather than add a second one, and wait for the operator to say it is
applied. The annotation probe (R29) then writes under the fence, and its tagged write landing shows
that the statement admits this release's writes. A write prefix already in use gets no statement
from this step: the store migration fences it (T90 R39), or an earlier setup on this release did.
The skill never reads, writes or applies the bucket policy.

**Why:** an install of an earlier release configured with a new deployment's write prefix would
overwrite artifacts this release writes and wipe their annotations — the loss the fence prevents on
a migrated store — and no migration runs on a new deployment to print the statement. Applied before
the first write, the fence leaves no artifact under the prefix unprotected.

**Example**

- Given a new deployment's write prefix that no statement covers, when Step 2 runs, then the skill
  shows the statement with the resource `arn:aws:s3:::<ARTIFACT_BUCKET>/<WRITE_PREFIX>/*`, and the
  annotation probe runs only after the operator says it is applied.
- Given a write prefix already in use, when Step 2 runs, then the skill shows no statement and the
  annotation probe runs as before.

Source: NFR-16; T90 R38, R39; a deployment set up on this release is fenced too (Operator, 2026-11-12)

## 5. Rules — Step 4: the MCP config entry

### R6 — The Step 4 reference table fixes each client's file, scope, keys and docs URL

Step 4 contains this client reference table — all 6 rows, a "Config scope" column distinguishing
project vs global for each client, and an "Official docs URL" column with the correct URL for each
client:

| Client | Config scope | File(s) to check | Top-level key | Env vars key | Official docs URL |
|--------|-------------|-----------------|---------------|--------------|-------------------|
| Claude Code | Project | `.mcp.json`, `.mcp.jsonc` (workspace root) | `mcpServers` | `env` | https://docs.anthropic.com/en/docs/claude-code/mcp |
| Claude Desktop | Global | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) · `%APPDATA%\Claude\claude_desktop_config.json` (Windows) | `mcpServers` | `env` | https://docs.anthropic.com/en/docs/claude-code/mcp |
| opencode | Project | `opencode.json` (workspace root) | `mcp` | `environment` ⚠ | https://opencode.ai/docs/mcp-servers/ |
| VS Code + Copilot Chat | Project | `.vscode/mcp.json` (workspace root) | `servers` | `env` | https://code.visualstudio.com/docs/copilot/chat/mcp-servers |
| Copilot CLI | Project | `.mcp.json` (workspace root, **shared with Claude Code**) | `mcpServers` | `env` | https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers |
| Codex CLI | Project | `.codex/config.toml` (workspace root) | `[mcp_servers.arkeology]` | `[mcp_servers.arkeology.env]` | https://developers.openai.com/codex/mcp |

Key notes on the table:
- `.mcp.json` at the workspace root is read by **both Claude Code and Copilot CLI** — one file
  serves both clients simultaneously. Use `mcpServers` as the top-level key; `servers` is NOT
  recognised by Copilot CLI.
- opencode uses `environment` (not `env`) — this is different from every other client. ⚠
- VS Code + Copilot Chat uses `servers` (not `mcpServers`) — this is different from every other
  client.
- Copilot CLI traverses from the working directory up to the git root (v1.0.11+), covering
  monorepo setups. Note: Copilot CLI itself also reads `~/.copilot/mcp-config.json` as a
  merge layer — this is a Copilot CLI behaviour independent of anything the skill writes; the
  skill writes only to `.mcp.json` in the project root and never touches the global file.
- Codex CLI project config requires the project to be explicitly trusted.

In the table as shown in Step 4: `.mcp.json`/`.mcp.jsonc` for Claude Code (project root);
`opencode.json` (no dot prefix) for opencode (project root) — NOT the global
`~/.config/opencode/opencode.json`; `environment` (not `env`) called out as the opencode env vars
key with a visible warning (e.g. ⚠ or bold); `.codex/config.toml` for Codex CLI (project root)
with a "trusted projects only" note; `.mcp.json` for Copilot CLI (project scope, shared with
Claude Code) with a note to use the `mcpServers` key (not `servers`) and add `"tools": ["*"]`; and
a note that `.mcp.json` serves both Claude Code and Copilot CLI simultaneously.

Source: none

### R7 — The entry carries every required env var, fully populated

When Step 4 runs, the skill writes the Arkeology server entry — including all required env vars
(`AWS_REGION`, `ARTIFACT_BUCKET`, `VECTORS_BUCKET`, `VECTORS_INDEX`, `WRITE_PREFIX`,
`BEDROCK_EMBEDDING_MODEL`, and any optional vars collected in Step 1) — into the correct config
file and at the correct key path for the chosen client, as the Step 4 reference table specifies.
Step 4 shows the complete Arkeology entry format for each client, with all required env vars
populated (no `YOUR-*` placeholders).

Source: none

### R8 — Every supported client gets a project-scoped config file

When Step 4 runs, the skill writes to a project-scoped config file for all four supported
clients: `.mcp.json` or `.mcp.jsonc` for Claude Code and GitHub Copilot CLI (shared file);
`opencode.json` for opencode; `.codex/config.toml` for Codex CLI. All four clients support
per-project config — no global-only fallback is required for any supported client — so the
`WRITE_PREFIX` fence is automatically per-project for every supported client. For GitHub Copilot
CLI the entry lands in `.mcp.json` at the workspace root (shared with Claude Code, supported since
v0.0.401), under the server name `arkeology`. When Step 4 targets a `.mcp.json` file, the skill
informs the operator that this file is read by both Claude Code and GitHub Copilot CLI
simultaneously, so one file covers both clients.

**Example**

- Given a client that supports a project-scoped config file (Claude Code, opencode, Codex CLI),
  when Step 4 writes the Arkeology entry, then it is written to the project-level file
  (`.mcp.json`, `opencode.json`, or `.codex/config.toml` respectively) — the user's global MCP
  client config is not modified.
- Given GitHub Copilot CLI, when Step 4 writes the Arkeology entry for each project, then it is
  written to that project's own `.mcp.json` at its workspace root, under the server name
  `arkeology` and with the correct `WRITE_PREFIX` — the same file and server name used by Claude
  Code; no global `~/.copilot/mcp-config.json` is modified.
- Given a developer who completed the skill for project A (with its own `WRITE_PREFIX`) and
  subsequently runs the skill for project B (with a different `WRITE_PREFIX`), when the skill
  completes for project B, then project B has its own project-scoped config file with the correct
  `WRITE_PREFIX`, and the project A config file is unchanged.

**Why:** a developer with multiple projects on their machine, each using Arkeology with a
different `WRITE_PREFIX`, never edits their global MCP client config when switching between
projects.

Source: none

### R9 — A missing project-scoped file is created under its documented name

Step 4 checks whether the target file exists: if yes, it parses and inserts; if no, it creates the
file with the correct filename. When Step 4 targets a project-scoped file that does not yet exist,
it creates it: `.mcp.json` for Claude Code; `opencode.json` (no dot prefix — this is the
officially documented project config name) for opencode; `.codex/config.toml` (creating the
`.codex/` directory if absent) for Codex CLI.

Source: none

### R10 — An existing JSON/JSONC file gets a structured insert

When Step 4 targets a config file that already exists and uses JSON or JSONC format, the skill
parses the existing file (stripping comment tokens for JSONC), inserts the `arkeology` entry at
the correct top-level key, and writes the complete updated structure back — it does not append raw
text or replace the file with only the Arkeology entry. All other existing MCP server entries in
the file are preserved unchanged.

Source: none

### R11 — An existing TOML file gets appended sections, and an existing Arkeology section is overwritten only on confirmation

When Step 4 targets a config file that already exists and uses TOML format, the skill appends the
`[mcp_servers.arkeology]` and `[mcp_servers.arkeology.env]` sections to the end of the file — it
does not modify any existing section. When Step 4 targets a TOML file that already contains a
`[mcp_servers.arkeology]` section, the skill shows the existing entry to the operator and asks
for confirmation before overwriting it.

Source: none

### R12 — opencode and Copilot CLI entries take their client's own shape

When Step 4 targets an opencode config, the skill uses `environment` as the key for the
environment variable block (not `env`) and includes `"command"` as a JSON array (e.g.
`["uvx", "arkeology"]`). When Step 4 targets a GitHub Copilot CLI config, the skill uses
`arkeology` as the MCP server name (same as all other clients) and includes `"tools": ["*"]` in
the entry; it uses `mcpServers` as the top-level key — NOT `servers`, which is not recognised by
Copilot CLI.

Source: none

### R13 — Codex CLI project config needs a trusted project

When Step 4 targets a Codex CLI project config, the skill informs the operator that
project-scoped Codex config only loads for trusted projects. If the operator declines to trust the
project, the skill displays the complete config entry for manual addition and proceeds to Step 5
— it does not write to `~/.codex/config.toml` or any other home-directory path.

Source: none

### R14 — The skill shows the entry and asks permission before modifying an existing file

Whenever Step 4 presents the config entry to the operator, it includes the official documentation
URL for the chosen client's MCP configuration (from the reference table) so the operator can
independently verify the format. When the target config file already exists, the skill shows the
operator the entry it plans to write and asks explicit permission before modifying the file. When
the operator grants permission, the skill inserts the Arkeology entry into the existing config,
preserving all other entries unchanged. When the operator declines permission, the skill displays
the complete correctly-formatted config entry for the operator to add manually and proceeds to
Step 5 without writing.

**Example**

- Given any IDE config file that already exists, when Step 4 is reached, then the skill shows the
  operator the Arkeology entry it plans to add and asks explicit permission before writing.
- Given an existing config file that already contains an Arkeology entry (re-run), when Step 4 is
  reached, then the skill shows the new entry and asks permission to update the existing one in
  place.
- Given an operator who declines permission, when Step 4 is reached, then the skill displays the
  complete config entry for the operator to add manually and continues without writing.
- Given any IDE config file, when the skill writes to it, then all other existing MCP server
  entries in the file are preserved unchanged.

**Why:** some IDE config files (OpenCode, Claude Desktop, Copilot CLI, Codex CLI) are user-level
and may already contain entries for other MCP servers; the skill must never silently overwrite
them.

Source: none

### R15 — Step 4 writes only inside the project root (Claude Desktop excepted), and never falls back to a global file

When any configuration file write occurs during Step 4, the skill writes only to a file in the
current working directory (the project root); it never reads from or writes to any home-directory
path — including `~/.config/opencode/`, `~/.codex/`, `~/.copilot/`, or any equivalent —
regardless of operator instruction. The sole exception is Claude Desktop (no per-project config
exists): the skill writes to its platform config path only when the operator explicitly chose
Claude Desktop as their client in Step 1. If an operator declines or is unable to use a
project-scoped file, the skill displays the complete entry for manual addition and proceeds to
Step 5 — it does not fall back to any global configuration file as a substitute write target.

Source: none

## 6. Rules — Step 5: health check

### R16 — Step 5 blocks until every component reports ok

When Step 5 runs, the skill calls `health_check` and blocks until all components return
`"status": "ok"` before proceeding to Step 6 — it blocks on anything other than all-ok.

Source: none

## 7. Rules — Step 6: the AGENTS.md config block and snippet

### R17 — Git-only ADR strategy auto-detects the ADR folder

When the git-only ADR strategy is chosen, the skill scans for ADR directories using the
recognised ADR directory name list (included in Step 6A), presents the result to the operator, and
asks for the path if none is found or multiple are found:

| Recognised ADR directories in the repository | The skill |
|---|---|
| Exactly one (`docs/adr/`) | Presents the detected path and asks for confirmation before adding it — the operator does not need to type the path |
| None | Asks the operator to provide the path |
| Multiple candidates | Lists all candidates and asks the operator to select one |

Source: none

### R18 — Additional exclusion paths get an inferred type on confirmation

When additional exclusion paths are provided, the skill attempts to infer an artifact type for
each using the migration skill's Pass 2 path-segment table, presents the inferences to the
operator for confirmation, and adds confirmed types to `local_only_types`. A path that maps to no
known type still appears in `local_only_paths`, with no new entry added to `local_only_types`.

**Example**

- Given an operator who provides additional exclusion paths, when type inference succeeds (e.g.
  `docs/specs/` → `spec`), then the inferred type is added to `local_only_types` after the
  operator confirms.
- Given an operator who provides a path that maps to no known type (e.g. `docs/internal/`), when
  Step 6 completes, then the path appears in `local_only_paths` but no new entry is added to
  `local_only_types`.

Source: none

### R19 — Step 6 writes the `arkeology:config` block with all exclusion decisions

Step 6 has two labelled parts (A: ADR strategy, B: additional exclusions) plus a final
config-block write instruction. When Step 6 completes, the skill writes a `<!-- arkeology:config`
block to AGENTS.md containing `installed` (ISO-8601 date), `adr_strategy`, `local_only_types`
(list, may be empty), and `local_only_paths` (list, may be empty). Step 6 includes this exact
block YAML structure with all four keys.

**Example**

- Given an operator who chooses git-only ADR strategy and the skill detects `docs/adr/`, when
  Step 6 completes, then AGENTS.md contains a `<!-- arkeology:config` block with
  `adr_strategy: git-only`, `local_only_types: [adr]`, and `local_only_paths: [docs/adr/]`.
- Given an operator who chooses arkeology-only ADR strategy, when Step 6 completes, then the
  block contains `adr_strategy: arkeology-only` and no `adr` entry in `local_only_types` or
  `local_only_paths`.

Source: none

### R20 — Re-running the skill replaces the config block in place

When a `<!-- arkeology:config` block already exists in AGENTS.md, the skill replaces it in place;
no second block is appended.

**Example**

- Given AGENTS.md already contains a `arkeology:config` block, when the operator re-runs the
  skill and provides new exclusion answers, then the existing block is replaced and no second
  block appears in the file.

Source: none

### R21 — Step 6 writes the narrative snippet variant matching the ADR strategy

When Step 6 completes, the skill writes the narrative AGENTS.md snippet from
`references/agents-snippet.md` to the project AGENTS.md, using the ADR variant matching the
operator's strategy choice; Step 6 instructs the agent to load and apply
`references/agents-snippet.md`. When the `SKILL.md` line count exceeds 500, the narrative snippet
stays in `references/agents-snippet.md` and is loaded in Step 6. `references/agents-snippet.md`
contains: the standing never-write instruction referencing `local_only_types` and
`local_only_paths` from the `arkeology:config` block; Variant A (git-only ADR) and Variant B
(arkeology-only ADR), clearly labelled so Step 6 can select the correct one; and when-to-write
guidance, the artifact type table, description quality guidance, tier 2 vs tier 3 selection,
query strategy, synthesis guidance, and a pointer to MCP Resources.

Source: none

### R26 — The snippet tells an agent running in a pipeline to reconcile before its job ends

WHEN Step 6 writes the narrative snippet THE SYSTEM SHALL include, in
`references/agents-snippet.md` and outside both ADR variants, an instruction for an agent running
in a CI/CD pipeline: whenever any Arkeology call in the job returned `failure_logged: true`, call
`reconcile_index` before the job ends, and fail the job, quoting the response, if that call itself
returns an error — `credential_error` or any other — or if any artifact those calls named is still
listed in its `failed` or `stuck_failures`; whenever a call returned `failure_logged: false`, fail
the job and quote the response, since no entry exists for `reconcile_index` to replay. Before a job
fails for any of these reasons, the agent keeps the entries it could not resolve (R28).

**Example**

- Given a pipeline agent whose write returned `partial_write` with `failure_logged: true`, when it
  reaches the end of its job, then it has called `reconcile_index` first, and the job fails if that
  artifact is still listed in `failed` or `stuck_failures`.
- Given the same agent whose end-of-job `reconcile_index` returns `credential_error`, when the job
  ends, then it has failed, quoting that response.

**Why:** the failure log sits in the per-user state directory of the host that ran the server
(T15 R7). On a pipeline runner that host is discarded when the job ends, and with it the only copy
of any annotations a failed restore left in the log; no later `reconcile_index` run can reach it.
A `reconcile_index` call that returns an error has resolved nothing, so it fails the job exactly as
an artifact still listed in `failed` does.

Source: NFR-11; T15 R7, R11

### R28 — A pipeline job that fails on an unresolved entry keeps that entry in a restricted job artifact, never in its log output

WHEN the R26 instruction fails a job THE SYSTEM SHALL have the snippet instruct the agent, before
the job ends, to write to `arkeology-recovery.jsonl` in the job's working directory — never printed
to the job's log output, never staged or committed — every line of the server's failure log whose
`artifact_id` is one the failing calls named. A call that returned `failure_logged: false` has no
entry to keep: the server's ERROR line names only the artifact and the failed step (T15 R4), and the
job's quoted response already names them (R26). The failure log is the file the server resolved at startup and logged at INFO (T15 R7,
R9): `FAILURE_LOG_PATH` when set, otherwise the per-bucket default,
`$XDG_STATE_HOME/arkeology/<ARTIFACT_BUCKET>/failures.jsonl` or
`~/.local/state/arkeology/<ARTIFACT_BUCKET>/failures.jsonl`. The snippet tells the team that owns
the pipeline that the job must keep `arkeology-recovery.jsonl` as a job artifact whenever it fails,
with access limited, as far as the CI system allows, to the people allowed to read the store. It
also states the recovery, which is the one-time procedure T15 R10 gives
for an old log: with every Arkeology server that uses the target log stopped, append the kept
entries to the failure log of a server configured with the same artifact bucket and write prefix,
then run `reconcile_index` from that server.

**Example**

- Given a pipeline agent whose update returned `partial_write` with `failure_logged: true` and whose
  end-of-job `reconcile_index` returned `credential_error`, when the job ends, then it has failed,
  `arkeology-recovery.jsonl` holds that artifact's failure-log line, and the job's log output holds
  the quoted response but not the line.
- Given a call that returned `failure_logged: false`, when the job ends, then it has failed, quoting
  the response, and `arkeology-recovery.jsonl` holds no line for that call, since no entry exists.
- Given the kept entries, when an operator follows T15 R10's procedure with a server configured with
  the same artifact bucket and write prefix, then that server's `reconcile_index` replays them as it
  replays any other entry of its own.

**Why:** a `reconcile_index` that failed on the runner has replayed nothing, so the artifact can
only be restored by a run elsewhere, and that run needs the entries themselves — quoting the
response saves only the artifact's id. The entries carry the artifact's links, revision history and
verifications, and the vision rates the store's data as sensitive (`vision.md` § Operating Context,
"Data sensitivity"). A job's log output is often readable more widely than the store and is kept by
the CI system on its own terms, so the entries go into a job artifact whose access the team sets,
never into the log. Some CI systems cannot restrict a job artifact below the repository's readers:
on GitHub Actions anyone with read access to the repository can download a run's artifacts. That
exposure is accepted. The kept entries hold artifact ids and titles, link targets, commit SHAs, and
who revised or verified an artifact and when — never artifact content.

Source: NFR-11; T15 R4, R7, R9, R10; vision.md § Operating Context; the job artifact's exposure to the repository's readers (Operator, 2026-11-10)

## 8. Rules — Connectivity probe objects

The Step 2 annotation probe writes a real object into the deployment's own `WRITE_PREFIX`.
Whether or not the probe succeeds, that object must be gone by the end of the step, and
`reconcile_index` must never treat one that survives as an artifact. Because a migrated write
prefix refuses every object write that lacks the store-schema tag, the probe's object write
carries it (R29).

### R22 — A probe object is named with the reserved `_arkeology_` marker

When a Step 2 check writes a throwaway probe object into the deployment's own `WRITE_PREFIX`, the
skill names it with the reserved non-artifact marker `_arkeology_<purpose>_probe` as the key's
final path segment — the annotation probe's key is `<WRITE_PREFIX>/_arkeology_annotation_probe`,
matching the existing `_arkeology_health_probe` (`tools/health.py`) and
`_arkeology_startup_probe` (`startup.py`) keys. Step 2's annotation probe writes only
`<WRITE_PREFIX>/_arkeology_annotation_probe`. No artifact identifier can collide with this
marker: every generated identifier starts with a type slug drawn from `ARTIFACT_TYPES`.

Source: none

### R23 — The aws-cli probe cleanup runs on every outcome

When the aws-cli annotation-probe path runs, the skill presents the annotation delete and the
object delete as an explicit always-run cleanup step that executes on every outcome — success,
`ANNOTATIONS_FAILED`, `AccessDenied`, or any other error — mirroring the boto3 path's `finally:`
block, and states that the agent must run it even when an earlier command in the sequence failed.

**Example**

- Given the aws-cli probe path and a bucket/IAM configuration that makes `put-object-annotation`
  fail with `AccessDenied`, when the probe runs, then the probe object and any annotation written
  on it are still deleted before the step reports its result — the cleanup commands are presented
  as an always-run step, not as the tail of a sequence that an agent abandons at the first
  failure.
- Given the boto3 probe path, when any step raises, then the probe object is still deleted (the
  existing `finally:` block) — behaviour unchanged.

Source: none

### R24 — A failed cleanup is reported with the key and the command to remove it

When a probe cleanup delete itself fails, the skill reports the orphaned key and the exact command
to remove it to the operator rather than continuing silently.

**Example**

- Given a probe object that survives anyway (e.g. the cleanup delete itself is denied), when the
  step reports, then the operator is told the exact key left behind and the command to remove it.

Source: none

### R25 — `reconcile_index`'s orphan scan excludes every own-scope key whose final path segment begins with `_arkeology_`

When `reconcile_index` builds its orphan-scan candidate list, it excludes every own-scope S3 key
whose final path segment begins with `_arkeology_`, replacing the two hard-coded probe-name checks
it applies today — so the setup, health, startup, and any future probe key are all excluded by one
rule rather than each needing its own patch. Excluded keys are not re-indexed, counted as orphans,
or named in the reconcile response.

**Example**

- Given a `<WRITE_PREFIX>/_arkeology_annotation_probe` object present in S3 with no vectors
  indexed for it, when `reconcile_index` runs, then it is not counted as an orphan, not
  re-indexed, and does not appear anywhere in the reconcile response.
- Given that same probe object alongside a genuinely orphaned artifact, when `reconcile_index`
  runs, then the real orphan is still found and re-indexed — the exclusion filters the probe only.
- Given the existing `_arkeology_health_probe` and `_arkeology_startup_probe` keys, when
  `reconcile_index` runs, then they remain excluded exactly as before.

Source: none

### R29 — The probe's object write carries the store-schema tag on both probe paths

WHEN Step 2's annotation probe writes `<WRITE_PREFIX>/_arkeology_annotation_probe` THE SYSTEM SHALL
send the object tag `arkeology-store-schema` with the value `2` (T90 R38) on that write: the
aws-cli path passes `--tagging 'arkeology-store-schema=2'` to `aws s3api put-object`, and the boto3
path passes `Tagging="arkeology-store-schema=2"` to `put_object`. WHEN that object write is refused
with `AccessDenied` THE SYSTEM SHALL stop Step 2 (R4) with a message that names `s3:PutObject` and
`s3:PutObjectTagging` on the write prefix — S3 requires both to write an object with a tag — and
states that a bucket-policy write fence requiring a newer store schema refuses the write as well,
rather than the message for a missing annotation permission. The probe's cleanup (R23, R24) is
unchanged.

**Example**

- Given a write prefix covered by T90 R39's write-fence statement and a role holding the core S3
  actions, `s3:PutObjectTagging` and the four annotation actions, when Step 2's annotation probe
  runs on either path, then the probe object lands, the probe prints `ANNOTATIONS_OK`, and the
  cleanup deletes the object.
- Given the same prefix and a role without `s3:PutObjectTagging`, when the probe runs, then Step 2
  stops with the message naming `s3:PutObject` and `s3:PutObjectTagging`, the cleanup still runs,
  and no config file is written.

**Why:** the write-fence statement a migrated prefix keeps for good (T90 R39) refuses every
`PutObject` under the prefix that does not send this tag. An untagged probe is therefore refused on
every setup against a migrated prefix — each new team member, machine or pipeline runner — and R4
stops setup with an `AccessDenied` that sends the Admin looking for an IAM grant that is not
missing. The probe is the one object write this skill makes, and it is made outside the server, so
the server's S3 client cannot tag it. On a prefix no fence covers, the tag changes nothing but the
permission it needs, which the server's own startup write probe needs as well (T90 R41).

Source: NFR-16; T90 R38, R39, R41; adr-2026-09-25-okf-v02-adoption § 9

## 9. Boundaries

**Always:**
- No bundled scripts — all agent actions are CLI commands or file writes.
- No `.env` file — all Arkeology environment variables are passed via the MCP client's
  config file env block.
- No AWS resource creation of any kind.
- No IAM policy generation — the README provides a static reference policy with
  `YOUR-*` placeholders; the skill never emits a policy document, except R30's write-fence
  bucket-policy statement.
- All parameter collection happens in Step 1 before any validation or AWS calls. Step 1
  always starts with the project-root scan for existing config files before asking any
  other questions.
- Step 6 is always the last step; the health check (Step 5) must pass before Step 6 runs.
- `local_only_types` and `local_only_paths` may both be empty lists — the config block
  is still written.
- The config block format is YAML inside an HTML comment:
  `<!-- arkeology:config\n<yaml>\n-->` — opening and closing tags each on their own line.
- Path syntax: trailing `/` = directory tree; no trailing `/` = exact file; no globs.
- The `SKILL.md` must be ≤ 500 lines — with the shipped file's connectivity probes as a
  standing exception; do not delete probe content to meet the count.
- The skill is compatible with Claude Code, opencode, GitHub Copilot CLI, and Codex CLI —
  client differences are confined to the reference table in Step 4.
- The files scanned for auto-detection in Step 1 are: `.mcp.json`, `.mcp.jsonc`
  (Claude Code + Copilot CLI — shared file); `opencode.json` (opencode);
  `.codex/config.toml` (Codex CLI); `.vscode/mcp.json` (VS Code + Copilot Chat).
  Note that `.mcp.json` is the only file shared by two clients; detecting it does not
  require the operator to choose between them — the same file serves both.
- For JSON/JSONC config files: the agent reads the existing file, parses the JSON
  (stripping comment tokens for JSONC), inserts the Arkeology entry at the correct key, then
  writes the complete updated JSON object back. This is always a structured insert, never
  a raw text append.
- For TOML config files: the agent appends the new `[mcp_servers.arkeology]` and
  `[mcp_servers.arkeology.env]` sections to the end of the existing file without touching
  any other section.
- Per-project config files (`.mcp.json`, `opencode.json`, `.codex/config.toml`) are
  the preferred write targets for the three clients that support them; the user's global
  MCP client config is never written to or modified during a project installation.
- Any object a check writes into `WRITE_PREFIX` is a throwaway probe named
  `_arkeology_<purpose>_probe`, carries the store-schema tag `arkeology-store-schema=2` (R29), is
  deleted by an always-run cleanup step, and is excluded from `reconcile_index`'s orphan scan by
  the `_arkeology_` marker.

**Ask First:**
- Before writing to or modifying any MCP config file — show the entry to be added and
  ask explicit permission. This applies on every run, including re-runs.
- Before overwriting an existing `[mcp_servers.arkeology]` section in a TOML file — show
  the existing entry and ask explicit confirmation.

**Never:**
- Do not write a `.env` file.
- Do not create any AWS resource.
- Do not generate, emit, or substitute values into any IAM policy document — refer the
  operator to the README's policy reference section. R30's write-fence bucket-policy statement is
  the one exception.
- Do not proceed past Step 5 if `health_check` reports any component as errored.
- Do not overwrite or delete existing MCP server entries in any config file — merge only.
- Do not replace a config file wholesale with only the Arkeology entry — always insert
  into the existing structure.
- Do not write to any home-directory path (`~/.config/`, `~/.codex/`, `~/.copilot/`,
  or any equivalent) during a project installation. This prohibition is absolute and
  holds even if the operator explicitly requests it — redirect them to manual addition
  instead. The sole exception is Claude Desktop's platform config file, and only when
  the operator explicitly chose Claude Desktop as their client in Step 1.
- Do not fall back to a global config file when an operator declines a project-scoped
  write (e.g. declining Codex project trust) — always redirect to manual addition.
- Do not embed the full narrative snippet inline if it would push `SKILL.md` over 500
  lines — keep it in `references/agents-snippet.md`.
- Do not write a probe object anywhere other than under the deployment's own
  `WRITE_PREFIX`, and do not leave one behind — the cleanup runs on the failure paths the
  probe exists to detect, not only on success.
- Do not add a third hard-coded probe name to `reconcile.py`'s orphan scan — the
  `_arkeology_` final-segment marker replaces the per-name checks so the next probe needs
  no code change.

## 10. For the developer agent

### Files to Touch

Skills live in `plugins/arkeology/skills/<name>/` — the canonical (and only) location, with no
top-level `skills/` directory and no symlinks.

| File | Action | Notes |
|------|--------|-------|
| `plugins/arkeology/skills/setting-up-arkeology/SKILL.md` | Create | 6-step workflow; ≤ 500 lines, probes excepted |
| `plugins/arkeology/skills/setting-up-arkeology/references/agents-snippet.md` | Create | Full narrative AGENTS.md snippet; both ADR variants; standing never-write instruction |

**Probe cleanup + orphan-scan exclusion:**

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_reconcile.py` | Modify | Red first: `_arkeology_annotation_probe` key excluded from the orphan scan and absent from the response; a real orphan alongside it is still re-indexed; the existing health/startup probe exclusion tests still pass under the generalised rule |
| `src/arkeology/tools/reconcile.py` | Modify | Phase 2 orphan scan (the `own_keys` comprehension in `reconcile_index`): replace the two `"_arkeology_health_probe" not in k` / `"_arkeology_startup_probe" not in k` checks with one final-path-segment `_arkeology_` marker check |
| `plugins/arkeology/skills/setting-up-arkeology/SKILL.md` | Modify | Step 2 annotation probe, aws-cli (`native`) branch of Check 8: make the annotation delete + object delete an explicit always-run cleanup step covering the `AccessDenied` path; report the key and delete command if cleanup itself fails. The boto3 (`fallback`) branch already cleans up in `finally:` — leave it |

**Pipeline reconcile instruction (R26, R28):**

| File | Action | Notes |
|------|--------|-------|
| `plugins/arkeology/skills/setting-up-arkeology/references/agents-snippet.md` | Modify | Add R26's and R28's instruction as a short pipeline subsection outside both ADR variants: fail the job on a `reconcile_index` error as well as on an artifact left in `failed`/`stuck_failures` or any `failure_logged: false`; before failing, write the named entries to `arkeology-recovery.jsonl`, never to the job's log output or a commit; the note to the pipeline's owners that the job keeps that file as a job artifact with access limited to those allowed to read the store; and the recovery by T15 R10's procedure. Lands with T15's `failure_logged` and per-bucket log path |

**Store-schema tag on the probe write (R29) and the new deployment's write fence (R30) — lands with T90's tag:**

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_skill_store_schema_tag_drift.py` | Create | Red first: extracts the tag that Step 2's annotation probe sends from the shipped `SKILL.md` — the aws-cli `put-object`'s `--tagging` and the boto3 `put_object`'s `Tagging` — and asserts each equals the key and value T90 adds to `constants.py`; likewise the `Sid`, tag key and value in the write-fence statement Step 2 shows (R30) |
| `plugins/arkeology/skills/setting-up-arkeology/SKILL.md` | Modify | Step 2 annotation probe, both branches of Check 8: the probe object's write sends `arkeology-store-schema=2`; a refused probe object write gets its own interpretation, naming `s3:PutObject`, `s3:PutObjectTagging` and the write fence, apart from the annotation `AccessDenied` one. T90's row for this file adds `s3:PutObjectTagging` to the IAM actions. Before Check 8, for a new deployment: the R30 statement built from `ARTIFACT_BUCKET` and `WRITE_PREFIX`, the merge into an existing `Sid`, and the wait for the operator's word that it is applied |

### Contracts

None.

### Testing Approach

The skill body is markdown — verification is by inspection against the checklist below.
Work through the checklist top-to-bottom after writing; do not mark done until every item
passes.

**The connectivity probe rules add one code change and one drift test, and the project uses TDD —
test file before the implementation file it gates:**

1. **`tests/unit/test_tools_reconcile.py` → `src/arkeology/tools/reconcile.py`** — write the
   failing test for the `_arkeology_annotation_probe` exclusion (and for a nested-path probe
   key, mirroring the existing health-probe cases) *before* touching the orphan scan; then
   generalise the filter to the `_arkeology_` marker and confirm the pre-existing
   health/startup exclusion tests stay green unchanged.
2. The skill-side cleanup change has no unit test — it is prose, covered by the checklist
   items below and by the manual run in `tests/skill_validation/`.
3. **`tests/unit/test_skill_store_schema_tag_drift.py` → `SKILL.md`** (R29, R30) — write the drift
   test first, red against the probe as it stands with no tag and no fence statement, then add the
   tag on both branches and the statement before Check 8.

**`SKILL.md` structure:**
- [ ] Exactly 6 numbered steps, each as a `##` section
- [ ] Step 1 opens with a project-root scan for existing MCP client config files before
  any other collection question; lists the files scanned (`.mcp.json`, `.mcp.jsonc`,
  `opencode.json`, `.codex/config.toml`, `.vscode/mcp.json`)
- [ ] Step 1 presents a single detected file as the default client choice and asks
  for confirmation when exactly one file is found
- [ ] Step 1 lists all detected files and asks the operator to select when multiple
  config files are found
- [ ] Step 1 shows the full supported client list with descriptions when no config
  file is found in the project root
- [ ] Step 1 lists every remaining required parameter with its default where applicable;
  no IAM principal ARN collected (no provisioning or IAM steps)
- [ ] Step 2 lists all five reachability checks explicitly: credentials, `uv`,
  S3 bucket (`head-bucket`), Vectors index (`get-index`), Bedrock embedding
  model (`invoke-model`); states that any failure is a hard stop
- [ ] Step 2 does NOT contain any AWS resource creation commands
- [ ] Step 2 reads the Vectors index's `indexMode`; on anything but `ENHANCED` it stops and shows
  the `update-index-mode` command for the Admin to run, without running it, and says the index
  must not be switched back while servers use it (R27)
- [ ] Step 3 is clone and `uv sync` only — no IAM policy step follows it
- [ ] Step 4 contains the client reference table with all 6 rows, a "Config scope"
  column distinguishing project vs global for each client, and an "Official docs URL"
  column with the correct URL for each client
- [ ] Step 4 table shows `.mcp.json`/`.mcp.jsonc` for Claude Code (project root)
- [ ] Step 4 table shows `opencode.json` (no dot prefix) for opencode (project root) —
  NOT the global `~/.config/opencode/opencode.json`
- [ ] Step 4 table calls out `environment` (not `env`) as the opencode env vars key,
  with a visible warning (e.g. ⚠ or bold)
- [ ] Step 4 table shows `.codex/config.toml` for Codex CLI (project root) with a
  "trusted projects only" note
- [ ] Step 4 table shows `.mcp.json` for Copilot CLI (project scope, shared with Claude
  Code) with a note to use `mcpServers` key (not `servers`) and add `"tools": ["*"]`
- [ ] Step 4 table notes that `.mcp.json` serves both Claude Code and Copilot CLI
  simultaneously
- [ ] Step 4 instructs the agent to show the proposed entry and the official docs URL
  and ask permission before writing; includes fallback instruction for manual addition
  if operator declines
- [ ] Step 4 shows the complete Arkeology entry format for each client, with all
  required env vars populated (no `YOUR-*` placeholders)
- [ ] Step 4 includes explicit file-existence-check logic: check whether the target
  file exists; if yes, parse and insert; if no, create with the correct filename
- [ ] Step 4 specifies the safe-edit approach for JSON/JSONC: parse → insert at correct
  key → write complete updated object back (not a raw text append)
- [ ] Step 4 specifies the safe-edit approach for TOML: append new sections at end
  without touching existing sections; ask confirmation if `[mcp_servers.arkeology]` already
  exists
- [ ] Step 4 specifies `opencode.json` as the filename to create when no opencode
  project config file exists
- [ ] Step 4 specifies creating `.codex/` directory if absent when creating Codex config
- [ ] Step 4 states that all four supported clients have per-project config files; no
  global config is written during project installation; when operator declines a
  project-scoped write (e.g. Codex trust), the skill shows the entry for manual
  addition and continues — it does not fall back to a global file
- [ ] Step 5 calls `health_check` and blocks on anything other than all-ok
- [ ] Step 6 has two labelled parts (A: ADR strategy, B: additional exclusions) plus
  a final config-block write instruction
- [ ] Step 6A includes the recognised ADR directory name list for auto-detection
- [ ] Step 6B includes the instruction to infer types using the migration skill's
  Pass 2 path-segment table and confirm with operator
- [ ] Step 6 includes the exact `arkeology:config` block YAML structure with all four
  keys (`installed`, `adr_strategy`, `local_only_types`, `local_only_paths`)
- [ ] Step 6 instructs the agent to replace an existing block in place (not append)
- [ ] Step 6 instructs the agent to load and apply `references/agents-snippet.md`
- [ ] No `YOUR-*` placeholder remains in any emitted config or entry example
- [ ] No `.env` file is written or mentioned as a step
- [ ] No AWS resource creation command appears anywhere in the skill
- [ ] No IAM policy generation or substitution appears anywhere in the skill, R30's write-fence
  statement excepted
- [ ] Line count ≤ 500
- [ ] Step 2's annotation probe writes only `<WRITE_PREFIX>/_arkeology_annotation_probe`
- [ ] Step 2's aws-cli probe branch has an always-run cleanup step (annotation delete +
  object delete) explicitly stated to run on failure paths including `AccessDenied`, not
  just as trailing commands
- [ ] Step 2 tells the operator the leftover key and the delete command if cleanup itself
  fails
- [ ] Step 2's probe object write sends `arkeology-store-schema=2` on both branches (`--tagging` /
  `Tagging`), and a refused probe object write names `s3:PutObject`, `s3:PutObjectTagging` and the
  write fence (R29)
- [ ] For a new deployment, Step 2 shows T90 R39's write-fence statement built from
  `ARTIFACT_BUCKET` and `WRITE_PREFIX`, says to merge into an existing statement with the same
  `Sid`, and runs the annotation probe only after the operator says it is applied; for a write
  prefix already in use it shows none (R30)

**`references/agents-snippet.md` structure:**
- [ ] Contains the standing never-write instruction referencing `local_only_types` and
  `local_only_paths` from the `arkeology:config` block
- [ ] Contains Variant A (git-only ADR) and Variant B (arkeology-only ADR) clearly
  labelled so Step 6 can select the correct one
- [ ] Contains when-to-write guidance, artifact type table, description quality
  guidance, tier 2 vs tier 3 selection, query strategy, synthesis guidance, and pointer
  to MCP Resources
- [ ] Contains R26's pipeline instruction: `reconcile_index` before the job ends after any
  `failure_logged: true`, and a failed job on `failure_logged: false`, an unresolved entry or a
  `reconcile_index` error
- [ ] Contains R28's instruction: the named entries go to `arkeology-recovery.jsonl`, never to the
  job's log output or a commit; the pipeline keeps that file, and the server's stderr when the
  agent cannot read it, as a job artifact with restricted access; recovery follows T15 R10's
  procedure
