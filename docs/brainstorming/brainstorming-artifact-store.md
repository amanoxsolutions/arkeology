---
status: complete
project: amanox-artifact-store-mcp
language: python
decisions_locked: [D1, D2, D3, D4, D5, D6-metadata-schema, D7-deployment-agnostic, D8-tier3-sharing, D8b-confidentiality-visibility, D9-key-generation, D10-embedding-model, D11-tools-interface]
decisions_closed_not_applicable: [OQ3-cross-team-iam, OQ5-vector-index-topology]
---

# Brainstorming — amanox-artifact-store-mcp

## Description

New standalone project brainstorming. An AWS S3-based agent knowledge store delivered as a Python MCP server. Enables AI agents to write, search, and retrieve structured artifacts (code reviews, implementation notes, ADRs, specs, session summaries) across projects, teams, and AI coding sessions. Inspired by the awslabs/mcp architecture. Separate repo from `amanox-ai-agents`.

**Date:** 2026-05-27
**Facilitator Agent:** Analyst

---

## Problem Statement

AI coding agents are stateless. Knowledge produced in one session — code review findings, architectural decisions, implementation notes — is discarded when the context window closes. Engineers who return to a project the next day, or a second engineer joining the project, start from zero. The more agents are used, the worse this gets: decisions are re-made, patterns are re-discovered, bugs are re-fixed.

This is the tier 2 artifact gap identified in the artifact store research (`research-artifact-store.md`): artifacts exist locally and ephemerally but are unindexed and invisible across sessions and engineers.

The research ruled out external object stores for the *general skill baseline* (too much infra overhead). This project is that infrastructure — built once, used everywhere.

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

### S3 Vector blog post: The Missing Link (dev.to/mlnrt)

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

The server supports **all standard boto3 credential environments** — local developer machines, CI/CD pipelines, ECS tasks, Lambda, and any other runtime where AWS credentials are available. This explicitly includes automated use cases such as a code reviewer AI agent running in a CI/CD pipeline.

`AWS_PROFILE` is **optional and developer-facing**: when set, `boto3.Session(profile_name=profile)` is used. When absent, the standard boto3 default credential chain applies (environment variables → IAM role → instance profile → etc.). `AWS_PROFILE` is not the primary auth mechanism — it is a convenience for interactive local use. The default credential chain is the primary mechanism and works in all environments.

`AWS_REGION` is required for all API calls.

This pattern is informed by awslabs/mcp but refined: awslabs frames `AWS_PROFILE` as the primary mechanism because their tools are exclusively interactive. cairn-mcp is designed for both interactive and automated use.

### D2 — Startup credential check is the first guard ✅ Locked

`sts:GetCallerIdentity` is called at server startup. This is the **first** guard — it catches invalid or expired credentials before any tool is ever invoked, providing a fast-fail UX improvement. It is **not** the only guard.

Every boto3 API call throughout the server must independently catch credential-related errors (`ExpiredTokenException`, `InvalidClientTokenId`, and equivalents) and re-raise them as typed MCP error responses — never as raw exceptions. The agent receives a human-readable re-auth instruction on any credential failure, regardless of when in the session it occurs.

The startup check does not guarantee that credentials remain valid for the life of the session. Temporary credentials (STS tokens, SSO sessions, CI/CD OIDC tokens) can expire mid-session. The per-call error wrapping is the reliability layer; the startup check is the early-warning layer.

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

**Startup prefix access verification (mandatory, hard failure):** At startup, after the credential check (D2), the server verifies access to every configured prefix:
- `WRITE_PREFIX`: verify both **read and write** access (the server reads from and writes to this prefix)
- Each entry in `READ_PREFIXES`: verify **read** access

Any verification failure marks the server as failed and surfaces a clear error identifying the unreachable prefix. The server does not start in a degraded state. A misconfigured foreign prefix that silently returns empty results would be extremely difficult to debug — a loud startup failure is strictly preferable.

### D4 — Standalone new MCP server, new repo ✅ Locked

Not embedded in `amanox-ai-agents`. Not a fork of awslabs/mcp. New repo, new Python package. `awslabs/mcp` is an architecture and implementation reference only.

**Candidate name:** `amanox-artifact-store-mcp`
**Language:** Python
**Framework:** FastMCP (same as awslabs/mcp)
**Transport:** stdio — the transport for the **primary use case** (local interactive developer tooling). Not the only transport forever.
**Distribution:** `uvx amanox-artifact-store-mcp@latest` (or local install for initial development)

**Transport extensibility:** The server must be structured so that adding an HTTP/SSE transport in the future is a configuration choice, not an architectural rework. FastMCP natively supports multiple transports — no extra design work is needed now, but no design decision should close that door. The CI/CD use case (D1) may eventually require a persistent shared server rather than a per-job spawned process; when that need arises, HTTP/SSE transport should be addable without touching the tool implementations.

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

**Layering principle:** The server must be implemented in layers — storage (S3), vector search (S3 Vectors), embedding (Bedrock), and server (FastMCP) — each behind a clean interface. This is a general design discipline: technology evolves fast, and any layer must be replaceable without touching the others. This is not a hedge against S3 Vectors specifically — S3 Vectors is the right choice. It is an architectural discipline that keeps the codebase refactorable as the ecosystem changes.

**Architecture per the blog post pattern:**

```
WRITE:
  content → S3 Bucket PutObject(key)
  content → Bedrock InvokeModel → embedding
  {key, embedding, metadata} → S3 Vectors PutVector(key)

SEARCH:
  query → Bedrock InvokeModel → query_embedding
  query_embedding → S3 Vectors QueryVectors(filter?) → [{key, metadata, description, score}]
  → returns metadata + score only (no S3 GetObject — content fetched on demand via read_artifact)

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

**⚠️ Metadata size constraints (S3 Vectors limitations):**
- Filterable metadata per vector: **2 KB** — all filterable fields combined must stay under this limit
- Non-filterable metadata keys per index: **10** — must be declared at index creation; cannot be changed to filterable later
- Total metadata per vector: 40 KB (filterable + non-filterable combined)
- Top-K results per `QueryVectors` request: **100** — hard ceiling on `top_k` in `search_artifacts`
- Vectors per `GetVectors` API call: **100** — hard ceiling on batch size in `list_artifacts`

Reference: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html

**Filterable metadata fields (stored in S3 Vectors per vector, subject to 2 KB combined limit):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✅ | Artifact type: `code-review`, `impl-note`, `adr`, `spec`, `issue-record`, `session-summary`, `research` |
| `team` | string | ✅ | Team identifier provided by caller at write time (e.g. `platform`, `network`) |
| `project` | string | ✅ | Project slug provided by caller at write time (e.g. `my-service`, `vpc-infra`) |
| `tier` | string | ✅ | `"2"` for project-local artifacts; `"3"` for permanent/shareable knowledge |
| `date` | string | ✅ | ISO date: `YYYY-MM-DD` |
| `status` | string | ✅ | `active` (default) or `archived` — archived excluded from search by default |
| `title` | string | ✅ | Human-readable title — enables display without S3 content fetch |
| `visibility` | string | ✅ | `shared` (default) or `confidential` — controls cross-prefix read eligibility |
| `features` | list[string] | ❌ | Feature or work-unit slugs: `["auth", "vpc-peering"]` — omit for cross-cutting artifacts (ADRs, research, session summaries) |
| `author_role` | string | ❌ | Producing role: `developer`, `architect`, `analyst` |

**Non-filterable metadata fields (declared at index creation, returned with query results, not usable in filters):**

| Field | Type | Required | Description | Size limit |
|-------|------|----------|-------------|------------|
| `description` | string | ✅ | Tweet-length summary of the artifact — primary signal for agents deciding whether to call `read_artifact` | Max 280 characters |

`description` is stored as non-filterable metadata: it is never filtered on, but is returned with every `QueryVectors` result at zero additional S3 read cost. This is the mechanism that allows `search_artifacts` to return useful context without fetching full artifact content from S3. It uses 1 of the 10 available non-filterable key slots per index and must be declared at index creation time.

**S3 Vectors array filtering:** `features` is stored as a list. The S3 Vectors `$eq` operator matches if the query value equals **any element** in the list — `{"features": {"$eq": "auth"}}` correctly returns artifacts where `features` contains `"auth"` alongside other slugs. Validated against: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-metadata-filtering.html

**Why `team` and `project` are required (not derived from prefix):**

After a `QueryVectors` call across multiple prefixes, results are a flat list `{key, metadata, score}`. Without `team` and `project` in metadata, context must be inferred by parsing the key string — fragile and unreliable since prefix structure is user-defined (the server enforces no naming convention). These fields are provided by the caller at `write_artifact` time and stored in the vector metadata, making origin context explicit and filter-ready.

**Visibility and cross-prefix read scoping:**

The server enforces confidentiality at query time, not via IAM. The server knows its `WRITE_PREFIX`. When searching across `READ_PREFIXES`, it automatically adds a filter to exclude confidential artifacts:

| Query context | Filter applied |
|---|---|
| Within `WRITE_PREFIX` | No restriction — all artifacts, all visibility levels, all tiers |
| Within `READ_PREFIXES` | `tier = "3"` AND `visibility = "shared"` |

This means:
- Tier 2 artifacts never leak cross-prefix, even if a shared bucket is used
- Confidential artifacts (any tier) never appear in cross-prefix results
- An ADR containing security-sensitive details can be tier 3 but `visibility: confidential` — permanent but not shared

This is a **soft control** at the MCP layer. It is enforced by the server, not IAM. Engineers with direct S3 or S3 Vectors access can still read all objects. The MCP layer ensures agents operating via the server cannot surface confidential artifacts from foreign prefixes. Documenting this distinction in the server's README is mandatory.

V1 may implement `visibility` as a stored field without full enforcement (store it, return it in results, do not yet filter on it in cross-prefix reads). Full enforcement is a V2 hardening step — but the field must be in the schema from day one to avoid a breaking schema migration later.

**Connection to amanox-ai-agents:** This schema directly addresses R6 (Artifact schema) from `research-artifact-store.md`. The server IS the "semantic / vector search (MCP tool)" that the artifact store research listed as a future R3 solution. Once deployed, it becomes the tier 2 and tier 3 infrastructure for the three-tier document lifecycle.

### D7 — The server is deployment-agnostic ✅ Locked

The server is given a bucket name, an S3 Vectors bucket name, and an index name. It uses them. It does not care about the topology behind those names.

A deployment of the tool is its own independent tool. The deployment topology — one shared org-wide bucket, one bucket per team, one bucket per project, or one bucket per engineer — is entirely the user's and admin's concern. IAM policies (managed externally) control what the configured profile can actually access. The server trusts the credentials it is given.

**Regional constraints are the admin's responsibility.** The admin must deploy the server in an AWS region where S3 Vectors, Bedrock, and the configured Titan embedding model are all available. The server does not validate regional service availability — permission errors and service unavailability surface as typed MCP errors at runtime (D2 per-call error wrapping).

**No Bedrock model enablement step required.** Titan Text Embeddings v2 (`amazon.titan-embed-text-v2:0`) is an Amazon-native model — it is not sold through AWS Marketplace and requires no explicit opt-in or subscription. It is available by default to any IAM identity with `bedrock:InvokeModel` permission. No startup probe for model enablement is needed. Reference: https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html

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

### D8 — Cross-team sharing is restricted to tier 3 only ✅ Locked

Tier 2 artifacts are project-local working documents (code reviews, impl notes, session summaries). They are relevant to the team that produced them, not the org at large.

Cross-team sharing via `READ_PREFIXES` is **restricted to tier 3** artifacts — ADRs, architecture decisions, canonical patterns — content with org-wide relevance that a different team's agent legitimately needs to find.

**The `tier=3` gate on cross-prefix access is absolute.** A tier 2 artifact with `visibility=shared` is still never accessible cross-prefix. `visibility` is an additional control *within* the tier gate, not a substitute for it. Two independent controls must both pass: tier must be 3, and visibility must be shared.

**Why the absolute rule is correct:**

1. **Explicit promotion over accidental leak.** If information surfacing in a code review is genuinely org-wide relevant — an architectural insight, a security finding, a design constraint — the right action is to write it into a tier 3 document (ADR, design doc, spec) explicitly. That is a deliberate decision by a human or agent. Letting `visibility=shared` bypass the tier gate would allow working notes to leak cross-prefix without any conscious promotion step.

2. **Agent context quality.** Cross-prefix search results are loaded into an agent's context window. Tier 2 working documents from another team are written for that team's context — they reference their codebase, their decisions, their conventions. Loading them into an unrelated agent session introduces noise that actively misleads rather than informs. The tier=3 gate ensures cross-prefix results are signal-rich: only permanent, deliberately shared knowledge crosses team boundaries.

The `tier` metadata field (D6) enables this distinction: when searching across `READ_PREFIXES`, agents can filter to `tier=3` to read only the sharing-intended permanent knowledge from another team's prefix, without accidentally surfacing their tier 2 working documents.

### D9 — Key generation: content hash ✅ Locked

Key generation differs by tier because tier 2 and tier 3 artifacts have fundamentally different lifecycle semantics.

**Tier 2 — `{write_prefix}{type}/{sha256(type + date + title)[:16]}.md`**

Example: `code-review/a3f8b2c1d4e5f678.md`

Tier 2 artifacts are historical records. The same code review done in January and again in June are two distinct artifacts, both valuable. `date` is included in the hash as a temporal discriminator — different day → different key → different artifact. Same `type + date + title` on the same calendar day → same key → silent overwrite (idempotent retry).

**Tier 3 — `{write_prefix}{type}/{sha256(type + title)[:16]}.md`**

Example: `adr/b7c3e1f9a2d4e890.md`

Tier 3 artifacts are living documents. There is one `plan.md`, one `prd.md`, one "VPC peering ADR". They are updated in place as decisions evolve. `date` is excluded from the hash — same `type + title` always produces the same key and overwrites the previous version regardless of when the update happens. The `date` metadata field is still stored in S3 Vectors and updated on every write to record when the artifact was last written.

**Why hash over path+UUID:**
- **Idempotent**: same logical artifact written again produces the same key and overwrites. No duplicate artifacts, no orphaned S3 Vectors entries.
- **Shorter**: no UUID segment in the key itself.
- **Deterministic**: key is reconstructible from inputs — useful for targeted reads without a search.

**Hash inputs summary:**

| Tier | Hash inputs | Behaviour |
|---|---|---|
| Tier 2 | `type + date + title` | New day → new artifact; same day → overwrite |
| Tier 3 | `type + title` | Always overwrites; living document |

`features` was removed from hash inputs for both tiers. It is optional (absent for ADRs, research, session summaries) and therefore carries no reliable discriminating weight. Including it would require sorting the list for stability, adding complexity for near-zero benefit.

The key is opaque in the S3 console, but all meaningful context (title, type, features, team, project, date) lives in S3 Vectors metadata returned on every query result. The key's only job is to be a stable unique pointer.

### D10 — Embedding model: Titan Text Embeddings v2 ✅ Locked

Default: `amazon.titan-embed-text-v2:0` (1024 dimensions). Configurable via `BEDROCK_EMBEDDING_MODEL` env var.

The S3 Vectors index dimension must match the embedding model's output dimension. Changing the model requires recreating the index — this is enforced programmatically at startup, not left to documentation.

**Startup dimension check (mandatory):** At server startup, the server queries the S3 Vectors index metadata for its configured dimension and derives the embedding model's output dimension (from a known model registry or a probe call to Bedrock). If they do not match, the server refuses to start with a clear error:

> *"Configured embedding model produces N-dimensional vectors but the S3 Vectors index expects M dimensions. Recreate the index with the correct dimension or restore the original model."*

This turns a silent index corruption risk (mixed-dimension vectors producing meaningless search results) into a loud, actionable startup failure. "Documented in the README" is not a sufficient control for an operation that permanently corrupts the search index.

---

## D11 — Tools interface ✅ Locked

### `write_artifact`

```
write_artifact(
    content: str,                  # Full markdown content
    title: str,                    # Human-readable title
    description: str,              # Tweet-length summary ≤280 chars — shown in search results without fetching content
    artifact_type: str,            # One of the type values in D6 schema
    features: list[str] = [],      # Feature/work-unit slugs — optional, omit for cross-cutting artifacts
    team: str,                     # Team identifier (stored in D6 metadata)
    project: str,                  # Project slug (stored in D6 metadata)
    tier: str = "2",               # "2" or "4" — defaults to tier 2
    visibility: str = "shared",    # "shared" or "confidential"
    author_role: str = "",         # Optional producing role
) → artifact_id: str
```

Steps:
1. Key = `{WRITE_PREFIX}{type}/{sha256(type+date+title)[:16]}.md` for tier 2; `{WRITE_PREFIX}{type}/{sha256(type+title)[:16]}.md` for tier 3 (D9)
2. `S3 PutObject(key, content)`
3. `Bedrock InvokeModel(content)` → embedding (D10)
4. `S3 Vectors PutVector(key, embedding, metadata)` with full D6 schema
5. Returns `artifact_id` (= key)

### `read_artifact`

```
read_artifact(artifact_id: str) → content: str
```

Complements both `search_artifacts` and `list_artifacts`: after receiving metadata-only results from either tool, the agent fetches full content only for the specific artifacts it actually needs.

1. `S3 Vectors GetVectors(key)` → retrieve metadata
2. If key is within `WRITE_PREFIX` → allow unconditionally
3. If key is within a foreign prefix → allow only if `tier=3 AND visibility=shared`; otherwise return "not found" (never leak existence of a confidential artifact)
4. `S3 GetObject(key)` → return content

### `search_artifacts`

```
search_artifacts(
    query: str,
    artifact_type: str = "",
    features: str = "",            # Matches any artifact whose features list contains this value
    team: str = "",
    project: str = "",
    tier: str = "",
    top_k: int = 5                 # Hard ceiling: 100 (S3 Vectors QueryVectors limit)
) → list[{id, title, description, score, metadata}]
```

Returns **metadata + score only** — no S3 content fetch. The `description` field (stored as non-filterable metadata in S3 Vectors, returned at zero additional cost) gives the agent enough context to judge relevance and decide which artifacts to read via `read_artifact`. This avoids fetching full documents the agent may not need, keeps MCP response payloads bounded, and prevents context window flooding.

1. `Bedrock InvokeModel(query)` → query embedding
2. `S3 Vectors QueryVectors` across `WRITE_PREFIX` (no restriction) and each `READ_PREFIXES` entry (filter: `tier=3 AND visibility=shared`)
3. Merge and re-rank results by score
4. Return results ordered by semantic relevance — no S3 `GetObject` calls

### `list_artifacts`

```
list_artifacts(
    artifact_type: str = "",
    features: str = "",            # Matches any artifact whose features list contains this value
    team: str = "",
    project: str = "",
    tier: str = "",
    status: str = "active"
) → list[{id, title, description, date, type, features, team, project, tier, visibility, status}]
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
health_check() → {auth_ok, bucket_ok, vectors_ok, write_prefix_ok, read_prefixes_ok, identity, region}
```

1. `STS GetCallerIdentity` → `auth_ok`
2. `S3 HeadBucket(ARTIFACT_BUCKET)` → `bucket_ok`
3. `S3 Vectors DescribeVectorBucket(VECTORS_BUCKET)` → `vectors_ok`
4. Probe read + write access to `WRITE_PREFIX` → `write_prefix_ok`
5. Probe read access to each `READ_PREFIXES` entry → `read_prefixes_ok` (per-prefix status map)
6. Returns status dict — any `false` entry indicates a misconfiguration

---

## Connection to amanox-ai-agents

The new project directly resolves open questions in `research-artifact-store.md`:

| Requirement | Status in research | How cairn-mcp resolves it |
|---|---|---|
| R1 — Storage location | Open | S3 Bucket — now viable because we own the infra |
| R2 — Naming convention | Open | Key derived from D9; type in path provides grouping |
| R3 — Index / retrieval | Open | S3 Vectors + metadata filter = the "Semantic / vector search (MCP tool)" option |
| R6 — Artifact schema | Open | D6 metadata schema in S3 Vectors — server-side filtering without parsing markdown |
| Promising idea #1 | Deferred | Semantic search over project history — now the core feature |

Once cairn-mcp exists, the tier 2 solution for amanox-ai-agents skills becomes: "configure `cairn-mcp`, then each skill that produces significant output includes a `write_artifact` step."

---

## What We Are NOT Building (Ruled Out)

- **Bedrock Knowledge Base**: sync latency, requires pre-provisioning, no direct write path
- **DynamoDB as metadata index**: not needed — S3 Vectors metadata handles filtering; unique keys eliminate concurrent write race
- **INDEX.json**: concurrent write race, no semantic search
- **Dual backend (S3 Vectors + INDEX.json fallback)**: over-engineering
- **GitHub wiki hack**: GitHub-specific, not portable
- **Local vector DB (Chroma, FAISS)**: not shared across engineers or machines
- **Offline-first / local cache**: out of scope for V1
- **Artifact content editing**: tier 2 artifacts are **append-only and immutable by design** — a code review, session summary, or implementation note is a historical record; its value lies in being an unmodified point-in-time snapshot. New knowledge produces a new artifact, not an edit to an existing one. The sole exception is `archive_artifact`, which changes only the `status` metadata field, not the content. Tier 3 artifacts (ADRs, plans, specs) are intentionally mutable — plans change, decisions evolve — and should be updated via a new `write_artifact` call that produces a new dated artifact superseding the previous one.
- **Tier 2 → Tier 3 promotion tool**: if a code review or session note contains an insight important enough for org-wide permanent knowledge, the correct action is for the agent to surface that knowledge in existing or new tier 3 documentation. A `promote_artifact` tool would blur the boundary between working documents and canonical knowledge. The lifecycle is: produce artifacts → review and extract insights → write canonical tier 3 documents. This is an agent concern, not a server concern.
- **Context positioning enforcement**: how agents position retrieved artifacts in their context window (beginning vs. end) is a skill and agent convention, not a server responsibility. The server returns results; the skill instructs the agent where to place them.

---

## Next Steps

1. Challenge assumptions before scaffolding
2. Begin project scaffolding: new repo `cairn-mcp`, `pyproject.toml`, FastMCP skeleton
3. Update `research-artifact-store.md` with a link to this project as the tier 2 infrastructure answer
