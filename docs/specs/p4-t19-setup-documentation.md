---
type: spec
title: T19 — Setup Documentation and AGENTS.md Snippet
description: Adds actionable AWS provisioning steps, minimum IAM policy, index immutability warnings, and a copy-paste AGENTS.md snippet to the README so operators can deploy and configure cairn-mcp from scratch.
tags: []
timestamp: 2026-05-31T00:00:00Z
okf_version: "0.1"
feature: p4-t19-setup-documentation
status: ready
phase: 4
task: 19
references: []
authored:
  by: "architect"
  date: "2026-05-31"
revised:
  by: ""
  date: ""
---

# T19 — Setup Documentation and AGENTS.md Snippet

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

The README currently covers installation, the configuration table, running the server,
and a basic MCP client example. What is absent is actionable AWS provisioning guidance:
the exact steps to create an S3 bucket, S3 Vectors bucket, and S3 Vectors index with the
correct dimension, distance metric, and non-filterable key declarations; the minimum IAM
policy; and an explicit immutability warning (dimension, distance metric, and
non-filterable keys cannot be changed after index creation — a new index is required).
Also absent is the recommended AGENTS.md snippet — the copy-paste block that operators
paste into their project `AGENTS.md` so that every future agent session writes, searches,
and synthesises using cairn-mcp correctly. T17 must complete before this task so that
every statement in the documentation reflects empirically verified, not assumed, behaviour.

## User Stories

### Story 1 — Admin provisions all AWS resources following only the README (P1)

An admin unfamiliar with cairn-mcp internals follows the README and creates a working
deployment from scratch.

**Acceptance criteria:**
- Given an admin reads the "AWS Provisioning" section, then they can create an S3 artifact
  bucket, S3 Vectors bucket, and S3 Vectors index with the correct configuration using
  only the README steps — no other documentation required.
- Given the provisioning steps are complete and `.env` is filled in, when the admin runs
  `uv run cairn-mcp`, then the server starts without validation errors.
- Given the README provisioning steps, when an admin creates the S3 Vectors index, then
  they have declared both `description` and `source_artifacts` as non-filterable key slots
  and selected a dimension that matches their configured embedding model.

### Story 2 — Admin understands the index immutability constraint before creating it (P1)

**Acceptance criteria:**
- Given an admin reads the S3 Vectors index creation step, then they encounter a prominent
  warning that dimension, distance metric, index name, and non-filterable key slots are
  immutable after creation and that a new index must be created to change any of them.
- The warning explicitly states that a mismatch between the embedding model output
  dimension and the index dimension requires a new index.

### Story 3 — Admin configures a minimum IAM policy (P1)

**Acceptance criteria:**
- Given an admin applies the minimum IAM policy from the README to a service account,
  then all cairn-mcp tools operate correctly with no permission errors.
- The policy document in the README covers: S3 (`s3:GetObject`, `s3:PutObject`,
  `s3:DeleteObject`, `s3:ListObjectsV2`, `s3:HeadBucket`), S3 Vectors
  (`s3vectors:PutVectors`, `s3vectors:GetVectors`, `s3vectors:QueryVectors`,
  `s3vectors:DeleteVectors`, `s3vectors:DescribeIndex`, `s3vectors:ListVectors`), and
  Bedrock (`bedrock:InvokeModel` scoped to the embedding model ARN).

### Story 4 — Operator pastes the AGENTS.md snippet into their project (P1)

**Acceptance criteria:**
- Given an operator copies the AGENTS.md snippet from the README into their project
  `AGENTS.md`, then future agents in that project have all the guidance they need: when to
  write artifacts, which type to choose, how to write a quality description, tier 2 vs
  tier 3 selection, query strategy, when to synthesise and how to write the result back,
  and a pointer to the server's MCP Resources for runtime precision.
- The snippet is self-contained — it does not require the operator to look up any
  additional documentation before pasting it.

## Requirements

- THE README SHALL include an "AWS Provisioning" section with sequential steps covering:
  (1) create the S3 artifact bucket, (2) create the S3 Vectors bucket, (3) create the S3
  Vectors index — specifying dimension, cosine distance metric, and declaring `description`
  and `source_artifacts` as non-filterable metadata key slots, (4) enable Bedrock Titan
  Text Embeddings v2 model access in the target region.
- THE README SHALL include a prominent warning block immediately before or within the
  index creation step stating that the dimension, distance metric, index name, and
  non-filterable key slots are immutable after creation, and that any change requires
  destroying and recreating the index plus re-indexing all artifacts.
- THE README SHALL include a "Minimum IAM Policy" subsection containing a JSON IAM policy
  document listing all and only the permissions required for the server to function:
  S3 object operations (GetObject, PutObject, DeleteObject, ListObjectsV2, HeadBucket),
  S3 Vectors operations (PutVectors, GetVectors, QueryVectors, DeleteVectors,
  DescribeIndex, ListVectors), and Bedrock InvokeModel scoped to the embedding model ARN.
- THE README SHALL include a "Recommended AGENTS.md Snippet" section containing a
  fenced copy-paste block covering: when to write artifacts (at session close, after
  key decisions, after code reviews), artifact type selection guidance for all eight
  types, description quality guidance (tweet-length, search-optimised, not a file
  heading), tier 2 vs tier 3 selection (point-in-time record vs living document),
  query strategy (start with type + tags filters; issue a pure semantic query
  only if filters return insufficient results; use `list_artifacts` to browse without a
  query), synthesise guidance (when to synthesise, how to call `synthesise_artifacts`,
  how to write the result back as `type="synthesis"`, `tier=3` with `source_artifacts`),
  and a pointer to `cairn://schema/*` MCP Resources for runtime schema precision.
- All documented behaviours SHALL reflect empirically verified results from T17.

## Boundaries

**Always:**
- This is a documentation-only task — no new code is written.
- All existing README content is preserved and extended, not replaced.
- The AGENTS.md snippet lives in the README as a copy-paste reference — it is NOT added
  to the cairn-mcp repository's own `AGENTS.md`.
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
- Do not add the AGENTS.md snippet to `cairn-mcp/AGENTS.md` — it is for operators'
  projects, not this repo.
- Do not exceed the README's existing register — match the existing tone and structure.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `README.md` | Modify | Add "AWS Provisioning" section (with immutability warning), "Minimum IAM Policy" subsection, "Recommended AGENTS.md Snippet" section |

## Testing Approach

Documentation task — no automated tests. Acceptance is manual:

- Follow the "AWS Provisioning" steps in a clean environment; verify the server starts
  with `uv run cairn-mcp` and the startup validation sequence completes without errors.
- Apply the minimum IAM policy to a test role; run the integration test suite; verify no
  permission-denied errors occur.
- Copy the AGENTS.md snippet into a scratch `AGENTS.md`; review it against all items
  required by NFR-12 and FR-18 (types, tiers, description quality, query strategy,
  synthesis, MCP Resources pointer).

## Open Questions

- **Dependency on T17:** this task must not be started until T17 passes green and its
  Learnings are recorded. The upsert result, `#` key confirmation, and `$nin` confirmation
  from T17 may affect a clarifying note in the configuration reference. Review T17 Learnings
  before finalising any behaviour-describing statement in the README.
