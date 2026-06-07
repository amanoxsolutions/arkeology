---
type: feature-spec
feature: p9-t31a-installing-cairn-skill
status: ready
phase: 9
task: 31a
references:
  - docs/brainstorming/brainstorming-2026-06-02-installing-cairn-skill.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-06-07"
revised:
  by: "architect"
  date: "2026-06-07"
---

# T31a — Installing-Cairn Skill

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Create `skills/installing-cairn/SKILL.md` — a 6-step agent-driven workflow that
assumes all required AWS resources are already provisioned externally, validates their
reachability, writes the cairn-mcp server entry (including all required environment
variables) directly into the IDE's MCP config file, runs a health check, and writes a
machine-readable `cairn-mcp:config` block plus a narrative usage snippet to the project
AGENTS.md. Create `skills/installing-cairn/references/agents-snippet.md` to hold the
narrative snippet (keeping the skill itself under 500 lines). No Python code, no bundled
scripts, no `.env` file, no AWS resource creation, no IAM policy generation.

## Problem Statement

First-time cairn-mcp setup currently requires an operator to read README ops content,
manually substitute placeholders, and copy configuration into multiple files — with no
validation between steps and no record of the decisions made. A skill replaces that with
an agent-driven workflow that collects all resource identifiers upfront, validates that
every declared resource is actually reachable, writes the MCP client configuration, and
ends with two artefacts written to AGENTS.md: the `cairn-mcp:config` block
(machine-readable, consumed by the migration skill and future agent sessions) and the
narrative usage snippet.

AWS resource creation, IAM policy generation, and IAM policy application are all
**out of scope** — the operator handles these using their existing AWS tooling and the
README's policy reference before running the skill. The skill's responsibility is
connection and configuration, not provisioning or access management.

## User Stories

### Story 1 — Operator connects to a fully working cairn-mcp instance (P1)

An operator on a new project runs the skill and reaches a working cairn-mcp instance
without consulting the README.

**Acceptance criteria:**
- Given a fresh environment where all required AWS resources are already provisioned,
  when the operator follows every skill step, then all declared resources are confirmed
  reachable, the cairn-mcp server entry with all env vars is written into the IDE's MCP
  config file, and `health_check` returns `"status": "ok"` for all components.
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

### Story 3 — cairn-mcp:config block written with all exclusion decisions (P1)

**Acceptance criteria:**
- Given an operator who chooses git-only ADR strategy and the skill detects `docs/adr/`,
  when Step 6 completes, then AGENTS.md contains a `<!-- cairn-mcp:config` block with
  `adr_strategy: git-only`, `local_only_types: [adr]`, and
  `local_only_paths: [docs/adr/]`.
- Given an operator who provides additional exclusion paths, when type inference
  succeeds (e.g. `docs/specs/` → `spec`), then the inferred type is added to
  `local_only_types` after the operator confirms.
- Given an operator who provides a path that maps to no known type (e.g.
  `docs/internal/`), when Step 6 completes, then the path appears in
  `local_only_paths` but no new entry is added to `local_only_types`.
- Given an operator who chooses cairn-mcp-only ADR strategy, when Step 6 completes,
  then the block contains `adr_strategy: cairn-mcp-only` and no `adr` entry in
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
  skill shows the operator the cairn-mcp entry it plans to add and asks explicit
  permission before writing.
- Given an existing config file that already contains a cairn-mcp entry (re-run),
  when Step 4 is reached, then the skill shows the new entry and asks permission to
  update the existing one in place.
- Given an operator who declines permission, when Step 4 is reached, then the skill
  displays the complete config entry for the operator to add manually and continues
  without writing.
- Given any IDE config file, when the skill writes to it, then all other existing MCP
  server entries in the file are preserved unchanged.

### Story 6 — Re-running the skill updates the config block in place (P2)

**Acceptance criteria:**
- Given AGENTS.md already contains a `cairn-mcp:config` block, when the operator
  re-runs the skill and provides new exclusion answers, then the existing block is
  replaced and no second block appears in the file.

## Requirements

- WHEN the skill starts THE SYSTEM SHALL collect all required parameters before any
  action is taken: AWS region, S3 artifact bucket name, S3 Vectors bucket name, S3
  Vectors index name, embedding model (default `amazon.titan-embed-text-v2:0`),
  embedding dimension (default 1024), AWS profile, IDE choice, team name, project name,
  and optional `READ_PREFIXES`.
- WHEN Step 2 runs THE SYSTEM SHALL validate: AWS credentials are active
  (`aws sts get-caller-identity`), `uv` is installed, the declared S3 bucket is
  reachable (`s3api head-bucket`), the declared Vectors index is reachable
  (`s3vectors describe-index`), and the declared Bedrock embedding model is accessible
  (`bedrock invoke-model` with a minimal payload).
- WHEN any Step 2 check fails THE SYSTEM SHALL stop immediately with a message
  identifying which resource is unreachable — no subsequent steps are executed.
- WHEN Step 4 runs THE SYSTEM SHALL write the cairn-mcp server entry — including all
  required env vars (`AWS_REGION`, `ARTIFACT_BUCKET`, `VECTORS_BUCKET`,
  `VECTORS_INDEX`, `WRITE_PREFIX`, `BEDROCK_EMBEDDING_MODEL`, and any optional vars
  collected in Step 1) — into the `env` (or `environment`) block of the IDE's MCP
  config file using the format and file location correct for the chosen IDE.
- WHEN the IDE config file already exists THE SYSTEM SHALL show the operator the entry
  it plans to write and ask explicit permission before modifying the file.
- WHEN the operator grants permission THE SYSTEM SHALL merge the cairn-mcp entry into
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
- WHEN Step 6 completes THE SYSTEM SHALL write a `<!-- cairn-mcp:config` block to
  AGENTS.md containing `installed` (ISO-8601 date), `adr_strategy`,
  `local_only_types` (list, may be empty), and `local_only_paths` (list, may be empty).
- WHEN a `<!-- cairn-mcp:config` block already exists in AGENTS.md THE SYSTEM SHALL
  replace it in place; no second block shall be appended.
- WHEN Step 6 completes THE SYSTEM SHALL write the narrative AGENTS.md snippet from
  `references/agents-snippet.md` to the project AGENTS.md, using the ADR variant
  matching the operator's strategy choice.
- WHEN the SKILL.md line count exceeds 500 THE SYSTEM SHALL keep the narrative snippet
  in `references/agents-snippet.md` and load it in Step 6.

## Boundaries

**Always:**
- No bundled scripts — all agent actions are CLI commands or file writes.
- No `.env` file — all cairn-mcp environment variables are passed via the IDE's MCP
  config file's `env` (Claude Code, Claude Desktop, VS Code, Copilot CLI) or
  `environment` (OpenCode) block.
- No AWS resource creation of any kind.
- No IAM policy generation — the README provides a static reference policy with
  `YOUR-*` placeholders; the skill never emits a policy document.
- All parameter collection happens in Step 1 before any validation or AWS calls.
- Step 6 is always the last step; the health check (Step 5) must pass before Step 6 runs.
- `local_only_types` and `local_only_paths` may both be empty lists — the config block
  is still written.
- The config block format is YAML inside an HTML comment:
  `<!-- cairn-mcp:config\n<yaml>\n-->` — opening and closing tags each on their own line.
- Path syntax: trailing `/` = directory tree; no trailing `/` = exact file; no globs.
- The `SKILL.md` must be ≤ 500 lines.
- The skill is compatible with OpenCode, Claude Code, VS Code + Copilot Chat, Copilot
  CLI, and Codex CLI — IDE differences are confined to a reference table in Step 4.

**IDE config file locations and env key names (Step 4 reference):**

| IDE | Config file | Top-level key | Env vars key |
|-----|-------------|---------------|--------------|
| Claude Code | `.mcp.json` (project root) | `mcpServers` | `env` |
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) / `%APPDATA%\Claude\claude_desktop_config.json` (Windows) | `mcpServers` | `env` |
| OpenCode | `~/.config/opencode/opencode.json` or `.jsonc` | `mcp` | `environment`; command is a single array |
| VS Code + Copilot Chat | `.vscode/mcp.json` (project root) | `servers` | `env` |
| Copilot CLI | `~/.copilot/mcp-config.json` | `mcpServers` | `env`; `"tools": ["*"]` required |
| Codex CLI | `~/.codex/config.toml` | `[mcp_servers.<name>]` | `[mcp_servers.<name>.env]` sub-table |

**Ask First:**
- Before writing to or modifying any IDE config file — show the entry to be added and
  ask explicit permission. This applies on every run, including re-runs.

**Never:**
- Do not write a `.env` file.
- Do not create any AWS resource.
- Do not generate, emit, or substitute values into any IAM policy document — refer the
  operator to the README's policy reference section.
- Do not proceed past Step 5 if `health_check` reports any component as errored.
- Do not overwrite or delete existing MCP server entries in any config file — merge only.
- Do not embed the full narrative snippet inline if it would push `SKILL.md` over 500
  lines — keep it in `references/agents-snippet.md`.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `skills/installing-cairn/SKILL.md` | Create | 6-step workflow; ≤ 500 lines |
| `skills/installing-cairn/references/agents-snippet.md` | Create | Full narrative AGENTS.md snippet; both ADR variants; standing never-write instruction |

## Testing Approach

This is a pure skill (markdown) update — no Python source files or unit tests. Verification
is by inspection against the checklist below. Work through the checklist top-to-bottom after
writing; do not mark done until every item passes.

**`SKILL.md` structure:**
- [ ] Exactly 6 numbered steps, each as a `##` section
- [ ] Step 1 lists every required parameter with its default where applicable; no IAM
  principal ARN collected (no provisioning or IAM steps)
- [ ] Step 2 lists all five reachability checks explicitly: credentials, `uv`,
  S3 bucket (`head-bucket`), Vectors index (`describe-index`), Bedrock embedding
  model (`invoke-model`); states that any failure is a hard stop
- [ ] Step 2 does NOT contain any AWS resource creation commands
- [ ] Step 3 is clone and `uv sync` only — no IAM policy step follows it
- [ ] Step 4 contains the IDE config file reference table (all 6 IDEs)
- [ ] Step 4 instructs the agent to show the proposed entry and ask permission before
  writing; includes fallback instruction for manual addition if operator declines
- [ ] Step 4 shows the complete cairn-mcp server entry format for each IDE, with all
  required env vars populated (no `YOUR-*` placeholders)
- [ ] Step 4 includes the merge instruction: preserve all existing entries
- [ ] Step 5 calls `health_check` and blocks on anything other than all-ok
- [ ] Step 6 has two labelled parts (A: ADR strategy, B: additional exclusions) plus
  a final config-block write instruction
- [ ] Step 6A includes the recognised ADR directory name list for auto-detection
- [ ] Step 6B includes the instruction to infer types using the migration skill's
  Pass 2 path-segment table and confirm with operator
- [ ] Step 6 includes the exact `cairn-mcp:config` block YAML structure with all four
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
  `local_only_paths` from the `cairn-mcp:config` block
- [ ] Contains Variant A (git-only ADR) and Variant B (cairn-mcp-only ADR) clearly
  labelled so Step 6 can select the correct one
- [ ] Contains when-to-write guidance, artifact type table, description quality
  guidance, tier 2 vs tier 3 selection, query strategy, synthesis guidance, and pointer
  to MCP Resources

## Open Questions

*(none — all constraints are defined)*
