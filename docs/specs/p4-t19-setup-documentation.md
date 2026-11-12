---
type: Spec
id: p4-t19-setup-documentation
title: T19 — Setup Documentation and AGENTS.md Snippet
description: Adds actionable AWS provisioning steps, minimum IAM policy, index immutability warnings, and a copy-paste AGENTS.md snippet to the README so operators can deploy and configure Arkeology from scratch.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-31T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-12T14:38:17Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T19 — Setup Documentation and AGENTS.md Snippet

## TL;DR

The README gains actionable AWS provisioning steps with a prominent index-immutability warning, a
minimum IAM policy, and a copy-paste AGENTS.md snippet. An admin can then deploy Arkeology from
scratch using only the README, and an operator can paste the snippet into their own project so
every future agent session uses Arkeology correctly — with every documented behaviour backed by
T17's empirically verified results.

## Open Questions

- **Dependency on T17:** this task must not be started until T17 passes green and its
  Learnings are recorded. The upsert result, `#` key confirmation, and `$nin` confirmation
  from T17 may affect a clarifying note in the configuration reference. Review T17 Learnings
  before finalising any behaviour-describing statement in the README.

## 1. Problem Statement

The README currently covers installation, the configuration table, running the server, and a basic
MCP client example. What is absent is actionable AWS provisioning guidance: the exact steps to
create an S3 bucket, S3 Vectors bucket, and S3 Vectors index with the correct dimension, distance
metric, and non-filterable key declarations; the minimum IAM policy; and an explicit immutability
warning (dimension, distance metric, and non-filterable keys cannot be changed after index creation
— a new index is required). Also absent is the recommended AGENTS.md snippet — the copy-paste block
that operators paste into their project `AGENTS.md` so that every future agent session writes,
searches, and synthesises using Arkeology correctly. T17 must complete before this task so that
every statement in the documentation reflects empirically verified, not assumed, behaviour. The
four stories — an admin provisioning all AWS resources following only the README, an admin
understanding the index immutability constraint before creating the index, an admin configuring a
minimum IAM policy, and an operator pasting the AGENTS.md snippet into their project — are all P1.

## 2. Rules — AWS provisioning

### R1 — The "AWS Provisioning" section is enough to deploy from scratch

The README includes an "AWS Provisioning" section with sequential steps covering:

1. create the S3 artifact bucket;
2. create the S3 Vectors bucket;
3. create the S3 Vectors index — specifying dimension, cosine distance metric, and declaring
   `description` and `source_artifacts` as non-filterable metadata key slots;
4. enable Bedrock Titan Text Embeddings v2 model access in the target region.

An admin unfamiliar with Arkeology internals who reads the "AWS Provisioning" section can create
an S3 artifact bucket, S3 Vectors bucket, and S3 Vectors index with the correct configuration using
only the README steps — no other documentation required — and so creates a working deployment from
scratch.

| Given | When | Then |
|-------|------|------|
| The provisioning steps are complete and `.env` is filled in | The admin runs `uv run arkeology` | The server starts without validation errors |
| The README provisioning steps | An admin creates the S3 Vectors index | They have declared both `description` and `source_artifacts` as non-filterable key slots and selected a dimension that matches their configured embedding model |

Source: none

### R2 — A prominent immutability warning comes at the index creation step

The README includes a prominent warning block immediately before or within the index creation
step, so an admin reading the S3 Vectors index creation step encounters it. It states that the
dimension, distance metric, index name, and non-filterable key slots are immutable after creation,
that a new index must be created to change any of them, and that any change requires destroying
and recreating the index plus re-indexing all artifacts. The warning explicitly states that a
mismatch between the embedding model output dimension and the index dimension requires a new
index.

Source: none

## 3. Rules — Minimum IAM policy

### R3 — The "Minimum IAM Policy" subsection lists all and only the required permissions

The README includes a "Minimum IAM Policy" subsection containing a JSON IAM policy document listing
all and only the permissions required for the server to function:

- S3: `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListObjectsV2`, `s3:HeadBucket`;
- S3 Vectors: `s3vectors:PutVectors`, `s3vectors:GetVectors`, `s3vectors:QueryVectors`,
  `s3vectors:DeleteVectors`, `s3vectors:GetIndex`, `s3vectors:ListVectors`;
- Bedrock: `bedrock:InvokeModel` scoped to the embedding model ARN.

Given an admin applies the minimum IAM policy from the README to a service account, all Arkeology
tools operate correctly with no permission errors.

Source: https://docs.aws.amazon.com/service-authorization/latest/reference/list_s3vectors.html

## 4. Rules — Recommended AGENTS.md snippet

### R4 — The "Recommended AGENTS.md Snippet" gives future agents all the guidance they need

The README includes a "Recommended AGENTS.md Snippet" section containing a fenced copy-paste block
covering:

- when to write artifacts (at session close, after key decisions, after code reviews);
- artifact type selection guidance for all artifact types (the full catalogue lives in
  `arkeology://schema/types`);
- description quality guidance (tweet-length, search-optimised, not a file heading);
- tier 2 vs tier 3 selection (point-in-time record vs living document);
- query strategy (start with type + tags filters; issue a pure semantic query only if filters
  return insufficient results; use `list_artifacts` to browse without a query);
- synthesise guidance (when to synthesise, how to call `synthesise_artifacts`, how to write the
  result back as `type="synthesis"`, `tier=3` with `source_artifacts`);
- a pointer to `arkeology://schema/*` MCP Resources for runtime schema precision.

Given an operator copies the AGENTS.md snippet from the README into their project `AGENTS.md`,
future agents in that project have all the guidance they need. The snippet is self-contained — it
does not require the operator to look up any additional documentation before pasting it.

Source: NFR-12, FR-18 — the types, tiers, description quality, query strategy, synthesis and MCP
Resources pointer items (per the Testing Approach)

## 5. Rules — Verified behaviour

### R5 — Every documented behaviour reflects T17's verified results

All documented behaviours reflect empirically verified results from T17, not assumed behaviour.

Source: none

## 6. Boundaries

**Always:**
- This is a documentation-only task — no new code is written.
- All existing README content is preserved and extended, not replaced.
- The AGENTS.md snippet lives in the README as a copy-paste reference — it is NOT added
  to the Arkeology repository's own `AGENTS.md`.
- The IAM policy must be minimum-viable — no wildcard actions, no extra permissions.
- The provisioning steps use AWS CLI commands or console steps as prose — no CDK,
  CloudFormation, or Terraform is included.

**Ask First:**
- Nothing — all constraints are defined. Block on T17 completion before writing.

**Never:**
- Do not document unverified behaviours — all statements must be backed by T17's
  empirical results.
- Do not include infrastructure-as-code provisioning (CDK, Terraform, CloudFormation) —
  manual CLI steps only.
- Do not add the AGENTS.md snippet to `arkeology/AGENTS.md` — it is for operators'
  projects, not this repo.
- Do not exceed the README's existing register — match the existing tone and structure.

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `README.md` | Modify | Add "AWS Provisioning" section (with immutability warning), "Minimum IAM Policy" subsection, "Recommended AGENTS.md Snippet" section |

### Contracts

None.

### Testing Approach

Documentation task — no automated tests. Acceptance is manual:

- Follow the "AWS Provisioning" steps in a clean environment; verify the server starts
  with `uv run arkeology` and the startup validation sequence completes without errors.
- Apply the minimum IAM policy to a test role; run the integration test suite; verify no
  permission-denied errors occur.
- Copy the AGENTS.md snippet into a scratch `AGENTS.md`; review it against all items
  required by NFR-12 and FR-18 (types, tiers, description quality, query strategy,
  synthesis, MCP Resources pointer).
