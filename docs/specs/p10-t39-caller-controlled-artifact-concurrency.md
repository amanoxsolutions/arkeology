---
type: feature-spec
feature: p10-t39-caller-controlled-artifact-concurrency
status: ready
phase: 10
task: 39
references:
  - docs/brainstorming/brainstorming-2026-06-10-migrate-artifacts-concurrency.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-06-11"
revised:
  by: "architect"
  date: "2026-06-11"
---

# T39 — Caller-Controlled `artifact_concurrency` on `write_artifacts` and `migrate_artifacts`

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Replace the `ARTIFACT_CONCURRENCY` server env var with an optional per-call
`artifact_concurrency` parameter (default 3) on `write_artifacts` and `migrate_artifacts`.
Out-of-range values are never rejected: above 15 is capped to 15, below 1 is substituted
with the default 3; both produce a top-level `warning` field in the response. The migration
skill gains a recommendation step before each call and batches 3.B3 and 3.B5 calls by
`artifact_concurrency`, giving the operator a progress update after every batch.

## Problem Statement

`ARTIFACT_CONCURRENCY` is a server-level env var that requires a server restart to change.
For one-time bulk operations like migration, this is the wrong friction point: the operator
cannot right-size concurrency for the description phase (Nova Lite) versus the write phase
(Titan embeddings × `SECTION_CONCURRENCY`) without editing their MCP client config and
restarting. A per-call parameter lets the skill pass a different value for each sequential
call (`dry_run=True` then `dry_run=False`) with no configuration change. The env var is
removed entirely — the server is not yet deployed anywhere, so there is no migration burden.

## User Stories

### Story 1 — High concurrency for the description phase (P1)

**Given** a migration with 30 files, **when** the skill calls
`migrate_artifacts(dry_run=True, artifact_concurrency=15, ...)`, **then** the server runs
up to 15 Nova Lite description calls concurrently and returns enriched descriptors.

**Acceptance criteria:**
- `migrate_artifacts(dry_run=True, artifact_concurrency=15)` uses a description semaphore
  of 15 — verified by spy on `asyncio.Semaphore` or by call-count assertion.
- `migrate_artifacts(dry_run=True, artifact_concurrency=20)` caps to 15, runs successfully,
  returns enriched descriptors, and includes a non-empty `warning` field in the response.

### Story 2 — Conservative concurrency forwarded to the write phase (P1)

**Given** a migration with 30 files, **when** the skill calls
`migrate_artifacts(dry_run=False, artifact_concurrency=3)`, **then** the server forwards
`artifact_concurrency=3` to `write_artifacts` so at most 3 artifacts write concurrently.

**Acceptance criteria:**
- `migrate_artifacts(dry_run=False, artifact_concurrency=3)` results in `write_artifacts`
  being called with an effective semaphore of 3 — verified by spy on `asyncio.Semaphore`.

### Story 3 — Direct callers of `write_artifacts` control concurrency per call (P1)

**Given** an agent calling `write_artifacts` directly, **when** it passes
`artifact_concurrency=10`, **then** the server uses a semaphore of 10 for that call
regardless of any environment variable.

**Acceptance criteria:**
- `write_artifacts(artifact_concurrency=10, artifacts=[...])` processes up to 10
  artifacts concurrently.
- `write_artifacts(artifact_concurrency=20, ...)` caps to 15, writes all artifacts
  successfully, and returns `{"results": [...], "warning": "..."}` with a non-empty
  warning string identifying the requested and effective values.
- `write_artifacts(artifact_concurrency=0, ...)` substitutes the default (3), writes all
  artifacts successfully, and returns a `warning` field.
- `write_artifacts()` with no parameter behaves as before with effective concurrency of 3.

### Story 4 — Operator receives a concurrency recommendation before each call (P1)

**Given** the migration skill is about to call `migrate_artifacts`, **when** it reaches
the execute step, **then** it presents `min(file_count, 15)` as its recommended
`artifact_concurrency`, explains the relevant quota context for that phase, and waits for
the operator to confirm or supply their own value.

**Acceptance criteria:**
- The recommendation step appears before the `migrate_artifacts` call in 3.A3, 3.B3,
  and 3.B5.
- For 3.A3 and 3.B3 (description or dry-run phase): explanation references Nova Lite
  concurrent calls.
- For 3.B5 (write phase): explanation references the `SECTION_CONCURRENCY` multiplier
  and the 100 req/s Titan ceiling, so the operator can reason about the compound load.
- The operator can supply their own integer and the skill uses that value.

### Story 5 — `ARTIFACT_CONCURRENCY` env var is ignored at startup and runtime (P1)

**Given** `ARTIFACT_CONCURRENCY=10` is present in the environment, **when** the server
starts, **then** no startup error is raised and the value has no effect on any tool call.

**Acceptance criteria:**
- `Settings(...)` does not raise `ValidationError` when `ARTIFACT_CONCURRENCY` is set
  (the field is absent from `Settings`; the env var is silently ignored via `extra="ignore"`).
- `write_artifacts()` with no explicit `artifact_concurrency` uses 3, not the env var.

## Requirements

- WHEN `write_artifacts` is called with `artifact_concurrency` > 15 THE SYSTEM SHALL cap
  the effective concurrency to 15, proceed with all writes, and include a top-level
  `"warning"` field in the response identifying the requested value and the effective cap.
- WHEN `write_artifacts` is called with `artifact_concurrency` < 1 THE SYSTEM SHALL
  substitute the default (3), proceed with all writes, and include a top-level `"warning"`
  field in the response identifying the supplied value and the substituted value.
- WHEN `write_artifacts` is called with 1 ≤ `artifact_concurrency` ≤ 15 THE SYSTEM SHALL
  process at most that many artifacts concurrently via `asyncio.Semaphore` with no warning.
- WHEN `write_artifacts` is called without `artifact_concurrency` THE SYSTEM SHALL default
  to 3 with no warning.
- WHEN `migrate_artifacts` is called with `artifact_concurrency` > 15 or < 1 THE SYSTEM
  SHALL apply the same substitution rules as `write_artifacts` and include a `"warning"`
  field in the response.
- WHEN `migrate_artifacts(dry_run=True)` is called THE SYSTEM SHALL use the effective
  `artifact_concurrency` to bound concurrent Nova Lite description calls.
- WHEN `migrate_artifacts(dry_run=False)` is called THE SYSTEM SHALL forward the effective
  `artifact_concurrency` to `write_artifacts`.
- WHEN `ARTIFACT_CONCURRENCY` is present in the environment THE SYSTEM SHALL ignore it; the
  `Settings` class shall not define a field for it.
- WHEN the migrating-to-cairn skill is about to call `migrate_artifacts` THE SKILL SHALL
  compute `min(file_count, 15)`, present the recommendation with phase-appropriate Titan
  quota context, and wait for the operator to confirm or supply their own value.
- WHEN the migrating-to-cairn skill executes 3.B3 or 3.B5 THE SKILL SHALL split the
  descriptor list into batches of `artifact_concurrency` and call `migrate_artifacts` once
  per batch, reporting progress to the operator after each batch.

## Boundaries

**Always:**
- `SECTION_CONCURRENCY` env var is unchanged — server configuration, default 5.
- Out-of-range handling is symmetric: > 15 → cap to 15 + warning; < 1 → substitute
  default 3 + warning; in-range → no warning; omitted → default 3, no warning. The tool
  never rejects a call on the concurrency parameter alone.
- Effective value (after any substitution) is what the semaphore receives and what is
  forwarded from `migrate_artifacts` to `write_artifacts`.
- `write_artifact` (single-artifact write) is unchanged — `artifact_concurrency` is added
  to bulk tools only.
- The skill batching in 3.B3 and 3.B5 (batch_size = artifact_concurrency) is an explicit
  **stdio workaround**. When Streamable HTTP + SSE is adopted, the batching loop is
  removed and replaced with a single call per phase; `artifact_concurrency` retains its
  server-side semaphore role.

**Never:**
- Do not add `artifact_concurrency` to `write_artifact` (single write).
- Do not rename or remove `SECTION_CONCURRENCY` or any other existing env var.
- Do not add a compound `artifact_concurrency × section_concurrency ≤ ceiling` validation
  in this task — note it as a future concern in the module docstring and move on.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_write_artifacts.py` | Modify | Replace `monkeypatch.setenv("ARTIFACT_CONCURRENCY", ...)` with `artifact_concurrency=` parameter; add cap+warn test (> 15); add substitute+warn test (< 1); confirm no warning when in-range |
| `src/cairn_mcp/tools/write_artifacts.py` | Modify | Add `artifact_concurrency: int = 3` to public + inner signatures; clamp to [1, 15] at top of `_inner`, adding `"warning"` to response dict when clamped; semaphore uses effective value |
| `tests/unit/test_tools_migrate_artifacts.py` | Modify | Replace `monkeypatch.setenv("ARTIFACT_CONCURRENCY", ...)` with parameter; add > 15 cap+warn test; add < 1 substitute+warn test; add forward-to-write-phase test |
| `src/cairn_mcp/tools/migrate_artifacts.py` | Modify | Add `artifact_concurrency: int = 3`; clamp to [1, 15] + warn; use effective value for description semaphore; pass effective value to `_write_artifacts` call |
| `tests/unit/test_config.py` | Modify | Remove `ARTIFACT_CONCURRENCY` test blocks; add one test confirming `ARTIFACT_CONCURRENCY` in env raises no `ValidationError` |
| `src/cairn_mcp/config.py` | Modify | Remove `ARTIFACT_CONCURRENCY` field, `validate_artifact_concurrency` validator, and `artifact_concurrency` property |
| `skills/migrating-to-cairn/SKILL.md` | Modify | Add concurrency recommendation sub-step before the `migrate_artifacts` call in 3.A3, 3.B3, and 3.B5 |

## Testing Approach

TDD — each test file is written and run (Red) before the implementation file it gates.

---

### Round 1 — `write_artifacts` parameter

`tests/unit/test_tools_write_artifacts.py` (modify → Red) →
`src/cairn_mcp/tools/write_artifacts.py` (modify → Green)

Tests to add or update:

- **Update C3** (was `ARTIFACT_CONCURRENCY=1`): change `monkeypatch.setenv(...)` to
  `artifact_concurrency=1` keyword argument; remove the monkeypatch call entirely.
- **Update C5** (was `ARTIFACT_CONCURRENCY=2`): same change.
- Add: `artifact_concurrency=15` → all artifacts written; `written=True` for every entry;
  no `"warning"` key in response.
- Add: `artifact_concurrency=20` → all artifacts written; response contains `"warning"`
  key mentioning 20 and 15; semaphore constructed with 15 (spy confirms).
- Add: `artifact_concurrency=0` → all artifacts written; response contains `"warning"`
  key mentioning 0 and 3 (default substituted); semaphore constructed with 3 (spy confirms).
- Add: omitted `artifact_concurrency` → semaphore constructed with 3; no `"warning"` key.

---

### Round 2 — `migrate_artifacts` parameter

`tests/unit/test_tools_migrate_artifacts.py` (modify → Red) →
`src/cairn_mcp/tools/migrate_artifacts.py` (modify → Green)

Tests to add or update:

- **Update E8** (was `ARTIFACT_CONCURRENCY=2`): change to `artifact_concurrency=2` parameter.
- Add: `artifact_concurrency=20` with missing descriptions → descriptions generated,
  enriched descriptors returned, `"warning"` key present; `bedrock.invoke_text_model`
  called with semaphore of 15.
- Add: `artifact_concurrency=0` with missing descriptions → descriptions generated,
  enriched descriptors returned, `"warning"` key present; semaphore of 3 used.
- Add: `dry_run=True, artifact_concurrency=5` → description semaphore constructed with 5;
  no `"warning"` key.
- Add: `dry_run=False, artifact_concurrency=5` → `write_artifacts` semaphore constructed
  with 5 (spy on `asyncio.Semaphore` inside `_write_artifacts_inner`).

---

### Round 3 — config cleanup

`tests/unit/test_config.py` (modify → Red) → `src/cairn_mcp/config.py` (modify → Green)

- Remove the `ARTIFACT_CONCURRENCY` test block (tests T26 / Z1 label — default, custom,
  zero-invalid, negative-invalid).
- Add: `monkeypatch.setenv("ARTIFACT_CONCURRENCY", "10")` then construct `Settings(...)`
  → no `ValidationError`; confirm `hasattr(settings, "artifact_concurrency")` is `False`
  (or `getattr(settings, "artifact_concurrency", "NOT_SET") == "NOT_SET"`).

---

### SKILL.md changes (no unit tests)

**Step 3.A3** — insert before the `migrate_artifacts` call:

> Compute `artifact_concurrency = min(file_count, 15)`. Explain to the operator: this
> controls both how many artifacts write concurrently server-side and how many descriptors
> are sent per call (for ≤ 10 files this is typically the full list in one call). Note the
> Bedrock ~100 req/s Titan ceiling. Ask the operator to confirm or supply their own value.
> Use the confirmed value in the call.

**Step 3.B3** — replace the single `migrate_artifacts(dry_run=True)` call with a batch loop:

> Compute `artifact_concurrency = min(file_count, 15)`. Explain to the operator: this
> controls how many Nova Lite description calls run concurrently per batch AND how many
> descriptors are sent per call — so `artifact_concurrency=15` means 15 descriptions
> generated concurrently in each batch, and you will receive a progress update after every
> 15 files. Note the Bedrock ~100 req/s Titan ceiling. Ask the operator to confirm or
> supply their own value.
>
> Split the pending descriptor list into batches of `artifact_concurrency`. For each batch:
> call `migrate_artifacts(dry_run=True, artifact_concurrency=…, descriptors=batch)`,
> write the returned descriptions back to `CAIRN_IMPORT.yaml` as `description_override`,
> and report progress (e.g. "Described 15 of 95 files"). Continue until all batches are
> processed.
>
> *(stdio workaround — when Streamable HTTP + SSE is available, replace this loop with a
> single call that receives per-description SSE events; the artifact_concurrency parameter
> and the concurrency explanation above remain unchanged.)*

**Step 3.B5** — replace the single `migrate_artifacts(dry_run=False)` call with a batch loop:

> Compute `artifact_concurrency = min(file_count, 15)`. Explain to the operator: in the
> write phase each concurrent artifact also runs up to `SECTION_CONCURRENCY` (default 5)
> Titan embedding calls, so `artifact_concurrency=15` at default settings means up to 75
> concurrent Bedrock embedding calls — 25% headroom under the 100 req/s ceiling. Batching
> by this value means a progress update after every `artifact_concurrency` files written.
> Ask the operator to confirm or supply a lower value if concerned about quota.
>
> Split the pending descriptor list into batches of `artifact_concurrency`. For each batch:
> call `migrate_artifacts(dry_run=False, artifact_concurrency=…, descriptors=batch)`,
> update `CAIRN_IMPORT.yaml` statuses (written/failed), and report progress (e.g.
> "Written 15 of 95 files"). Continue until all batches are processed.
>
> *(stdio workaround — same as 3.B3; remove the loop when SSE is available.)*

## Open Questions

*(none — all constraints resolved in brainstorming session 2026-06-11)*
