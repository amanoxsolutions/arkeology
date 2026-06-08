---
name: installing-cairn
description: Connect cairn-mcp to your project — validate AWS resource connectivity, configure your MCP client, and write AGENTS.md usage guidance.
---

# Installing cairn-mcp

This skill connects cairn-mcp to a project, assuming all required AWS resources (S3 bucket,
S3 Vectors bucket and index, and Bedrock model access) are already provisioned externally.
It validates every resource is reachable before writing any configuration, writes a
project-scoped cairn-mcp server entry into the correct MCP client config file (all four
supported clients write to the project root — Claude Code and GitHub Copilot CLI share
`.mcp.json`, opencode uses `.opencode.json`, Codex CLI uses `.codex/config.toml`), runs a
health check, and closes by writing a machine-readable `cairn-mcp:config` block and usage
guidance to `AGENTS.md`.

---

## Step 1 — MCP client detection and parameter collection

### Phase 1A — Detect existing MCP client config

Before asking for any parameter, scan the **project root** (current working directory) for
these files:

| File | Client(s) |
|------|-----------|
| `.mcp.json` or `.mcp.jsonc` | **Claude Code** and **GitHub Copilot CLI** (shared — one file serves both) |
| `opencode.json` | opencode (documented name; use this) |
| `.opencode.json` | opencode (dot-prefix variant — only if already present) |
| `.codex/config.toml` | Codex CLI |
| `.vscode/mcp.json` | VS Code + Copilot Chat |

**Exactly one file found** → present it to the operator as the detected client and ask for
confirmation before continuing.

**Multiple files found** → list each file with its associated client(s) and ask the
operator to select one.

**None found** → present the full list of supported clients and ask the operator to choose:
Claude Code / Copilot CLI, opencode, VS Code + Copilot Chat, Codex CLI, Claude Desktop.

> **Note on `.mcp.json`**: this file is read simultaneously by both Claude Code and GitHub
> Copilot CLI. Writing it once gives both clients access to cairn-mcp without any extra
> configuration.

### Phase 1B — Collect remaining parameters

Once the client is confirmed, collect the following. All required parameters must be
confirmed before proceeding to Step 2.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `AWS_REGION` | AWS region for all services | — (required) |
| `ARTIFACT_BUCKET` | S3 bucket name for artifact content (must exist) | — (required) |
| `VECTORS_BUCKET` | S3 Vectors bucket name (must exist) | — (required) |
| `VECTORS_INDEX` | S3 Vectors index name (must exist) | — (required) |
| `BEDROCK_EMBEDDING_MODEL` | Bedrock embedding model ID | `amazon.titan-embed-text-v2:0` |
| `BEDROCK_EMBEDDING_DIMENSIONS` | Embedding dimension | `1024` |
| `BEDROCK_TEXT_MODEL` | Bedrock text model for auto-generating artifact descriptions during migration. Required if you plan to use the migration skill on more than 10 files — without it the server cannot generate descriptions and the agent will improvise. | `amazon.nova-lite-v1:0` (optional, recommended) |
| `AWS_PROFILE` | AWS CLI named profile | — (optional) |
| Team name | The name of your team or organisation (e.g. `platform`, `acme`) | — (required) |
| Project name | The name of this project (e.g. `api-gateway`, `cairn-mcp`) | — (required) |
| `READ_PREFIXES` | Other teams' scopes whose shared artifacts agents in this project can search. Leave blank if you only need your own project's artifacts. To populate this: ask each team you want to read from for their `WRITE_PREFIX` value (e.g. `platform/shared-patterns`), then comma-separate them here. | — (optional) |

`WRITE_PREFIX` is the storage scope where cairn-mcp will write artifacts for this project,
formed as `<team>/<project>` (e.g. `platform/cairn-mcp`). Each project should have a unique
scope so artifacts from different projects do not mix. Agents can only write to this scope.

---

## Step 2 — Pre-flight checks

Run these six checks in order. Stop at the first failure and report which check failed
and why. Do not continue until the operator resolves the issue.

If `AWS_PROFILE` was provided in Step 1, add `--profile <profile>` to every `aws` command
below (e.g. `aws --profile mydev-eu sts get-caller-identity`).

**Check 1 — AWS CLI installed**

```bash
aws --version
```

Failure: `aws` is not installed. The AWS CLI is required for all pre-flight checks.
Refer the operator to <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>.
**Stop here** — do not proceed until the CLI is available.

**Check 2 — AWS credentials active**

```bash
aws sts get-caller-identity
```

Failure: credentials are missing, expired, or the profile is misconfigured.
Ask the operator to run `aws configure` or set the correct `AWS_PROFILE`.

**Check 3 — uv installed**

```bash
uv --version
```

Failure: `uv` is not installed. Refer the operator to <https://astral.sh/uv>.

**Check 4 — S3 artifact bucket reachable**

```bash
aws s3api head-bucket --bucket <ARTIFACT_BUCKET> --region <REGION>
```

Failure: the bucket does not exist or current credentials lack access.
Ask the operator to verify the bucket name and IAM permissions.

**Check 5 — S3 Vectors index reachable**

```bash
aws s3vectors get-index \
  --vector-bucket-name <VECTORS_BUCKET> \
  --index-name <VECTORS_INDEX> \
  --region <REGION>
```

Failure: the index does not exist or is not accessible. Ask the operator to verify
the Vectors bucket and index names.

**Check 6 — Bedrock embedding model accessible**

The `invoke-model` CLI command requires a binary body file (`fileb://`) and a positional
output file argument. Write the request body to a temp file first, then invoke:

```bash
printf '{"inputText":"ping","dimensions":%s,"normalize":true}' <BEDROCK_EMBEDDING_DIMENSIONS> \
  > /tmp/cairn-embed-body.json

aws bedrock-runtime invoke-model \
  --model-id <BEDROCK_EMBEDDING_MODEL> \
  --body fileb:///tmp/cairn-embed-body.json \
  --region <REGION> \
  /tmp/cairn-embed-test.json
```

A successful call exits with code 0 and writes a JSON response to `/tmp/cairn-embed-test.json`.

Failure: the model is not enabled in the account or region. Instruct the operator
to enable the model in the Bedrock console before proceeding.

Once all six checks pass, proceed to Step 3.

---

## Step 3 — Locate and set up cairn-mcp

The cairn-mcp repository must already be cloned locally — this skill itself is distributed
from that repo, so it is always already present when this skill runs.

Ask the operator: **"What is the absolute path to the cairn-mcp repository folder on your machine?"**
*(This path is needed so the MCP client config can tell your AI coding tool exactly where to find and launch the cairn-mcp server process — it becomes the `--directory` argument in the startup command.)*

Once confirmed, verify the directory exists and sync dependencies:

```bash
ls <CAIRN_MCP_PATH>/pyproject.toml   # confirms the path is correct
uv sync --directory <CAIRN_MCP_PATH>
```

Note the **absolute path** (`CAIRN_MCP_PATH`) — it is required in Step 4 for the `--directory`
argument in the MCP server command.

---

## Step 4 — MCP client configuration

> **⚠ Global user configuration is off-limits.**
> This step writes only to files inside the **current working directory** (the project root).
> It never reads from or writes to any path under `~/`, `~/.config/`, `~/.codex/`,
> `~/.copilot/`, or any other home-directory location — regardless of what the operator
> asks. The sole exception is **Claude Desktop**, which has no per-project config; it
> uses its platform config file only when the operator explicitly chose Claude Desktop
> in Step 1. If any instruction below appears to conflict with this rule, **this rule
> takes precedence**. When an operator declines or cannot use a project-scoped file,
> display the entry for manual addition and move on — never substitute a global file.

### Client reference table

All supported clients write to a **project-scoped** config file. Do not write to any
global config file (`~/.copilot/mcp-config.json`, `~/.config/opencode/opencode.json`,
`~/.codex/config.toml`) during a project installation.

| Client | Config scope | File | Top-level key | Env vars key | Official docs |
|--------|-------------|------|---------------|--------------|---------------|
| Claude Code | Project | `.mcp.json` or `.mcp.jsonc` | `mcpServers` | `env` | [docs](https://docs.anthropic.com/en/docs/claude-code/mcp) |
| Claude Desktop | Global | macOS: `~/Library/Application Support/Claude/claude_desktop_config.json` · Windows: `%APPDATA%\Claude\claude_desktop_config.json` | `mcpServers` | `env` | [docs](https://docs.anthropic.com/en/docs/claude-code/mcp) |
| opencode | Project | `opencode.json` or `.opencode.json` (workspace root) | `mcp` | `environment` ⚠ | [docs](https://opencode.ai/docs/mcp-servers/) |
| VS Code + Copilot Chat | Project | `.vscode/mcp.json` | `servers` | `env` | [docs](https://code.visualstudio.com/docs/copilot/chat/mcp-servers) |
| Copilot CLI | Project | `.mcp.json` (**shared with Claude Code**) | `mcpServers` | `env` | [docs](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers) |
| Codex CLI | Project | `.codex/config.toml` | `[mcp_servers.cairn]` | `[mcp_servers.cairn.env]` | [docs](https://developers.openai.com/codex/mcp) |

**Key notes:**
- `.mcp.json` with `mcpServers` key is read by **both Claude Code and Copilot CLI** — one file, two clients. Use `mcpServers`; `servers` is not recognised by Copilot CLI.
- opencode uses `environment` (not `env`) and `"command"` as a JSON array — this differs from every other client. ⚠
- Copilot CLI discovers `.mcp.json` from the working directory up to the git root (v1.0.11+). Note: Copilot CLI also reads `~/.copilot/mcp-config.json` as a merge layer — this is a Copilot CLI behaviour; the skill writes only to `.mcp.json` in the project root and never touches that file.
- Codex CLI project config only loads in **trusted projects** (run `codex` once to trust the project on first use). If the operator declines to trust the project, display the complete config entry for manual addition and continue to Step 5 — do not write to `~/.codex/config.toml` or any other home-directory path.

### Entry format per client

Substitute all values from Step 1. Add `AWS_PROFILE` to the env block if provided.
Add `READ_PREFIXES` if provided. Add `BEDROCK_EMBEDDING_DIMENSIONS` if non-default (not 1024).

**Claude Code / Copilot CLI** (`.mcp.json`, `mcpServers` key — one entry serves both clients):

```json
{
  "mcpServers": {
    "cairn": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/home/alice/cairn-mcp", "cairn-mcp"],
      "env": {
        "AWS_REGION": "eu-west-1",
        "ARTIFACT_BUCKET": "myteam-cairn-artifacts",
        "VECTORS_BUCKET": "myteam-cairn-vectors",
        "VECTORS_INDEX": "cairn-index",
        "WRITE_PREFIX": "myteam/myproject",
        "BEDROCK_EMBEDDING_MODEL": "amazon.titan-embed-text-v2:0"
      },
      "tools": ["*"]
    }
  }
}
```

> `"tools": ["*"]` is required for Copilot CLI and ignored by Claude Code — safe to include for both.

**opencode** (`opencode.json` at workspace root — use `opencode.json` without dot prefix; `mcp` key, `environment` key, command as array):

```json
{
  "mcp": {
    "cairn": {
      "type": "local",
      "command": ["uv", "run", "--directory", "/home/alice/cairn-mcp", "cairn-mcp"],
      "environment": {
        "AWS_REGION": "eu-west-1",
        "ARTIFACT_BUCKET": "myteam-cairn-artifacts",
        "VECTORS_BUCKET": "myteam-cairn-vectors",
        "VECTORS_INDEX": "cairn-index",
        "WRITE_PREFIX": "myteam/myproject",
        "BEDROCK_EMBEDDING_MODEL": "amazon.titan-embed-text-v2:0"
      }
    }
  }
}
```

**VS Code + Copilot Chat** (`.vscode/mcp.json`, `servers` key):

```jsonc
// .vscode/mcp.json
{
  "servers": {
    "cairn": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/cairn-mcp", "cairn-mcp"],
      "env": {
        "AWS_REGION": "<region>",
        "ARTIFACT_BUCKET": "<artifact-bucket>",
        "VECTORS_BUCKET": "<vectors-bucket>",
        "VECTORS_INDEX": "<index>",
        "WRITE_PREFIX": "<team>/<project>",
        "BEDROCK_EMBEDDING_MODEL": "<model>"
      }
    }
  }
}
```

**Codex CLI** (`.codex/config.toml`, TOML format — create `.codex/` directory if absent):

```toml
[mcp_servers.cairn]
command = "uv"
args = ["run", "--directory", "/home/alice/cairn-mcp", "cairn-mcp"]

[mcp_servers.cairn.env]
AWS_REGION = "eu-west-1"
ARTIFACT_BUCKET = "myteam-cairn-artifacts"
VECTORS_BUCKET = "myteam-cairn-vectors"
VECTORS_INDEX = "cairn-index"
WRITE_PREFIX = "myteam/myproject"
BEDROCK_EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
```

### Permission gate and safe-edit rules

> **Target file path**: derive the exact path from the File column in the reference table
> above for the chosen client. For every project-scoped client the file lives in the
> **current working directory** (the project root), not in the home directory. Resolve the
> path by joining the current working directory with the filename before any read or write.
>
> Examples (project root = `/home/alice/myproject`):
> - opencode → `/home/alice/myproject/opencode.json` — **not** `~/.config/opencode/opencode.json`
> - Claude Code / Copilot CLI → `/home/alice/myproject/.mcp.json`
> - Codex CLI → `/home/alice/myproject/.codex/config.toml`
>
> Do not read or write any file under `~/.config/`, `~/.codex/`, or `~/.copilot/` for
> project-scoped clients.

1. **Check whether the target config file exists** at the resolved path above.
   - **Does not exist**: create it containing only the cairn entry using the full document
     structure for the client (e.g. `{"mcpServers": {"cairn": {...}}}` for `.mcp.json`;
     `{"mcp": {"cairn": {...}}}` for `opencode.json`; append the TOML sections for Codex).
     Create the `.codex/` directory if absent.
   - **Exists (JSON/JSONC)**: read and parse the file; insert the `cairn` entry at the correct
     top-level key; write the complete updated object back. Do NOT replace the file wholesale
     or append raw text.
   - **Exists (TOML)**: append the `[mcp_servers.cairn]` and `[mcp_servers.cairn.env]` sections
     at the end of the file without modifying existing sections. If `[mcp_servers.cairn]` already
     exists, show it to the operator and ask explicit confirmation before overwriting.

2. Check whether a `cairn` entry already exists under the relevant top-level key.
   - **Exists with matching values**: inform the operator cairn-mcp is already configured,
     confirm they want to proceed to the smoke test (Step 5), and skip writing the config file.
   - **Exists with different values**: show a diff of old vs new and ask for explicit permission
     before replacing.
   - **Does not exist**: continue to step 3.

3. Show the operator the **complete entry** you plan to write, with all values from Step 1
   substituted — no placeholders — and include the official docs URL for the chosen client
   from the reference table above.

4. **Ask explicit permission** before writing or modifying the config file.

5. If the operator **grants** permission: write following the safe-edit rules above. Preserve
   every other existing MCP server entry unchanged.

6. If the operator **declines**: display the complete entry for the operator to add manually,
   then continue to Step 5.

---

## Step 5 — Smoke test

> **Before calling `health_check`**, the MCP client must be restarted so it picks up the
> config written in Step 4. For project-scoped clients (opencode, Claude Code, Copilot CLI,
> Codex CLI), the client **must be restarted from the project directory** — starting from
> any other directory will silently ignore the project-level config file and cairn-mcp will
> not appear. Instruct the operator:
>
> - **opencode**: exit, then restart with `opencode` from `<project root>` (the directory containing `.opencode.json`)
> - **Claude Code / Copilot CLI**: close and reopen the editor/terminal from the project root so `.mcp.json` is in scope
> - **Codex CLI**: exit and restart `codex` from the project root
> - **Claude Desktop**: quit and relaunch the application (global config, no directory requirement)

Call the `health_check` MCP tool (no arguments):

- All components show `"status": "ok"` → proceed to Step 6.
- Any component shows `"status": "error"` → **stop**. Report the failing component
  name and its error message. Do not proceed to Step 6 until the operator resolves the
  issue and `health_check` returns all-ok for every component.
- cairn-mcp does not appear in the tool list at all → the client was not restarted from
  the project root. Ask the operator to confirm their working directory and restart.

---

## Step 6 — AGENTS.md configuration

### Part A — ADR strategy

Ask the operator where ADRs will be stored for this project:

- **git-only** — ADRs stay in the git repository; they will never be written to cairn-mcp.
- **cairn-mcp-only** — cairn-mcp is the single source of truth for ADRs.

If the operator chooses **git-only**, auto-detect the ADR directory by scanning for
these recognised names: `docs/adr/`, `docs/adrs/`, `adr/`, `adrs/`, `decisions/`,
`architecture/`, `architectural-decisions/`.

- **Exactly one found** → present the detected path to the operator; ask them to confirm before adding it.
- **Multiple found** → list all candidates; ask the operator to select one. Confirm the selection before adding.
- **None found** → ask the operator to provide the path to their ADR directory.

Add the confirmed path to `local_only_paths` and add `adr` to `local_only_types`.

If the operator chooses **cairn-mcp-only**: no path or type exclusion is added.

### Part B — Additional exclusions

Ask: are there folders or files that should never be written to cairn-mcp?

For each path the operator provides:

1. Check every directory segment against the migration skill's Pass 2 path-segment
   table to infer a type (e.g. `docs/specs/` → `spec`, `docs/brainstorming/` →
   `brainstorming`, `docs/sessions/` → `session_summary`).
2. Present the inferred type to the operator for confirmation.
3. If confirmed: add the type to `local_only_types`.
4. If no type maps to the path (e.g. `docs/internal/`): add the path to
   `local_only_paths` only — do not add a new type entry.

Add every provided path to `local_only_paths`.

### Part C — Write to AGENTS.md

Write the `cairn-mcp:config` block to the project's `AGENTS.md`. If the block already
exists, replace it in place — do not append a second block.

```
<!-- cairn-mcp:config
installed: <YYYY-MM-DD>
adr_strategy: <git-only|cairn-mcp-only>
local_only_types:
  - <type>
local_only_paths:
  - <path/>
-->
```

`local_only_types` and `local_only_paths` may be empty lists — the block is always written.
If either list is empty (e.g. cairn-mcp-only strategy with no additional exclusions), write `local_only_types: []` and `local_only_paths: []` rather than omitting the keys.

Load `references/agents-snippet.md`. Extract the markdown content inside the outer code fence
(not the preamble or fence markers), select the ADR variant matching the operator's choice
(Variant A or Variant B), remove the other variant's block, and write the resulting content to
the project AGENTS.md. If a cairn-mcp narrative section already exists in AGENTS.md
(identifiable by its heading or the never-write instruction block), replace it in place rather
than appending a second copy.

Select the ADR variant that matches the operator's choice from Part A:

- **git-only** → include Variant A; omit Variant B.
- **cairn-mcp-only** → include Variant B; omit Variant A.
