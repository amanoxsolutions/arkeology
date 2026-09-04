---
type: Contract
title: arkeology.tools.write_artifacts
description: The write_artifacts MCP tool — bulk concurrent write of many artifact descriptors, bounded by a caller-supplied concurrency, delegating every entry to the single write implementation so no write-path logic is duplicated.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p9-t30-write-artifacts.md
  - docs/specs/p2-t7-write-artifact.md
  - docs/specs/p10-t39-caller-controlled-artifact-concurrency.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: ""
  date: YYYY-MM-DD
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
  top-level `warning`.
- `overwrite` applies as a batch default; the same reject-by-default collision semantics as
  `write_artifact` apply per entry.

**Preconditions**

- Each descriptor must carry the fields `write_artifact` requires.
- The caller is responsible for choosing an `artifact_concurrency` that, multiplied by section
  concurrency, stays within its Bedrock and S3 Vectors throughput.

**Postconditions**

- Returns `{"results": [...]}`, one entry per input descriptor, positionally aligned.
- A successful entry carries `written=True`, `artifact_id`, and `sections_indexed`; a failed entry
  carries `error` and `message`.
- A top-level `warning` is present only when `artifact_concurrency` was out of range.
- The batch is not transactional. There is no rollback: successful entries stay written when others
  fail.
