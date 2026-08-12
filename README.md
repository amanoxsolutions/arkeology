# Arkeology

> *Archaeology is the practice of reading what earlier lives left buried, one layer at a time.*
> *Agents dig for agents.*

Arkeology is a Python MCP server that gives AI agents persistent artifact memory, backed entirely
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

Arkeology is an attempt to address both problems in AWS environments: **structured durable storage** and
**semantic search**. Artifacts are written mid-session and immediately searchable — by keyword,
by metadata filter, or by semantic similarity. Canonical knowledge can be flagged as shareable,
making it discoverable by agents on other projects or teams that point at the same store.

## Key Features

- **Immediate write-then-read consistency** — an artifact written in one agent call is searchable in the next. There is no ingestion delay between producing knowledge and finding it.
- **Semantic search with metadata filtering** — retrieve artifacts by meaning, not just keyword. Combine a natural-language query with filters for type, feature tag, team, or project in a single call.
- **Section-level search precision** — queries match the specific section of an artifact that is relevant, not a whole-document average. Precision improves as artifacts grow longer.
- **Cross-team knowledge sharing** — canonical artifacts such as ADRs and architecture decisions can be made discoverable by agents on other projects or teams. Working documents stay project-local by default; sharing requires a deliberate promotion step, not an accidental one.
  > IMPORTANT: Cross-team visibility control is enforced at the MCP server layer — it is a convention honoured by consumers, not an access control. Artifact *content* in S3 can be hard-protected with prefix-scoped IAM permissions, but the shared vector index cannot: S3 Vectors authorization is all-or-nothing per index, so every team with query access can read all teams' vector metadata (titles, descriptions, tags) and embeddings — including tier 2 working documents. Only share a vector index with teams you trust at that level, and write descriptions accordingly. See [Cross-Scope Security Model](SERVER-REFERENCE.md#cross-scope-security-model).
- **Rich, filterable metadata** — every artifact carries structured metadata that is returned with every search result. Browse and filter without fetching full content.
- **Commit-to-artifact traceability** — artifact vectors carry git commit SHA references as metadata. At the end of a session, unlinked artifacts can be discovered and linked to the session's commit SHA in a single confirmation step — without re-embedding. Commit refs can also be supplied at write time.
- **Arkeology Studio — inline visual browser** — calling Arkeology Studio opens an HTML application inline in any MCP host that supports [MCP Apps](https://modelcontextprotocol.io/extensions/apps/overview). It renders a filterable artifact list on the left and full markdown content — including Mermaid diagrams — issuing artifact queries over the same MCP connection without leaving the host UI. On non-supporting hosts, the full artifact listing is returned as structured data.
- **Human-readable MCP resources** — two data resources expose artifact content for direct human browsing: `arkeology://artifacts` returns a markdown table of all active own-scope artifacts; `arkeology://artifact/{id}` returns the full markdown content of a named artifact. Both are readable from MCP Inspector, Claude Desktop, and Claude Code without a tool call.
- **Knowledge synthesis** — compile multiple related artifacts into a single reference document. The result is stored as a first-class artifact with source identifiers recorded, so provenance is always traceable.
- **Full artifact lifecycle** — archive, delete, and purge artifacts as projects evolve. Referential safety checks warn before removing an artifact that other synthesis documents depend on.
- **Migration skill and server tools for existing projects** — adopt Arkeology on a project with years of accumulated docs without starting from zero. A bundled skill and a dedicated `migrate_artifacts` server tool classify, enrich, and import existing documentation in a single structured workflow. For large batches (> 10 files), Bedrock generates artifact descriptions server-side — avoiding the agent consuming and summarising hundreds of files in-context — using Amazon Nova Lite by default.
- **AWS-native — no extra services** — S3, S3 Vectors, and Bedrock are the only dependencies. Teams already running on AWS have nothing new to operate or secure.
- **CI/CD-ready** — works with any standard AWS credential environment: local developer profiles, IAM roles, ECS tasks, or CI/CD OIDC tokens. A pipeline agent and an interactive developer agent use identical tools.
- **Flexible ADR & document strategy** — teams choose which knowledge stays in git and which moves to Arkeology. ADRs, specs, plans, or any folder can be designated as git-only during installation; the decision is recorded once in `AGENTS.md` and respected by every future agent session and the migration skill automatically.

### Arkeology vs. other approaches

Most existing approaches solve one half of the problem — storage or retrieval — but not both, and not at team scale with immediate consistency. The table below surfaces one gap Arkeology closes for each, and one gap it does not.

| Approach | Where Arkeology wins | Where they win |
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
- You need to handle high-volume automated pipelines generating hundreds of artifacts per hour — Arkeology is designed for interactive developer sessions and moderate CI/CD workloads, not bulk ingestion

---

## Why AWS, and why this stack?

**Why AWS?**
Arkeology is designed for teams already running workloads on AWS. Using S3, S3 Vectors, and
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

Artifacts are stored in S3, indexed in S3 Vectors, and embedded with Amazon Bedrock
(Titan Text v2). The server exposes 16 MCP tools, five schema resources for runtime
schema discovery, and two data resources for human browsing — see the
[Server Reference](SERVER-REFERENCE.md#tools) for the complete tool and resource tables.

---

## Prerequisites

The following must be provisioned and accessible before running the `setting-up-arkeology`
skill or starting the server manually:

- **S3 bucket** — a standard S3 bucket for artifact content storage
- **S3 Vectors bucket and index** — created with `float32` data type, `cosine` distance
  metric, and four non-filterable metadata keys — `description`, `source_artifacts`, `title`,
  and `author_role` (display fields never used in `$eq` filters, so declaring them non-filterable
  keeps them out of the scarce filterable-metadata budget and leaves it for the fields that are
  actually filtered); the index dimension must match your embedding model (default: `1024` for
  Titan Text v2). These index attributes — dimension, distance metric, and the non-filterable
  metadata keys — are fixed at index creation and immutable; changing any of them later requires
  deleting and recreating the index, which loses all stored vectors
- **S3 object annotations** (optional) — back the `commit_refs` / `references` link-tracking
  feature (`link_metadata` and the write path's dual-write). Unavailable in the UAE and Bahrain
  regions and on S3 Express One Zone, Outposts, and directory buckets — no IAM change fixes a
  bucket in one of these categories. The `setting-up-arkeology` skill probes availability and IAM
  permissions during setup; the core server starts and serves content, search, and embeddings
  normally when annotations are unavailable — only this one feature degrades. See the
  [Server Reference](SERVER-REFERENCE.md#minimum-iam-policy) for the required IAM actions
- **Amazon Bedrock** — embedding model access (`amazon.titan-embed-text-v2:0` by default)
  enabled in your AWS region; a Nova Lite model is only required when using `migrate_artifacts`.
  **Cross-region inference profiles are required in most regions outside `us-east-1`** — use a
  region-prefixed model ID such as `eu.amazon.nova-lite-v1:0` (EU) or `us.amazon.nova-lite-v1:0`
  (US cross-region) rather than the bare `amazon.nova-lite-v1:0`
- **IAM credentials** with the minimum runtime permissions listed in the
  [Server Reference](SERVER-REFERENCE.md#minimum-iam-policy)
- **AWS CLI** configured with the above credentials
- **Python ≥ 3.14** and [`uv`](https://docs.astral.sh/uv/)

---

## How to use Arkeology in your project

### 1. Clone and install

```bash
git clone https://github.com/amanoxsolutions/arkeology.git
cd arkeology
uv sync
```

`uv sync` installs the server's Python dependencies into a local virtual environment.
Your AI tool launches the server via `uv run` which reuses this environment — syncing
once upfront means no cold-start delay the first time a session connects.

### 2. Wire your AI tool

The fastest way to wire Arkeology into your AI coding tool. Run `./install.sh` to detect and
configure all installed tools automatically, or follow the per-tool steps below.

**OpenCode** — add one line to `~/.config/opencode/opencode.jsonc`:

```json
"plugin": ["arkeology@git+ssh://git@github.com/amanoxsolutions/arkeology.git"]
```

> HTTPS alternative (no SSH key required):
> ```json
> "plugin": ["arkeology@git+https://github.com/amanoxsolutions/arkeology.git"]
> ```

**Claude Code** — two commands:

```bash
claude plugin marketplace add git@github.com:amanoxsolutions/arkeology.git
claude plugin install arkeology@arkeology
```

> HTTPS alternative (for environments where outbound SSH / port 22 is blocked):
> ```bash
> claude plugin marketplace add https://github.com/amanoxsolutions/arkeology.git
> claude plugin install arkeology@arkeology
> ```

**GitHub Copilot** — covered by `./install.sh` via `gh skill install`.

**Coexistence:** Arkeology registers its skills under the `arkeology:` namespace. It does not collide with skills from other installed plugins — both can be active simultaneously.

### 3. Set up your project

After wiring your AI tool in step 2, invoke the `setting-up-arkeology` skill. It validates AWS
connectivity for all declared resources, configures the MCP client for your chosen IDE by
writing the Arkeology server entry into the correct project-scoped configuration file, and
writes the `arkeology:config` block and usage snippet to `AGENTS.md`. Re-running the skill
updates the config block in place with no second copy appended.

### 4. Migrate existing documentation (optional)

The `migrating-to-arkeology` skill and the `migrate_artifacts` server tool together provide a
structured one-time workflow for importing existing repository documentation into Arkeology.
Use them when adopting Arkeology on a project that already has months or years of accumulated
docs. Run the `setting-up-arkeology` skill first — the migration skill requires the
`arkeology:config` block it writes to `AGENTS.md`.

The skill covers discovery, classification by directory convention, and two execution paths
based on the number of files to import:

- **≤ 10 files — agent-generated descriptions:** the agent reads each file, writes a
  description in-context (≤ 280 chars), presents the list to the operator for review, then
  calls `migrate_artifacts` directly. No external model call is made.
- **> 10 files — server-generated descriptions:** the agent produces a `ARKEOLOGY_IMPORT.yaml`
  manifest, calls `migrate_artifacts(dry_run=True)` to trigger server-side description
  generation via Bedrock (Amazon Nova Lite by default), writes the generated descriptions
  back into the manifest for operator review, then executes with `dry_run=False`. The agent
  never consumes file content to produce descriptions — Bedrock handles it server-side,
  keeping the agent context window free regardless of batch size.

Both paths support resume: if a migration is interrupted or partially fails, the skill
detects the existing manifest at startup and resumes from the correct step.

### 5. Keep skills current

Invoke `sync-arkeology-plugin` to pull the latest Arkeology skill content at any time. The skill
detects which AI coding tool it is running in (OpenCode, Claude Code, or Copilot) and applies
the correct update action automatically — no manual steps required.

---

> For the complete IAM policy, configuration reference, and headless server setup see
> [`SERVER-REFERENCE.md`](./SERVER-REFERENCE.md).

---

## Status

> **v0.5.0** — all tools implemented and unit-tested: `write_artifact`, `write_artifacts`, `migrate_artifacts`, `search_artifacts`, `read_artifact`, `list_artifacts`, `archive_artifact`, `delete_artifact`, `purge_archived`, `health_check`, `synthesise_artifacts`, `reconcile_index`, `check_synthesis_freshness`, `propose_commit_links`, `link_metadata`, and `arkeology_studio`. Five schema resources (`arkeology://schema/*`) and two data resources (`arkeology://artifacts`, `arkeology://artifact/{id}`) are registered and available.

---

## Skills

Four skills, delivered via the plugin mechanisms above — no manual file copying needed.

| Skill | Purpose |
|-------|---------|
| `setting-up-arkeology` | First-time project setup: validate AWS connectivity, configure your MCP client, write the AGENTS.md Arkeology config block |
| `migrating-to-arkeology` | One-time migration of existing documentation — run `setting-up-arkeology` first |
| `backfilling-references` | Optional, decoupled, dry-run-first: backfill unresolved `references` onto already-written artifacts via `link_metadata` |
| `sync-arkeology-plugin` | Keep skills current: detects your tool and applies the correct update action |

---

## Development

```bash
# Unit tests (no AWS required)
uv run pytest tests/unit/ -q -m 'not integration'

# Integration tests (require real AWS credentials via environment or MCP config)
# See CONTRIBUTING.md "Integration tests" — safe to run against any store, run-scoped.
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
