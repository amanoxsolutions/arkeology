---
type: code_review
title: Review Fix 17 — Minor Client Layer Improvements
description: Code review spec for six client layer issues — Any return types, duplicated credential error string, filter built-in shadow, missing ordering guarantee docstring, ABC vs Protocol discrepancy, and loosely typed request body dict.
tags: []
timestamp: 2026-05-31T00:00:00Z
okf_version: "0.1"
status: ready
references: []
authored:
  by: "developer"
  date: "2026-05-31"
revised:
  by: "developer"
  date: "2026-08-12"
---
# Review Fix 17 — Minor Client Layer Improvements

## Verification — 2026-08-12

Re-verified finding-by-finding against current `main`. All six items were fixed the
same day this spec was authored, by `f642725` (2026-05-31, "production hardening — 20
review-fix specs"). One item (the duplicated credential-error string / helper) was
carried further by a later, unrelated simplification pass — see its inline marker.

- **Resolved:** 6 of 6 — `VectorMetadata` alias, credential-error dedup, `filter` →
  `filter_expr`, `list_objects` ordering docstring, `ABC` → `Protocol` migration, and
  the narrowed `bedrock.py` request body.
- **Still valid / no longer applicable:** none.

See inline `[Verified 2026-08-12 — …]` markers below and the "Items Resolved Since Last
Review" section at the end.

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
  **[Verified 2026-08-12 — ✅ RESOLVED.** `interfaces.py` defines
  `VectorMetadata = dict[str, str | int | float | list[str]]` and `put_vector` takes
  `metadata: VectorMetadata`. Remaining `Any` usages in the file (`filter_expr`,
  `head_object`/`describe_index` return dicts, `put_vectors_batch`/`get_vectors` item
  dicts) are genuinely heterogeneous shapes, not metadata specifically — in scope for
  neither this finding nor its acceptance criteria. Fixed by `f642725`, deliberate.]
- WHEN the `filter` → `filter_expr` rename is applied THE SYSTEM SHALL compile cleanly
  with `mypy --strict` and pass `ruff check` with no `A002` (shadowed built-in) warnings.
  **[Verified 2026-08-12 — ✅ RESOLVED.** Every vector-client method signature and call
  site (`interfaces.py`, `vectors.py`, `search.py`, `list.py`) uses `filter_expr`; no
  bare `filter` keyword remains. Fixed by `f642725`, deliberate.]
- WHEN `_credential_error` helper is extracted THE SYSTEM SHALL produce an identical
  `CredentialError` message to the six duplicated call sites it replaces.
  **[Verified 2026-08-12 — ✅ RESOLVED, mechanism evolved.** `f642725` extracted the
  `_credential_error` helper as specified. A later, unrelated architect-authored
  simplification pass (`329614c`, 2026-06-29, tracked as M3 in
  `review-2026-06-29-simplification.md`) went further and replaced it with a shared
  `wrap_credential_errors(service)` context manager in `clients/credentials.py`, used
  identically by `s3.py`, `vectors.py`, and `bedrock.py` — the same de-duplication goal,
  via a more DRY mechanism than this spec asked for. Not a regression.]
- WHEN `list_objects` docstring is updated THE SYSTEM SHALL state that keys are returned
  in lexicographic order.
  **[Verified 2026-08-12 — ✅ RESOLVED.** `S3ClientInterface.list_objects`'s docstring
  states "List matching object keys in lexicographic order." Fixed by `f642725`,
  deliberate.]
- WHEN `bedrock.py` request body is narrowed THE SYSTEM SHALL use
  `dict[str, str | int]` instead of `dict[str, Any]`.
  **[Verified 2026-08-12 — ✅ RESOLVED.** The `embed` method's `request_body` is
  `dict[str, str | int] = {"inputText": text, "dimensions": dimensions}`. (The shared
  `_invoke` helper added later still accepts `dict[str, Any]` generically since it wraps
  multiple differently-shaped request bodies — out of this finding's scope.) Fixed by
  `f642725`, deliberate.]

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

  **[Verified 2026-08-12 — ✅ RESOLVED.** `interfaces.py`'s module docstring reads
  "Protocol interfaces for all AWS service clients... Each interface uses
  `typing.Protocol`..."; `S3ClientInterface`, `VectorsClientInterface`, and
  `BedrockClientInterface` all subclass `Protocol`, not `ABC`. `AGENTS.md`'s
  Non-Negotiable Rules document the convention (client interfaces use
  `typing.Protocol`; concrete implementations and fakes satisfy the structural contract
  without inheriting). Fixed by `f642725`, deliberate.]

**Never:**
- Change the runtime behavior of any client method.
- Introduce `Any` in new code.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_fake_s3.py` | Modify | Add/confirm tests covering `_credential_error` parity (Red) |
| `src/arkeology/clients/interfaces.py` | Modify | Migrate from `ABC`/`abstractmethod` to `typing.Protocol`; add `VectorMetadata` alias; rename `filter` → `filter_expr`; update `list_objects` docstring; update module-level docstring to state Protocol |
| `src/arkeology/clients/s3.py` | Modify | Drop `ABC` inheritance; extract `_credential_error` helper; rename `filter` → `filter_expr` at call sites |
| `src/arkeology/clients/vectors.py` | Modify | Drop `ABC` inheritance; rename `filter` → `filter_expr` at call sites |
| `src/arkeology/clients/bedrock.py` | Modify | Drop `ABC` inheritance; narrow `request_body` to `dict[str, str \| int]` |
| `src/arkeology/clients/fakes/fake_s3.py` | Modify | Drop `ABC` inheritance; apply `VectorMetadata` alias where applicable |
| `src/arkeology/clients/fakes/fake_vectors.py` | Modify | Drop `ABC` inheritance; rename `filter` → `filter_expr`; apply `VectorMetadata` alias |
| `src/arkeology/clients/fakes/fake_bedrock.py` | Modify | Drop `ABC` inheritance |
| `AGENTS.md` | Modify | Add convention: client interfaces use `typing.Protocol`; implementations and fakes satisfy the structural contract without inheriting |
| `src/arkeology/tools/search.py` | Modify | Update `filter_expr` call site |
| `src/arkeology/tools/list.py` | Modify | Update `filter_expr` call site |
| `src/arkeology/tools/archive.py` | Modify | Update `filter_expr` call site if present |

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

  **[Verified 2026-08-12 — decision confirmed and still in effect on `main`.]**

## Items Resolved Since Last Review

<!-- changelog-style: prepend new entries -->
- 2026-08-12 — **Re-verification pass (developer): all 6 items confirmed resolved.**
  This spec sat with `status: ready` and no closure note for ~2.5 months despite the
  code having matched every requirement since the day it was authored. `f642725`
  ("production hardening — 20 review-fix specs", 2026-05-31, same day as this review)
  deliberately implemented the `VectorMetadata` alias, the `filter` → `filter_expr`
  rename, the `_credential_error` extraction, the `list_objects` ordering docstring, the
  `ABC` → `Protocol` migration, and the narrowed `bedrock.py` request body. One item
  evolved further under unrelated later work: `_credential_error` was superseded by a
  shared `wrap_credential_errors(service)` context manager (`329614c`, 2026-06-29, M3 in
  `review-2026-06-29-simplification.md`) — same de-duplication goal, more DRY mechanism,
  not a regression. No code was changed by this re-verification pass.
