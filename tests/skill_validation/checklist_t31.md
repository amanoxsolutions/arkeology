# T31 Manual Inspection Checklist

Items in this file require a human or agent to read the content and exercise judgment.
They cannot be verified by automated `grep` or `wc` checks alone.

Work through these top-to-bottom after `validate_t31.sh` passes all automated checks.
Do not mark T31 done until every item below is ticked.

---

## T31a — `skills/setting-up-cairn/SKILL.md`

### Step 1 — Parameter collection

- [ ] Step 1 lists every required parameter from the spec: AWS region, S3 artifact bucket
  name, S3 Vectors bucket name, S3 Vectors index name, embedding model (default
  `amazon.titan-embed-text-v2:0`), embedding dimension (default 1024), AWS profile, IDE
  choice, team name, project name, and optional `READ_PREFIXES`.
- [ ] Step 1 includes the default value beside each parameter that has one.
- [ ] Step 1 does NOT ask for an IAM principal ARN — no provisioning or policy-generation
  step exists in the skill.
- [ ] All parameter collection in Step 1 is described as happening before any validation
  or AWS API call.

### Step 2 — Pre-flight validation

- [ ] Step 2 lists all five reachability checks explicitly and in order: (1) AWS
  credentials (`aws sts get-caller-identity`), (2) `uv` installed, (3) S3 bucket
  reachable (`s3api head-bucket`), (4) Vectors index reachable (`s3vectors
  describe-index`), (5) Bedrock embedding model accessible (`bedrock invoke-model` with
  a minimal payload).
- [ ] Step 2 states clearly that any single check failure is a hard stop — no subsequent
  steps are executed until the failure is resolved.
- [ ] Step 2 does not contain any AWS resource-creation commands (e.g., `mb`, `create-bucket`,
  `create-index`, `create-bucket-with-index`). The five checks above are read-only
  reachability probes only.

### Step 3 — Clone and sync

- [ ] Step 3 covers only cloning the cairn-mcp repo and running `uv sync` — no IAM
  policy step appears at any point in or after Step 3.

### Step 4 — IDE config file

- [ ] Step 4 contains the IDE config reference table with all 6 IDEs: Claude Code,
  Claude Desktop, OpenCode, VS Code + Copilot Chat, Copilot CLI, and Codex CLI.
- [ ] For each IDE, the table shows the correct config file path, top-level key name, and
  env vars key name (matching the spec: `env` vs `environment`, `mcpServers` vs `mcp`
  vs `servers`, and the Codex TOML sub-table format).
- [ ] Step 4 instructs the agent to show the operator the complete cairn-mcp server entry
  it plans to write and ask explicit permission before modifying any config file.
- [ ] Step 4 includes a fallback instruction: if the operator declines permission, display
  the complete correctly-formatted config entry for the operator to add manually, then
  continue to Step 5.
- [ ] Step 4 shows the complete cairn-mcp server entry format for at least one
  representative IDE, including all required env vars: `AWS_REGION`, `ARTIFACT_BUCKET`,
  `VECTORS_BUCKET`, `VECTORS_INDEX`, `WRITE_PREFIX`, and `BEDROCK_EMBEDDING_MODEL`.
- [ ] The example config entries in Step 4 contain no `YOUR-*` placeholders — they use
  the actual values collected in Step 1 (shown as template variables or descriptive
  placeholders, not `YOUR-*` literal strings).
- [ ] Step 4 includes an explicit merge instruction: when writing to an existing config
  file, all other MCP server entries must be preserved unchanged.

### Step 5 — Health check

- [ ] Step 5 calls the `health_check` MCP tool and instructs the agent to block progress
  until every component returns `"status": "ok"`.
- [ ] Step 5 states that if any component reports `"status": "error"`, the agent must not
  proceed to Step 6.

### Step 6 — Config block and AGENTS.md snippet

- [ ] Step 6 has two clearly labelled parts: Part A (ADR strategy and auto-detection) and
  Part B (additional exclusions and type inference).
- [ ] Step 6A includes the recognised ADR directory name list for auto-detection (at
  minimum: `docs/adr/`, `adr/`, `adrs/`, `docs/decisions/`, or equivalent names from
  the migration skill's Pass 2 table).
- [ ] Step 6A instructs the agent to present the detected path to the operator and ask for
  confirmation; to ask the operator to provide the path if none is found; and to list all
  candidates if multiple are found.
- [ ] Step 6B instructs the agent to attempt to infer an artifact type for each additional
  exclusion path using the migration skill's Pass 2 path-segment table, present each
  inference to the operator for confirmation, and add confirmed types to
  `local_only_types`.
- [ ] Step 6B states that paths mapping to no known type are added to `local_only_paths`
  only — no new entry is added to `local_only_types` without operator confirmation.
- [ ] Step 6 shows the exact `cairn-mcp:config` YAML structure with all four required
  keys: `installed` (ISO-8601 date), `adr_strategy`, `local_only_types` (list),
  `local_only_paths` (list).
- [ ] Step 6 states that `local_only_types` and `local_only_paths` may both be empty
  lists — the config block is still written.
- [ ] Step 6 instructs the agent to replace an existing `cairn-mcp:config` block in
  AGENTS.md in place; not to append a second block.
- [ ] Step 6 instructs the agent to load `references/agents-snippet.md` and write the ADR
  variant matching the operator's strategy choice to AGENTS.md.

### Overall SKILL.md quality

- [ ] No `.env` file creation is mentioned or implied anywhere in the skill as a step or
  instruction. The skill consistently directs all env vars through the IDE's MCP config
  `env`/`environment` block.
- [ ] No AWS resource creation commands appear anywhere in the skill (other than the five
  read-only reachability checks in Step 2).
- [ ] No IAM policy generation, substitution, or emission appears anywhere in the skill;
  the README is referenced as the source for the static policy template.
- [ ] The skill reads naturally and coherently as a 6-step agent workflow.

---

## T31a — `skills/setting-up-cairn/references/agents-snippet.md`

- [ ] The file opens with or prominently contains a standing never-write instruction that
  tells agents to consult the `cairn-mcp:config` block in AGENTS.md and never write
  artifact types listed in `local_only_types` or files/paths listed in
  `local_only_paths` to cairn-mcp.
- [ ] Variant A (git-only ADR) and Variant B (cairn-mcp-only ADR) sections are clearly
  labelled so Step 6 can select exactly one to copy into the project AGENTS.md.
- [ ] The snippet contains when-to-write guidance (at minimum: start of session, end of
  session, after a key decision, after a code review).
- [ ] The snippet contains an artifact type selection table covering the main artifact types.
- [ ] The snippet contains description quality guidance (≤ 280 chars, specific, no "This
  document describes…" preamble).
- [ ] The snippet contains guidance on choosing tier 2 vs tier 3 artifacts.
- [ ] The snippet contains query strategy guidance (how to search effectively).
- [ ] The snippet contains synthesis guidance (how and when to use `synthesise_artifacts`).
- [ ] The snippet contains a pointer to MCP Resources for browsing artifact types and
  available tools.

---

## T31b — `skills/migrating-to-cairn/SKILL.md`

### Step 2 — Pre-flight and discovery order

- [ ] The very first action in Step 2 is the `cairn-mcp:config` block check — it appears
  before Step 2a (manifest check) in the document. The Step 2 opening prose or sub-step
  header makes the new order explicit: config check → manifest check → scope → classify.
- [ ] The hard-stop message is unambiguous, names `setting-up-cairn` explicitly, and
  provides no inline fallback that re-asks exclusion questions — the operator is always
  redirected to the installation skill when the block is absent.
- [ ] Step 2a (manifest check: look for `CAIRN_IMPORT.yaml`) is unchanged in content
  from the original skill — only its position (now after the new config pre-flight
  check) has changed.
- [ ] Step 2b (scope) explicitly describes that files/paths in `local_only_paths` are
  excluded during the scan using prefix-matching semantics (trailing `/` = directory
  tree; no trailing `/` = exact file match).
- [ ] What was previously Step 2d (scan and classify) is now renumbered Step 2c and
  explicitly states that files whose resolved type appears in `local_only_types` are
  discarded after classification (classified first, then type-checked against the list).
- [ ] The workflow summary at the top of the skill (the numbered list before Step 1) is
  updated to reflect the new sub-step order and the pre-flight config check.

### Step 5 — Post-migration

- [ ] Step 5 does not contain any question to the operator about ADR strategy.
- [ ] The Variant A and Variant B markdown blocks that were in Step 5's AGENTS.md update
  section are fully absent — no remnant prose, no "see installation skill" substitution
  in their place.
- [ ] The AGENTS.md update section in Step 5 instructs the agent to verify (not write)
  that both the `cairn-mcp:config` block and the narrative snippet are already present
  in AGENTS.md. If either is absent, the agent is directed to run `setting-up-cairn` to
  write them.
- [ ] The ADR row in the Step 5 tier 2 file removal table now reads something equivalent
  to "Depends on the `adr_strategy` in your `cairn-mcp:config` block" — it no longer
  references "your strategy chosen in Step 2" or any step-specific ADR decision.

### Regression check

- [ ] Steps 1, 3.A, 3.B, and 4 are fully unchanged — a diff of the file should show no
  edits outside Steps 2 and 5.
- [ ] The always-skip exclusion list (README.md, AGENTS.md, CONTRIBUTING.md, CHANGELOG.md,
  non-markdown files, auto-generated docs, `.docs/` directory) is unchanged.
- [ ] The two-pass classification tables (Pass 1 filename rules, Pass 2 path-segment
  rules) are unchanged.

---

## T31c — `README.md`

### Key Features bullet

- [ ] The "Flexible ADR & document strategy" bullet description conveys that teams can
  designate ADRs, specs, plans, or any folder as git-only — not just ADRs.
- [ ] The bullet description states that the decision is recorded once in `AGENTS.md` and
  respected automatically by every future agent session and the migration skill.
- [ ] Reading the bullet in isolation, it no longer implies ADRs are the only type of
  document that can stay in git.

### Removed sections and pointer sentences

- [ ] A clear pointer to the `setting-up-cairn` skill appears in the README at or near the
  location where `## Connecting to an MCP client` was — the pointer sentence is coherent
  in context and does not leave an orphaned sub-heading.
- [ ] A clear pointer to the `setting-up-cairn` skill appears in the README at or near the
  location where `## Recommended AGENTS.md Snippet` was — same coherence requirement.
- [ ] The full AGENTS.md snippet body (from the ````markdown` fence containing
  `## cairn-mcp — Persistent Artifact Memory` through to the closing fence) is absent.
- [ ] Both IDE sub-sections that were under `## Connecting to an MCP client` (OpenCode
  and Claude Code / Desktop examples) are absent.
- [ ] Any IAM policy JSON blocks that previously lived inside the now-removed sections are
  absent — only the policy block under `## Minimum IAM Policy` remains.

### Configuration section

- [ ] The `## Configuration` section intro does not reference `.env` or `.env.example` as
  the mechanism for setting environment variables — the intro correctly describes env
  vars being set through the IDE's MCP config file (matching T31 scope-correction).

### Overall README quality

- [ ] All retained sections are fully intact and unmodified except for the one Key
  Features bullet update: `## The pain point`, `## Key Features` (all other bullets),
  `### cairn-mcp vs. other approaches`, `## Who this is for`, `## Why AWS`,
  `## How it works`, `## Status`, `## Using the Migration Skill`, `## Prerequisites`,
  `## Minimum IAM Policy`, `## Installation`, `## Configuration` table,
  `## Running the server`, `## Development`, `## License`.
- [ ] The README reads coherently top-to-bottom with no orphaned headings, no broken
  prose, and no abrupt transitions introduced by the section removals.
- [ ] The `## Minimum IAM Policy` section is complete and contains the `YOUR-*` placeholder
  values exactly as they were — these are intentional operator-substitution markers that
  must not be removed.
