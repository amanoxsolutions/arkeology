---
type: spec
title: T31a — Setting-Up-Arkeology Skill
description: Spec for a 6-step agent-driven skill that validates AWS resources, writes the Arkeology MCP config entry for the chosen client, and records the setup in AGENTS.md.
tags: []
timestamp: 2026-06-07T00:00:00Z
okf_version: "0.1"
feature: p9-t31a-setting-up-arkeology-skill
status: ready
phase: 9
task: 31a
references:
  - docs/brainstorming/brainstorming-2026-06-02-setting-up-arkeology-skill.md
  - docs/brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md
  - docs/planning-artifacts/prd.md
  - https://docs.anthropic.com/en/docs/claude-code/mcp
  - https://opencode.ai/docs/mcp-servers/
  - https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers
  - https://developers.openai.com/codex/mcp
authored:
  by: "architect"
  date: "2026-06-07"
revised:
  by: "architect"
  date: "2026-06-08"
---

# T31a — Setting-Up-Arkeology Skill

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Create `skills/setting-up-arkeology/SKILL.md` — a 6-step agent-driven workflow that
assumes all required AWS resources are already provisioned externally, validates their
reachability, writes a complete and project-scoped Arkeology server entry into the
correct MCP configuration file for the chosen client (Claude Code, opencode,
GitHub Copilot CLI, or OpenAI Codex), runs a health check, and writes a
machine-readable `arkeology:config` block plus a narrative usage snippet to the
project AGENTS.md. All four clients support per-project config files, so the
`WRITE_PREFIX` fence is automatically per-project for every supported client; for
GitHub Copilot CLI the entry lands in `.mcp.json` at the workspace root (shared
with Claude Code, supported since v0.0.401).
No Python code, no bundled scripts, no `.env` file, no AWS resource creation, no
IAM policy generation.

## Problem Statement

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

## User Stories

### Story 1 — Operator connects to a fully working Arkeology instance (P1)

An operator on a new project runs the skill and reaches a working Arkeology instance
without consulting the README.

**Acceptance criteria:**
- Given a fresh environment where all required AWS resources are already provisioned,
  when the operator follows every skill step, then all declared resources are confirmed
  reachable, the Arkeology server entry with all env vars is written into the correct
  MCP config file for the chosen client, and `health_check` returns `"status": "ok"`
  for all components.
- Given a client that supports a project-scoped config file (Claude Code, opencode,
  Codex CLI), when Step 4 writes the Arkeology entry, then it is written to the
  project-level file — the user's global MCP client config is not modified.
- Given GitHub Copilot CLI, when Step 4 writes the Arkeology entry, then it is
  written to `.mcp.json` at the workspace root under the server name `arkeology` — the
  same file and server name used by Claude Code; no global `~/.copilot/mcp-config.json`
  is modified.
- Given a step that fails (e.g. wrong region), when the operator fixes it and re-runs
  that step, then the skill continues without re-executing earlier steps.

### Story 2 — Pre-flight catches unreachable resources before any work is done (P1)

The skill validates every declared resource is reachable before writing any
configuration file.

**Acceptance criteria:**
- Given a declared S3 bucket that does not exist or is inaccessible, when Step 2
  runs, then the skill stops and tells the operator which resource failed and why —
  no config file is written.
- Given a declared Vectors index that does not exist, when Step 2 runs, then the
  skill stops with a clear error identifying the missing index.
- Given an embedding model that is not enabled in the operator's region, when Step 2
  runs, then the skill stops and instructs the operator to enable the model in the
  Bedrock console before proceeding.
- Given all declared resources are reachable, when Step 2 completes, then the skill
  proceeds to Step 3.

### Story 3 — arkeology:config block written with all exclusion decisions (P1)

**Acceptance criteria:**
- Given an operator who chooses git-only ADR strategy and the skill detects `docs/adr/`,
  when Step 6 completes, then AGENTS.md contains a `<!-- arkeology:config` block with
  `adr_strategy: git-only`, `local_only_types: [adr]`, and
  `local_only_paths: [docs/adr/]`.
- Given an operator who provides additional exclusion paths, when type inference
  succeeds (e.g. `docs/specs/` → `spec`), then the inferred type is added to
  `local_only_types` after the operator confirms.
- Given an operator who provides a path that maps to no known type (e.g.
  `docs/internal/`), when Step 6 completes, then the path appears in
  `local_only_paths` but no new entry is added to `local_only_types`.
- Given an operator who chooses arkeology-only ADR strategy, when Step 6 completes,
  then the block contains `adr_strategy: arkeology-only` and no `adr` entry in
  `local_only_types` or `local_only_paths`.

### Story 4 — ADR folder auto-detected (P1)

**Acceptance criteria:**
- Given a repository with exactly one recognised ADR directory (`docs/adr/`), when the
  operator chooses git-only, then the skill presents the detected path and asks for
  confirmation before adding it — the operator does not need to type the path.
- Given a repository with no recognised ADR directory, when the operator chooses
  git-only, then the skill asks the operator to provide the path.
- Given a repository with multiple candidate ADR directories, when the operator chooses
  git-only, then the skill lists all candidates and asks the operator to select one.

### Story 5 — Skill asks permission before editing the IDE config file (P1)

Some IDE config files (OpenCode, Claude Desktop, Copilot CLI, Codex CLI) are
user-level and may already contain entries for other MCP servers. The skill must
never silently overwrite them.

**Acceptance criteria:**
- Given any IDE config file that already exists, when Step 4 is reached, then the
  skill shows the operator the Arkeology entry it plans to add and asks explicit
  permission before writing.
- Given an existing config file that already contains an Arkeology entry (re-run),
  when Step 4 is reached, then the skill shows the new entry and asks permission to
  update the existing one in place.
- Given an operator who declines permission, when Step 4 is reached, then the skill
  displays the complete config entry for the operator to add manually and continues
  without writing.
- Given any IDE config file, when the skill writes to it, then all other existing MCP
  server entries in the file are preserved unchanged.

### Story 6 — Re-running the skill updates the config block in place (P2)

**Acceptance criteria:**
- Given AGENTS.md already contains a `arkeology:config` block, when the operator
  re-runs the skill and provides new exclusion answers, then the existing block is
  replaced and no second block appears in the file.

### Story 7 — Developer working across multiple projects keeps each project independently scoped (P1)

A developer has multiple projects on their machine. Each project uses Arkeology with a
different `WRITE_PREFIX`. The developer never edits their global MCP client config when
switching between projects.

**Acceptance criteria:**
- Given a developer who completed the skill for project A (with its own `WRITE_PREFIX`)
  and subsequently runs the skill for project B (with a different `WRITE_PREFIX`), when
  the skill completes for project B, then project B has its own project-scoped config
  file with the correct `WRITE_PREFIX`, and the project A config file is unchanged.
- Given a developer using Claude Code, opencode, or Codex CLI, when the skill writes
  the Arkeology entry for a project, then the entry lands in a project-level file
  (`.mcp.json`, `opencode.json`, or `.codex/config.toml` respectively); the global
  MCP client config is not touched.
- Given a developer using GitHub Copilot CLI, when the skill writes the Arkeology entry
  for each project, then each project has its own `.mcp.json` at its workspace root with
  the correct `WRITE_PREFIX`; no global `~/.copilot/mcp-config.json` is modified.

### Story 8 — Skill auto-detects the MCP client from existing project config files (P1)

An operator running the skill should not need to know which config file format their
client uses — the skill detects it from what is already in the project.

**Acceptance criteria:**
- Given exactly one recognised MCP client config file exists in the project root
  (e.g. `.mcp.json`), when Step 1 reaches the client-choice question, then the skill
  presents the detected file and associated client as the default and asks the operator
  to confirm rather than presenting an open-ended choice.
- Given multiple recognised MCP client config files exist in the project root (e.g.
  both `opencode.json` and `.vscode/mcp.json`), when Step 1 reaches the client-choice
  question, then the skill lists each detected file with its associated client and asks
  the operator to select one.
- Given no recognised MCP client config file exists in the project root, when Step 1
  reaches the client-choice question, then the skill presents the full list of
  supported clients with a brief description and asks the operator to choose.

## Requirements

- WHEN the skill starts THE SYSTEM SHALL scan the project root for recognised MCP
  client config files (`.mcp.json`, `.mcp.jsonc`, `opencode.json`,
  `.codex/config.toml`, `.vscode/mcp.json`) before prompting for the client choice.
  If exactly one file is found, THE SYSTEM SHALL present it as the
  detected client and ask for confirmation; if multiple are found, THE SYSTEM SHALL list
  them with their associated client names and ask the operator to select; if none are
  found, THE SYSTEM SHALL present the full list of supported clients and ask the operator
  to choose. When `.mcp.json` is detected, THE SYSTEM SHALL note that it is compatible
  with both Claude Code and GitHub Copilot CLI simultaneously.
- WHEN the skill starts THE SYSTEM SHALL collect all remaining required parameters
  before any action is taken: AWS region, S3 artifact bucket name, S3 Vectors bucket
  name, S3 Vectors index name, embedding model (default `amazon.titan-embed-text-v2:0`),
  embedding dimension (default 1024), AWS profile, team name, project name, and optional
  `READ_PREFIXES`.
- WHEN Step 2 runs THE SYSTEM SHALL validate: AWS credentials are active
  (`aws sts get-caller-identity`), `uv` is installed, the declared S3 bucket is
  reachable (`s3api head-bucket`), the declared Vectors index is reachable
  (`s3vectors describe-index`), and the declared Bedrock embedding model is accessible
  (`bedrock invoke-model` with a minimal payload).
- WHEN any Step 2 check fails THE SYSTEM SHALL stop immediately with a message
  identifying which resource is unreachable — no subsequent steps are executed.
- WHEN Step 4 runs THE SYSTEM SHALL write the Arkeology server entry — including all
  required env vars (`AWS_REGION`, `ARTIFACT_BUCKET`, `VECTORS_BUCKET`,
  `VECTORS_INDEX`, `WRITE_PREFIX`, `BEDROCK_EMBEDDING_MODEL`, and any optional vars
  collected in Step 1) — into the correct config file and at the correct key path for
  the chosen client, as specified in the Step 4 reference table in Boundaries.
- WHEN Step 4 presents the config entry to the operator THE SYSTEM SHALL include the
  official documentation URL for the chosen client's MCP configuration (see Boundaries
  reference table) so the operator can independently verify the format.
- WHEN the target config file already exists THE SYSTEM SHALL show the operator the entry
  it plans to write and ask explicit permission before modifying the file.
- WHEN the operator grants permission THE SYSTEM SHALL insert the Arkeology entry into
  the existing config, preserving all other entries unchanged.
- WHEN the operator declines permission THE SYSTEM SHALL display the complete
  correctly-formatted config entry for the operator to add manually and proceed to
  Step 5.
- WHEN Step 5 runs THE SYSTEM SHALL call `health_check` and block until all components
  return `"status": "ok"` before proceeding to Step 6.
- WHEN git-only ADR strategy is chosen THE SYSTEM SHALL scan for ADR directories using
  the recognised name list; present the result to the operator; ask for the path if
  none is found or multiple are found.
- WHEN additional exclusion paths are provided THE SYSTEM SHALL attempt to infer an
  artifact type for each using the migration skill's Pass 2 path-segment table; present
  inferences to the operator for confirmation; add confirmed types to `local_only_types`.
- WHEN Step 6 completes THE SYSTEM SHALL write a `<!-- arkeology:config` block to
  AGENTS.md containing `installed` (ISO-8601 date), `adr_strategy`,
  `local_only_types` (list, may be empty), and `local_only_paths` (list, may be empty).
- WHEN a `<!-- arkeology:config` block already exists in AGENTS.md THE SYSTEM SHALL
  replace it in place; no second block shall be appended.
- WHEN Step 6 completes THE SYSTEM SHALL write the narrative AGENTS.md snippet from
  `references/agents-snippet.md` to the project AGENTS.md, using the ADR variant
  matching the operator's strategy choice.
- WHEN the SKILL.md line count exceeds 500 THE SYSTEM SHALL keep the narrative snippet
  in `references/agents-snippet.md` and load it in Step 6.
- WHEN Step 4 runs THE SYSTEM SHALL write to a project-scoped config file for all four
  supported clients: `.mcp.json` or `.mcp.jsonc` for Claude Code and GitHub Copilot CLI
  (shared file); `opencode.json` for opencode; `.codex/config.toml`
  for Codex CLI. All four clients support per-project config — no global-only fallback
  is required for any supported client.
- WHEN Step 4 targets a `.mcp.json` file THE SYSTEM SHALL inform the operator that this
  file is read by both Claude Code and GitHub Copilot CLI simultaneously, so one file
  covers both clients.
- WHEN Step 4 targets a project-scoped file that does not yet exist THE SYSTEM SHALL
  create it: `.mcp.json` for Claude Code; `opencode.json` (no dot prefix — this is the
  officially documented project config name) for opencode; `.codex/config.toml`
  (creating `.codex/` directory if absent) for Codex CLI.
- WHEN Step 4 targets a config file that already exists and uses JSON or JSONC format
  THE SYSTEM SHALL parse the existing file, insert the `arkeology` entry at the correct
  top-level key, and write the complete updated structure back — it SHALL NOT append
  raw text or replace the file with only the Arkeology entry.
- WHEN Step 4 targets a config file that already exists and uses TOML format THE SYSTEM
  SHALL append the `[mcp_servers.arkeology]` and `[mcp_servers.arkeology.env]` sections to the
  end of the file — it SHALL NOT modify any existing section.
- WHEN Step 4 targets a TOML file that already contains a `[mcp_servers.arkeology]` section
  THE SYSTEM SHALL show the existing entry to the operator and ask for confirmation
  before overwriting it.
- WHEN Step 4 targets an opencode config THE SYSTEM SHALL use `environment` as the key
  for the environment variable block (not `env`) and SHALL include `"command"` as a
  JSON array (e.g. `["uvx", "arkeology"]`).
- WHEN Step 4 targets a GitHub Copilot CLI config THE SYSTEM SHALL use `arkeology` as the
  MCP server name (same as all other clients) and SHALL include `"tools": ["*"]` in
  the entry. THE SYSTEM SHALL use `mcpServers` as the top-level key — NOT `servers`,
  which is not recognised by Copilot CLI.
- WHEN Step 4 targets a Codex CLI project config THE SYSTEM SHALL inform the operator
  that project-scoped Codex config only loads for trusted projects; if the operator
  declines to trust the project THE SYSTEM SHALL display the complete config entry for
  manual addition and proceed to Step 5 — it SHALL NOT write to `~/.codex/config.toml`
  or any other home-directory path.
- WHEN any configuration file write occurs during Step 4 THE SYSTEM SHALL write only to a
  file in the current working directory (the project root); it SHALL NEVER read from or
  write to any home-directory path — including `~/.config/opencode/`, `~/.codex/`,
  `~/.copilot/`, or any equivalent — regardless of operator instruction. The sole exception
  is Claude Desktop (no per-project config exists); the skill writes to its platform config
  path only when the operator explicitly chose Claude Desktop as their client in Step 1.
  If an operator declines or is unable to use a project-scoped file, THE SYSTEM SHALL
  display the complete entry for manual addition and proceed to Step 5 — it SHALL NOT fall
  back to any global configuration file as a substitute write target.

## Boundaries

**Always:**
- No bundled scripts — all agent actions are CLI commands or file writes.
- No `.env` file — all Arkeology environment variables are passed via the MCP client's
  config file env block.
- No AWS resource creation of any kind.
- No IAM policy generation — the README provides a static reference policy with
  `YOUR-*` placeholders; the skill never emits a policy document.
- All parameter collection happens in Step 1 before any validation or AWS calls. Step 1
  always starts with the project-root scan for existing config files before asking any
  other questions.
- Step 6 is always the last step; the health check (Step 5) must pass before Step 6 runs.
- `local_only_types` and `local_only_paths` may both be empty lists — the config block
  is still written.
- The config block format is YAML inside an HTML comment:
  `<!-- arkeology:config\n<yaml>\n-->` — opening and closing tags each on their own line.
- Path syntax: trailing `/` = directory tree; no trailing `/` = exact file; no globs.
- The `SKILL.md` must be ≤ 500 lines.
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

**IDE config file locations, scopes, env key names, and official docs (Step 4 reference):**

| Client | Config scope | File(s) to check | Top-level key | Env vars key | Official docs URL |
|--------|-------------|-----------------|---------------|--------------|-------------------|
| Claude Code | Project | `.mcp.json`, `.mcp.jsonc` (workspace root) | `mcpServers` | `env` | https://docs.anthropic.com/en/docs/claude-code/mcp |
| Claude Desktop | Global | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) · `%APPDATA%\Claude\claude_desktop_config.json` (Windows) | `mcpServers` | `env` | https://docs.anthropic.com/en/docs/claude-code/mcp |
| opencode | Project | `opencode.json` (workspace root) | `mcp` | `environment` ⚠ | https://opencode.ai/docs/mcp-servers/ |
| VS Code + Copilot Chat | Project | `.vscode/mcp.json` (workspace root) | `servers` | `env` | https://code.visualstudio.com/docs/copilot/chat/mcp-servers |
| Copilot CLI | Project | `.mcp.json` (workspace root, **shared with Claude Code**) | `mcpServers` | `env` | https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers |
| Codex CLI | Project | `.codex/config.toml` (workspace root) | `[mcp_servers.arkeology]` | `[mcp_servers.arkeology.env]` | https://developers.openai.com/codex/mcp |

**Key notes on the table above:**
- `.mcp.json` at the workspace root is read by **both Claude Code and Copilot CLI** — one file serves both clients simultaneously. Use `mcpServers` as the top-level key; `servers` is NOT recognised by Copilot CLI.
- opencode uses `environment` (not `env`) — this is different from every other client. ⚠
- VS Code + Copilot Chat uses `servers` (not `mcpServers`) — this is different from every other client.
- Copilot CLI traverses from the working directory up to the git root (v1.0.11+), covering
  monorepo setups. Note: Copilot CLI itself also reads `~/.copilot/mcp-config.json` as a
  merge layer — this is a Copilot CLI behaviour independent of anything the skill writes; the
  skill writes only to `.mcp.json` in the project root and never touches the global file.
- Codex CLI project config requires the project to be explicitly trusted.

**Ask First:**
- Before writing to or modifying any MCP config file — show the entry to be added and
  ask explicit permission. This applies on every run, including re-runs.
- Before overwriting an existing `[mcp_servers.arkeology]` section in a TOML file — show
  the existing entry and ask explicit confirmation.

**Never:**
- Do not write a `.env` file.
- Do not create any AWS resource.
- Do not generate, emit, or substitute values into any IAM policy document — refer the
  operator to the README's policy reference section.
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

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/setting-up-arkeology/SKILL.md` | Create | 6-step workflow; ≤ 500 lines |
| `skills/setting-up-arkeology/references/agents-snippet.md` | Create | Full narrative AGENTS.md snippet; both ADR variants; standing never-write instruction |

## Testing Approach

This is a pure skill (markdown) update — no Python source files or unit tests. Verification
is by inspection against the checklist below. Work through the checklist top-to-bottom after
writing; do not mark done until every item passes.

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
  S3 bucket (`head-bucket`), Vectors index (`describe-index`), Bedrock embedding
  model (`invoke-model`); states that any failure is a hard stop
- [ ] Step 2 does NOT contain any AWS resource creation commands
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
- [ ] No IAM policy generation or substitution appears anywhere in the skill
- [ ] Line count ≤ 500

**`references/agents-snippet.md` structure:**
- [ ] Contains the standing never-write instruction referencing `local_only_types` and
  `local_only_paths` from the `arkeology:config` block
- [ ] Contains Variant A (git-only ADR) and Variant B (arkeology-only ADR) clearly
  labelled so Step 6 can select the correct one
- [ ] Contains when-to-write guidance, artifact type table, description quality
  guidance, tier 2 vs tier 3 selection, query strategy, synthesis guidance, and pointer
  to MCP Resources

## Open Questions

*(none — all constraints are defined)*
