# cairn-mcp

> *A cairn is a pile of stones left at a waypoint so the next traveller knows the path was walked.*
> *Agents leave cairns for agents.*

cairn-mcp is a Python MCP server that gives AI agents persistent artifact memory. Knowledge
produced in one session — code reviews, architectural decisions, implementation notes, specs,
session summaries — is written as a structured artifact and made searchable by future agents,
across sessions and across team boundaries.

It is the answer to a simple problem: AI coding agents are stateless. When the context window
closes, everything learned is discarded. The next session, or the next engineer, starts from zero.
cairn-mcp makes that knowledge durable.

## How it works

Artifacts are stored in a standard S3 bucket and indexed in AWS S3 Vectors with embeddings from
Amazon Bedrock (Titan Text v2). Agents connect via the Model Context Protocol and call five tools:

| Tool | Purpose |
|---|---|
| `write_artifact` | Store a new artifact (embeds and indexes immediately) |
| `search_artifacts` | Semantic search with optional metadata filters |
| `read_artifact` | Fetch the full content of a known artifact by ID |
| `list_artifacts` | Browse artifacts by type, feature, team, or project |
| `archive_artifact` | Mark an artifact inactive without deleting it |

A sixth tool, `health_check`, validates connectivity to all three AWS services at startup.

## Status

> **Early development** — project scaffolding in progress.

## Prerequisites

<!-- TODO: fill in once pyproject.toml and AWS infrastructure requirements are finalised -->
- Python ≥ 3.13
- `uv`
- AWS credentials with access to S3, S3 Vectors, and Bedrock
- An S3 bucket, an S3 Vectors bucket, and an S3 Vectors index (provisioned externally)

## Quick start

<!-- TODO: fill in once the package is installable -->

## Configuration

<!-- TODO: fill in once environment variable handling is implemented -->
| Variable | Required | Default | Description |
|---|---|---|---|
| `AWS_REGION` | Yes | — | AWS region for all API calls |
| `ARTIFACT_BUCKET` | Yes | — | S3 bucket for artifact content |
| `VECTORS_BUCKET` | Yes | — | S3 Vectors bucket |
| `VECTORS_INDEX` | Yes | — | S3 Vectors index name |
| `AWS_PROFILE` | No | default chain | Named AWS profile |
| `WRITE_PREFIX` | No | *(empty)* | Prefix for all writes, e.g. `platform/my-service/` |
| `READ_PREFIXES` | No | *(empty)* | Comma-separated additional read prefixes |
| `BEDROCK_EMBEDDING_MODEL` | No | `amazon.titan-embed-text-v2:0` | Bedrock embedding model ID |

## License

<!-- TODO -->
