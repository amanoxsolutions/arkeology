---
type: brainstorming
title: Brainstorming — amanox-artifact-store-mcp
description: New standalone project brainstorming for an AWS S3-based agent knowledge store delivered as a Python MCP server, enabling AI agents to write, search, and retrieve structured artifacts across projects, teams, and sessions.
tags: []
timestamp: 2026-05-27T00:00:00Z
okf_version: "0.1"
status: complete
references: []
authored:
  by: "analyst"
  date: "2026-05-27"
revised:
  by: ""
  date: ""
techniques_used: []
assumptions_challenged: []
decisions_locked: [D1, D2, D3, D4, D5, D6-metadata-schema, D7-deployment-agnostic, D8-tier3-sharing, D8b-visibility-control, D9-key-generation, D10-embedding-model, D11-tools-interface, D12-section-level-indexing, D13-schema-discovery, D14-cross-scope-index-topology, D15-synthesis-tier3-artifact, D16-synthesise-artifacts-tool, D17-synthesis-granularity-any-lens, D18-synthesis-freshness-check]
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

This pattern is informed by awslabs/mcp but refined: awslabs frames `AWS_PROFILE` as the primary mechanism because their tools are exclusively interactive. Arkeology is designed for both interactive and automated use.

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
| `type` | string | ✅ | Artifact type: `code-review`, `impl-note`, `adr`, `spec`, `issue-record`, `session-summary`, `research`, `synthesis` |
| `team` | string | ✅ | Team identifier provided by caller at write time (e.g. `platform`, `network`) |
| `project` | string | ✅ | Project slug provided by caller at write time (e.g. `my-service`, `vpc-infra`) |
| `tier` | string | ✅ | `"2"` for project-local artifacts; `"3"` for permanent/shareable knowledge |
| `date` | string | ✅ | ISO date: `YYYY-MM-DD` |
| `status` | string | ✅ | `active` (default) or `archived` — archived excluded from search by default |
| `title` | string | ✅ | Human-readable title — enables display without S3 content fetch |
| `visibility` | string | ✅ | `shared` (default) or `hidden` — controls cross-prefix read eligibility |
| `features` | list[string] | ❌ | Feature or work-unit slugs: `["auth", "vpc-peering"]` — omit for cross-cutting artifacts (ADRs, research, session summaries) |
| `author_role` | string | ❌ | Producing role: `developer`, `architect`, `analyst` |

**Non-filterable metadata fields (declared at index creation, returned with query results, not usable in filters):**

| Field | Type | Required | Description | Size limit |
|-------|------|----------|-------------|------------|
| `description` | string | ✅ | Tweet-length summary of the artifact — primary signal for agents deciding whether to call `read_artifact` | Max 280 characters |
| `source_artifacts` | list[string] | ❌ | List of artifact identifiers used as source material — set only on `synthesis` type artifacts; enables staleness detection in the synthesis freshness check (FR-20) | Combined with description, must stay within 40 KB total metadata limit |

Uses 2 of the 10 available non-filterable key slots per index. Both must be declared at index creation time.

**S3 Vectors array filtering:** `features` is stored as a list. The S3 Vectors `$eq` operator matches if the query value equals **any element** in the list — `{"features": {"$eq": "auth"}}` correctly returns artifacts where `features` contains `"auth"` alongside other slugs. Validated against: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-metadata-filtering.html

**Why `team` and `project` are required (not derived from prefix):**

After a `QueryVectors` call across multiple prefixes, results are a flat list `{key, metadata, score}`. Without `team` and `project` in metadata, context must be inferred by parsing the key string — fragile and unreliable since prefix structure is user-defined (the server enforces no naming convention). These fields are provided by the caller at `write_artifact` time and stored in the vector metadata, making origin context explicit and filter-ready.

**Visibility and cross-prefix read scoping:**

The server enforces visibility control at query time, not via IAM. The server knows its `WRITE_PREFIX`. When searching across `READ_PREFIXES`, it automatically adds a filter to exclude hidden artifacts:

| Query context | Filter applied |
|---|---|
| Within `WRITE_PREFIX` | No restriction — all artifacts, all visibility levels, all tiers |
| Within `READ_PREFIXES` | `tier = "3"` AND `visibility = "shared"` |

This means:
- Tier 2 artifacts never leak cross-prefix, even if a shared bucket is used
- Hidden artifacts (any tier) never appear in cross-prefix results
- An ADR containing security-sensitive details can be tier 3 but `visibility: hidden` — permanent but not shared

This is a **soft control** at the MCP layer. It is enforced by the server, not IAM. Engineers with direct S3 or S3 Vectors access can still read all objects. The MCP layer ensures agents operating via the server cannot surface hidden artifacts from foreign prefixes. Documenting this distinction in the server's README is mandatory.

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
| `SEARCH_FETCH_TOP_K` | No | Section vectors requested per S3 Vectors call in the search re-fetch loop (default: 25, ceiling: 100) |
| `SEARCH_MAX_ITERATIONS` | No | Maximum S3 Vectors calls per search before returning whatever results are available (default: 3) |
| `SEARCH_DEFAULT_TOP_K` | No | Default number of artifacts returned when the caller does not specify (default: 5) |

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

Tier 3 artifacts are living documents. There is one `plan.md`, one `requirements.md`, one "VPC peering ADR". They are updated in place as decisions evolve. `date` is excluded from the hash — same `type + title` always produces the same key and overwrites the previous version regardless of when the update happens. The `date` metadata field is still stored in S3 Vectors and updated on every write to record when the artifact was last written.

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
    tier: str = "2",               # "2" or "3" — defaults to tier 2
    visibility: str = "shared",    # "shared" or "hidden"
    author_role: str = "",         # Optional producing role
) → artifact_id: str
```

Steps:
1. Key = `{WRITE_PREFIX}{type}/{sha256(type+date+title)[:16]}.md` for tier 2; `{WRITE_PREFIX}{type}/{sha256(type+title)[:16]}.md` for tier 3 (D9)
2. `S3 PutObject(key, content)`
3. Parse all `##` sections from content. For each section, `Bedrock InvokeModel(title + type + features + section_content)` → section embedding. If no `##` sections found, fall back to `Bedrock InvokeModel(title + description + type + features)` → single embedding (D12).
4. For each section: `S3 Vectors PutVector(key="{artifact_key}#{section_name_slug}", embedding, metadata={...D6 fields..., artifact_id: artifact_key, section: section_heading})`. For the fallback: `S3 Vectors PutVector(key=artifact_key, embedding, metadata={...D6 fields..., artifact_id: artifact_key})`.
5. Returns `artifact_id` (= artifact_key, never a section key)

### `read_artifact`

```
read_artifact(artifact_id: str) → content: str
```

Complements both `search_artifacts` and `list_artifacts`: after receiving metadata-only results from either tool, the agent fetches full content only for the specific artifacts it actually needs.

1. `S3 Vectors GetVectors(key)` → retrieve metadata
2. If key is within `WRITE_PREFIX` → allow unconditionally
3. If key is within a foreign prefix → allow only if `tier=3 AND visibility=shared`; otherwise return "not found" (never leak existence of a hidden artifact)
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

```
search_artifacts(
    query: str,
    artifact_type: str = "",
    features: str = "",            # Matches any artifact whose features list contains this value
    team: str = "",
    project: str = "",
    tier: str = "",
    top_k: int = SEARCH_DEFAULT_TOP_K   # Artifacts to return; server default via SEARCH_DEFAULT_TOP_K
) → list[{id, title, description, score, metadata}]
```

Returns **metadata + score only** — no S3 content fetch. The `description` field (stored as non-filterable metadata in S3 Vectors, returned at zero additional cost) gives the agent enough context to judge relevance and decide which artifacts to read via `read_artifact`. This avoids fetching full documents the agent may not need, keeps MCP response payloads bounded, and prevents context window flooding.

Re-fetch loop (D12):
1. `Bedrock InvokeModel(query)` → query embedding (once, before the loop)
2. `seen_artifact_ids = []`; `results = []`; `iteration = 0`
3. While `len(results) < top_k` AND `iteration < SEARCH_MAX_ITERATIONS`:
   - Build filter: user filters AND (`artifact_id` NOT IN `seen_artifact_ids`) AND cross-scope gate (`tier=3 AND visibility=shared` for `READ_PREFIXES` keys)
   - `S3 Vectors QueryVectors(top_k=SEARCH_FETCH_TOP_K, filter=filter)` across `WRITE_PREFIX` and each `READ_PREFIXES` entry
   - If no results returned: break (index exhausted)
   - Group returned section vectors by `artifact_id`; add new artifacts to `results`; extend `seen_artifact_ids`
   - `iteration += 1`
4. Return `results[:top_k]` ordered by best section score per artifact

**Known trade-off:** each re-fetch iteration adds one S3 Vectors call. In practice the loop exits on the first iteration for the vast majority of queries (small `top_k`, 3–6 sections per artifact). `SEARCH_MAX_ITERATIONS` is the hard latency bound.

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
4. Apply visibility control client-side: keys from `WRITE_PREFIX` — no restriction; keys from `READ_PREFIXES` — keep only `tier=3 AND visibility=shared`
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

| Requirement | Status in research | How Arkeology resolves it |
|---|---|---|
| R1 — Storage location | Open | S3 Bucket — now viable because we own the infra |
| R2 — Naming convention | Open | Key derived from D9; type in path provides grouping |
| R3 — Index / retrieval | Open | S3 Vectors + metadata filter = the "Semantic / vector search (MCP tool)" option |
| R6 — Artifact schema | Open | D6 metadata schema in S3 Vectors — server-side filtering without parsing markdown |
| Promising idea #1 | Deferred | Semantic search over project history — now the core feature |

Once Arkeology exists, the tier 2 solution for amanox-ai-agents skills becomes: "configure `arkeology`, then each skill that produces significant output includes a `write_artifact` step."

---

### D12 — Embedding strategy: automatic section-level indexing ✅ Locked

**Why not embed full content:**

Full content embedding suffers from boilerplate dilution. Structured artifacts have scaffolding (headings, reference lists, boilerplate) that occupies tokens without adding semantic meaning. The embedding ends up representing document structure rather than meaning.

**Why not a single configurable section list (`EMBEDDING_SECTIONS`):**

A configurable list of section names to embed was the original approach. It was replaced for three reasons: (1) it requires operator configuration that can be wrong or missing; (2) it produces one embedding per artifact, diluting the signal across heterogeneous sections; (3) a query for "trade-offs of the chosen approach" should match the `## Trade-offs` section directly, not a blended document-level embedding.

**What gets embedded — section-level indexing:**

Every `##` (H2) section in the artifact markdown is indexed as an independent vector. Each section vector is generated from: title + type + feature tags + section content. This produces N vectors per artifact (one per section), each carrying the full D6 filterable metadata plus `artifact_id` (the S3 object key) and `section` (the heading text) for grouping and display.

**Fallback — no `##` sections:**

If the artifact contains no H2 sections, one document-level vector is generated from: title + description field + type + feature tags. Vector key = artifact key (same as S3 object key). This preserves the "same key" property for the simple case.

**Section vector key scheme:**

Section vectors use key `{artifact_key}#{section_name_slug}` (e.g. `platform/code-review/a3f8b2c1.md#trade-offs`). The `#` character validity in S3 Vectors keys is to be verified in integration tests; `--` is the fallback separator with no design implications. Section keys are internal to the server and never exposed to callers — the `artifact_id` in filterable metadata is what callers use.

**Re-write idempotency:**

When an artifact is re-written (tier 3 living document, or same-day tier 2 overwrite), `PutVector` on existing section keys acts as an upsert (to be verified in integration tests — existing risk item). For removed or renamed sections, the server queries by `artifact_id` to find orphaned section keys and deletes them before writing new section vectors.

**Write cost:**

Each write now calls Bedrock N times (once per section) instead of once. For typical structured artifacts (3–6 sections), this is 3–6 embedding calls per write. At Titan Text Embeddings v2 pricing, the cost impact is negligible. Noted as a known trade-off; not a problem in practice.

**No configuration required:**

`EMBEDDING_SECTIONS` env var is eliminated. Zero configuration needed — all `##` sections are indexed automatically. Operators with no section structure still get a functional fallback embedding.

---

### D13 — Agent schema discovery: MCP Resources + recommended AGENTS.md snippet ✅ Locked

**Problem:**

The server's write capability requires agents to populate multiple metadata fields (type, tier, visibility, feature tags) correctly. Hardcoding valid values into each team's skills creates a version coupling problem and requires skill rewriting when the schema evolves.

**Two-layer solution:**

**Layer 1 — MCP Resources (runtime, server-side):**

The server exposes MCP Resources providing precise, always-current schema information:
- Artifact metadata schema: all required and optional fields, valid values, constraints
- Tier model: tier 2 vs tier 3 semantics, immutability rules, key generation behaviour
- Visibility and cross-scope access model
- Artifact type catalogue with usage guidance

Any MCP-compatible agent can query these resources at runtime. They are always in sync with the running server version.

**Layer 2 — Recommended AGENTS.md snippet (behavioural, repo-provided):**

The Arkeology repository ships a recommended AGENTS.md snippet in its documentation. Teams add this block to their root `AGENTS.md` once. It covers:
- When to write artifacts (end of session, after code review, after architecture decision)
- Artifact types and when to use each
- How to write a high-quality description — the key lever for search quality
- Tier 2 vs tier 3 decision guidance
- A pointer to MCP Resources for runtime schema precision

**Why AGENTS.md over a companion skill:**

- AGENTS.md is the machine-readable instruction convention — any agent that reads it picks up the guidance automatically, no skill loading required
- No skill rewriting — existing skills are untouched
- Framework-agnostic — works with any agent following the AGENTS.md convention
- Simple versioning — when Arkeology evolves, teams update their snippet from the docs

**Why not a companion skill:**

A companion skill requires teams to load it explicitly, creates a version coupling between the skill and the server, and adds framework dependency. The AGENTS.md + MCP Resources combination achieves the same outcome with less coupling and no framework dependency.

---

### D14 — Cross-scope vector index topology ✅ Locked

Cross-scope semantic search requires all participating teams to share **one S3 Vectors index, one embedding model, and one vector dimension**. Each team may have its own S3 prefix (and optionally its own S3 bucket) for content storage, but the vector index is shared. All writes from all participating deployments go into the same index — scoped by prefix in the metadata.

**Why a shared index:**

Reverse engineering the cross-team sharing use case: for a microservices team agent to retrieve a platform team ADR via semantic search, both the query and the indexed vectors must live in the same vector space. If teams use separate indexes with different dimensions or different embedding models, cross-scope search is broken at the index layer — not at the access control layer.

**Implication:**

Deployments using separate vector indexes per team cannot perform cross-scope semantic search. This is a hard deployment constraint documented in the prerequisites. Single-team deployments are unaffected.

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
- **Companion skill**: a dedicated skill for Arkeology would create a version coupling between the skill and the server schema, require skill loading by each team, and add framework dependency. Replaced by: MCP Resources for runtime schema discovery (D13) and a recommended AGENTS.md snippet shipped with the repo documentation.

---

## Next Steps

1. Challenge assumptions before scaffolding
2. Begin project scaffolding: new repo `arkeology`, `pyproject.toml`, FastMCP skeleton
3. Update `research-artifact-store.md` with a link to this project as the tier 2 infrastructure answer

---

## External Source Analysis — 2026-05-29

Two external sources were reviewed after vision.md and requirements.md were complete to challenge relevance before implementation begins.

### Source 1 — PageIndex (VectifyAI/PageIndex)

**What it is:** A vectorless, reasoning-based RAG system. For long, complex, unstructured documents (financial filings, legal manuals, academic textbooks), it builds a hierarchical tree index per document and uses LLM reasoning to navigate it. Core claim: *similarity ≠ relevance*; vector similarity search misses multi-step reasoning across long documents.

**Does it challenge Arkeology?** No.

PageIndex targets documents where structure is implicit and reasoning-intensive navigation is required. Arkeology artifacts are short (a few hundred to a few thousand words), explicitly structured by agent skills using consistent markdown templates, and written to be semantically dense. Vector search with metadata filtering is well-suited to them. At team scale with thousands of artifacts, tree-index-per-document navigation would be prohibitively expensive.

**What it validates:** structure matters in retrieval — which is exactly why D12 (EMBEDDING_SECTIONS) exists.

---

### Source 2 — Karpathy's llm-wiki

**What it is:** A pattern for LLM-maintained persistent knowledge bases. Instead of RAG (re-deriving knowledge from raw sources at query time), an LLM incrementally builds and maintains a structured wiki — synthesising new inputs into existing concept pages, cross-referencing related entries, and flagging contradictions. Three layers: raw sources (immutable), wiki (LLM-maintained synthesis), schema (AGENTS.md / CLAUDE.md for agent instructions).

**Does it challenge Arkeology?** No — complementary, not competing.

| | Arkeology | Karpathy wiki |
|---|---|---|
| What is stored | Raw agent work products — point-in-time records | Synthesised knowledge — evolving understanding |
| Scale | Teams, cross-project, thousands of artifacts | Individual to small team, one project |
| Infrastructure | AWS-backed, shared | Local markdown files |
| Search | Semantic + metadata filtering | index.md + LLM reasoning; optional hybrid search at scale |
| Cross-team sharing | First-class (tier 3 + shared gate) | Not designed for it |
| Write model | Agent writes → stored immediately | Agent writes → LLM synthesises into existing pages |
| Maintenance cost | Zero (store-and-retrieve) | Real (synthesis, contradiction flagging, linting) |

Arkeology stores raw artifacts; a Karpathy-style wiki synthesises them into compiled knowledge. They operate at different abstraction levels. The wiki pattern is a natural future layer *above* Arkeology — tier 3 shared artifacts are the natural vehicle for storing the synthesised output. This was captured as a Future Consideration in requirements.md.

**What it validates:**
- The three-layer model (raw sources / wiki / schema) directly mirrors our three-tier model (tier 1 ephemeral / tier 2 working artifacts / tier 3 canonical knowledge)
- AGENTS.md as the schema layer is independently chosen by Karpathy — validates D13
- His "lint" operation (check knowledge quality, flag contradictions, surface stale claims) is a more sophisticated counterpart to our health check and reconciliation tools
- The index.md approach works at small scale without vector search — but Karpathy explicitly references a hybrid BM25/vector search tool (`qmd`) as the wiki grows, validating that vector search is the right call at team scale

**Small-scale nuance:** For individuals on a single project, a local Karpathy wiki may be sufficient — no AWS infrastructure required. This correctly aligns with our existing "not a good fit" list: *small teams or short-lived projects where storing artifacts in the repository is sufficient*.

---

### Verdict

Both sources are in the same problem space (knowledge persistence for LLMs). Neither challenges the core approach. Arkeology is the right tool for its target use case: teams, cross-project sharing, AWS environments, semantic search at scale, immediate write-then-read consistency. The synthesis/wiki pattern is now **in scope** as of the 2026-05-29 brainstorming session — locked as D15–D17 below.

**D15 — Synthesis lives as tier 3 artifacts in Arkeology ✅ Locked**

Synthesis pages are stored as tier 3 shared artifacts with `type: synthesis`. They are living documents — overwritten when updated (tier 3 semantics). They participate in semantic search like any other artifact. No new infrastructure is required. `synthesis` is a first-class type in the type catalogue from day one.

**D16 — `synthesise_artifacts` is a V1 MCP tool (8th tool) ✅ Locked**

The server provides a synthesis preparation capability: semantic search + batch read of source artifact content, returned as a single response. The agent performs the synthesis in-context and writes the result back via `write_artifact` with `type=synthesis`, `tier=3`, and `source_artifacts=[...]`. The server retrieves and assembles; the agent synthesises. Covered by FR-19.

**D17 — Synthesis granularity is unconstrained ✅ Locked**

The `synthesise_artifacts` tool does not impose a granularity lens (per-topic, per-type, per-team). The agent provides the query and determines what to synthesise — both topic-based ("authentication architecture") and type-based ("all code review patterns for auth") are valid. The tool is a general-purpose preparation mechanism.

**D18 — Synthesis freshness check is a V1 Could-have ✅ Locked**

A synthesis freshness check tool scans all `synthesis` artifacts, compares their `date` against the `date` of each listed `source_artifact`, and flags stale or archived sources. Covered by FR-20. This is a metadata-only operation — no LLM call, no S3 content fetch.
