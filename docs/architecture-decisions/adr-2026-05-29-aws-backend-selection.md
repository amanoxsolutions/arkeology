---
type: ADR
id: adr-2026-05-29-aws-backend-selection
title: AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend
description: Records the choice of Amazon S3, Amazon S3 Vectors, and Amazon Bedrock as the unified AWS backend for content storage, semantic vector search, and model inference in Arkeology, and how the one vector index every team shares is configured and read — it runs in ENHANCED mode, which the server requires at startup for scoped-search recall, and every vector of an artifact is keyed {artifact_id}#{n} with at most 100 per artifact, so one GetVectors over #0..#99 reads them all and no per-artifact path scans the index or enumerates by filtered query, which a calibration on real AWS showed is not exhaustive.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/planning-artifacts/vision.md
    title: "Arkeology — Persistent Artifact Memory"
  - resource: docs/planning-artifacts/requirements.md
    title: "Arkeology — Requirements"
    last_modified: 2026-11-10T16:09:26Z
  - resource: docs/planning-artifacts/backlog.md
    title: Backlog
    last_modified: 2026-11-10T16:24:49Z
  - resource: docs/learnings.md
    title: Learnings
  - resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
  - resource: docs/contracts/modules/arkeology.tools.list.md
    title: arkeology.tools.list
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_ListVectors.html
    title: Amazon S3 API Reference — ListVectors
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_QueryVectors.html
    title: Amazon S3 API Reference — QueryVectors
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_GetVectors.html
    title: Amazon S3 API Reference — GetVectors
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_GetIndex.html
    title: Amazon S3 API Reference — GetIndex
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_Index.html
    title: Amazon S3 API Reference — Index (indexMode)
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_UpdateIndexMode.html
    title: Amazon S3 API Reference — UpdateIndexMode
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-metadata-filtering.html
    title: Amazon S3 User Guide — Metadata filtering (S3 Vectors)
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-index-mode.html
    title: Amazon S3 User Guide — Changing a vector index's mode
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html
    title: Amazon S3 User Guide — S3 Vectors limitations and restrictions
  - resource: https://aws.amazon.com/about-aws/whats-new/2026/09/s3-vectors-introduces-metadata-pre-filtering/
    title: Amazon S3 Vectors introduces metadata pre-filtering (What's New, September 2026)
  - resource: .docs/reviews/architecture-review-2026-11-10-arkeology.md
    title: "Architecture review — Arkeology (whole design record)"
    last_modified: 2026-11-10T11:21:17Z
  - resource: .docs/review-fixes/calibration-2026-11-12.md
    title: "Calibration: is a filtered, paged QueryVectors (ENHANCED) an exhaustive per-artifact lookup?"
  - resource: tests/integration/test_calibration_enhanced_filtered_query.py
    title: Calibration test — filtered, paged QueryVectors on ENHANCED
  - resource: docs/architecture-decisions/adr-2026-05-29-deterministic-artifact-ids.md
    title: Deterministic Slug-Based Artifact Identifiers
    last_modified: 2026-11-12T14:38:17Z
  - resource: docs/architecture-decisions/adr-2026-05-29-section-level-embedding.md
    title: Section-Level Embedding at H2 Boundaries
    last_modified: 2026-11-12T14:38:17Z
relationships:
  - to: adr-2026-05-29-deterministic-artifact-ids
    type: amends
  - to: adr-2026-05-29-section-level-embedding
    type: amends
generated:
  by: "axians-architect/unknown"
  at: 2026-05-29T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-12T17:36:17Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "human:mlnrt"
    at: 2026-11-12T17:36:17Z
---

# AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend

## Description

Arkeology requires four backend capabilities: durable content storage, a semantic vector
index with metadata filtering, an embedding model for write and search operations, and a text
generation model for server-side description generation during migration. This decision records
the choice of Amazon S3, Amazon S3 Vectors, and Amazon Bedrock (Titan Text Embeddings v2 for
embeddings; Amazon Nova Lite for text generation) to provide those capabilities, and the
rationale for preferring an all-AWS stack over alternatives. It also records how the one vector
index every team shares must be configured and read so that work on one artifact does not slow as
other teams' areas grow: the index runs in `ENHANCED` mode, so filtered searches find what their
filters match, and every vector of an artifact sits at a numbered key, `{artifact_id}#{n}`, so all of
one artifact's vectors are read by key, never by a scan of the whole index or a filtered query.

## Status

Accepted. The amendment of 2026-11-12 — the `ENHANCED` index-mode requirement and the numbered
vector keys — was accepted by the operator on 2026-11-12.

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

**One index for every team, and lookups by artifact.** Constraints C-03 and C-04 have every
participating team share one vector index, so its size is the whole organisation's. At the vision's
target — dozens of teams, each area holding hundreds to low thousands of artifacts, one vector per
indexed section (vision § Operating Context) — it holds on the order of a hundred thousand vectors:
about 240,000 at thirty teams of a thousand artifacts averaging eight vectors each. Much of the
server needs not a similarity search but every vector of one named artifact, or the metadata of a
short list of them: an overwriting write cleaning up the previous version's section vectors, a
delete, an archive, a lifecycle change, a link backfill, a purge deleting each artifact in turn, a
freshness check resolving sources, the cross-scope link gate, a migration checking each candidate,
and a reconcile re-indexing each artifact.

S3 Vectors has three read operations that could serve such a lookup:

- **`ListVectors`** takes no filter and no key prefix — only a page size of at most 1,000 (a page
  also ends once 1 MB has been processed), a continuation token, an optional parallel segment (at
  most 16), and switches for data and metadata. A lookup through it pages the whole index and keeps
  the matches in memory: at the target, at least 240 sequential pages for every lookup, about a
  minute at the quarter-second per page measured against real AWS on a small development index
  (`tests/integration/test_calibration_per_artifact_vector_lookup.py`), and it grows with every
  other team's area. The lesson that retired the union read model is the same cost: the read and
  list contracts already forbid a whole-index scan per artifact (`docs/learnings.md`).
- **`QueryVectors`** takes a metadata filter, a top-K of at most 10,000 results delivered in pages
  of at most 100 with a continuation token, and a query mode. How it applies the filter depends on
  the index's mode. On a `CLASSIC` index the filter and the similarity search run together, and a
  query whose filter matches few vectors may return fewer than top-K results although more match.
  On an `ENHANCED` index the filter is evaluated first and the search runs only over the vectors it
  matched (pre-filtering), and a query may carry at most 100 filter constraints, each value in an
  `$in` list counting as one. Vector buckets created on or after 30 September 2026 create
  `ENHANCED` indexes; older buckets hold `CLASSIC` ones, which `UpdateIndexMode` switches to
  `ENHANCED` in place, with no re-ingestion and no additional charge. `GetIndex` reports an index's
  mode. Pre-filtering is available in every commercial Region that has S3 Vectors.
- **`GetVectors`** reads up to 100 named keys per call, with or without each vector's data and
  metadata. `PutVectors` and `DeleteVectors` each take up to 500 keys per call.

**Measured on real AWS on 2026-11-12** (`.docs/review-fixes/calibration-2026-11-12.md`, instrument
`tests/integration/test_calibration_enhanced_filtered_query.py`): 12,545 synthetic vectors in a
1,024-dimension index in eu-west-1, queried with `queryMode` `ENHANCED`, which AWS documents as
running the query with pre-filtering exactly as an `ENHANCED` index does. A filtered query on one
`artifact_id`, with a top-K of 10,000 and its continuation token followed to the end:

- is complete only for artifacts of 10 or fewer vectors. Above that, 24–26 of 29 artifacts came
  back short, keeping 48–86% of their vectors; a 300-vector artifact returned 190 in one run and
  213 in another. The same keys came back on every repeat, eight minutes of re-polling changed
  nothing, and no probe vector — not even one of the artifact's own — made it complete;
- pages correctly but ends early: the token stops once the returned set is used up, not once every
  match is sent, with no error and nothing in the response showing that matches are missing;
- returns a vector written immediately before it, on the first query, for artifacts of 10 or fewer
  vectors;
- rejects an `$in` filter of 100 real ids: its error message limits a filter to 10,240 bytes. The
  two rejections are consistent with AWS counting the filter's JSON as sent, which would fit about
  93 ids; that counting is not confirmed.

With the index's own `CLASSIC` mode, 16 of the 21 artifacts of 10 or fewer vectors were also
incomplete, one returning 1 of 3. Every `GetVectors` the calibration made asked for keys that were
all present — 945 of them, all returned — or all missing: a re-check of all 12,545 keys after their
deletion returned none and raised nothing. A request mixing present and missing keys was not made,
and AWS documents the behaviour for a missing key in neither case.

## Decision

We chose Amazon S3 for content storage, Amazon S3 Vectors for the semantic index, and Amazon
Bedrock for model inference — with Titan Text Embeddings v2 as the embedding model (always
required) and Amazon Nova Lite as the optional text generation model for server-side
description generation during migration. All services share a single AWS region, a single IAM
credential chain, and a single billing account. No external SaaS dependencies are introduced.

**The vector index runs in `ENHANCED` mode, and the server refuses to start on any other.** Startup
check 5, which already reads the index's attributes with `GetIndex` to compare its dimension, also
requires the index mode to be `ENHANCED`. An index reporting `CLASSIC`, or reporting no mode, fails
the check with a message giving the `update-index-mode` command that switches it in place. The
reason is scoped-search recall: every scoped search, synthesis preparation and the store-shape
check 9 is a filtered query, and on a `CLASSIC` index those queries lost vectors even for artifacts
of 10 or fewer vectors, where `ENHANCED` returned them all. No degraded path is kept for a `CLASSIC`
index: a supported deployment is required instead, per `AGENTS.md` § Non-Negotiable Rules and
NFR-03. A deployment in a vector bucket created on or after 30 September 2026 is `ENHANCED`
already; an older one is switched once by the Admin, and never switched back while any server uses
it. The switch ships in the same major, breaking release as the OKF v0.2 store migration (Phase
15), an upgrade every server of a deployment must take, and the store-migration skill has the Admin
make it in that upgrade's window, while the servers are stopped and upgraded. No deployment yet
shares its index between teams, so in practice no server of an earlier release reads a switched
index. Where teams do share one (C-03) and upgrade in stages, a team still on an earlier release
keeps its `ListVectors` lookups, which the mode does not change, and its filtered searches gain
pre-filtering, under the same 100-constraint limit (Consequences).

Source: C-03, C-04, NFR-03; the release coupling (Operator, 2026-11-10); the calibration of 2026-11-12 (`.docs/review-fixes/calibration-2026-11-12.md`); https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_GetIndex.html; https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-index-mode.html; https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-metadata-filtering.html

**Every vector of an artifact sits at a numbered key, and every per-artifact path reads by key —
never by a scan of the whole index, never by a filtered query.** Each vector is keyed
`{artifact_id}#{n}`, `n` from 0 to 99. A write numbers an artifact's vectors in the document order of
its embedded sections, and an artifact with nothing to embed has its one document vector at `#0`.
The order carries no meaning — nothing reads a section from its key — so an artifact the store
migration re-keyed keeps the migration's numbering until its next update or re-index.
Heading-slug keys, and the disambiguation of colliding slugs, are retired. `EMBED_MAX_SECTIONS`
gets a maximum of 100 — the `GetVectors` per-call limit — checked at startup like its existing
range; the default stays 20. Then:

- **all of one artifact's vectors** are one `GetVectors` over `#0..#99`, which returns exactly the
  keys present. The range is always the full 100, never the live setting, so an artifact written
  under a higher setting is still read in full. Delete, purge and the freshness clean-up delete only
  the keys that read returned. An overwriting write puts `#0..#k-1`, then reads `#k..#99` and
  deletes what it found; reconcile's re-index does the same with its token test. Archive, the
  lifecycle change and the link backfill read with data and metadata, then re-put each key;
- **the metadata of several artifacts** — the freshness check's sources, the cross-scope link gate,
  the store migration's foreign sources and the `migrate_artifacts` candidate check — is one
  `GetVectors` of `{id}#0` per id, up to 100 ids per call. Every indexed artifact holds `#0`, and
  each of its vectors carries the same artifact-level metadata;
- **filtered `QueryVectors`** stays for similarity search, synthesis preparation and check 9's
  existence probe, which needs one hit and got one from every `ENHANCED` lookup with matches in the
  calibration. Reconcile keeps its one own-scope sweep per run as the orphan safety net; the other
  whole-scope enumerations keep their scans (Consequences).

The store migration of Phase 15 re-keys every own-scope vector by copy — read with data and
metadata, put under the numbered key, delete the old one — with no embedding call, from one
own-scope sweep, idempotently and resumably under its existing dry-run and `--apply` flow. Each
mutating operation's module contract states its by-key read, and `s3vectors.artifact` states the
key shape, so a later spec cannot add a scan or a filtered enumeration unseen. This amends the
section-key format of the deterministic artifact ids ADR, and the section key, the update clean-up
and the section cap of the section-level embedding ADR; each carries an accepted revision note
pointing here.

Source: C-03, C-04, NFR-13, NFR-17; vision § Operating Context; the calibration of 2026-11-12 (`.docs/review-fixes/calibration-2026-11-12.md`), which answered whether a filtered query on an `ENHANCED` index is exhaustive; the numbered-key ruling, "Agree with option B and have it put in place together in phase 15" (Operator, 2026-11-12); https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_GetVectors.html; https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — S3 + S3 Vectors + Bedrock | All-AWS: unified IAM, billing, auditability; immediate write-then-query consistency; metadata filtering built in; no external SaaS credentials | S3 Vectors is a new service — not available in all regions; API surface may evolve; vector index dimension immutable after creation |
| S3 + Pinecone + OpenAI Embeddings | Pinecone is mature and widely used; OpenAI embeddings are high quality | Adds two external SaaS dependencies; separate API keys and billing; data leaves AWS boundary; potential compliance concern |
| S3 + OpenSearch Serverless + Bedrock | OpenSearch is a mature vector store; same AWS account | More operational complexity (cluster, access policies, index mapping); higher baseline cost; over-engineered for the team size and scale |
| S3 + ChromaDB (local) + Bedrock | Zero cloud cost for the index; simple setup | Index lives on the agent's local machine — not shared across agents, sessions, or team members; persistence requires manual backup |
| DynamoDB + OpenSearch + Bedrock | Fully managed; strong consistency on DynamoDB | Two separate services for what S3 Vectors provides in one; higher cost; DynamoDB adds complexity for binary content storage |

**Reading the vectors of named artifacts from the shared index:**

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — numbered keys `{artifact_id}#{n}` under a 100-vector ceiling; one `GetVectors` over `#0..#99` per artifact, `{id}#0` for metadata lookups | Exact: a read by key has no recall to trust; one request per artifact, or per 100 ids, whatever the index holds; independent of the index mode and of settings history; deletes touch only keys that exist | Every per-artifact call site changes; an artifact holds at most 100 vectors; existing vectors must be re-keyed by the store migration, and until another team migrates, its artifacts have no `#0`; rests on `GetVectors` omitting missing keys, observed but not documented |
| Keep the `ListVectors` scan for every lookup (minimal option) | No change | Not taken — cost: at the documented target each lookup pages about 240,000 vectors, about a minute, against a write that must finish in under 2 seconds (NFR-13); a reconcile of one team's thousand artifacts makes a thousand such scans; the cost grows with every other team's area |
| Keep the scan, made parallel over up to 16 `ListVectors` segments | No key change | Not taken — cost: still downloads every team's vector metadata for each artifact; at best divides a minute by 16, and the cost still grows with the whole organisation's index |
| A filtered `QueryVectors` on `artifact_id`, top-K 10,000, paged to completion, on an `ENHANCED` index | No key change; one call site change in the client | Not taken — measured: complete only up to 10 vectors per artifact; above that it silently returned 48–86%, with no error and no remaining token, so a delete or an update's clean-up would leave vectors behind unseen. `$in` is also capped at 10,240 bytes of filter, per the error message — about 93 ids if AWS counts the filter as sent, which the measurement is consistent with but did not confirm |
| A filtered `QueryVectors` on whatever mode the index has, treating fewer than top-K results as proof of completeness | No Admin step | Not taken — unsafe on both modes: the measured shortfalls all returned fewer than top-K while more matched |
| Keep each artifact's vector key list in an annotation or another store | Any key shape; no ceiling | Not taken — extra state that can drift from the index: every write, delete, re-index and failed clean-up would have to keep it in step, and a stale list deletes too little or reads too little with no error |
| Derive the keys from the artifact's current content and settings | No new key shape | Not taken — settings drift: a lowered section cap or minimum length, or edited content, derives fewer keys than the index holds, and the vectors written under the earlier settings are never found again |
| A vector index per team | Each lookup and each enumeration is proportional to the team, not the organisation | Ends cross-scope semantic search (C-03); a separate decision, queued in the backlog under cross-scope security |

**Configuring the shared index's query mode:**

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — require an `ENHANCED` index at startup | Scoped searches and check 9 find what their filters match; follows AWS's own recommendation and the default for new buckets | One Admin step for an index in a bucket created before 30 September 2026, and it changes every team's servers on the shared index at once |
| Leave the index's mode alone (minimal option) | No Admin step | Not taken — on `CLASSIC`, scoped filtered queries lost vectors even for artifacts of 10 or fewer vectors, so a scoped search misses own-scope matches and check 9 can pass an unmigrated scope |
| Require nothing of the index, and set `queryMode` to `ENHANCED` on each filtered query — which AWS documents on a `CLASSIC` index as running one query with pre-filtering while the index stays as it is | No Admin step and no switch of the shared index; each query's behaviour travels with its own request | Correctness rests on a per-request parameter every query path must remember, and AWS presents it as the way to try pre-filtering before switching the index. Not taken (Operator, 2026-11-10): the switch ships with the breaking release whose upgrade every server already takes, no deployment shares its index between teams yet, and switching the index gives every filtered search pre-filtering |

## Consequences

- The server is AWS-only. Teams not operating in AWS cannot use it — accepted constraint
  documented in vision.md's Product-Value-Failure Pre-Mortem section.
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
- A deployment whose vector bucket was created before 30 September 2026 needs one Admin step
  before a server of this release starts: `UpdateIndexMode` to `ENHANCED` on the shared index,
  which needs `s3vectors:UpdateIndexMode` for the Admin only. The server needs no new permission:
  it already holds `s3vectors:GetIndex`, `s3vectors:GetVectors`, `s3vectors:QueryVectors`,
  `s3vectors:PutVectors` and `s3vectors:DeleteVectors`. The setting-up skill checks the mode of a
  new deployment's index, and the store-migration skill checks it during the upgrade.
- Reading all of one artifact's vectors costs one `GetVectors` request, and a metadata lookup one
  request per 100 ids, whatever the index holds and whatever other teams' areas grow to. An
  overwriting write adds one such read to its clean-up; a delete or a purge makes one read and at
  most one delete per artifact. None of these depends on the index mode.
- `EMBED_MAX_SECTIONS` above 100 refuses to start. An artifact therefore never holds more than 100
  vectors, against a default of 20. Raising the ceiling means changing the key scheme, not a
  setting.
- The store migration re-keys every own-scope vector from its heading-slug or bare-id key to its
  numbered key, with no embedding call. Until another team sharing the index migrates, its
  artifacts have no `#0`: a freshness check reports such a source missing, and the cross-scope link
  gate withholds an entry pointing at one, both until that team migrates. The store migration gives
  such a converted source no baseline, and that lasts: it never touches an artifact it has already
  migrated, so a synthesis migrated before its source's team keeps that source unchecked until the
  synthesis is updated. Teams whose syntheses cite each other's shared artifacts therefore migrate
  in the same window, or the citing team after the cited one. Own-scope lookups are unaffected,
  because an upgraded server does not start until its own scope is migrated (check 9).
- Every by-key read rests on `GetVectors` returning the keys that exist and omitting the others
  without an error. On 2026-11-12 that was observed only for requests whose keys were all present
  or all missing, and AWS documents neither, so an integration test observes the mixed request
  before the code that relies on it; if a missing key ever made the call fail, the reads would fail
  loudly rather than lose vectors silently.
- Filtered semantic search runs with pre-filtering on an `ENHANCED` index, so a selective filter
  returns more of its matches. A search filter that matches a large share of the index — the own
  scope plus every shared foreign artifact — does more work before the similarity search. Measured
  on about 12,500 vectors, a scoped top-10 search took about 100–110 ms at the median in both modes;
  with three to five samples that figure is indicative only.
- Every query on the index may carry at most 100 filter constraints, and a query over the limit is
  rejected with a validation error. A search filter holds about eight fixed constraints plus one per
  configured read prefix, one per tag, and one per id in the re-fetch loop's exclusion list, which
  the loop stops growing at 1 KB of ids — a few dozen at most. A deployment reading a handful of
  prefixes therefore stays well below 100. Search gets no constraint cap of its own: the limit is
  accepted as a known limit, to be revisited when a deployment reads several dozen prefixes or
  searches with many tags (Operator, 2026-11-10). A filter is also limited to 10,240 bytes, as AWS's
  error message states; whether the JSON is counted as sent is not confirmed.
- Startup check 9 of the store migration — one top-1 filtered query for an own-scope vector still
  in the pre-upgrade shape — is reliable only because check 5 has refused a `CLASSIC` index: on
  one, a filter matching a few vectors may return nothing, and an unmigrated scope would pass. On
  `ENHANCED` it needs one hit, and every lookup with matches in the calibration returned at least
  one.
- The whole-scope enumerations still scan the whole index, and they are a separate decision:
  listing, purge's two discovery steps, the freshness check's synthesis enumeration, the
  commit-link proposal, the delete and archive referrer check, and reconcile's one own-scope sweep
  per run. A filtered query cannot serve them completely, as the calibration showed, so that
  decision has to find another key-addressable structure or keep the scan.

**Known limits**

| Known limit | Documented workload it sits above |
|-------------|-----------------------------------|
| An artifact holds at most 100 vectors; `EMBED_MAX_SECTIONS` above 100 refuses to start | The default section cap is 20, and NFR-13's typical artifact has up to 20 sections |
| Every by-key read relies on `GetVectors` omitting a missing key without an error — observed on 2026-11-12 only for requests whose keys were all present or all missing, and not documented by AWS | No workload figure applies; an integration test observes the mixed request first, and a change to an error fails reads loudly rather than silently |
| A scoped search, and check 9's proof, are complete only while the index stays `ENHANCED`; switched back to `CLASSIC` while servers run, they may silently miss vectors until each server restarts and check 5 refuses it | No event at the documented workload switches it back: it is a manual Admin action, possible only for a bucket created before 30 September 2026, and both skills say not to |
| Until another team migrates its store, a cross-scope key lookup finds no `#0` for its artifacts; a synthesis migrated before its source's team keeps that source without a baseline until the synthesis is updated | No multi-team deployment exists yet; the missing and withheld effects end when that team runs the store migration, and the lost baseline is avoided by migrating citing teams with or after the teams they cite |
| Every query on the index carries at most 100 filter constraints and at most 10,240 bytes of filter, as AWS's error message states; a search carries about eight fixed constraints, one per read prefix, one per tag, and an exclusion list capped at 1 KB of ids | A deployment reading a handful of prefixes stays well below 100. Accepted with no search cap (Operator, 2026-11-10); revisit when a deployment reads several dozen prefixes or searches with many tags |
| An index holds at most 2 billion vectors | About 240,000 at the target |
