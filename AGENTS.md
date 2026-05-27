# cairn-mcp

## Overview
cairn-mcp is a Python MCP server that gives AI agents persistent artifact memory backed by AWS S3
(durable content storage), AWS S3 Vectors (vector embeddings + metadata filtering), and Amazon
Bedrock (embeddings via Titan Text v2). Agents connect via MCP to write, search, and recall
structured artifacts — code reviews, ADRs, implementation notes, specs, session summaries — across
sessions and across team boundaries. It directly resolves the tier 2 artifact gap from the F3.2
research: knowledge produced in one agent session is no longer discarded when the context window
closes. Any agent or workflow that depends on recalled context relies on this server; if it is
unavailable or misconfigured, all persisted memory is inaccessible.

## Project
- **Name:** cairn-mcp
- **Type:** mcp-server
- **Description:** MCP server for persistent artifact memory powered by AWS S3, S3 Vectors, and Bedrock embeddings

## Stack
- **Languages:** python
- **Frameworks:** fastmcp
- **Infrastructure:** none — the server is deployment-agnostic; S3 bucket, S3 Vectors bucket/index, and IAM are provisioned externally

## Agent Settings
- **Documentation:** docs/
- **Scratchpad:** .docs/

## Conventions
- **Testing approach:** test driven development
- **Python:**
  - **Logging:** logging

<!-- ──────────────────────────────────────────────────────────── -->
<!-- The sections below are OPTIONAL.                             -->
<!-- Include only what adds real value for agents.               -->
<!-- Missing sections are never errors.                          -->
<!-- ──────────────────────────────────────────────────────────── -->

## Repository Structure
<!-- TODO: Fill in once the project structure is established.
     Example:
     | Path          | Purpose                                                    |
     |---------------|------------------------------------------------------------|
     | `src/`        | MCP server source — tools, resources, prompts              |
     | `tests/`      | Unit and integration tests                                 |
     | `docs/`       | Committed documentation and ADRs                          |
     | `.docs/`      | Agent scratchpad — gitignored                             | -->

## Component Dependencies
<!-- TODO: List external services, data stores, or other repos this project depends on,
     and what a breaking change in each would mean for this project.
     Example: "Reads AWS Cost Explorer billing exports from the `billing-exports` S3 bucket owned
     by the management account team. A schema change in their export format requires updates to the
     Glue job in `src/etl/` and the Athena DDL in `sql/`." -->

## Working Conventions
<!-- TODO: What naming rules, patterns, or structural conventions should agents follow
     that are not obvious from reading the code?
     Example: "All CDK stacks are named <Domain>Stack (e.g. IngestionStack, TransformStack).
     New Lambdas go in src/functions/<name>/handler.py — business logic in a sibling module,
     never in handler.py directly. Athena queries are append-only — never modify existing files." -->

## Non-Negotiable Rules
<!-- TODO: The 3-5 things agents must never do in this repo. Think: security boundaries,
     architectural invariants, off-limits paths.
     Example:
     - Never commit secrets or credentials — use SSM Parameter Store or Secrets Manager
     - Never modify the `sql/` directory — queries are owned by the analytics team
     - Never deploy directly from a local machine — all deployments go through CI/CD -->

## High-Friction Areas
<!-- TODO: Gotchas, implicit contracts, and non-obvious dependencies that have caused problems before.
     Example: "The KMS key in InfraStack has a circular dependency with the S3 bucket policy.
     Adding new key grants requires a two-step deploy — see docs/adr/2026-03-kms-circular-dep.md.
     The Glue job IAM role must be updated manually when a new S3 bucket is added to the lake." -->

## CI and Quality Gates
<!-- TODO: What checks run in CI? What must pass before merge? What commands should agents run
     to validate their work before pushing?
     Example: "Run `make test` before pushing. Pre-commit hooks enforce ruff + mypy + terraform fmt.
     CI also runs `cdk synth` and `terraform validate` — a synthesis failure blocks merge.
     Glue jobs are validated with `pytest tests/unit/` using the local Docker Glue image." -->
