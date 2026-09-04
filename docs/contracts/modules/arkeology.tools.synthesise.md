---
type: Contract
title: arkeology.tools.synthesise
description: The synthesise_artifacts MCP tool — combines semantic search with batch S3 content retrieval to return full content for the top-k matching artifacts in one call, assembling source material only.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p3-t16-synthesise-artifacts.md
  - docs/specs/p2-t8-search-artifacts.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: ""
  date: YYYY-MM-DD
---

# arkeology.tools.synthesise

## Scope

The bulk-recall boundary: one call that returns enough full content for a caller to synthesise
across artifacts. The synthesis itself is explicitly **not** this tool's job — it assembles source
material and stops.

## Symbols

### synthesise_artifacts

```python
async def synthesise_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    query: str,
    top_k: int = 10,
    type: str | None = None,
    tags: list[str] | None = None,
    team: str | None = None,
    project: str | None = None,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Every failure is a returned dict carrying an `"error"` key.

- `validation_error` — an invalid filter or parameter value.
- `credential_error` — an AWS call raised `CredentialError`, at the embed call, inside the shared
  `_search_helper.run_search_loop` re-fetch loop, or during the batch content fetch from S3.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- This tool performs **no** synthesis, summarisation, or model inference over the retrieved
  content. It retrieves and returns. A future version that summarised would be a different
  contract.
- The same cross-scope gate as `search_artifacts` applies: own-scope unrestricted, foreign-scope
  restricted to `tier == 3` and `visibility == "shared"`.
- The re-fetch loop is the shared `_search_helper.run_search_loop`, identical to
  `search_artifacts`. Fixes belong in that helper, never here.
- Content is fetched in batch from S3 after the vector search resolves, not per result serially.
- `score` follows the same `1.0 - cosine_distance` convention as `search_artifacts`.

**Preconditions**

- `query` is a natural-language string.
- All four clients are required — unlike `search_artifacts`, `s3` is mandatory here because content
  retrieval is the point.

**Postconditions**

- Returns `{"artifacts": [...]}` where each entry carries all metadata fields **plus** `content`.
- `index_corruption_detected: True` is included when the loop stopped because a vector result was
  missing its `distance` field. Whatever was already collected is still returned — never a hard
  error, so a partially corrupt index degrades rather than blocks recall.
- Result count may be below `top_k` without that meaning fewer matches exist.
