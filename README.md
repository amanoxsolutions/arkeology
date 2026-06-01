# cairn-mcp

> *A cairn is a pile of stones left at a waypoint so the next traveller knows the path was walked.*
> *Agents leave cairns for agents.*

cairn-mcp is a Python MCP server that gives AI agents persistent artifact memory, backed entirely
by AWS — S3 for durable content storage, S3 Vectors for semantic search, and Amazon Bedrock for
embeddings. Knowledge produced in one session — code reviews, architectural decisions,
implementation notes, specs, session summaries — is written as a structured artifact and made
searchable by future agents, across sessions and potentially across team boundaries.

## The pain point: the artifact gap

AI-assisted engineering produces knowledge at three levels:

| Tier | What it is | Where it lives today |
|---|---|---|
| **Code** | The deliverable — functions, tests, infrastructure | Git — durable, searchable, shared |
| **Working artifacts** | Code reviews, session summaries, implementation notes, specs | Scattered — in the repo, in proprietary tool memory, or simply lost when the session ends |
| **Canonical knowledge** | ADRs, architecture decisions, org-wide patterns | Wikis or documentation folders in the repo |

The code tier is solved. The working artifact tier is the gap.

On a small project, ad-hoc approaches work. Commit a few notes to the repo, store some summaries
in a `docs/` folder, rely on your agent tool's built-in memory. But on any project with real
longevity, the volume compounds: months of agent sessions produce hundreds or thousands of
artifacts — brainstorming outputs, feature specifications, implementation notes, code reviews,
issue and bug reports, session summaries, and more. Storing them in the repo adds noise to git
history and pollutes the codebase. And
even if they are stored, no agent can be asked to scan thousands of files to find the one that
matters.

Some teams have found creative workarounds. The Streamlit engineering team, for example,
[repurposed their GitHub wiki git repo](https://blog.streamlit.io/the-repo-is-the-harness-how-we-made-an-8-year-old-codebase-agent-native-75629a953354)
as a scratch space. They describe it as "a hack, honestly. But it works surprisingly well."
It does. But it is GitHub-specific, has no semantic search, and does not scale across projects or
teams.

cairn-mcp is an attempt to address both problems in AWS environments: **structured durable storage** and
**semantic search**. Artifacts are written mid-session and immediately searchable — by keyword,
by metadata filter, or by semantic similarity. Canonical knowledge can be flagged as shareable,
making it discoverable by agents on other projects or teams that point at the same store.

## Key Features

- **Immediate write-then-read consistency** — an artifact written in one agent call is searchable in the next. There is no ingestion delay between producing knowledge and finding it.
- **Semantic search with metadata filtering** — retrieve artifacts by meaning, not just keyword. Combine a natural-language query with filters for type, feature tag, team, or project in a single call.
- **Section-level search precision** — queries match the specific section of an artifact that is relevant, not a whole-document average. Precision improves as artifacts grow longer.
- **Cross-team knowledge sharing** — canonical artifacts such as ADRs and architecture decisions can be made discoverable by agents on other projects or teams. Working documents stay project-local by default; sharing requires a deliberate promotion step, not an accidental one.
- **Flexible ADR strategy** — teams that approve ADRs through pull request review keep them in git (preserving the PR as the approval record) while still making them semantically searchable through cairn-mcp. Teams without a formal PR-based approval ceremony can store ADRs in cairn-mcp as the single source of truth. The choice is declared once in the project's `AGENTS.md` and respected by every agent that reads it.
- **Rich, filterable metadata** — every artifact carries structured metadata that is returned with every search result. Browse and filter without fetching full content.
- **Knowledge synthesis** — compile multiple related artifacts into a single reference document. The result is stored as a first-class artifact with source identifiers recorded, so provenance is always traceable.
- **Full artifact lifecycle** — archive, delete, and purge artifacts as projects evolve. Referential safety checks warn before removing an artifact that other synthesis documents depend on.
- **Migration skill for existing projects** — adopt cairn-mcp on a project with years of accumulated docs without starting from zero. A bundled skill classifies, enriches, and imports existing documentation in a single structured workflow.
- **AWS-native — no extra services** — S3, S3 Vectors, and Bedrock are the only dependencies. Teams already running on AWS have nothing new to operate or secure.
- **CI/CD-ready** — works with any standard AWS credential environment: local developer profiles, IAM roles, ECS tasks, or CI/CD OIDC tokens. A pipeline agent and an interactive developer agent use identical tools.
- **Any MCP-compatible agent** — no framework lock-in. Schema documentation is published at runtime so any connected agent can discover valid types, tiers, and field constraints without consulting external documentation.

### cairn-mcp vs. other approaches

Most existing approaches solve one half of the problem — storage or retrieval — but not both, and not at team scale with immediate consistency. The table below surfaces one gap cairn-mcp closes for each, and one gap it does not.

| Approach | Where cairn-mcp wins | Where they win |
|---|---|---|
| **Repo + `index.md`**<br>(e.g. Streamlit's GitHub wiki hack, an `artifacts/` folder with a shared index file) | - No semantic search<br>- No cross-team or cross-project sharing<br>- Potential index file write race condition or merge conflict | - Zero infrastructure and cloud cost<br>- No AWS account required<br>- Full artifact history in git |
| **LLM wiki**<br>(Karpathy's [llm-wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern) | - Not shared across engineers, machines, or CI/CD without git discipline<br>- No semantic search at team scale without bolt-on tooling<br>- No cross-team sharing mechanism | - Synthesised, compiled knowledge rather than raw point-in-time records<br>- Contradiction detection and staleness flagging (lint) |
| **PageIndex**<br>([VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex)) | - Retrieval-only: no write path, no artifact storage<br>- No metadata schema or filtering<br>- No cross-team sharing | - Handles long unstructured documents where vector similarity fails<br>- No embedding pre-computation required |
| **MemoRAG**<br>([qhjqhj00/MemoRAG](https://github.com/qhjqhj00/MemoRAG)) | - Retrieval-only: no write path, no artifact storage<br>- Requires training a specialised model (RLGF) — significant ML overhead<br>- No metadata schema or cross-team sharing | - Handles implicit queries where the user cannot articulate search terms<br>- Scales to massive, unstructured corpora |
| **Bedrock Knowledge Base**<br>(AWS managed RAG) | - Ingestion latency: an artifact written now is not searchable immediately<br>- Higher cost | - Fully managed: no index to create or maintain<br>- Broader document format support beyond markdown |

---

## Who this is for — and who it isn't?

**A good fit if:**
- Your team already runs workloads on AWS
- You use structured AI agents and skills with explicit instructions to produce and consume structured documentation artifacts — writing findings at the end of a session and searching for prior context at the start of one
- Your projects have real longevity: multiple sessions, multiple contributors, or both

**Not a good fit if:**
- Your team is not using AWS
- Your project is small or short-lived and a `docs/` folder in the repo is sufficient
- Your do not use structured agents and skills with explicit instructions for when to write artifacts and when to search for them — a store that is never written to and never queried, delivers no value. Filled with inconsistent, low-quality artifacts might be even worse.
- You are running an open source project with public contributors — no one should grant public read/write access to an S3 bucket
- You are already using a dedicated knowledge management system and your agents can query it
- You need to handle high-volume automated pipelines generating hundreds of artifacts per hour — cairn-mcp is designed for interactive developer sessions and moderate CI/CD workloads, not bulk ingestion

---

## Why AWS, and why this stack?

**Why AWS?**
cairn-mcp is designed for teams already running workloads on AWS. Using S3, S3 Vectors, and
Bedrock means no additional services to run or secure — the infrastructure agents use to build
software is the same infrastructure that stores what they learn.

**Why not a simple S3 bucket with an index file?**
A shared index file (e.g. `INDEX.json`) is a single mutable resource. Two agents writing
simultaneously produce a race condition. It also provides no semantic search — retrieval is
exact-match only, which misses conceptually related artifacts.

**Why not a Bedrock Knowledge Base (RAG)?**
Bedrock Knowledge Bases require pre-provisioning a managed vector store before the first write.
The ingestion pipeline — chunking, embedding, and indexing — introduces latency between a write
and when that artifact becomes searchable. Bedrock Knowledge Bases also carry noticeable additional cost.

**Why S3 Bucket + S3 Vectors + Bedrock?**
S3 Vectors provides immediate, consistent vector storage with server-side metadata filtering.
Bedrock produces the embeddings. The design is simple: artifact content lives in a standard S3
bucket; its embedding and metadata live in S3 Vectors under the same key. Write latency is the
sum of three sequential API calls. Search latency is a single vector query followed by a batch
S3 fetch. No sync jobs, no separate index service, no infrastructure beyond what AWS already
provides.

## How it works

Artifacts are stored in a standard S3 bucket and indexed in AWS S3 Vectors with embeddings from
Amazon Bedrock (Titan Text v2). Agents connect via the Model Context Protocol and call these tools:

| Tool | What it does | Key inputs | Key outputs |
|---|---|---|---|
| `write_artifact` | Store an artifact in S3 and index it in S3 Vectors | `type`, `team`, `project`, `tier`, `title`, `content`, `visibility`, optional filters | `artifact_id`, `sections_indexed` |
| `search_artifacts` | Semantic search over the vector index with optional metadata filters | `query`, optional: `type`, `feature_tags`, `team`, `project`, `tier`, `status`, `top_k` | List of artifact metadata (no content) |
| `read_artifact` | Fetch the full content of an artifact by ID | `artifact_id` | Full artifact dict including `content` |
| `list_artifacts` | List artifact metadata with optional filters; defaults to active artifacts | optional: `type`, `team`, `project`, `tier`, `status`, `feature_tags` | List of artifact metadata records |
| `archive_artifact` | Set an artifact's status to inactive (own scope only) | `artifact_id` | Confirmation with updated `artifact_id` |
| `delete_artifact` | Hard-delete an artifact from S3 and S3 Vectors; warns if referenced by a synthesis | `artifact_id`, `confirm=True` | Deletion confirmation |
| `purge_archived` | Bulk-delete all inactive artifacts in own scope; cascade-deletes orphaned syntheses | `confirm=True` | Count of deleted artifacts and syntheses |
| `health_check` | Per-component connectivity status (S3, vectors, Bedrock, write prefix, read prefixes) | — | Status dict; never raises |
| `synthesise_artifacts` | Semantic search followed by full S3 content fetch for a set of top-k artifacts | `query`, optional: filters, `top_k` (clamped to 100) | List of full artifact dicts including `content` |
| `reconcile_index` | Replay the failure log and scan for orphaned S3 objects, re-indexing any artifacts present in S3 but absent from the vector index | — | `reconciled` (list of re-indexed IDs with section counts), `failed` (list of IDs that failed again), `orphans_found`, `total_reconciled`, `failure_log_entries_before` / `after` |
| `check_synthesis_freshness` | Audit every synthesis in own scope against its declared source artifacts; report stale (source newer), archived sources, missing sources (deleted), and malformed syntheses (no sources declared); optionally hard-delete malformed ones | `confirm` (bool, default `false` — set `true` to hard-delete malformed syntheses) | `stale`, `archived_sources`, `missing_sources`, `malformed`, `deleted_malformed`, `total_checked`, `all_fresh` (bool) |

The server also exposes MCP Resources — always-current schema documentation covering artifact
types, the tier model, visibility rules, and field constraints — so any connected agent can
discover what to provide without consulting external documentation.

## Status

> **Phase 5 complete** — `write_artifact`, `search_artifacts`, `read_artifact`, `list_artifacts`, `archive_artifact`, `delete_artifact`, `purge_archived`, `health_check`, `synthesise_artifacts`, `reconcile_index`, and `check_synthesis_freshness` are implemented and unit-tested.

## Using the Migration Skill

The migration skill provides a structured one-time workflow for importing
existing repository documentation into cairn-mcp. Use it when adopting
cairn-mcp on a project that already has months or years of accumulated docs
in `docs/`.

The skill covers discovery, classification by directory convention, metadata
enrichment (descriptions, git-recovered dates), and two execution paths:

- **< 30 files (agent-only):** the agent reads each file, generates
  descriptions in-context, and calls `write_artifact` for each. No extra
  tooling required.
- **≥ 30 files (manifest + script):** the agent produces a `CAIRN_IMPORT.yaml`
  manifest, the operator reviews it, then `migrate.py` executes bulk writes
  with Bedrock-generated descriptions and `--dry-run` preview before
  committing.

### Installation

Copy the skill into your IDE's skills directory:

```bash
cp -r skills/migrating-to-cairn /path/to/ide-skills-directory/
```

| IDE | Skills directory |
|-----|-----------------|
| Claude Code | `.claude/skills/` or `~/.claude/skills/` |
| GitHub Copilot (VS Code) | `.github/copilot-instructions.d/` |
| OpenCode | `~/.config/opencode/skills/` |
| Codex | `.codex/skills/` |

Once installed, load the skill and follow the seven-step workflow in
`SKILL.md` — from pre-migration health check through to post-migration
`AGENTS.md` update.

## Prerequisites

- Python ≥ 3.12
- [`uv`](https://docs.astral.sh/uv/)
- AWS credentials with access to S3, S3 Vectors, and Bedrock
- An S3 bucket, an S3 Vectors bucket, and an S3 Vectors index (provisioned externally)
- Amazon Bedrock Titan Text Embeddings v2 model access enabled in your AWS account

## Installation

```bash
git clone https://github.com/amanoxsolutions/cairn-mcp.git
cd cairn-mcp
uv sync
cp .env.example .env
# Edit .env — fill in at minimum AWS_REGION, ARTIFACT_BUCKET, VECTORS_BUCKET, VECTORS_INDEX
```

## Configuration

All configuration is read from environment variables (or a `.env` file in the working directory).

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
| `LOG_LEVEL` | No | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## AWS Provisioning

Provision the four required resources in order. All commands use the AWS CLI; substitute
`YOUR-*` placeholders with your actual values.

### Step 1 — Create the S3 artifact bucket

```bash
aws s3api create-bucket \
  --bucket YOUR-ARTIFACT-BUCKET \
  --region YOUR-REGION \
  --create-bucket-configuration LocationConstraint=YOUR-REGION
  # Omit --create-bucket-configuration for us-east-1
```

This is a standard S3 bucket — it stores artifact content as S3 objects. Enable versioning
and server-side encryption according to your team's data policy; cairn-mcp works with either.

### Step 2 — Create the S3 Vectors bucket

```bash
aws s3vectors create-vector-bucket \
  --vector-bucket-name YOUR-VECTORS-BUCKET \
  --region YOUR-REGION
```

### Step 3 — Create the S3 Vectors index

> **⚠️ Warning — the following index properties are immutable after creation.** They cannot
> be changed without destroying and recreating the index:
> - Vector dimension
> - Distance metric
> - Index name
> - Non-filterable metadata key names
>
> A dimension, metric, or key mismatch after creation requires creating a new index and
> re-indexing all artifacts. Choose these values carefully before running the command below.

```bash
aws s3vectors create-index \
  --vector-bucket-name YOUR-VECTORS-BUCKET \
  --index-name YOUR-INDEX-NAME \
  --data-type float32 \
  --dimension 1024 \
  --distance-metric cosine \
  --metadata-configuration '{
    "nonFilterableMetadataKeys": ["description", "source_artifacts"]
  }'
```

Two metadata keys are declared non-filterable because filtering on them is never needed:

- `description` — tweet-length summary stored with each vector; returned in search results
  but not used as a filter predicate.
- `source_artifacts` — comma-joined list of source artifact IDs carried by `synthesis` type
  artifacts; not used for filtering.

`1024` is the default output dimension for Amazon Titan Text Embeddings v2. Titan v2 also
supports 256 and 512. If you use a non-default dimension, set `BEDROCK_EMBEDDING_DIMENSIONS`
to the same value — the server validates that the configured dimension matches the index at
startup.

### Step 4 — Enable Bedrock model access

Go to **AWS Console → Amazon Bedrock → Model access** and enable access to
**Amazon Titan Text Embeddings V2** (`amazon.titan-embed-text-v2:0`) in the same region
you used for the index. Model access must be in the same AWS region as `AWS_REGION`.

### Minimum IAM Policy

Attach the following policy to the IAM user or role that runs cairn-mcp. Replace each
`YOUR-*` placeholder with real values — account ID, region, and resource names.

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
    }
  ]
}
```

#### Provisioning IAM policy (one-time setup only)

The actions below are required only when creating or deleting the vector index.
**Do not include these in your runtime role policy** — `DeleteIndex` in a runtime
policy is a destructive misconfiguration risk.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3VectorsProvisioning",
      "Effect": "Allow",
      "Action": [
        "s3vectors:CreateIndex",
        "s3vectors:DeleteIndex"
      ],
      "Resource": "arn:aws:s3vectors:YOUR-REGION:YOUR-ACCOUNT-ID:bucket/YOUR-VECTORS-BUCKET/index/YOUR-INDEX-NAME"
    }
  ]
}
```

## Running the server

```bash
uv run cairn-mcp
# or
uv run python -m cairn_mcp
```

The server runs on stdio and is ready to accept MCP client connections.

## Development

```bash
# Unit tests (no AWS required)
uv run pytest tests/unit/ -q -m 'not integration'

# Integration tests (require real AWS credentials in .env)
uv run pytest tests/integration/ -q

# Lint
uv run ruff check src/ tests/

# Format check
uv run ruff format --check src/ tests/

# Type check
uv run mypy src/
```

## Connecting to an MCP client

Add the server to your MCP client configuration. Example for a client that reads `mcp-servers.json`:

```json
{
  "mcpServers": {
    "cairn": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/cairn-mcp", "cairn-mcp"],
      "env": {
        "AWS_REGION": "eu-central-1",
        "ARTIFACT_BUCKET": "my-artifacts-bucket",
        "VECTORS_BUCKET": "my-vectors-bucket",
        "VECTORS_INDEX": "artifacts-index"
      }
    }
  }
}
```

## Recommended AGENTS.md Snippet

Copy and paste this block into your project's root `AGENTS.md`. It gives every agent the
guidance it needs to write, search, and synthesise effectively using cairn-mcp.

### Declare your ADR strategy first

Before agents start writing, decide where ADRs will live. This is a one-time decision that is
hard to reverse cleanly — changing strategy mid-project means either migrating existing content
or accepting a mixed state where some ADRs are in git and others are in cairn-mcp.

**The deciding question:** Does your team use pull request review as the approval mechanism
for ADRs?

- **Yes (git only):** Keep ADRs in git. The PR merge is the approval record; removing ADRs
  from git would destroy it. Add **Variant A** below to your `AGENTS.md`.
- **No (cairn-mcp only):** Store ADRs in cairn-mcp as the single source of truth. Add
  **Variant B** below to your `AGENTS.md`.

Include exactly one of the following blocks in your `AGENTS.md`, immediately after the
artifact type selection table:

**Variant A — git only (team uses PR-based ADR approval)**

```markdown
**ADRs:** This project keeps ADRs in git. Do NOT write `type=adr` artifacts to
cairn-mcp. When you create or update an ADR, commit it to the project's ADR
directory in git. After committing, you may index it in cairn-mcp by calling
`write_artifact` (type=adr, tier=3, visibility=shared) so agents can search it
semantically — but the git file is the authoritative source. Draft ADRs that
have not yet been committed may be written to cairn-mcp with `visibility=hidden`.
```

**Variant B — cairn-mcp only (no formal PR-based ADR approval)**

```markdown
**ADRs:** This project stores ADRs in cairn-mcp only. Write ADRs using
`write_artifact` (type=adr, tier=3, visibility=shared). Do NOT commit ADR files
to git — cairn-mcp is the single source of truth. Draft ADRs use `visibility=hidden`
until approved.
```

---

````markdown
## cairn-mcp — Persistent Artifact Memory

cairn-mcp is connected to this project. Use it to persist knowledge across sessions.

### When to write artifacts

- **Start of session** — search for prior context before doing any substantial work.
- **End of session** — write findings, decisions, and implementation notes before closing.
- **After a key decision** — write a `decision_note` or `adr` while the reasoning is fresh.
- **After a code review** — write a `code_review` artifact with findings and recommendations.

### Artifact type selection

| Type | When to use |
|------|-------------|
| `code_review` | After completing a code review — findings, issues, recommendations |
| `session_summary` | At the end of any productive session — what was decided, implemented, or discovered |
| `implementation_note` | When implementing a non-obvious solution — why this approach, constraints, edge cases |
| `spec` | Feature specifications and requirements documents — living documents updated as features evolve |
| `adr` | Architectural Decision Records — a decision that affects system design; tier 3, shared by default |
| `bug_report` | When a bug is diagnosed — root cause, affected behaviour, fix applied |
| `decision_note` | A lightweight decision with rationale — smaller than an ADR, larger than a code comment |
| `synthesis` | When consolidating multiple prior artifacts into a summary — must include `source_artifacts` |

### Description quality

The `description` field is the primary search signal. Invest in it.

- Write it as a tweet: ≤ 280 characters, present tense, concrete.
- **Bad:** `"Notes from the session on 2024-11-15"`
- **Good:** `"Evaluates three auth strategies for the payments API; recommends JWT with rotating keys; identifies Redis session cache as a dependency"`
- Include the key outcome, technology involved, and any named constraints.

### Tier selection

- **Tier 2** — point-in-time records that document a moment: `code_review`, `session_summary`,
  `implementation_note`, `bug_report`. Immutable after write; keyed by type + date + title.
- **Tier 3** — living documents that evolve: `spec`, `adr`, `decision_note`, `synthesis`.
  Overwrite in place on re-write; keyed by type + title only (no date).

### Query strategy — start narrow, broaden only if needed

```python
# Step 1 — Filter by type + feature tags (fastest, most precise)
search_artifacts(query="auth token refresh", type="implementation_note", feature_tags=["auth"])

# Step 2 — If step 1 returns too few results, drop the type filter
search_artifacts(query="auth token refresh", feature_tags=["auth"])

# Step 3 — If still insufficient, pure semantic search
search_artifacts(query="auth token refresh")

# For browsing without a query
list_artifacts(type="adr", project="payments-api")
```

### Synthesis workflow

Use `synthesise_artifacts` when you need to compile multiple prior artifacts into a
single reference document (e.g. summarise an epic, compile related code-review findings,
consolidate session notes).

```python
# 1. Prepare source material — returns full content for top-k matches
result = synthesise_artifacts(query="auth module code reviews", type="code_review", top_k=5)

# 2. Synthesise in-context using the returned content

# 3. Write result back as a tier 3 synthesis artifact
write_artifact(
    type="synthesis",
    tier=3,
    visibility="shared",
    title="Auth Module Code Review Synthesis — Q4 2024",
    description="Consolidated findings from 5 code reviews of the auth module; identifies 3 recurring issues and 2 best-practice patterns.",
    source_artifacts=[r["artifact_id"] for r in result["results"]],
    content="..."  # your synthesis
)
```

### Runtime schema precision

For always-current field definitions, valid values, and query strategy guidance, call the
MCP Resources the server exposes at runtime:

- `cairn://schema/artifact` — all fields, valid values, constraints
- `cairn://schema/types` — type catalogue with usage notes
- `cairn://schema/tiers` — tier 2 vs tier 3 semantics
- `cairn://schema/query-strategy` — query strategy guidance
- `cairn://schema/visibility` — cross-scope access rules
````

## License

Apache License 2.0 — see [LICENSE](LICENSE) for the full text.

Copyright 2026 Amanox Solutions
