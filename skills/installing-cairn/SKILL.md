---
name: installing-cairn
description: Connect cairn-mcp to your project — validate AWS resource connectivity, configure your MCP client, and write AGENTS.md usage guidance.
---

# Installing cairn-mcp

This skill connects cairn-mcp to a project, assuming all required AWS resources (S3 bucket,
S3 Vectors bucket and index, and Bedrock model access) are already provisioned externally.
It validates every resource is reachable before writing any configuration, writes the
cairn-mcp server entry into the IDE's MCP config file, runs a health check, and closes by
writing a machine-readable `cairn-mcp:config` block and usage guidance to `AGENTS.md`.

---

## Step 1 — Parameter collection

Collect all parameters **before** any AWS call or file write.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `AWS_REGION` | AWS region for all services | — (required) |
| `ARTIFACT_BUCKET` | S3 bucket name for artifact content (must exist) | — (required) |
| `VECTORS_BUCKET` | S3 Vectors bucket name (must exist) | — (required) |
| `VECTORS_INDEX` | S3 Vectors index name (must exist) | — (required) |
| `BEDROCK_EMBEDDING_MODEL` | Bedrock embedding model ID | `amazon.titan-embed-text-v2:0` |
| `BEDROCK_EMBEDDING_DIMENSIONS` | Embedding dimension | `1024` |
| `AWS_PROFILE` | AWS CLI named profile | — (optional) |
| IDE | Target MCP client | — (required) |
| Team name | Used to form `WRITE_PREFIX` | — (required) |
| Project name | Used to form `WRITE_PREFIX` | — (required) |
| `READ_PREFIXES` | Comma-separated prefixes for cross-team reads | — (optional) |

Valid IDE choices: **Claude Code**, **Claude Desktop**, **OpenCode**,
**VS Code + Copilot Chat**, **Copilot CLI**, **Codex CLI**.

`WRITE_PREFIX` is formed as `<team>/<project>` (e.g. `platform/cairn-mcp`).

Do not proceed to Step 2 until all required parameters are confirmed.

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

Ask the operator: **"What is the absolute path to the cairn-mcp directory on your machine?"**

Once confirmed, verify the directory exists and sync dependencies:

```bash
ls <CAIRN_MCP_PATH>/pyproject.toml   # confirms the path is correct
uv sync --directory <CAIRN_MCP_PATH>
```

Note the **absolute path** (`CAIRN_MCP_PATH`) — it is required in Step 4 for the `--directory`
argument in the MCP server command.

---

## Step 4 — MCP client configuration

### IDE reference table

| IDE | Config file | Top-level key | Env vars key |
|-----|-------------|---------------|--------------|
| Claude Code | `.mcp.json` (project root) | `mcpServers` | `env` |
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) · `%APPDATA%\Claude\claude_desktop_config.json` (Windows) | `mcpServers` | `env` |
| OpenCode | `~/.config/opencode/opencode.json` or `.jsonc` | `mcp` | `environment`; command is a single array |
| VS Code + Copilot Chat | `.vscode/mcp.json` (project root) | `servers` | `env` |
| Copilot CLI | `~/.copilot/mcp-config.json` | `mcpServers` | `env`; add `"tools": ["*"]` |
| Codex CLI | `~/.codex/config.toml` | `[mcp_servers.cairn]` | `[mcp_servers.cairn.env]` sub-table |

### Entry format per IDE

Substitute all values from Step 1. The examples below use representative values;
replace them with the actual values collected in Step 1.

**Claude Code / Claude Desktop** (`.mcp.json` or `claude_desktop_config.json`,
`mcpServers` key):

```json
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
  }
}
```

**OpenCode** (`~/.config/opencode/opencode.json`, `mcp` key, `environment`,
command as a single array):

```json
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
```

**VS Code + Copilot Chat** (`.vscode/mcp.json`, `servers` key, `env`):

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

**Copilot CLI** (`~/.copilot/mcp-config.json`, `mcpServers` key, add `"tools": ["*"]`):

```json
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
```

**Codex CLI** (`~/.codex/config.toml`, TOML format):

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

Add `AWS_PROFILE` to the env block if provided in Step 1.
Add `READ_PREFIXES` to the env block if provided in Step 1.
Add `BEDROCK_EMBEDDING_DIMENSIONS` to the env block if a non-default value (not 1024) was provided in Step 1.

### Permission gate

1. **Read the current config file** before writing anything. Check whether a `cairn` entry
   already exists under the relevant top-level key for the chosen IDE.
   - If a `cairn` entry exists **and its env values match all parameters from Step 1**:
     inform the operator that cairn-mcp is already configured, confirm they want to proceed
     to the smoke test (Step 5), and **skip writing the config file**.
   - If a `cairn` entry exists **but with different parameter values**: show a diff of the
     old vs new values and ask for explicit permission before replacing it.
   - If **no `cairn` entry exists**: continue to step 2 below.
2. Show the operator the complete entry you plan to write, with all values substituted
   from Step 1 — no placeholders.
3. **Ask explicit permission before writing or modifying the config file.**
4. If the operator **grants** permission: merge the cairn entry into the existing config.
   Preserve every other existing MCP server entry unchanged.
5. If the operator **declines**: display the complete entry for the operator to add
   manually, then continue to Step 5.

---

## Step 5 — Smoke test

Call the `health_check` MCP tool (no arguments):

- All components show `"status": "ok"` → proceed to Step 6.
- Any component shows `"status": "error"` → **stop**. Report the failing component
  name and its error message. Do not proceed to Step 6 until the operator resolves the
  issue and `health_check` returns all-ok for every component.

If the IDE config was added manually in Step 4, restart the IDE before calling
`health_check`.

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
