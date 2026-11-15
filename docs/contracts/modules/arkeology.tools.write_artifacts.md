---
type: Contract
id: arkeology.tools.write_artifacts
title: arkeology.tools.write_artifacts
description: The write_artifacts MCP tool — bulk concurrent write of many artifact descriptors, bounded by a caller-supplied concurrency, delegating every entry to the single write implementation so no write-path logic is duplicated.
tags: []
okf_version: "0.2"
sources:
  - resource: docs/specs/p9-t30-write-artifacts.md
    title: Write Performance Z1 — write_artifacts + migrate_artifacts + P4 Section Truncation
    last_modified: 2026-07-05T00:00:00Z
  - resource: docs/specs/p2-t7-write-artifact.md
    title: T7 — Write Artifact Tool
    last_modified: 2026-07-05T00:00:00Z
  - resource: docs/specs/p10-t39-caller-controlled-artifact-concurrency.md
    title: T39 — Caller-Controlled artifact_concurrency on write_artifacts and migrate_artifacts
    last_modified: 2026-07-05T00:00:00Z
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
generated:
  by: "axians-tech-writer/claude-opus-5"
  at: 2026-09-04T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:28:28Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# arkeology.tools.write_artifacts

## Scope

The bulk write boundary. Its contract is mostly a promise about what it does **not** do: it adds
concurrency and per-entry isolation over `write_artifact` and reimplements none of its logic.

## Symbols

### write_artifacts

```python
async def write_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    artifacts: list[dict[str, Any]],
    artifact_concurrency: int = 3,
    file_extension: str = ".md",
    overwrite: bool = False,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. A whole-call failure is a returned dict carrying an `"error"` key; a per-descriptor
failure is reported inside that entry's own result.

- `validation_error` — the batch itself is malformed, or a descriptor is missing a required field.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- Every entry delegates to the single `write_artifact` implementation. Section embedding, orphan
  cleanup, budget validation, collision guarding, and failure logging are **inherited**, never
  re-expressed here. A behaviour that differs between this tool and `write_artifact` is a defect in
  this tool.
- **Partial failures are isolated.** A failed descriptor is recorded with an `error` field while
  every other descriptor continues. One bad entry never aborts the batch.
- Results are **positionally aligned** with the input descriptors, so a caller can map outcome to
  input by index without matching on ids.
- `artifact_concurrency` bounds concurrent artifact writes. It composes with the per-artifact
  section concurrency, so effective peak embed concurrency is the product of the two — there is
  deliberately **no** compound ceiling validation, which means a caller can configure a combination
  that exceeds service limits.
- An out-of-range `artifact_concurrency` is clamped rather than rejected, and the response carries a
  top-level `concurrency_warning`.
- `overwrite` is the batch default. A descriptor may carry its own `overwrite` key, which takes
  precedence over the call-level value for that entry alone — `False` included, so a descriptor
  carrying `overwrite: False` keeps its entry under the collision guard in a call made with
  `overwrite=True`. Each entry then gets the same reject-by-default collision semantics as
  `write_artifact`.

**Preconditions**

- Each descriptor must carry the fields `write_artifact` requires.
- The caller is responsible for choosing an `artifact_concurrency` that, multiplied by section
  concurrency, stays within its Bedrock and S3 Vectors throughput.

**Postconditions**

- Returns `{"results": [...]}`, one entry per input descriptor, positionally aligned.
- A successful entry carries `written=True`, `artifact_id`, and `sections_indexed`; a failed entry
  carries `error` and `message`.
- A top-level `concurrency_warning` is present only when `artifact_concurrency` was out of range.
- The batch is not transactional. There is no rollback: successful entries stay written when others
  fail.
