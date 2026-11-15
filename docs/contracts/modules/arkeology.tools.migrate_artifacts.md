---
type: Contract
id: arkeology.tools.migrate_artifacts
title: arkeology.tools.migrate_artifacts
description: The migrate_artifacts MCP tool — bulk one-time import with Nova Lite description enrichment, dry-run by default, and a skip-never-overwrite guarantee that makes re-running a migration idempotent and non-destructive.
tags: []
okf_version: "0.2"
sources:
  - resource: docs/specs/p9-t30-write-artifacts.md
    title: Write Performance Z1 — write_artifacts + migrate_artifacts + P4 Section Truncation
    last_modified: 2026-11-15T18:43:54Z
  - resource: docs/specs/p12-t56-deterministic-content-reference-rewrite.md
    title: T56 — Deterministic Server-Side Content Reference Rewrite (Frontmatter + Body)
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/specs/p8-t29-migrate-skill.md
    title: Write Performance L1+L2 — Migration Skill Parallel Writes
    last_modified: 2026-06-02T00:00:00Z
  - resource: docs/specs/p7-t25c-migration-skill-two-pass-classification.md
    title: Migration Skill — Two-Pass File Classification
    last_modified: 2026-06-01T00:00:00Z
  - resource: docs/specs/p9-t31b-migration-skill-exclusion-gate.md
    title: T31b — Migration Skill Exclusion Gate and ADR Gate Removal
    last_modified: 2026-06-10T00:00:00Z
  - resource: docs/specs/p12-t61-migration-self-heal.md
    title: T61 — Migration Self-Heal — skipped_unindexed Classification
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/specs/p10-t39-caller-controlled-artifact-concurrency.md
    title: T39 — Caller-Controlled artifact_concurrency on write_artifacts and migrate_artifacts
    last_modified: 2026-07-05T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-05-29-aws-backend-selection.md
    title: AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend
    last_modified: 2026-11-12T13:11:40Z
  - resource: docs/specs/p15-t92-numbered-vector-keys.md
    title: T92 — Numbered Vector Keys and Per-Artifact Vector Access by Key
    last_modified: 2026-11-12T13:11:40Z
  - resource: docs/specs/p1-t3-aws-client-layer.md
    title: T3 — AWS Client Layer
    last_modified: 2026-11-10T16:40:30Z
  - resource: .docs/reviews/architecture-review-2026-11-10-arkeology.md
    title: "Architecture review — Arkeology (whole design record)"
    last_modified: 2026-11-10T11:21:17Z
generated:
  by: "axians-tech-writer/claude-opus-5"
  at: 2026-09-04T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T19:39:39Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# arkeology.tools.migrate_artifacts

## Scope

The bulk-import boundary, used once per project when adopting Arkeology on an existing codebase.
It runs against a corpus the caller does not fully control, so its non-destructive and
re-runnability guarantees carry more weight than its throughput.

## Symbols

### migrate_artifacts

```python
async def migrate_artifacts(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    descriptors: list[dict[str, Any]],
    dry_run: bool = True,
    artifact_concurrency: int = 3,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. A whole-call failure is a returned dict carrying an `"error"` key; per-descriptor
failures are reported inside their own entries.

- `validation_error` — the descriptor list or an individual descriptor is malformed.
- `configuration_error` — the text model required for description enrichment is not configured or
  not reachable.
- `credential_error` — an AWS call raised `CredentialError` during the existence/indexing check
  pass. The check pass dispatches concurrently but decides in original descriptor-index order, so
  the surfaced failure always matches the one a sequential scan would have hit first. A
  `CredentialError` raised during description enrichment is different: it is caught per descriptor
  and recorded as that descriptor's own generation failure, never surfaced as this top-level code.
- `internal_error` — any otherwise unhandled exception. A non-credential, non-`KeyError`
  transport failure from the per-candidate existence/indexing check specifically is no longer
  such a case: it is caught per candidate and reported as that candidate's own `check_failed`
  entry, never surfaced as this top-level code.

**Invariants**

- **`dry_run` defaults to `True`.** An accidental call writes nothing. This is the inverse of the
  usual default and is deliberate: the tool operates on a whole corpus.
- **Bulk migration never overwrites a pre-existing key.** Each candidate's generated key is checked
  before the write phase; an existing key is skipped with no write and no error. Re-running a
  migration over an already-imported corpus is therefore idempotent and non-destructive. This is a
  deliberate split from `write_artifacts`, which accepts `overwrite` — an earlier version forwarded
  `overwrite=True` here and reopened the silent-overwrite class.
- `description` is optional per descriptor. A missing description is generated by the configured
  text model and clipped to the description length bound. Clipping happens in exactly one place,
  never independently at two. An answer that is empty or holds only whitespace is a generation
  failure, exactly as a raising model call is: the descriptor takes the `generation_failed` path
  (Postconditions) and that answer is never used as its description.
- `artifact_concurrency` bounds **both** the enrichment-phase description semaphore and the
  write-phase semaphore, forwarded to `write_artifacts`.
- Out-of-range `artifact_concurrency` is clamped **silently**, with a top-level `concurrency_warning` in the
  response rather than a rejection.
- The write phase delegates to `write_artifacts`, inheriting the whole write path.
- An artifact whose content object exists but which is not actually indexed is not treated as
  already-migrated. It is classified separately and **reported**, with the message naming
  `reconcile_index` as the repair — this tool never writes to, re-indexes, or otherwise repairs
  such an artifact, and running it does not trigger the repair path. The existence check is per
  candidate, not a bulk pre-scan.
- **A candidate's check reads its `#0` by key.** Whether an existing candidate is indexed is
  answered by reading `{key}#0` with `GetVectors` — every indexed artifact holds it
  (`s3vectors.artifact`) — so a migration of N files makes reads by key, never N scans of the index
  every team shares. A scan or a filtered query per candidate is the regression this forbids.

**Preconditions**

- Each descriptor is a dict of the keys below. The tool reads no other key, and an unknown key has
  no effect.

  | Key | Required | Meaning |
  |---|---|---|
  | `type`, `team`, `project`, `tier`, `date`, `title`, `content`, `visibility` | Yes | As `write_artifact`'s parameters of the same names (`arkeology.tools.write`). A descriptor missing one is reported as `write_artifacts` reports it (`arkeology.tools.write_artifacts`). |
  | `description` | No | Generated by the configured text model when absent or empty, then clipped; see Invariants. |
  | `tags`, `author_role`, `source_artifacts`, `commit_refs`, `references`, `status` | No | As `write_artifact`'s parameters of the same names, passed through unchanged. |
  | `file_extension` | No | Defaults to `.md`. A value not starting with `.` is that descriptor's `validation_error`, with no existence check. |
  | `resolved_references_map` | No | `{original reference text: full artifact key}`, built by the caller from the migration's path-to-key resolution. When non-empty, the descriptor's `content` is rewritten by the deterministic reference rewrite `p12-t56-deterministic-content-reference-rewrite` specifies, after description generation and before the existence check and the write, in both `dry_run` modes, so the previewed, stored and embedded content are one text. The key is consumed by this tool alone: it never reaches `write_artifacts`, the `Artifact` model, S3 object metadata, vector metadata or the annotation store, and **no response ever surfaces it** — not a dry-run entry, a write result, a skip entry, or an error. |
  | `overwrite` | — | Never read. Every write is made with `overwrite` off, whatever a descriptor carries; see the never-overwrites invariant. |

- The caller has already applied the exclusion gate — deciding which repository files are eligible
  is not this tool's job.
- A text model must be configured when any descriptor omits `description`.

**Postconditions**

- With `dry_run=True`, returns `{"descriptors": [...]}` with no writes performed — one entry per
  input descriptor, positionally aligned, carrying `index` and the clipped `description`, which is
  absent when that descriptor's generation failed. An entry never echoes the descriptor's `content`
  or any other field the caller submitted, with one exception: a descriptor that carried a non-empty
  `resolved_references_map` also returns its rewritten `content`, the preview of the reference
  rewrite. This is the review surface a caller inspects before committing.
- With `dry_run=False`, returns `{"results": [...]}`, positionally aligned with the input.
- A skipped descriptor's entry is `{"written": False, "skipped": True, "artifact_id": ...}`.
- `skipped_existing` is present only when at least one descriptor was skipped, one entry per skip
  carrying `index`, `artifact_id`, and `title`.
- `skipped_unindexed` is present only when at least one candidate's object exists in S3 with no
  indexed vectors; one entry per such candidate carrying `index`, `artifact_id`, `title`, and
  `message`. Its `results` entry is `{"written": False, "skipped": True, "artifact_id": ...,
  "reason": "unindexed", "message": ...}` — the `reason` is what distinguishes it from a
  `skipped_existing` skip, whose entry carries no `reason` at all.
- `generation_failed` is present, in both `dry_run` and live responses, only when at least one
  descriptor's description generation failed; one entry per failure carrying `index`, `title`, and
  `message`. A generation failure does not abort the call, but the affected descriptor is never
  written with an empty description: in a live run its `results` entry is
  `{"written": False, "skipped": True, "reason": "description_generation_failed", "message": ...}`,
  distinct from the `skipped_existing` reason.
- `check_failed` is present only when at least one candidate's existence/indexing check
  (`head_object` or the `#0` read) raised a non-credential, non-`KeyError`
  exception; one entry per such candidate carrying `index`, `artifact_id`, `title`, and
  `message`. Its `results` entry is `{"written": False, "skipped": True, "artifact_id": ...,
  "reason": "existence_check_failed", "message": ...}`. This does not abort the batch — every
  other candidate is still checked and, if eligible, written normally.
- No pre-existing artifact's content, metadata, or link fields are modified by any run.
