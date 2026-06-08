---
status: accepted
references: []
authored:
  by: architect
  date: "2026-05-29"
revised:
  by: ""
  date: ""
---

# AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend

## Description

cairn-mcp requires four backend capabilities: durable content storage, a semantic vector
index with metadata filtering, an embedding model for write and search operations, and a text
generation model for server-side description generation during migration. This decision records
the choice of Amazon S3, Amazon S3 Vectors, and Amazon Bedrock (Titan Text Embeddings v2 for
embeddings; Amazon Nova Lite for text generation) to provide those capabilities, and the
rationale for preferring an all-AWS stack over alternatives.

## Status

Accepted

## Context

The server targets teams that already operate in AWS. Any backend choice must satisfy five
constraints:

1. **Durable content storage** — full artifact markdown must survive process restarts and be
   retrievable by deterministic key.
2. **Semantic vector search with metadata filtering** — queries must combine a similarity
   vector with structured filters (type, tier, team, project, feature tags). Results must be
   immediately consistent after a write in the same session (NFR-01).
3. **Embedding generation** — text must be embedded at write time and at query time. The model
   and its output dimension must be stable; changing either after data has been written
   invalidates all existing vectors.
4. **Server-side description generation** — the `migrate_artifacts` tool generates tweet-length
   descriptions for artifacts that arrive without one, server-side and concurrently, so that
   migrated artifacts are immediately searchable without requiring the agent to write each
   description manually.
5. **Unified IAM** — credentials, billing, and audit trail should be consolidated within the
   operator's existing AWS account. Adding external SaaS credentials increases operational
   surface.

S3 Vectors is a new AWS service (launched 2025) that stores vectors alongside their metadata
in a dedicated index, supports cosine similarity queries, and provides metadata filtering with
`$eq`, `$in`, `$nin`, and (now) `$gte`/`$lte` operators. It was purpose-built for the
write-then-query pattern this server requires.

Amazon Bedrock provides two distinct model capabilities, both accessed via the standard
`bedrock:InvokeModel` IAM permission:

- **Titan Text Embeddings v2** — the embedding model. Produces fixed-size float vectors at
  configurable dimensions (256, 512, or 1024). Used on every artifact write and on every
  search query. Its output dimension must match the S3 Vectors index dimension exactly.
- **Amazon Nova Lite** — a lightweight, cost-efficient text generation model. Used exclusively
  by `migrate_artifacts` to generate tweet-length descriptions (≤ 280 characters) for
  artifacts whose descriptors arrive without a `description` field. Nova Lite is opt-in:
  it is activated by setting `BEDROCK_TEXT_MODEL=amazon.nova-lite-v1:0`. When not configured,
  the startup check for it is skipped entirely and `migrate_artifacts` requires all
  descriptors to include a description.

**Critical immutability constraint:** The S3 Vectors index dimension cannot be changed after
creation. Changing `BEDROCK_EMBEDDING_MODEL` or `BEDROCK_EMBEDDING_DIMENSIONS` after data has
been written makes existing vectors semantically incompatible with new queries. A model change
requires deleting and recreating the index and re-indexing all artifacts via `reconcile_index`.

## Decision

We chose Amazon S3 for content storage, Amazon S3 Vectors for the semantic index, and Amazon
Bedrock for model inference — with Titan Text Embeddings v2 as the embedding model (always
required) and Amazon Nova Lite as the optional text generation model for server-side
description generation during migration. All services share a single AWS region, a single IAM
credential chain, and a single billing account. No external SaaS dependencies are introduced.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — S3 + S3 Vectors + Bedrock | All-AWS: unified IAM, billing, auditability; immediate write-then-query consistency; metadata filtering built in; no external SaaS credentials | S3 Vectors is a new service — not available in all regions; API surface may evolve; vector index dimension immutable after creation |
| S3 + Pinecone + OpenAI Embeddings | Pinecone is mature and widely used; OpenAI embeddings are high quality | Adds two external SaaS dependencies; separate API keys and billing; data leaves AWS boundary; potential compliance concern |
| S3 + OpenSearch Serverless + Bedrock | OpenSearch is a mature vector store; same AWS account | More operational complexity (cluster, access policies, index mapping); higher baseline cost; over-engineered for the team size and scale |
| S3 + ChromaDB (local) + Bedrock | Zero cloud cost for the index; simple setup | Index lives on the agent's local machine — not shared across agents, sessions, or team members; persistence requires manual backup |
| DynamoDB + OpenSearch + Bedrock | Fully managed; strong consistency on DynamoDB | Two separate services for what S3 Vectors provides in one; higher cost; DynamoDB adds complexity for binary content storage |

## Consequences

- The server is AWS-only. Teams not operating in AWS cannot use it — accepted constraint
  documented in the PRD's Product Value Failure section.
- S3 Vectors regional availability must be verified by the operator before provisioning; the
  server does not validate this at startup.
- The vector index dimension is a one-time decision. It is validated at startup (check 5) but
  cannot be changed without full re-indexing. Operators must document their dimension choice
  and treat it as immutable infrastructure.
- Changing the embedding model after go-live degrades search quality silently — new vectors
  are not comparable to old ones. The `reconcile_index` tool can rebuild the index but
  requires a new index to be created with the new dimension first.
- All communication with AWS services uses HTTPS (NFR-10). Encryption at rest is the
  operator's responsibility and is out of scope for the server.
- Bedrock throttling is handled with one retry and jitter (NFR-11); persistent throttling
  surfaces as a structured error to the agent.
- The two Bedrock models have independent failure modes: an unavailable or misconfigured
  embedding model (`BEDROCK_EMBEDDING_MODEL`) is a hard startup failure that prevents the
  server from starting; an unavailable text generation model (`BEDROCK_TEXT_MODEL`) is also a
  hard startup failure but only when `BEDROCK_TEXT_MODEL` is explicitly configured. Operators
  who do not need `migrate_artifacts`' description generation can omit `BEDROCK_TEXT_MODEL`
  entirely, reducing the required IAM surface by one model ARN.
