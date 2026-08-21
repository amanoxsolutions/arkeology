---
name: setting-up-arkeology
description: Connect Arkeology to your project — validate AWS resource connectivity, configure your MCP client, and write AGENTS.md usage guidance.
---

# Setting up Arkeology

This skill connects Arkeology to a project, assuming all required AWS resources (S3 bucket,
S3 Vectors bucket and index, and Bedrock model access) are already provisioned externally.
It validates every resource is reachable before writing any configuration, writes a
project-scoped Arkeology server entry into the correct MCP client config file (all four
supported clients write to the project root — Claude Code and GitHub Copilot CLI share
`.mcp.json`, opencode uses `.opencode.json`, Codex CLI uses `.codex/config.toml`), writes
a machine-readable `arkeology:config` block and usage guidance to `AGENTS.md`, then asks
for a single restart to pick up both files before confirming everything is healthy.

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
> Copilot CLI. Writing it once gives both clients access to Arkeology without any extra
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
| `BEDROCK_TEXT_MODEL` | Bedrock text generation model for auto-generating artifact descriptions during migration. Only invoked by the `migrating-to-arkeology` skill — it has no effect on normal Arkeology operation. Without it the migration skill blocks for any project with more than 10 documentation files. **Cross-region inference profiles are required in most regions outside `us-east-1`** — use a region-prefixed model ID such as `eu.amazon.nova-lite-v1:0` (EU) or `us.amazon.nova-lite-v1:0` (US cross-region) rather than the bare `amazon.nova-lite-v1:0`. | — (required) |
| `AWS_PROFILE` | AWS CLI named profile | — (optional) |
| Team name | The name of your team or organisation (e.g. `platform`, `acme`) | — (required) |
| Project name | The name of this project (e.g. `api-gateway`, `arkeology`) | — (required) |
| `READ_PREFIXES` | Other teams' scopes whose shared artifacts agents in this project can search. Leave blank if you only need your own project's artifacts. To populate this: ask each team you want to read from for their `WRITE_PREFIX` value (e.g. `platform/shared-patterns`), then comma-separate them here. | — (optional) |

`WRITE_PREFIX` is the storage scope where Arkeology will write artifacts for this project,
formed as `<team>/<project>` (e.g. `platform/arkeology`). Each project should have a unique
scope so artifacts from different projects do not mix. Agents can only write to this scope.

---

## Step 2 — Pre-flight checks

Run these eight checks in order. **Checks 1–7 are blocking** — stop at the first failure
and report which check failed and why; do not continue until the operator resolves the
issue. **Check 8 is feature-level and non-blocking** (see its own section below) — S3
object annotations back only the `commit_refs` / `references` link-tracking feature, not
the core content/vector/embedding store, so a Check 8 failure never stops the
installation (ADR-011 decision 5: annotation availability is never a hard startup gate).

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
  > /tmp/arkeology-embed-body.json

aws bedrock-runtime invoke-model \
  --model-id <BEDROCK_EMBEDDING_MODEL> \
  --body fileb:///tmp/arkeology-embed-body.json \
  --region <REGION> \
  /tmp/arkeology-embed-test.json
```

A successful call exits with code 0 and writes a JSON response to `/tmp/arkeology-embed-test.json`.

Failure: the model is not enabled in the account or region. Instruct the operator
to enable the model in the Bedrock console before proceeding.

**Check 7 — Bedrock text model accessible**

Uses the Nova message format (same request shape as Arkeology's `invoke_text_model`).
Note: the `"type"` key is intentionally omitted from the content object — cross-region
inference profiles reject it. Write the request body first, then invoke:

```bash
printf '{"messages":[{"role":"user","content":[{"text":"ping"}]}],"inferenceConfig":{"maxTokens":1}}' \
  > /tmp/arkeology-text-body.json

aws bedrock-runtime invoke-model \
  --model-id <BEDROCK_TEXT_MODEL> \
  --body fileb:///tmp/arkeology-text-body.json \
  --region <REGION> \
  /tmp/arkeology-text-test.json
```

A successful call exits with code 0 and writes a JSON response to `/tmp/arkeology-text-test.json`.

Failure: the model is not enabled in the account or region, or the model ID uses the wrong
format (e.g. bare `amazon.nova-lite-v1:0` instead of the cross-region inference profile
`eu.amazon.nova-lite-v1:0` for EU). Instruct the operator to enable the model in the
Bedrock console and verify the model ID format before proceeding.

**Check 8 — S3 object annotation availability + IAM (feature-level, non-blocking)**

S3 object annotations are the durable store behind Arkeology's `commit_refs` /
`references` link-tracking feature (`link_metadata`, and the write path's automatic
link-field persistence). They require four IAM actions beyond core S3 storage, and are
unavailable in some regions and on some bucket types — none of which affects the core
memory server (content, search, embeddings). This check probes both, but **unlike
Checks 1–7, a failure here does not stop the installation** — report the outcome and let
the operator decide whether to proceed; the feature simply degrades gracefully at
runtime (a `warning` on `write_artifact`, a structured error from `link_metadata`).

The four required IAM actions:

- `s3:PutObjectAnnotation`
- `s3:GetObjectAnnotation`
- `s3:ListObjectAnnotations`
- `s3:DeleteObjectAnnotation`

Annotations are **unavailable** in the UAE and Bahrain regions, and on **S3 Express One
Zone**, **Outposts**, and **directory** buckets — no IAM change fixes a bucket in one of
these categories; the operator must accept the degraded feature or relocate the bucket.

First determine the AWS CLI version already captured in Check 1:

```bash
AWS_CLI_VERSION=$(aws --version 2>&1 | sed -E 's#.*aws-cli/([0-9.]+).*#\1#')
if [ "$(printf '%s\n' "2.35.14" "$AWS_CLI_VERSION" | sort -V | head -n1)" = "2.35.14" ]; then
  echo "native"   # aws-cli >= 2.35.14 — use the CLI's native annotation commands below
else
  echo "fallback"  # older aws-cli — annotation subcommands are absent; use the boto3 fallback
fi
```

**If `native`** (aws-cli ≥ 2.35.14), put→get→delete a throwaway annotation on a throwaway
object directly with the CLI. The probe writes a real object into the deployment's own
`WRITE_PREFIX`, so it comes in two blocks: the probe itself, then a cleanup block that
**always runs**.

Block 1 — the probe. Every command tolerates its own failure so the run reaches cleanup:

```bash
printf 'arkeology-probe' > /tmp/arkeology-annotation-probe.txt

aws s3api put-object --bucket <ARTIFACT_BUCKET> \
  --key "<WRITE_PREFIX>/_arkeology_annotation_probe" --body /dev/null --region <REGION> \
  || echo "ANNOTATIONS_FAILED: probe object could not be created — see the error above"

aws s3api put-object-annotation --bucket <ARTIFACT_BUCKET> \
  --key "<WRITE_PREFIX>/_arkeology_annotation_probe" \
  --annotation-name arkeology_probe --annotation-payload fileb:///tmp/arkeology-annotation-probe.txt \
  --region <REGION> \
  || echo "ANNOTATIONS_FAILED: put-object-annotation — read the error code above"

aws s3api get-object-annotation --bucket <ARTIFACT_BUCKET> \
  --key "<WRITE_PREFIX>/_arkeology_annotation_probe" \
  --annotation-name arkeology_probe --region <REGION> /tmp/arkeology-annotation-probe-out.txt \
  && diff /tmp/arkeology-annotation-probe.txt /tmp/arkeology-annotation-probe-out.txt \
  && echo "ANNOTATIONS_OK" \
  || echo "ANNOTATIONS_FAILED: annotation round-trip — read the error code above"
```

Block 2 — cleanup. **Run this block unconditionally**, before reporting the check's result:
run it when Block 1 printed `ANNOTATIONS_OK`, and equally when it printed
`ANNOTATIONS_FAILED` for any reason including `AccessDenied`. A failed probe still leaves
the probe object behind — abandoning the sequence at the first error is what strands it.

```bash
aws s3api delete-object-annotation --bucket <ARTIFACT_BUCKET> \
  --key "<WRITE_PREFIX>/_arkeology_annotation_probe" \
  --annotation-name arkeology_probe --region <REGION> 2>/dev/null || true

aws s3api delete-object --bucket <ARTIFACT_BUCKET> \
  --key "<WRITE_PREFIX>/_arkeology_annotation_probe" --region <REGION> \
  && echo "PROBE_CLEANUP_OK" \
  || echo "PROBE_CLEANUP_FAILED: <WRITE_PREFIX>/_arkeology_annotation_probe still exists"

rm -f /tmp/arkeology-annotation-probe.txt /tmp/arkeology-annotation-probe-out.txt
```

**If `fallback`** (aws-cli < 2.35.14 — the CLI's annotation subcommands are absent, but
botocore supports the underlying APIs regardless of CLI version), run the equivalent
probe through boto3 via `uv run` — no dependency on the Arkeology repo being cloned yet,
since `--with boto3` installs it into a throwaway environment:

```bash
uv run --with boto3 python - <<'PYEOF'
import boto3
import botocore.exceptions

region = "<REGION>"
profile = "<AWS_PROFILE>"  # omit profile_name entirely if no AWS_PROFILE was provided
bucket = "<ARTIFACT_BUCKET>"
key = "<WRITE_PREFIX>/_arkeology_annotation_probe"

session = boto3.Session(profile_name=profile, region_name=region)
s3 = session.client("s3")
try:
    s3.put_object(Bucket=bucket, Key=key, Body=b"")
    s3.put_object_annotation(Bucket=bucket, Key=key, AnnotationName="arkeology_probe", AnnotationPayload=b"arkeology-probe")
    payload = s3.get_object_annotation(Bucket=bucket, Key=key, AnnotationName="arkeology_probe")["AnnotationPayload"].read()
    print("ANNOTATIONS_OK" if payload == b"arkeology-probe" else f"ANNOTATIONS_FAILED: unexpected payload {payload!r}")
    s3.delete_object_annotation(Bucket=bucket, Key=key, AnnotationName="arkeology_probe")
except botocore.exceptions.ClientError as exc:
    code = exc.response.get("Error", {}).get("Code", "")
    print(f"ANNOTATIONS_FAILED: {code} — {exc}")
finally:
    s3.delete_object(Bucket=bucket, Key=key)
PYEOF
```

Interpreting the result:

- **`ANNOTATIONS_OK`** — annotations are available and IAM is correctly configured.
  `commit_refs` / `references` will be durably tracked. Continue to Step 3.
- **`ANNOTATIONS_FAILED: AccessDenied ...`** — the bucket/region supports annotations but
  the caller's IAM policy is missing one or more of the four actions listed above. Show
  the operator the failing action and ask them to add it to the deployment's IAM policy,
  then re-run this check. Or, if they choose, proceed anyway — `link_metadata` will
  return a structured `annotation_unavailable` error and `write_artifact` will succeed
  with a `warning` until the policy is fixed.
- **`ANNOTATIONS_FAILED: NotImplemented ...`** (or a similar region/bucket-type
  rejection) — the bucket's region or type does not support annotations at all (see the
  unavailable list above). No IAM change will fix this. Inform the operator the
  `commit_refs` / `references` feature will not be durable on this bucket — core memory
  (content, search, embeddings) is fully unaffected — and let them decide whether to
  proceed, migrate to a supported bucket/region, or accept the limitation.
- Any other failure (e.g. the throwaway object/bucket itself is unreachable) — report the
  raw error and let the operator decide whether it is safe to proceed; this check never
  blocks Step 3 by itself.
- **`PROBE_CLEANUP_FAILED`** (aws-cli path), or a `delete_object` error from the boto3
  path's `finally:` block — the probe object could not be removed and is still in the
  bucket. Report the exact key, `<WRITE_PREFIX>/_arkeology_annotation_probe`, and give the
  operator the command to remove it themselves:

  ```bash
  aws s3api delete-object --bucket <ARTIFACT_BUCKET> \
    --key "<WRITE_PREFIX>/_arkeology_annotation_probe" --region <REGION>
  ```

  A surviving probe object is harmless to the server — `reconcile_index` skips every key
  whose final path segment begins with `_arkeology_`, so it is never mistaken for an
  artifact — but never leave one behind silently.

Once Checks 1–7 pass, proceed to Step 3 (Check 8's outcome is reported but never blocks
progression).

---

## Step 3 — Locate and set up Arkeology

The Arkeology repository must already be cloned locally — this skill itself is distributed
from that repo, so it is always already present when this skill runs.

Ask the operator: **"What is the absolute path to the Arkeology repository folder on your machine?"**
*(This path is needed so the MCP client config can tell your AI coding tool exactly where to find and launch the Arkeology server process — it becomes the `--directory` argument in the startup command.)*

Once confirmed, verify the directory exists and sync dependencies:

```bash
ls <ARKEOLOGY_MCP_PATH>/pyproject.toml   # confirms the path is correct
uv sync --directory <ARKEOLOGY_MCP_PATH>
```

Note the **absolute path** (`ARKEOLOGY_MCP_PATH`) — it is required in Step 4 for the `--directory`
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
| Codex CLI | Project | `.codex/config.toml` | `[mcp_servers.arkeology]` | `[mcp_servers.arkeology.env]` | [docs](https://developers.openai.com/codex/mcp) |

**Key notes:**
- `.mcp.json` with `mcpServers` key is read by **both Claude Code and Copilot CLI** — one file, two clients. Use `mcpServers`; `servers` is not recognised by Copilot CLI.
- opencode uses `environment` (not `env`) and `"command"` as a JSON array — this differs from every other client. ⚠
- Copilot CLI discovers `.mcp.json` from the working directory up to the git root (v1.0.11+). Note: Copilot CLI also reads `~/.copilot/mcp-config.json` as a merge layer — this is a Copilot CLI behaviour; the skill writes only to `.mcp.json` in the project root and never touches that file.
- Codex CLI project config only loads in **trusted projects** (run `codex` once to trust the project on first use). If the operator declines to trust the project, display the complete config entry for manual addition and continue to Step 5 — do not write to `~/.codex/config.toml` or any other home-directory path.

### Entry format per client

Substitute all values from Step 1. Add `AWS_PROFILE` to the env block if provided.
Add `READ_PREFIXES` if provided. Add `BEDROCK_EMBEDDING_DIMENSIONS` if non-default (not 1024).
Always include `BEDROCK_TEXT_MODEL` (it is only invoked by the `migrating-to-arkeology` skill but is required by the setup).

**Claude Code / Copilot CLI** (`.mcp.json`, `mcpServers` key — one entry serves both clients):

```json
{
  "mcpServers": {
    "arkeology": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/home/alice/arkeology", "arkeology"],
      "env": {
        "AWS_REGION": "eu-west-1",
        "ARTIFACT_BUCKET": "myteam-arkeology-artifacts",
        "VECTORS_BUCKET": "myteam-arkeology-vectors",
        "VECTORS_INDEX": "arkeology-index",
        "WRITE_PREFIX": "myteam/myproject",
        "BEDROCK_EMBEDDING_MODEL": "amazon.titan-embed-text-v2:0",
        "BEDROCK_TEXT_MODEL": "eu.amazon.nova-lite-v1:0"
      },
      "tools": ["*"]
    }
  }
}
```

> `"tools": ["*"]` is required for Copilot CLI and ignored by Claude Code — safe to include for both.
> `BEDROCK_TEXT_MODEL` is only invoked by the `migrating-to-arkeology` skill and has no effect on normal operation.
> Use a cross-region inference profile ID for your region (e.g. `eu.amazon.nova-lite-v1:0` for EU,
> `us.amazon.nova-lite-v1:0` for US cross-region). The bare `amazon.nova-lite-v1:0` only works in `us-east-1`.

**opencode** (`opencode.json` at workspace root — use `opencode.json` without dot prefix; `mcp` key, `environment` key, command as array):

```json
{
  "mcp": {
    "arkeology": {
      "type": "local",
      "command": ["uv", "run", "--directory", "/home/alice/arkeology", "arkeology"],
      "environment": {
        "AWS_REGION": "eu-west-1",
        "ARTIFACT_BUCKET": "myteam-arkeology-artifacts",
        "VECTORS_BUCKET": "myteam-arkeology-vectors",
        "VECTORS_INDEX": "arkeology-index",
        "WRITE_PREFIX": "myteam/myproject",
        "BEDROCK_EMBEDDING_MODEL": "amazon.titan-embed-text-v2:0",
        "BEDROCK_TEXT_MODEL": "eu.amazon.nova-lite-v1:0"
      }
    }
  }
}
```

> `BEDROCK_TEXT_MODEL` is only invoked by the `migrating-to-arkeology` skill and has no effect on normal operation.
> Use a cross-region inference profile ID for your region (e.g. `eu.amazon.nova-lite-v1:0` for EU,
> `us.amazon.nova-lite-v1:0` for US cross-region). The bare `amazon.nova-lite-v1:0` only works in `us-east-1`.

**VS Code + Copilot Chat** (`.vscode/mcp.json`, `servers` key):

```jsonc
// .vscode/mcp.json
{
  "servers": {
    "arkeology": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/arkeology", "arkeology"],
      "env": {
        "AWS_REGION": "<region>",
        "ARTIFACT_BUCKET": "<artifact-bucket>",
        "VECTORS_BUCKET": "<vectors-bucket>",
        "VECTORS_INDEX": "<index>",
        "WRITE_PREFIX": "<team>/<project>",
        "BEDROCK_EMBEDDING_MODEL": "<model>",
        "BEDROCK_TEXT_MODEL": "<cross-region-text-model>"
      }
    }
  }
}
```

> `BEDROCK_TEXT_MODEL` is only invoked by the `migrating-to-arkeology` skill and has no effect on normal operation.
> Use a cross-region inference profile ID for your region (e.g. `eu.amazon.nova-lite-v1:0` for EU).

**Codex CLI** (`.codex/config.toml`, TOML format — create `.codex/` directory if absent):

```toml
[mcp_servers.arkeology]
command = "uv"
args = ["run", "--directory", "/home/alice/arkeology", "arkeology"]

[mcp_servers.arkeology.env]
AWS_REGION = "eu-west-1"
ARTIFACT_BUCKET = "myteam-arkeology-artifacts"
VECTORS_BUCKET = "myteam-arkeology-vectors"
VECTORS_INDEX = "arkeology-index"
WRITE_PREFIX = "myteam/myproject"
BEDROCK_EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
# Only invoked by the migrating-to-arkeology skill — no effect on normal operation.
# Use a cross-region inference profile ID for your region (e.g. eu.amazon.nova-lite-v1:0 for EU).
BEDROCK_TEXT_MODEL = "eu.amazon.nova-lite-v1:0"
```

### Permission gate and safe-edit rules

> **Target file path**: derive from the File column in the client reference table above.
> For every project-scoped client the file lives in the **current working directory**
> (the project root). Resolve the absolute path before any read or write. Do not read
> or write any file under `~/.config/`, `~/.codex/`, or `~/.copilot/`.

1. **Check whether the target config file exists** at the resolved path above.
   - **Does not exist**: create it containing only the Arkeology entry using the full document
     structure for the client (e.g. `{"mcpServers": {"arkeology": {...}}}` for `.mcp.json`;
     `{"mcp": {"arkeology": {...}}}` for `opencode.json`; append the TOML sections for Codex).
     Create the `.codex/` directory if absent.
   - **Exists (JSON/JSONC)**: read and parse the file; insert the `arkeology` entry at the correct
     top-level key; write the complete updated object back. Do NOT replace the file wholesale
     or append raw text.
   - **Exists (TOML)**: append the `[mcp_servers.arkeology]` and `[mcp_servers.arkeology.env]` sections
     at the end of the file without modifying existing sections. If `[mcp_servers.arkeology]` already
     exists, show it to the operator and ask explicit confirmation before overwriting.

2. Check whether a `arkeology` entry already exists under the relevant top-level key.
   - **Exists with matching values**: inform the operator Arkeology is already configured,
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

## Step 5 — AGENTS.md configuration

### Part A — ADR strategy

Ask the operator where ADRs will be stored for this project:

- **git-only** — ADRs stay in the git repository; they will never be written to Arkeology.
- **arkeology-only** — Arkeology is the single source of truth for ADRs.

If the operator chooses **git-only**, auto-detect the ADR directory by scanning for
these recognised names: `docs/adr/`, `docs/adrs/`, `adr/`, `adrs/`, `decisions/`,
`architecture/`, `architectural-decisions/`.

- **Exactly one found** → present the detected path to the operator; ask them to confirm before adding it.
- **Multiple found** → list all candidates; ask the operator to select one. Confirm the selection before adding.
- **None found** → ask the operator to provide the path to their ADR directory.

Add the confirmed path to `local_only_paths` and add `adr` to `local_only_types`.

If the operator chooses **arkeology-only**: no path or type exclusion is added.

### Part B — Additional exclusions

Ask: are there folders or files that should never be written to Arkeology?

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

> **Target file:** `AGENTS.md` in the **current working directory** (the project being
> set up — never the Arkeology repo's own AGENTS.md). Resolve the absolute path before
> reading or writing. Create the file if it does not exist.

Write the `arkeology:config` block to that file. If the block already exists, replace
it in place — do not append a second block.

```
<!-- arkeology:config
installed: <YYYY-MM-DD>
team: <team>
project: <project>
adr_strategy: <git-only|arkeology-only>
local_only_types:
  - <type>
local_only_paths:
  - <path/>
-->
```

`local_only_types` and `local_only_paths` may be empty lists — the block is always written.
If either list is empty (e.g. arkeology-only strategy with no additional exclusions), write `local_only_types: []` and `local_only_paths: []` rather than omitting the keys.

Load `references/agents-snippet.md`. Extract the markdown content inside the outer code fence
(not the preamble or fence markers), select the ADR variant matching the operator's choice
(**git-only** → Variant A; **arkeology-only** → Variant B), remove the other variant's block,
and write the resulting content to the project AGENTS.md. If an Arkeology narrative section
already exists in AGENTS.md (identifiable by its heading or the never-write instruction block),
replace it in place rather than appending a second copy.

### Part D — Update Documentation and Scratchpad keys

Scan the entire `AGENTS.md` for lines matching `**Documentation:**` and `**Scratchpad:**`
(regardless of which section they appear in). Update or add them automatically — no
operator confirmation required.

**Scratchpad** — always set to `arkeology`.

**Documentation** — derive from `local_only_types` and `local_only_paths` (Parts A and B).
Tier 3 types: `spec`, `adr`, `decision_note`, `synthesis`, `plan`, `vision`, `requirements`, `runbook`, `learning`.

| Condition | New value |
|-----------|-----------|
| `local_only_types` and `local_only_paths` both empty | `arkeology` |
| Every tier 3 type in `local_only_types` | leave unchanged (or use existing local value if key was absent) |
| Mixed — some tier 3 types stay local | `arkeology, <existing-local-value>` |

For the mixed case, read the existing `**Documentation:**` value from the file and
prefix it — e.g. `arkeology, docs/`.

**Key already present**: update in place. **Key absent**: add it under the `## Agent Settings`
section if one exists (insert missing line(s) as bullet items). If no `## Agent Settings`
section exists, create it near the top of the file (after the first heading or project overview)
with both keys:

```markdown
## Agent Settings
- **Documentation:** <value>
- **Scratchpad:** arkeology
```

---

## Step 6 — Smoke test

> **One restart picks up both changes.** The MCP client must now be restarted to load
> the config written in Step 4 **and** the AGENTS.md written in Step 5 together. For
> project-scoped clients (opencode, Claude Code, Copilot CLI, Codex CLI), the client
> **must be restarted from the project directory** — starting from any other directory
> will silently ignore the project-level config file and Arkeology will not appear.
> Instruct the operator:
>
> - **opencode**: exit, then restart with `opencode` from `<project root>` (the directory containing `opencode.json` or `.opencode.json`)
> - **Claude Code / Copilot CLI**: close and reopen the editor/terminal from the project root so `.mcp.json` is in scope
> - **Codex CLI**: exit and restart `codex` from the project root
> - **Claude Desktop**: quit and relaunch the application (global config, no directory requirement)

Call the `health_check` MCP tool (no arguments):

- All components show `"status": "ok"` → installation complete.
- Any component shows `"status": "error"` → **stop**. Report the failing component
  name and its error message. Do not declare installation complete until the operator
  resolves the issue and `health_check` returns all-ok for every component.
- Arkeology does not appear in the tool list at all → the client was not restarted from
  the project root. Ask the operator to confirm their working directory and restart.
