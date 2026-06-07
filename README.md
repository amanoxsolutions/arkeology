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
  > IMPORTANT: Cross-team visibility control is enforced at the MCP server layer. True access control (keeping content private from unauthorized AWS principals) requires enforcing permissions at the IAM or S3 resource permissions level.
- **Rich, filterable metadata** — every artifact carries structured metadata that is returned with every search result. Browse and filter without fetching full content.
- **Knowledge synthesis** — compile multiple related artifacts into a single reference document. The result is stored as a first-class artifact with source identifiers recorded, so provenance is always traceable.
- **Full artifact lifecycle** — archive, delete, and purge artifacts as projects evolve. Referential safety checks warn before removing an artifact that other synthesis documents depend on.
- **Migration skill and server tools for existing projects** — adopt cairn-mcp on a project with years of accumulated docs without starting from zero. A bundled skill and a dedicated `migrate_artifacts` server tool classify, enrich, and import existing documentation in a single structured workflow. For large batches (> 10 files), Bedrock generates artifact descriptions server-side — avoiding the agent consuming and summarising hundreds of files in-context — using Amazon Nova Lite by default.
- **AWS-native — no extra services** — S3, S3 Vectors, and Bedrock are the only dependencies. Teams already running on AWS have nothing new to operate or secure.
- **CI/CD-ready** — works with any standard AWS credential environment: local developer profiles, IAM roles, ECS tasks, or CI/CD OIDC tokens. A pipeline agent and an interactive developer agent use identical tools.
- **Flexible ADR & document strategy** — teams choose which knowledge stays in git and which moves to cairn-mcp. ADRs, specs, plans, or any folder can be designated as git-only during installation; the decision is recorded once in `AGENTS.md` and respected by every future agent session and the migration skill automatically.

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
| `write_artifacts` | Bulk-write multiple artifacts in a single call with per-entry success/error reporting | list of artifact descriptors | per-artifact list of `artifact_id` + `written: true` or `error` |
| `migrate_artifacts` | Migration-specific bulk write; generates descriptions server-side via Bedrock when omitted; `dry_run=True` previews enriched descriptors without writing | list of artifact descriptors, `dry_run` | enriched descriptor list (dry run) or per-artifact write results |
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

> **v0.2.0** — all tools implemented and unit-tested: `write_artifact`, `write_artifacts`, `migrate_artifacts`, `search_artifacts`, `read_artifact`, `list_artifacts`, `archive_artifact`, `delete_artifact`, `purge_archived`, `health_check`, `synthesise_artifacts`, `reconcile_index`, and `check_synthesis_freshness`.

## Using the Migration Skill

The migration skill and the `migrate_artifacts` server tool together provide a structured
one-time workflow for importing existing repository documentation into cairn-mcp. Use them
when adopting cairn-mcp on a project that already has months or years of accumulated docs.

The skill covers discovery, classification by directory convention, and two execution paths
based on the number of files to import:

- **≤ 10 files — agent-generated descriptions:** the agent reads each file, writes a
  description in-context (≤ 280 chars), presents the list to the operator for review, then
  calls `migrate_artifacts` directly. No external model call is made.
- **> 10 files — server-generated descriptions:** the agent produces a `CAIRN_IMPORT.yaml`
  manifest, calls `migrate_artifacts(dry_run=True)` to trigger server-side description
  generation via Bedrock (Amazon Nova Lite by default), writes the generated descriptions
  back into the manifest for operator review, then executes with `dry_run=False`. The agent
  never consumes file content to produce descriptions — Bedrock handles it server-side,
  keeping the agent context window free regardless of batch size.

Both paths support resume: if a migration is interrupted or partially fails, the skill
detects the existing manifest at startup and resumes from the correct step.

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

## Skills

cairn-mcp ships two skills that cover the two main setup tasks. Copy the ones you need into
your IDE's skills directory.

| Skill | Path | Purpose |
|-------|------|---------|
| `installing-cairn` | `skills/installing-cairn/SKILL.md` | First-time setup: validate AWS connectivity, configure your MCP client, write the `AGENTS.md` cairn config block |
| `migrating-to-cairn` | `skills/migrating-to-cairn/SKILL.md` | One-time migration of existing documentation into cairn-mcp — run `installing-cairn` first |

## Prerequisites

The following must be provisioned and accessible before running the `installing-cairn`
skill or starting the server manually:

- **S3 bucket** — a standard S3 bucket for artifact content storage
- **S3 Vectors bucket and index** — created with `float32` data type, `cosine` distance
  metric, and two non-filterable metadata keys: `description` and `source_artifacts`;
  the index dimension must match your embedding model (default: `1024` for Titan Text v2)
- **Amazon Bedrock** — embedding model access (`amazon.titan-embed-text-v2:0` by default)
  enabled in your AWS region; Nova Lite (`amazon.nova-lite-v1:0`) only required when using
  `migrate_artifacts`
- **IAM credentials** with the minimum runtime permissions listed below
- **AWS CLI** configured with the above credentials
- **Python ≥ 3.12** and [`uv`](https://docs.astral.sh/uv/)

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
      "Comment": "Required only if using migrate_artifacts. Adjust the resource ARN if your region requires a cross-region inference profile for Nova Lite.",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:YOUR-REGION::foundation-model/amazon.nova-lite-v1:0"
    }
  ]
}
```

## Installation

```bash
git clone https://github.com/amanoxsolutions/cairn-mcp.git
cd cairn-mcp
uv sync
```

Run the `installing-cairn` skill to configure your MCP client and AGENTS.md, or set the
environment variables below directly in your IDE's MCP config file.

## Configuration

All configuration is read from environment variables. Pass them via your IDE's MCP config
file `env` (or `environment`) block — see the `installing-cairn` skill for the exact
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
| `ARTIFACT_CONCURRENCY` | No | `3` | Max artifacts processed concurrently by `write_artifacts` and `migrate_artifacts`. Must be ≥ 1. |
| `BEDROCK_TEXT_MODEL` | No | `amazon.nova-lite-v1:0` | Bedrock text model used by `migrate_artifacts` to generate artifact descriptions server-side. Set to empty to disable server-side generation. |
| `LOG_LEVEL` | No | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Running the server

```bash
uv run cairn-mcp
# or
uv run python -m cairn_mcp
```

The server runs on stdio and is ready to accept MCP client connections.

> To configure your MCP client for cairn-mcp, run the `installing-cairn` skill.
> For the recommended AGENTS.md usage snippet and ADR strategy setup, run the `installing-cairn` skill.

## Development

```bash
# Unit tests (no AWS required)
uv run pytest tests/unit/ -q -m 'not integration'

# Integration tests (require real AWS credentials via environment or MCP config)
uv run pytest tests/integration/ -q

# Lint
uv run ruff check src/ tests/

# Format check
uv run ruff format --check src/ tests/

# Type check
uv run mypy src/
```

## License

Apache License 2.0 — see [LICENSE](LICENSE) for the full text.

Copyright 2026 Amanox Solutions
