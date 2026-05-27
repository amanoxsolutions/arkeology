---
status: complete
project: amanox-artifact-store-mcp
language: python
decisions_locked: [D1, D2, D3, D4, D5, D6-metadata-schema, D7-deployment-agnostic, D8-tier4-sharing, D8b-confidentiality-visibility, D9-key-generation, D10-embedding-model, D11-tools-interface]
decisions_closed_not_applicable: [OQ3-cross-team-iam, OQ5-vector-index-topology]
---

# Brainstorming — amanox-artifact-store-mcp

## Description

New standalone project brainstorming. An AWS S3-based agent knowledge store delivered as a Python MCP server. Enables AI agents to write, search, and retrieve structured artifacts (code reviews, implementation notes, ADRs, specs, session summaries) across projects, teams, and AI coding sessions. Inspired by the awslabs/mcp architecture. Separate repo from `amanox-ai-agents`.

**Date:** 2026-05-27
**Facilitator:** Mary (Business Analyst)

---

## Problem Statement

AI coding agents are stateless. Knowledge produced in one session — code review findings, architectural decisions, implementation notes — is discarded when the context window closes. Engineers who return to a project the next day, or a second engineer joining the project, start from zero. The more agents are used, the worse this gets: decisions are re-made, patterns are re-discovered, bugs are re-fixed.

This is the tier 2 artifact gap identified in F3.2 (`f3.2-research.md`): artifacts exist locally and ephemerally but are unindexed and invisible across sessions and engineers.

The F3.2 research ruled out external object stores for the *general skill baseline* (too much infra overhead). This project is that infrastructure — built once, used everywhere.

### Why a separate project, not a skill

A skill is a set of instructions embedded in a markdown file. It cannot provision infrastructure, make API calls, or maintain state across sessions. An MCP server can. The artifact store requires:

- API calls to S3, S3 Vectors, and Bedrock at write and search time
- Per-project configuration (bucket, prefix, team, subscriptions)
- Credential management

These are not skill concerns. The MCP server provides the tools; the skills instruct agents when and how to use them.

---

## Context and Inspiration

### awslabs/mcp bedrock-kb-retrieval-mcp-server

Key findings:
- **Auth**: `AWS_PROFILE` + `AWS_REGION` env vars. `boto3.Session(profile_name=...)` if profile is set; default credential chain otherwise. Clients created at module init.
- **Framework**: FastMCP
- **Transport**: stdio only
- **Distribution**: `uvx awslabs.<name>@latest`
- **Search approach**: delegates semantic search entirely to Bedrock Knowledge Base (managed RAG). Server is a *reader* of pre-existing KBs — does not write artifacts.
- **Why not applicable**: Bedrock KB sync latency (minutes to hours between S3 write and KB indexing) breaks the immediate write-then-read workflow agents need.

Confirmed insight: awslabs chose managed vector search (Bedrock KB) over text index. This validates the vector search direction for our project.

### Your blog post: The Missing Link (dev.to/mlnrt)

Critical architectural pattern for S3 Vectors:
- S3 Vectors stores only vectors, not documents.
- Documents live in a standard S3 bucket.
- The link: **same key** in both S3 bucket (object key) and S3 Vectors (vector key).
- Write: S3 PutObject → Bedrock embed → S3 Vectors PutVector (all with the same key)
- Search: Bedrock embed query → S3 Vectors QueryVectors → batch S3 GetObject (using returned keys)
- Vector metadata stores lightweight fields (title, tags, tier) — full content only fetched on demand.

---

## Vision

Each deployment of this MCP server is a self-contained, independent tool. An agent on a project uses it to write and retrieve its own artifacts. No topology assumptions are made.

When a shared bucket is deliberately configured (multiple projects or teams pointing at the same bucket with different prefixes), **tier 3 knowledge** — ADRs, architecture decisions, canonical patterns — can be discovered across project/team boundaries via `READ_PREFIXES`. This is the cross-boundary discovery scenario: a platform team's VPC peering ADR is findable by a microservices team agent that subscribed to the platform team's tier 3 prefix.

Tier 2 artifacts (session summaries, code reviews, impl notes) stay project-local. They are not the sharing layer.

---

## Locked Design Decisions

### D1 — Auth: AWS_PROFILE + AWS_REGION env vars ✅ Locked

Pattern identical to awslabs/mcp. `boto3.Session(profile_name=profile)` when `AWS_PROFILE` is set; default credential chain otherwise. Session hook calls `sts:GetCallerIdentity` at server startup to validate credentials eagerly. Mid-session credential expiry surfaces as a typed error on tool calls with a re-auth instruction.

### D2 — Session hook blocks on expired credentials ✅ Locked

`sts:GetCallerIdentity` is called at startup. If credentials are invalid or expired, the server surfaces a clear error with re-auth instructions. Mid-session expiry: the boto3 call fails with a credential error, which the server wraps into a typed MCP error response (not a generic exception). The agent receives a human-readable re-auth instruction.

**Offline concern dismissed:** anyone running an AI agent has internet. An optional local-cache-and-push pattern (save to `.docs/` and push to S3 when connectivity is restored) is a future V2 consideration.

### D3 — Write prefix and read prefix config ✅ Locked

Each MCP server config holds:
- `WRITE_PREFIX`: the prefix this deployment writes to (e.g. `platform/my-service/` or empty for root)
- `READ_PREFIXES`: comma-separated list of **additional** foreign prefixes to include in reads/searches (e.g. `network/,shared/`)

`WRITE_PREFIX` is **always implicitly in scope for all reads and searches** — the user never needs to add it to `READ_PREFIXES`. `READ_PREFIXES` is purely opt-in cross-boundary access. Omitting it means the deployment reads only from where it writes.

```
read scope = WRITE_PREFIX (always, implicit)
           + READ_PREFIXES (additional foreign prefixes, opt-in)
```

The server does not prescribe a prefix naming convention. Users adopt whatever structure makes sense for their deployment (e.g. `{org}/{team}/{project}/`, `{team}/`, or flat). Both config values are treated as opaque string prefixes. If every project has a dedicated bucket, both can be left empty — the whole bucket is the scope.

### D4 — Standalone new MCP server, new repo ✅ Locked

Not embedded in `amanox-ai-agents`. Not a fork of awslabs/mcp. New repo, new Python package. `awslabs/mcp` is an architecture and implementation reference only.

**Candidate name:** `amanox-artifact-store-mcp`
**Language:** Python
**Framework:** FastMCP (same as awslabs/mcp)
**Transport:** stdio
**Distribution:** `uvx amanox-artifact-store-mcp@latest` (or local install for initial development)

### D5 — Backend: S3 Bucket + S3 Vectors + Bedrock embeddings ✅ Locked

Single backend. No DynamoDB. No INDEX.json. No Bedrock Knowledge Base.

**Evaluation summary:**

| Option | Semantic search | Write-then-read latency | Concurrent write safety | Verdict |
|--------|----------------|------------------------|------------------------|---------|
| INDEX.json | None | Immediate | Race condition (shared file) | Eliminated |
| DynamoDB + S3 | None | Immediate | Native atomic writes | Eliminated — no semantic search |
| Bedrock KB + S3 | Excellent (managed) | Minutes–hours (sync delay) | N/A | Eliminated — sync latency |
| S3 Bucket + S3 Vectors + Bedrock | Full semantic | Immediate | Not a problem (unique keys per artifact) | **Selected** |

**Why no DynamoDB:** The concurrent write race condition was specific to INDEX.json (a single shared file). Each artifact gets a unique key in S3 — there is no shared mutable resource. Two agents writing different artifacts simultaneously do not conflict. If create-or-fail semantics are needed for an artifact ID, S3 conditional writes (`If-None-Match: *`) handle it without a separate service.

**Why no Bedrock KB:** Requires pre-provisioning a Knowledge Base, configuring data sources, and triggering periodic sync. Sync latency (minutes to hours) breaks the immediate write-then-read workflow. Our write path must produce immediately searchable artifacts.

**Architecture per the blog post pattern:**

```
WRITE:
  content → S3 Bucket PutObject(key)
  content → Bedrock InvokeModel → embedding
  {key, embedding, metadata} → S3 Vectors PutVector(key)

SEARCH:
  query → Bedrock InvokeModel → query_embedding
  query_embedding → S3 Vectors QueryVectors(filter?) → [{key, metadata, score}]
  keys → S3 Bucket batch GetObject → full documents

READ (direct):
  artifact_id → S3 Bucket GetObject → content
```

### D6 — Artifact metadata schema stored in S3 Vectors ✅ Locked

S3 Vectors supports server-side metadata filtering on `query_vectors` calls. This replaces the need for a separate index (INDEX.md) or DynamoDB for filtering. Filtering is combined with semantic search in a single API call:

```python
s3_vectors.query_vectors(
    ...
    filter={"type": {"$eq": "code-review"}, "team": {"$eq": "platform"}}
)
```

**Required metadata fields (stored in S3 Vectors per vector):**

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Artifact type: `code-review`, `impl-note`, `adr`, `spec`, `issue-record`, `session-summary`, `research` |
| `feature` | string | Feature or work-unit slug: `auth`, `vpc-peering` |
| `team` | string | Team identifier provided by caller at write time (e.g. `platform`, `network`) |
| `project` | string | Project slug provided by caller at write time (e.g. `my-service`, `vpc-infra`) |
| `tier` | string | `"2"` for project-local artifacts; `"4"` for permanent/shareable knowledge |
| `date` | string | ISO date: `YYYY-MM-DD` |
| `status` | string | `active` (default) or `archived` — archived excluded from search by default |
| `title` | string | Human-readable title — enables display without S3 content fetch |
| `visibility` | string | `shared` (default) or `confidential` — controls cross-prefix read eligibility |

**Optional metadata fields:**

| Field | Type | Description |
|-------|------|-------------|
| `author_role` | string | Producing role: `developer`, `architect`, `analyst` |

**Why `team` and `project` are required (not derived from prefix):**

After a `QueryVectors` call across multiple prefixes, results are a flat list `{key, metadata, score}`. Without `team` and `project` in metadata, context must be inferred by parsing the key string — fragile and unreliable since prefix structure is user-defined (the server enforces no naming convention). These fields are provided by the caller at `write_artifact` time and stored in the vector metadata, making origin context explicit and filter-ready.

**Visibility and cross-prefix read scoping:**

The server enforces confidentiality at query time, not via IAM. The server knows its `WRITE_PREFIX`. When searching across `READ_PREFIXES`, it automatically adds a filter to exclude confidential artifacts:

| Query context | Filter applied |
|---|---|
| Within `WRITE_PREFIX` | No restriction — all artifacts, all visibility levels, all tiers |
| Within `READ_PREFIXES` | `tier = "4"` AND `visibility = "shared"` |

This means:
- Tier 2 artifacts never leak cross-prefix, even if a shared bucket is used
- Confidential artifacts (any tier) never appear in cross-prefix results
- An ADR containing security-sensitive details can be tier 3 but `visibility: confidential` — permanent but not shared

This is a **soft control** at the MCP layer. It is enforced by the server, not IAM. Engineers with direct S3 or S3 Vectors access can still read all objects. The MCP layer ensures agents operating via the server cannot surface confidential artifacts from foreign prefixes. Documenting this distinction in the server's README is mandatory.

V1 may implement `visibility` as a stored field without full enforcement (store it, return it in results, do not yet filter on it in cross-prefix reads). Full enforcement is a V2 hardening step — but the field must be in the schema from day one to avoid a breaking schema migration later.

**Connection to F3.2:** This schema directly addresses R6 (Artifact schema) from `f3.2-research.md`. The server IS the "semantic / vector search (MCP tool)" that F3.2 listed as a future R3 solution. Once deployed, it becomes the tier 2 and tier 3 infrastructure for F3.2.

### D7 — The server is deployment-agnostic ✅ Locked

The server is given a bucket name, an S3 Vectors bucket name, and an index name. It uses them. It does not care about the topology behind those names.

A deployment of the tool is its own independent tool. The deployment topology — one shared org-wide bucket, one bucket per team, one bucket per project, or one bucket per engineer — is entirely the user's and admin's concern. IAM policies (managed externally) control what the configured profile can actually access. The server trusts the credentials it is given.

**Config parameters:**

| Env var | Required | Description |
|---------|----------|-------------|
| `AWS_PROFILE` | No | If set: `boto3.Session(profile_name=...)`. Otherwise: default credential chain. |
| `AWS_REGION` | Yes | AWS region for all API calls |
| `ARTIFACT_BUCKET` | Yes | Standard S3 bucket name for artifact content |
| `VECTORS_BUCKET` | Yes | S3 Vectors bucket name |
| `VECTORS_INDEX` | Yes | S3 Vectors index name within the vectors bucket |
| `WRITE_PREFIX` | No | Prefix for all writes (default: empty = root). Example: `platform/my-service/` |
| `READ_PREFIXES` | No | Comma-separated additional read prefixes (default: `WRITE_PREFIX`). Example: `network/,shared/` |
| `BEDROCK_EMBEDDING_MODEL` | No | Embedding model ID (default: `amazon.titan-embed-text-v2:0`) |

### D8 — Cross-team sharing applies primarily to tier 3, not tier 2 ✅ Locked

Tier 2 artifacts are project-local working documents (code reviews, impl notes, session summaries). They are relevant to the team that produced them, not the org at large.

Cross-team sharing via `READ_PREFIXES` is intended for **tier 3** artifacts — ADRs, architecture decisions, canonical patterns — content with org-wide relevance that a different team's agent legitimately needs to find.

The `tier` metadata field (D6) enables this distinction: when searching across `READ_PREFIXES`, agents can filter to `tier=3` to read only the sharing-intended permanent knowledge from another team's prefix, without accidentally surfacing their tier 2 working documents.

### D9 — Key generation: content hash ✅ Locked

`{write_prefix}{type}/{sha256(type + feature + date + title)[:16]}.md`

Example: `code-review/a3f8b2c1d4e5f678.md`

**Why hash over path+UUID:**
- **Idempotent**: same logical artifact written twice (e.g. agent retries after crash) produces the same key and overwrites the previous write. No duplicate artifacts, no orphaned S3 Vectors entries.
- **Shorter**: no date segment, no UUID segment in the key itself.
- **Deterministic**: key is reconstructible from inputs — useful for targeted reads without a search.

The key is opaque in the S3 console, but all meaningful context (title, type, feature, team, project, date) lives in S3 Vectors metadata returned on every query result. The key's only job is to be a stable unique pointer.

### D10 — Embedding model: Titan Text Embeddings v2 ✅ Locked

Default: `amazon.titan-embed-text-v2:0` (1024 dimensions). Configurable via `BEDROCK_EMBEDDING_MODEL` env var.

The S3 Vectors index dimension must match the embedding model dimension. Changing the model requires recreating the index. This constraint is documented in the server README — it is not enforced programmatically in V1.

---

## D11 — Tools interface ✅ Locked

### `write_artifact`

```
write_artifact(
    content: str,                  # Full markdown content
    title: str,                    # Human-readable title
    artifact_type: str,            # One of the type values in D6 schema
    feature: str,                  # Feature/work-unit slug
    team: str,                     # Team identifier (stored in D6 metadata)
    project: str,                  # Project slug (stored in D6 metadata)
    tier: str = "2",               # "2" or "4" — defaults to tier 2
    visibility: str = "shared",    # "shared" or "confidential"
    author_role: str = "",         # Optional producing role
) → artifact_id: str
```

Steps:
1. Key = `{WRITE_PREFIX}{type}/{sha256(type+feature+date+title)[:16]}.md` (D9)
2. `S3 PutObject(key, content)`
3. `Bedrock InvokeModel(content)` → embedding (D10)
4. `S3 Vectors PutVector(key, embedding, metadata)` with full D6 schema
5. Returns `artifact_id` (= key)

### `read_artifact`

```
read_artifact(artifact_id: str) → content: str
```

Complements `list_artifacts`: after listing metadata-only results, the agent fetches full content for a specific known artifact. Confidentiality enforced before the S3 fetch:

1. `S3 Vectors GetVectors(key)` → retrieve metadata
2. If key is within `WRITE_PREFIX` → allow unconditionally
3. If key is within a foreign prefix → allow only if `tier=3 AND visibility=shared`; otherwise return "not found" (never leak existence of a confidential artifact)
4. `S3 GetObject(key)` → return content

### `search_artifacts`

```
search_artifacts(
    query: str,
    artifact_type: str = "",
    feature: str = "",
    team: str = "",
    project: str = "",
    tier: str = "",
    top_k: int = 5
) → list[{id, title, score, content, metadata}]
```

1. `Bedrock InvokeModel(query)` → query embedding
2. `S3 Vectors QueryVectors` across `WRITE_PREFIX` (no restriction) and each `READ_PREFIXES` entry (filter: `tier=3 AND visibility=shared`)
3. Merge and re-rank results by score
4. Batch `S3 GetObject(top-K keys)` → full content
5. Returns results ordered by semantic relevance

### `list_artifacts`

```
list_artifacts(
    artifact_type: str = "",
    feature: str = "",
    team: str = "",
    project: str = "",
    tier: str = "",
    status: str = "active"
) → list[{id, title, date, type, feature, team, project, tier, visibility, status}]
```

Metadata-only — no content fetch, no embedding call. Intended for browsing, not semantic retrieval.

1. `S3 ListObjects(prefix=WRITE_PREFIX)` → all keys in write scope
2. For each `READ_PREFIXES` entry: `S3 ListObjects(prefix=...)` → keys
3. Batch `S3 Vectors GetVectors(keys)` → metadata
4. Apply confidentiality client-side: keys from `WRITE_PREFIX` — no restriction; keys from `READ_PREFIXES` — keep only `tier=3 AND visibility=shared`
5. Apply caller's metadata filters (type, feature, status…) and return

### `archive_artifact`

```
archive_artifact(artifact_id: str) → ok: bool
```

1. `S3 Vectors GetVectors(key)` → verify key is within `WRITE_PREFIX` (archival is write-scope only)
2. `S3 Vectors PutVector(key, same_embedding, metadata: status=archived)`
3. S3 object tagged `archive=true` for optional lifecycle rules

### `health_check`

```
health_check() → {auth_ok, bucket_ok, vectors_ok, identity, region}
```

1. `STS GetCallerIdentity`
2. `S3 HeadBucket(ARTIFACT_BUCKET)`
3. `S3 Vectors DescribeVectorBucket(VECTORS_BUCKET)`
4. Returns status dict

---

## Connection to amanox-ai-agents (F3.2)

The new project directly resolves open questions in `f3.2-research.md`:

| F3.2 requirement | F3.2 status | How artifact-store-mcp resolves it |
|---|---|---|
| R1 — Storage location | Open | S3 Bucket — now viable because we own the infra |
| R2 — Naming convention | Open | Key derived from D9; type in path provides grouping |
| R3 — Index / retrieval | Open | S3 Vectors + metadata filter = the "Semantic / vector search (MCP tool)" option |
| R6 — Artifact schema | Open | D6 metadata schema in S3 Vectors — server-side filtering without parsing markdown |
| Promising idea #1 | Deferred | Semantic search over project history — now the core feature |

Once the MCP server exists, F3.2's tier 2 solution becomes: "configure `amanox-artifact-store-mcp`, then each skill that produces significant output includes a `write_artifact` step."

---

## What We Are NOT Building (Ruled Out)

- **Bedrock Knowledge Base**: sync latency, requires pre-provisioning, no direct write path
- **DynamoDB as metadata index**: not needed — S3 Vectors metadata handles filtering; unique keys eliminate concurrent write race
- **INDEX.json**: concurrent write race, no semantic search
- **Dual backend (S3 Vectors + INDEX.json fallback)**: over-engineering
- **GitHub wiki hack**: GitHub-specific, not portable
- **Local vector DB (Chroma, FAISS)**: not shared across engineers or machines
- **Offline-first / local cache**: out of scope for V1

---

## Next Steps

1. Challenge assumptions before scaffolding (in progress — see F3.2 tier model)
2. Begin project scaffolding: new repo, `pyproject.toml`, FastMCP skeleton
3. Update `f3.2-research.md` with link to this project as the tier 2 infrastructure answer
