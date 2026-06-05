---
status: ready
references: []
authored:
  by: "developer"
  date: "2026-05-31"
revised:
  by: ""
  date: ""
---
# Review Fix 17 — Minor Client Layer Improvements

## Problem Statement

Six small issues in the client layer reduce clarity, type safety, and maintainability:
`Any` return types make the interface hard to reason about; a credential error string is
duplicated six times; a parameter named `filter` shadows the Python built-in; a docstring
omits a documented ordering guarantee; the class docstring contradicts the implementation
(`Protocol` vs `ABC`); and a request body dict is typed too loosely. All are low-risk,
non-breaking, and safe to ship as one PR once the `ABC` vs `Protocol` question is
resolved.

## User Stories

### Story 1 — `filter` rename does not break call sites (P2)

**Acceptance criteria:**
- Given any existing code that calls a client method with the `filter` keyword argument,
  when the rename to `filter_expr` is applied, then all call sites are updated
  atomically in the same commit and `mypy --strict` reports zero errors.

### Story 2 — `VectorMetadata` type alias is used consistently (P2)

**Acceptance criteria:**
- Given `VectorMetadata` is defined as `dict[str, str | int | float | list[str]]`, when
  `mypy --strict` is run, then no method signature in `interfaces.py`, `s3_vectors.py`,
  or `fake_vectors.py` uses bare `Any` for metadata parameters or return values.

## Requirements

- WHEN `VectorMetadata` type alias is introduced THE SYSTEM SHALL be used in all
  interface method signatures that previously used `Any` for metadata.
- WHEN the `filter` → `filter_expr` rename is applied THE SYSTEM SHALL compile cleanly
  with `mypy --strict` and pass `ruff check` with no `A002` (shadowed built-in) warnings.
- WHEN `_credential_error` helper is extracted THE SYSTEM SHALL produce an identical
  `CredentialError` message to the six duplicated call sites it replaces.
- WHEN `list_objects` docstring is updated THE SYSTEM SHALL state that keys are returned
  in lexicographic order.
- WHEN `bedrock.py` request body is narrowed THE SYSTEM SHALL use
  `dict[str, str | int]` instead of `dict[str, Any]`.

## Boundaries

**Always:**
- Rename `filter` → `filter_expr` in the interface AND every call site in one atomic
  change — never leave a mismatch between interface and implementation.
- Runtime behaviour of every client method must remain identical.

**Decision (2026-05-31): Migrate to `Protocol`.**
- `interfaces.py` shall be rewritten to use `typing.Protocol` instead of `ABC`.
  Rationale: Protocol enables structural subtyping — implementations and fakes satisfy
  the interface contract without inheriting from it, which decouples the client layer
  from the interface hierarchy. This aligns with modern Python dependency-injection
  patterns and matches AGENTS.md (which will be updated to state this convention
  explicitly). The migration is one commit: update `interfaces.py` and remove the
  `ABC`/`abstractmethod` imports; concrete classes and fakes drop the inheritance
  declaration; no runtime behaviour changes.
- AGENTS.md is updated in the same PR to record the Protocol convention.

**Never:**
- Change the runtime behavior of any client method.
- Introduce `Any` in new code.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_fake_s3.py` | Modify | Add/confirm tests covering `_credential_error` parity (Red) |
| `src/cairn_mcp/clients/interfaces.py` | Modify | Migrate from `ABC`/`abstractmethod` to `typing.Protocol`; add `VectorMetadata` alias; rename `filter` → `filter_expr`; update `list_objects` docstring; update module-level docstring to state Protocol |
| `src/cairn_mcp/clients/s3.py` | Modify | Drop `ABC` inheritance; extract `_credential_error` helper; rename `filter` → `filter_expr` at call sites |
| `src/cairn_mcp/clients/vectors.py` | Modify | Drop `ABC` inheritance; rename `filter` → `filter_expr` at call sites |
| `src/cairn_mcp/clients/bedrock.py` | Modify | Drop `ABC` inheritance; narrow `request_body` to `dict[str, str \| int]` |
| `src/cairn_mcp/clients/fakes/fake_s3.py` | Modify | Drop `ABC` inheritance; apply `VectorMetadata` alias where applicable |
| `src/cairn_mcp/clients/fakes/fake_vectors.py` | Modify | Drop `ABC` inheritance; rename `filter` → `filter_expr`; apply `VectorMetadata` alias |
| `src/cairn_mcp/clients/fakes/fake_bedrock.py` | Modify | Drop `ABC` inheritance |
| `AGENTS.md` | Modify | Add convention: client interfaces use `typing.Protocol`; implementations and fakes satisfy the structural contract without inheriting |
| `src/cairn_mcp/tools/search.py` | Modify | Update `filter_expr` call site |
| `src/cairn_mcp/tools/list.py` | Modify | Update `filter_expr` call site |
| `src/cairn_mcp/tools/archive.py` | Modify | Update `filter_expr` call site if present |

## Testing Approach

**TDD cycle:** confirm/add tests for credential error message parity (Red) → extract
helper (Green) → run `mypy --strict` and `ruff check` clean.

**`tests/unit/clients/test_fake_s3.py` — verify credential error message:**
- Before extracting `_credential_error`, assert the exact error message string for one
  representative call (e.g. `get_object`) so the refactor cannot silently change it.

**For `filter_expr` rename:** no new tests needed — confirm existing unit tests that
exercise `search_artifacts`, `list_artifacts`, and `list_vectors_by_metadata` still pass
after the rename. Run `mypy --strict` to confirm no call site was missed.

**For `VectorMetadata` alias:** run `mypy --strict`; confirm zero `Any`-typed metadata
parameters remain in interface signatures.

**For docstring and comment changes:** no automated tests — verified by code review.

## Open Questions

- **m15 — RESOLVED (2026-05-31):** Migrate to `typing.Protocol`. Full structural
  migration: `interfaces.py` drops `ABC`; all concrete clients and fakes drop the
  inheritance declaration; `AGENTS.md` updated to record the convention. See decision
  note in Boundaries above.
