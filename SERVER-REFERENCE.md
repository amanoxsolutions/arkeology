# cairn-mcp — Server Reference

Configuration reference, IAM policy, and headless server setup for cairn-mcp operators
and CI/CD pipeline integrations.

## Minimum IAM Policy

Attach the following policy to the IAM user or role that runs cairn-mcp. Replace each `YOUR-*` placeholder with your actual values before applying.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3ArtifactBucket",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:HeadBucket",
        "s3:HeadObject"
      ],
      "Resource": [
        "arn:aws:s3:::YOUR-ARTIFACT-BUCKET",
        "arn:aws:s3:::YOUR-ARTIFACT-BUCKET/*"
      ]
    },
    {
      "Sid": "S3VectorsIndex",
      "Effect": "Allow",
      "Action": [
        "s3vectors:PutVectors",
        "s3vectors:GetVectors",
        "s3vectors:QueryVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:DescribeIndex",
        "s3vectors:ListVectors"
      ],
      "Resource": "arn:aws:s3vectors:YOUR-REGION:YOUR-ACCOUNT-ID:bucket/YOUR-VECTORS-BUCKET/index/YOUR-INDEX-NAME"
    },
    {
      "Sid": "BedrockEmbeddingModel",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:YOUR-REGION::foundation-model/amazon.titan-embed-text-v2:0"
    },
    {
      "Sid": "BedrockTextModel",
      "Comment": "Required only if using migrate_artifacts. In us-east-1 use the foundation-model ARN below. In all other regions replace with the cross-region inference profile ARN, e.g. arn:aws:bedrock:eu-west-1::inference-profile/eu.amazon.nova-lite-v1:0",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:YOUR-REGION::foundation-model/amazon.nova-lite-v1:0"
    }
  ]
}
```

## Configuration

All configuration is read from environment variables. Pass them via your IDE's MCP config
file `env` (or `environment`) block — see the `setting-up-cairn` skill for the exact
format for each supported IDE.

| Variable | Required | Default | Description |
|---|---|---|---|
| `AWS_REGION` | Yes | — | AWS region for all API calls |
| `ARTIFACT_BUCKET` | Yes | — | S3 bucket for artifact content |
| `VECTORS_BUCKET` | Yes | — | S3 Vectors bucket |
| `VECTORS_INDEX` | Yes | — | S3 Vectors index name |
| `AWS_PROFILE` | No | SDK default chain | Named AWS profile to use |
| `WRITE_PREFIX` | No | `artifacts` | Prefix for all artifact writes — must not be empty |
| `READ_PREFIXES` | No | *(none)* | Comma-separated foreign read scopes (e.g. `shared/org,shared/platform`) |
| `BEDROCK_EMBEDDING_MODEL` | No | `amazon.titan-embed-text-v2:0` | Bedrock embedding model ID |
| `BEDROCK_EMBEDDING_DIMENSIONS` | No | `1024` | Embedding dimensions — must match the S3 Vectors index dimension |
| `SEARCH_FETCH_TOP_K` | No | `25` | Section vectors requested from S3 Vectors per search iteration |
| `SEARCH_MAX_ITERATIONS` | No | `3` | Maximum S3 Vectors calls per search before returning available results |
| `SEARCH_DEFAULT_TOP_K` | No | `5` | Default number of artifacts returned when the caller does not specify |
| `FAILURE_LOG_PATH` | No | `.cairn_failures.jsonl` | Path to the tier 1 failure log file (JSONL); appended on partial write failures |
| `SECTION_CONCURRENCY` | No | `5` | Max concurrent Bedrock embed calls per artifact write. Increase for faster bulk writes; lower to avoid throttling. Must be ≥ 1. |
| `EMBED_MAX_SECTIONS` | No | `20` | Maximum number of `##` sections indexed per artifact. Sections beyond the cap are dropped from the vector index; full content is still stored in S3. Must be ≥ 1. |
| `EMBED_MIN_SECTION_LENGTH` | No | `50` | Minimum body length (chars, stripped) for a section to be indexed. Sections shorter than this are dropped from the vector index. Set to `0` to disable. |
| `EMBED_MAX_SECTION_LENGTH` | No | `24000` | Maximum body length (chars) per section before truncation for embedding. Set to `0` to disable. |
| `BEDROCK_TEXT_MODEL` | No | *(unset)* | Bedrock text model used by `migrate_artifacts` to generate artifact descriptions server-side. When unset, server-side generation is disabled. Use a cross-region inference profile ID for your region (e.g. `eu.amazon.nova-lite-v1:0` for EU, `us.amazon.nova-lite-v1:0` for US cross-region) — the bare `amazon.nova-lite-v1:0` only works in `us-east-1`. |
| `LOG_LEVEL` | No | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Per-call tool parameters

Some parameters are passed per call rather than configured server-wide. They let individual
callers tune behaviour without restarting the server.

| Parameter | Tool(s) | Default | Behaviour |
|---|---|---|---|
| `artifact_concurrency` | `write_artifacts`, `migrate_artifacts` | `3` | Max artifacts processed concurrently. Values above 15 are capped to 15; values below 1 are substituted with the default 3. Both out-of-range cases return a `"warning"` field in the response. In-range values produce no warning. Keep `artifact_concurrency × SECTION_CONCURRENCY ≤ 15` as a safe Bedrock quota guideline (e.g. `artifact_concurrency=3` × `SECTION_CONCURRENCY=5` = 15 concurrent embed calls). |

## Running the server

> **AI coding tools manage this automatically.** If you are connecting cairn-mcp to OpenCode,
> Claude Code, Copilot, or Codex, the tool launches the server process on session start using
> the command in your MCP config — you never run it manually. This section is relevant for
> **CI/CD pipeline agents** (e.g. an automated code reviewer running in a pipeline that needs
> cairn-mcp as a subprocess) and for **smoke-testing** a new installation before wiring it to
> an MCP client.

```bash
uv run cairn-mcp
# or
uv run python -m cairn_mcp
```

The server runs on stdio and is ready to accept MCP client connections.
