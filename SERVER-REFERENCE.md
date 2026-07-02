# cairn-mcp — Server Reference

Tool reference, configuration, IAM policy, and headless server setup for cairn-mcp
operators and CI/CD pipeline integrations.

## Tools

Agents connect via the Model Context Protocol and call the following tools. The server
also exposes MCP Resources in two categories: five schema resources that serve
always-current documentation to agents (no AWS calls), and two data resources that
serve browsable artifact content to humans — see [Resources](#resources) below.

| Tool | What it does | Key inputs | Key outputs |
|---|---|---|---|
| `write_artifact` | Store an artifact in S3 and index it in S3 Vectors | `type`, `team`, `project`, `tier`, `title`, `content`, `visibility`, optional filters | `artifact_id`, `sections_indexed` |
| `write_artifacts` | Bulk-write multiple artifacts in a single call with per-entry success/error reporting | list of artifact descriptors; optional `artifact_concurrency` (default `3`, max `15`) | per-artifact list of `artifact_id` + `written: true` or `error`; top-level `warning` if `artifact_concurrency` was out of range |
| `migrate_artifacts` | Migration-specific bulk write; generates descriptions server-side via Bedrock when omitted; `dry_run=True` previews enriched descriptors without writing | list of artifact descriptors, `dry_run`; optional `artifact_concurrency` (default `3`, max `15`) | enriched descriptor list (dry run) or per-artifact write results; top-level `warning` if `artifact_concurrency` was out of range |
| `search_artifacts` | Semantic search over the vector index with optional metadata filters | `query`, optional: `type`, `tags`, `team`, `project`, `tier`, `status`, `top_k` | List of artifact metadata (no content) |
| `read_artifact` | Fetch the full content of an artifact by ID | `artifact_id` | Full artifact dict including `content` |
| `list_artifacts` | List artifact metadata with optional filters; defaults to active artifacts | optional: `type`, `team`, `project`, `tier`, `status`, `tags` | List of artifact metadata records |
| `archive_artifact` | Set an artifact's status to inactive (own scope only) | `artifact_id` | Confirmation with updated `artifact_id` |
| `delete_artifact` | Hard-delete an artifact from S3 and S3 Vectors; warns if referenced by a synthesis | `artifact_id`, `confirm=True` | Deletion confirmation |
| `purge_archived` | Bulk-delete all inactive artifacts in own scope; cascade-deletes orphaned syntheses | `confirm=True` | Count of deleted artifacts and syntheses |
| `health_check` | Per-component connectivity status (S3, vectors, Bedrock, write prefix, read prefixes) | — | Status dict; never raises |
| `synthesise_artifacts` | Semantic search followed by full S3 content fetch for a set of top-k artifacts | `query`, optional: filters, `top_k` (clamped to 100) | List of full artifact dicts including `content` |
| `reconcile_index` | Replay the failure log and scan for orphaned S3 objects, re-indexing any artifacts present in S3 but absent from the vector index | — | `reconciled` (list of re-indexed IDs with section counts), `failed` (list of IDs that failed again), `orphans_found`, `total_reconciled`, `failure_log_entries_before` / `after` |
| `check_synthesis_freshness` | Audit every synthesis in own scope against its declared source artifacts; report stale (source newer), archived sources, missing sources (deleted), and malformed syntheses (no sources declared); optionally hard-delete malformed ones | `confirm` (bool, default `false` — set `true` to hard-delete malformed syntheses) | `stale`, `archived_sources`, `missing_sources`, `malformed`, `deleted_malformed`, `total_checked`, `all_fresh` (bool) |
| `propose_commit_links` | Discover own-scope artifacts with no `commit_refs`, optionally bounded to those written since a session ULID — read-only, no writes | `commit_sha`, optional `since_ulid` | `proposed` (list of candidates with `artifact_id`, `title`, `type`, `last_edited_at`), `commit_sha` |
| `link_commit` | Append a commit SHA to the `commit_refs` vector metadata of confirmed own-scope artifacts — no re-embedding | `artifact_ids`, `commit_sha` | `linked`, `skipped`, `commit_sha`, `next_since_ulid` |
| `cairn_studio` | Opens the visual artifact browser — renders an inline HTML application on hosts that support [MCP Apps](https://modelcontextprotocol.io/extensions/apps/overview); returns the full artifact listing as structured data on non-supporting hosts | — | Browser UI on supporting hosts; structured artifact listing on others |

## Resources

The server exposes seven MCP resources split into two categories by audience.

### Schema resources — agent-readable documentation (`audience: ["assistant"]`)

These five resources are pure documentation: they make no AWS calls, never fail at
runtime, and are always available regardless of credential or connectivity state. They
exist so a connected agent can discover the full schema without consulting external docs.

| URI | What it contains |
|-----|-----------------|
| `cairn://schema/artifact` | Required and optional fields, enum values, and constraints |
| `cairn://schema/tiers` | Tier 2 vs tier 3 semantics, key formats, and access rules |
| `cairn://schema/visibility` | Visibility values and the cross-scope access gate |
| `cairn://schema/types` | Type catalogue with one-line usage guidance per type |
| `cairn://schema/query-strategy` | Recommended query strategy: when to list vs search vs synthesise |

### Data resources — human browsing surface (`audience: ["user"]`)

These two resources require live AWS clients. They apply the same cross-scope and
visibility gates as the equivalent tools, so they respect the deployment's scope
configuration exactly.

| URI | What it returns | Notes |
|-----|----------------|-------|
| `cairn://artifacts` | Markdown table of all active own-scope artifacts (columns: Identifier, Title, Type, Description) | Equivalent to calling `list_artifacts` with `status="active"` and no filters |
| `cairn://artifact/{id}` | Full markdown content of the named artifact | Applies the same cross-scope/tier/visibility gate as `read_artifact`; returns a markdown error block on access failure |

#### Tools vs resources — when to use which

| | Resources (`cairn://`) | Tools |
|--|---|---|
| **Primary audience** | Human browsing in MCP Inspector, Claude Desktop, or Claude Code | Agent workflows in a session |
| **Typical use** | Quick index review, reading a specific artifact without tool overhead | Search, filter, write, archive, delete |
| **Requires AWS** | Data resources yes; schema resources no | Yes (except `health_check`) |
| **Output format** | Always markdown | Structured JSON dict |

Use the data resources for a quick human audit of what is stored. Use the tools for
everything agents do — search, filter, write, synthesise, archive.

### MCP App — Visual Browser

> See [ADR-010](docs/architecture-decisions/adr-2026-06-24-mcp-apps-visual-reading-interface.md)
> for the decision record behind this approach.

The `cairn_studio` tool is the primary human reading entry point. On hosts that support
the `io.modelcontextprotocol/ui` extension (Claude Desktop, claude.ai, VS Code Copilot),
calling `cairn_studio` renders a self-contained two-pane HTML/JS application inline in
the host. The browser is populated from the tool's initial result and then issues
subsequent tool calls (`list_artifacts`, `read_artifact`, `search_artifacts`) directly
from the iframe over the same MCP connection.

The browser application loads external assets from the following CDN origins, declared
in the server's `ResourceCSP` so the host can enforce a strict Content Security Policy:
`unpkg.com`, `cdn.jsdelivr.net`, `fonts.googleapis.com`, `fonts.gstatic.com`.

**Parameters:** none required.

**Return value:**
- **Supporting hosts** (UI extension present): structured JSON dict `{ "write_prefix": string, "artifacts": [...] }` consumed by the browser iframe on load.
- **Non-supporting hosts** (e.g. MCP Inspector, headless agents): plain-text listing of active artifacts, equivalent to calling `list_artifacts` with `status="active"`.

**Usage example:**

Simply call the tool with no arguments:

```
cairn_studio
```

The host renders the browser inline. From there you can:
- Browse and filter the active artifact list by type, tier, and status
- Select any artifact to read its full markdown content (with mermaid diagram rendering)
- Enter a search query for semantic artifact discovery
- Clear the search to restore the filter-based listing

On non-supporting hosts the tool returns a plain-text artifact index that agents can
read directly without any UI rendering.

#### Browsing with MCP Inspector

```bash
eval $(jq -r '.mcpServers.cairn.env | to_entries[] | "export \(.key)=\(.value)"' .mcp.json)
npx @modelcontextprotocol/inspector uv run --directory /path/to/cairn-mcp cairn-mcp
```

Navigate to the **Resources** tab to read `cairn://artifacts`, and the **Resource
Templates** tab to read `cairn://artifact/{id}` by supplying an artifact ID.

#### Using data resources in Claude Code

Ask the agent directly:

> "Read the `cairn://artifacts` resource and tell me what's there."

Claude Code fetches the resource via the MCP resources protocol and returns the
pre-rendered markdown table — useful for a quick human-readable index without
incurring tool-call overhead.

## Cross-Scope Security Model

The tier + visibility gate (only tier 3 + `shared` artifacts are served across scopes) is
applied by the server process at query time. It is a **soft control**: the filter is part of
the request the server sends, not a rule AWS enforces.

What IAM can and cannot hard-bound:

| Surface | Hard boundary possible? | How / why not |
|---|---|---|
| Artifact content (S3) | **Yes** | Prefix-scoped `s3:GetObject` — deny reads on foreign teams' prefixes |
| Vector index (S3 Vectors) | **No** | Authorization stops at the index ARN. The condition keys applicable to `s3vectors:QueryVectors`/`GetVectors`/`ListVectors` (`aws:ResourceTag`, `s3vectors:VectorBucketTag`) evaluate per index/bucket resource — none reference vector metadata or query filters |

Consequence: every principal granted query access to a shared index can read **all**
participants' vector metadata (titles, descriptions, tags, tier, status) and embeddings —
including tier 2 and hidden artifacts — with plain AWS API calls. Sharing a vector index is
a mutual-trust topology: choose index sharing according to the trust level between teams,
and write tier 2 descriptions knowing every index participant can read them. A hard
cross-team boundary requires separate vector indexes (see ADR-007, revision 2026-07-02, for
the candidate designs).

## Minimum IAM Policy

Attach the following policy to the IAM user or role that runs cairn-mcp. Replace each `YOUR-*` placeholder with your actual values before applying.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3ArtifactBucket",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:HeadBucket",
        "s3:HeadObject"
      ],
      "Resource": [
        "arn:aws:s3:::YOUR-ARTIFACT-BUCKET",
        "arn:aws:s3:::YOUR-ARTIFACT-BUCKET/*"
      ]
    },
    {
      "Sid": "S3VectorsIndex",
      "Effect": "Allow",
      "Action": [
        "s3vectors:PutVectors",
        "s3vectors:GetVectors",
        "s3vectors:QueryVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:DescribeIndex",
        "s3vectors:ListVectors"
      ],
      "Resource": "arn:aws:s3vectors:YOUR-REGION:YOUR-ACCOUNT-ID:bucket/YOUR-VECTORS-BUCKET/index/YOUR-INDEX-NAME"
    },
    {
      "Sid": "BedrockEmbeddingModel",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:YOUR-REGION::foundation-model/amazon.titan-embed-text-v2:0"
    },
    {
      "Sid": "BedrockTextModel",
      "Comment": "Required only if using migrate_artifacts. In us-east-1 use the foundation-model ARN below. In all other regions replace with the cross-region inference profile ARN, e.g. arn:aws:bedrock:eu-west-1::inference-profile/eu.amazon.nova-lite-v1:0",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:YOUR-REGION::foundation-model/amazon.nova-lite-v1:0"
    }
  ]
}
```

## Configuration

All configuration is read from environment variables. Pass them via your IDE's MCP config
file `env` (or `environment`) block — see the `setting-up-cairn` skill for the exact
format for each supported IDE.

| Variable | Required | Default | Description |
|---|---|---|---|
| `AWS_REGION` | Yes | — | AWS region for all API calls |
| `ARTIFACT_BUCKET` | Yes | — | S3 bucket for artifact content |
| `VECTORS_BUCKET` | Yes | — | S3 Vectors bucket |
| `VECTORS_INDEX` | Yes | — | S3 Vectors index name |
| `AWS_PROFILE` | No | SDK default chain | Named AWS profile to use |
| `WRITE_PREFIX` | No | `artifacts` | Prefix for all artifact writes — must not be empty |
| `READ_PREFIXES` | No | *(none)* | Comma-separated foreign read scopes (e.g. `shared/org,shared/platform`) |
| `BEDROCK_EMBEDDING_MODEL` | No | `amazon.titan-embed-text-v2:0` | Bedrock embedding model ID |
| `BEDROCK_EMBEDDING_DIMENSIONS` | No | `1024` | Embedding dimensions — must match the S3 Vectors index dimension |
| `SEARCH_FETCH_TOP_K` | No | `25` | Section vectors requested from S3 Vectors per search iteration |
| `SEARCH_MAX_ITERATIONS` | No | `3` | Maximum S3 Vectors calls per search before returning available results |
| `SEARCH_DEFAULT_TOP_K` | No | `5` | Default number of artifacts returned when the caller does not specify |
| `FAILURE_LOG_PATH` | No | `.cairn_failures.jsonl` | Path to the tier 1 failure log file (JSONL); appended on partial write failures |
| `SECTION_CONCURRENCY` | No | `5` | Max concurrent Bedrock embed calls per artifact write. Increase for faster bulk writes; lower to avoid throttling. Must be ≥ 1. |
| `EMBED_MAX_SECTIONS` | No | `20` | Maximum number of `##` sections indexed per artifact. Sections beyond the cap are dropped from the vector index; full content is still stored in S3. Must be ≥ 1. |
| `EMBED_MIN_SECTION_LENGTH` | No | `50` | Minimum body length (chars, stripped) for a section to be indexed. Sections shorter than this are dropped from the vector index. Set to `0` to disable. |
| `EMBED_MAX_SECTION_LENGTH` | No | `24000` | Maximum body length (chars) per section before truncation for embedding. Set to `0` to disable. |
| `BEDROCK_TEXT_MODEL` | No | *(unset)* | Bedrock text model used by `migrate_artifacts` to generate artifact descriptions server-side. When unset, server-side generation is disabled. Use a cross-region inference profile ID for your region (e.g. `eu.amazon.nova-lite-v1:0` for EU, `us.amazon.nova-lite-v1:0` for US cross-region) — the bare `amazon.nova-lite-v1:0` only works in `us-east-1`. |
| `LOG_LEVEL` | No | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Per-call tool parameters

Some parameters are passed per call rather than configured server-wide. They let individual
callers tune behaviour without restarting the server.

| Parameter | Tool(s) | Default | Behaviour |
|---|---|---|---|
| `artifact_concurrency` | `write_artifacts`, `migrate_artifacts` | `3` | Max artifacts processed concurrently. Values above 15 are capped to 15; values below 1 are substituted with the default 3. Both out-of-range cases return a `"warning"` field in the response. In-range values produce no warning. Keep `artifact_concurrency × SECTION_CONCURRENCY ≤ 15` as a safe Bedrock quota guideline (e.g. `artifact_concurrency=3` × `SECTION_CONCURRENCY=5` = 15 concurrent embed calls). |

## Running the server

> **AI coding tools manage this automatically.** If you are connecting cairn-mcp to OpenCode,
> Claude Code, Copilot, or Codex, the tool launches the server process on session start using
> the command in your MCP config — you never run it manually. This section is relevant for
> **CI/CD pipeline agents** (e.g. an automated code reviewer running in a pipeline that needs
> cairn-mcp as a subprocess) and for **smoke-testing** a new installation before wiring it to
> an MCP client.

```bash
uv run cairn-mcp
# or
uv run python -m cairn_mcp
```

The server runs on stdio and is ready to accept MCP client connections.
