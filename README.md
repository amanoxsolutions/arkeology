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

- **Immediate write-then-read consistency** — an artifact written in one tool call is searchable in the next. No background sync job, no ingestion pipeline, no delay between writing and finding.
- **Semantic search + metadata filtering** — retrieve artifacts by meaning, not just keyword. Combine a natural-language query with type, feature tag, team, or project filters in a single call. Start narrow, broaden only when needed.
- **Section-level indexing** — every `##` section in an artifact is indexed as an independent vector. A query for "trade-offs of the auth redesign" matches the `## Trade-offs` section directly instead of a diluted document-level embedding.
- **Cross-team knowledge sharing with a confidentiality gate** — tier 3 canonical artifacts (ADRs, architecture decisions) are discoverable across teams and projects when a shared S3 Vectors index is configured. Tier 2 working documents stay strictly project-local — a deliberate promotion step is required to share knowledge, not an accidental one. Cross-scope access control is enforced at the MCP server layer, not at the IAM layer; engineers with direct S3 or S3 Vectors console access bypass it. Infrastructure-level access controls remain the operator's responsibility.
- **Structured, filterable metadata** — every artifact carries typed metadata (type, team, project, tier, date, status, title, visibility, feature tags) stored in S3 Vectors and returned with every search result. No S3 content fetch needed to browse and filter.
- **Full artifact lifecycle — archive, delete, and purge** — archive hides an artifact from search and listing without removing it; delete permanently removes it from S3 and the vector index (vectors deleted first, so a failed S3 delete leaves no dangling search results); purge bulk-cleans all archived artifacts in one call. Synthesis reference safety is built in: deleting a source artifact warns which synthesis artifacts reference it; purging cascade-deletes any synthesis whose every source is in the purge set.
- **Migration skill for existing projects** — adopting cairn-mcp on a project with years of accumulated docs doesn't mean starting from zero. An [agentskills.io](https://agentskills.io)-compatible migration skill ships with the repository. The agent classifies existing docs by type and tier using directory conventions, generates search-quality descriptions in-context for high-value artifacts, and recovers original creation dates from git history. A bundled `migrate.py` script handles bulk operations for large migrations. Post-migration, the skill appends the cairn-mcp usage block to the project `AGENTS.md` so future agents write to cairn-mcp by default.
- **AWS-native — no additional services to run** — S3, S3 Vectors, and Bedrock are the only services required. If your team already runs workloads on AWS, there is nothing new to operate or secure.
- **CI/CD-ready** — all standard AWS credential environments are supported: local developer profiles, IAM roles, ECS tasks, CI/CD OIDC tokens. A code-review agent running in a pipeline writes findings using the same tools as an interactive developer agent.
- **Any MCP-compatible agent** — no framework dependency. Schema documentation is exposed as MCP Resources the server publishes at runtime, so any connected agent can discover valid types, tiers, and field constraints without consulting external docs.

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
| `list_artifacts` | List artifact metadata with optional filters; defaults to active artifacts | optional: `type`, `team`, `project`, `tier`, `status`, `feature_tags`, `limit` | List of artifact metadata records |
| `archive_artifact` | Set an artifact's status to inactive (own scope only) | `artifact_id` | Confirmation with updated `artifact_id` |
| `delete_artifact` | Hard-delete an artifact from S3 and S3 Vectors; warns if referenced by a synthesis | `artifact_id`, `confirm=True` | Deletion confirmation |
| `purge_archived` | Bulk-delete all inactive artifacts in own scope; cascade-deletes orphaned syntheses | `confirm=True` | Count of deleted artifacts and syntheses |
| `health_check` | Per-component connectivity status (S3, vectors, Bedrock, write prefix, read prefixes) | — | Status dict; never raises |
| `synthesise_artifacts` | Semantic search followed by full S3 content fetch for a set of top-k artifacts | `query`, optional: filters, `top_k` (clamped to 100) | List of full artifact dicts including `content` |

The server also exposes MCP Resources — always-current schema documentation covering artifact
types, the tier model, visibility rules, and field constraints — so any connected agent can
discover what to provide without consulting external documentation.

## Status

> **Phase 3 complete** — `write_artifact`, `search_artifacts`, `read_artifact`, `list_artifacts`, `archive_artifact`, `delete_artifact`, `purge_archived`, `health_check`, and `synthesise_artifacts` are implemented and unit-tested. MCP Resources, setup documentation, AGENTS.md snippet, and migration skill are planned for Phase 4.

## Prerequisites

- Python ≥ 3.12
- [`uv`](https://docs.astral.sh/uv/)
- AWS credentials with access to S3, S3 Vectors, and Bedrock
- An S3 bucket, an S3 Vectors bucket, and an S3 Vectors index (provisioned externally)
- Amazon Bedrock Titan Text Embeddings v2 model access enabled in your AWS account

## Installation

```bash
git clone https://github.com/your-org/cairn-mcp.git
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

## License

<!-- TODO -->
