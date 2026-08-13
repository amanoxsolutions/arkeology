---
type: code_review
title: "Codebase simplification review — reuse, redundancy, dead code, clarity"
description: "Whole-codebase review identifying simplification opportunities (DRY, dead code, over-engineering, clarity) across src/arkeology; report only, no changes applied."
tags: [simplification, refactoring, dry, maintainability, code-review]
timestamp: 2026-06-29T00:00:00Z
okf_version: "0.1"
status: draft # draft | ready | in-progress | done
references: []
authored:
  by: "architect"
  date: "2026-06-29"
revised:
  by: "developer"
  date: "2026-08-12"
---

# Codebase simplification review — reuse, redundancy, dead code, clarity

## Description

A whole-codebase simplification pass over `src/arkeology/` (~6,900 LOC, 30 files). The
goal was to find where code can be made simpler — duplication that should be shared, dead
code, over-engineering, and clarity issues — **without changing behaviour**. This is a
review only; no code was modified. Every finding preserves the project's Non-Negotiable
Rules (no stdout, `_inner` try/except safety net, `startswith(scope + "/")` scope checks,
no content in vector metadata, `typing.Protocol` client interfaces, `filter_expr` naming,
`1.0 - distance` scores).

Analysis was run as six parallel passes (core/config, clients, server/startup/resources,
write/read/search tools, lifecycle tools, and a cross-module duplication map), then
consolidated and independently verified.

## Verification — 2026-08-12

This review was re-verified finding-by-finding against current `main` (`3bd9944`). It had
never been folded into a remediation plan or closed, but the code was in fact fixed the
same day the review was authored: `329614c` (merged via `acff8c3`, 2026-06-29) applied
**C1, C2, C3, M1–M7, and all ten Minor items** exactly as recommended (net ~815 deletions,
707 unit tests passing at the time). The Observation (`purge.py` partial-failure reporting)
was independently resolved shortly after by `a0be166` (best-effort bulk partial-failure
contract, p3-t13). None of this was ever reflected in this document's "Items Resolved"
section — that gap is what this pass closes.

Phase 9–12 feature work (ADR-011/ADR-012 annotation + optimistic-concurrency support, the
`link_commit` → `link_metadata` retirement, and the project rename to Arkeology) landed after
the fix. Every item in the review — severity findings, the health-check preamble, the
"Verified NOT a defect" note, the Observation, and the leave-as-is trade-offs — was re-checked
against today's code, not just the fix commit, and is annotated inline with its current
status. Aggregate across all 30 discrete items in the document:

- **Resolved:** 21 — C1, C2, C3, M1–M7, all 10 Minor items, and the Observation
  (`purge.py` partial-failure reporting, via the later `a0be166`).
- **Still valid (accurate, not a defect):** 3 — the "Verified NOT a defect" `except A, B:`
  note, and two of the three health-check preamble bullets (`write.py`/`write_artifacts.py`
  split; all tool files registered + shared `run_search_loop`).
- **No longer applicable:** 1 — the `link_commit.py` vs `propose_commit_links.py` health-check
  bullet (`link_commit.py` was retired and superseded by `link_metadata.py` in Phase 12).
- **Changed enough to need restating:** 2 — C3 (the per-call credential-catch fragment
  regrew in volume from unrelated later CAS-retry/annotation work, though the fold-per-phase
  fix itself holds); the leave-as-is `startup.py` note (now a seven-check sequence, not six).
- **Confirmed as deliberate (leave-as-is section):** 4 of 5 (the fifth, `startup.py`, is the
  "needs restating" item above).

See the inline `[Verified 2026-08-12 — …]` markers on each finding and the changelog entry
appended to "Items Resolved Since Last Review" below for full detail.

## Spec and ADRs Consulted

- `AGENTS.md` / `CLAUDE.md` — conventions, Non-Negotiable Rules, High-Friction Areas
- `pyproject.toml` — `requires-python = ">=3.14"`, ruff/mypy config
- Prior review logs in `docs/reviews/` (e.g. `review-2026-06-25-full-codebase.md`,
  `review-2026-05-31-fix-11-search-synthesise-shared-helper.md`) for context on
  decisions already made
- No feature spec — this is a maintainability review of existing code, not a feature change.

## Files Reviewed

All `.py` under `src/arkeology/`: `artifact.py`, `config.py`, `errors.py`,
`failure_log.py`, `__main__.py`, `server.py`, `startup.py`, `resources.py`;
`clients/{interfaces,s3,vectors,bedrock,filter,credentials}.py` and
`clients/fakes/fake_bedrock.py`; and all `tools/*.py`.

## Findings

> Severity here means **simplification leverage**, not defect severity. There are no
> correctness or security defects in scope. **Critical = highest-value, low-risk wins**;
> **Major = meaningful complexity reduction**; **Minor = polish**.

### Health check first: no dead code, no orphaned tools

The cross-module pass confirmed clean structural health, which is worth recording because
two things *looked* like redundancy and are not:

- **`write.py` vs `write_artifacts.py` are NOT duplicates.** `write.py` owns the single
  write implementation (`_write_artifact_inner`); `write_artifacts.py` is a thin bulk
  orchestrator (concurrency clamp + intra-batch dup detection) that calls that same inner
  function under a semaphore, and is itself reused by `migrate_artifacts.py`. Both are
  distinct registered MCP tools. Keep both.
  **[Verified 2026-08-12 — STILL VALID.** Unchanged in substance; both files still exist
  with the same relationship.]
- **`link_commit.py` vs `propose_commit_links.py` are complementary**, not overlapping
  (propose = read-only discovery; link = write the SHA). Keep both.
  **[Verified 2026-08-12 — NO LONGER APPLICABLE.** `link_commit.py` no longer exists: it
  was retired and superseded by `link_metadata.py` in Phase 12 (T49, commit `1b611bc`),
  which generalizes commit-SHA linking into a broader `commit_refs`/`references` backfill
  tool built on ADR-011 dual-write annotations. `propose_commit_links.py` still stands
  alone, complementary to `link_metadata.py` in the same way (read-only discovery vs.
  write).]
- **All 16 tool files are registered** in `server.py::register_tools()`; `_search_helper.py`
  is correctly a shared module, not a tool. `search.py` and `synthesise.py` both correctly
  delegate the re-fetch loop to `run_search_loop` — the documented single-source contract holds.
  **[Verified 2026-08-12 — STILL VALID.** Still true today (16 tool files, per
  `AGENTS.md`'s repository table); the number is unchanged from the review's own count
  because tools were both added and retired (e.g. `link_commit` → `link_metadata`) since
  2026-06-29. `run_search_loop` is still the sole shared re-fetch loop.]

### Critical (highest-value, low-risk — do these first)

**C1. `list.py` rebuilds the scope filter instead of calling `build_scope_filter`
(`list.py:113–133`).** `_search_helper.build_scope_filter(settings)` already produces the
exact `$or`/`$and` scope clause; `list.py` re-implements it inline (the inline comment even
says "same logic as search.py"). The scope gate is a **Non-Negotiable Rule**, so two copies
is a real drift risk — a future fix to one can silently miss the other. Replace the inline
block with `clauses.append(build_scope_filter(settings))`. ~18 lines removed, output
identical. *Effort: low · Risk: low.*

**[Verified 2026-08-12 — ✅ RESOLVED.** `list.py` now does exactly
`clauses.append(build_scope_filter(settings))`, importing `build_scope_filter` from
`_search_helper.py`. Fixed by `329614c` on 2026-06-29 (the same day as the review),
as part of the deliberate simplification pass — not coincidental.]

**C2. Delete the no-op `try/except CredentialError: raise` blocks in `reconcile.py`
(`reconcile.py:99–131`).** Four blocks catch `CredentialError` only to re-raise it
unchanged — identical to not catching it. Pure deletion, ~16–20 lines, zero behaviour
change. Also dead: the `else` at `reconcile.py:276–278` re-sets
`failure_log_entries_before/after = 0`, already initialised at `:193–194`.
*Effort: low · Risk: none.*

**[Verified 2026-08-12 — ✅ RESOLVED.** The no-op reraises are gone; every
`except CredentialError` in `reconcile.py` now does meaningful work — an early
`return {"error": ErrorCode.CREDENTIAL_ERROR, ...}` — rather than a bare `raise`. The dead
`else` branch is also gone. Fixed by `329614c`, deliberate.]

**C3. Collapse the per-call `except CredentialError → {"error": "credential_error", ...}`
blocks.** This exact 2–3 line fragment recurs ~30 times across `archive`, `delete`,
`purge`, `reconcile`, `freshness`, `link_commit`, `propose_commit_links` (and ~59 times if
you count clients). Where every catch in a tool is identical, fold them into **one `try`
per logical phase** wrapping several client calls. Caveat: a few sites carry extra fields
(`delete.py:155`, `purge.py:172` add `artifact_id`) or map non-credential exceptions
differently (`delete`'s `partial_delete`/`delete_vectors_failed`) — leave those bespoke;
the win is in the files where the catch is uniform. *Effort: low–med · Risk: low.*

**[Verified 2026-08-12 — 🔄 RESOLVED AS SCOPED, BUT CHANGED ENOUGH TO NEED RESTATING.**
`329614c` did fold the per-call catches into one `try` per logical phase across the
lifecycle tools, deliberately, as recommended. However, three of those tools
(`archive.py`, `write.py`, `delete.py`) have since grown substantially under
ADR-011/ADR-012 (S3 annotations, ETag-guarded compare-and-swap retry loops) — each CAS
attempt needs its own credential catch around each of several client calls, so the same
2-line `except CredentialError: return {"error": ErrorCode.CREDENTIAL_ERROR, ...}`
fragment has regrown to ~9–10 occurrences in `archive.py` and `write.py` individually
(up from a ~30-occurrence total across 7 files at review time). This is not a reversion of
the fix — the fold-per-phase shape still holds, and `link_commit.py` (one of the original
7 sites) no longer exists — but the underlying repetition is back at a comparable order of
magnitude from unrelated feature work. A `wrap_credential_errors`-style tool-layer helper
(mirroring M3, e.g. a decorator or the CAS retry loop itself owning one catch) would be a
reasonable follow-up if the PM wants to revisit; not urgent, purely stylistic.]

### Major (meaningful complexity reduction)

**M1. `config.py` — seven range-check `@field_validator`s are boilerplate
(`config.py:205–231, 285–311`).** They collapse to declarative pydantic
`Field(ge=…, le=…)` constraints (~107 lines removed). **Caveat:** `load_settings` surfaces
pydantic's raw `err['msg']` to the operator, so built-in constraint messages differ from
the current custom strings (`"X must be between 1 and 100 (got 0)"`). If any test asserts
on that text, use the lower-risk route instead: a single `_check_range(name, v, lo, hi)`
helper called as a one-liner from each validator — preserves messages, still cuts most of
the bulk. **Check `tests/` for `"must be between"` assertions to pick the route.**
*Effort: low · Risk: low (helper route) / med (Field route).*

**[Verified 2026-08-12 — ✅ RESOLVED.** `config.py` now uses declarative
`Field(ge=…, le=…)` constraints (the Field route, not the message-preserving helper
route) for every numeric range check. Fixed by `329614c`, deliberate; no test currently
asserts on the old custom range-message text.]

**M2. `bedrock.py` — `embed` and `invoke_text_model` are near-identical
(`bedrock.py:72–104, 136–168`).** Both share the `range(2)` retry loop, `invoke_model`
call, JSON parse, credential block, and transient-retry-with-jitter block verbatim;
only the request body and response-extraction path differ. Extract one
`_invoke(model_id, request_body, extract)` helper → each method becomes 3–4 lines.
Removes ~50 lines and the two `raise RuntimeError("Unreachable")` tails. *Effort: med ·
Risk: low–med (retry/credential semantics must stay byte-identical; throttle/timeout tests
cover this).*

**[Verified 2026-08-12 — ✅ RESOLVED.** `bedrock.py` now has a single `_invoke(model_id,
request_body, extract)` helper; `embed` and `invoke_text_model` are each a short call into
it with a lambda extractor. Fixed by `329614c`, deliberate.]

**M3. Shared credential-error construction across clients.** The same message string and
`CredentialError(message=…, service=…, original=exc)` construction appear in
`s3.py::_credential_error`, `vectors.py::_wrap_credential_error`, and `bedrock.py` (inline
×2), plus the `if is_credential_error(exc): raise … from exc; raise` boilerplate ~13 times.
`clients/credentials.py` already exists and is imported by all three — add a
`@contextmanager wrap_credential_errors(service)` there and reuse it. Pairs naturally with
C3. *Effort: med · Risk: low.* Constraint-safe (does not touch `interfaces.py`, `filter_expr`,
or score logic).

**[Verified 2026-08-12 — ✅ RESOLVED.** `clients/credentials.py` now has exactly this:
a `@contextmanager wrap_credential_errors(service)`, used by `s3.py`, `vectors.py`, and
`bedrock.py`. Fixed by `329614c`, deliberate — and the helper was extended further since
(ADR-011 decision 5) to also classify annotation-unavailable errors, without disturbing
this finding's resolution.]

**M4. `resources.py` — data-drive the five schema-resource registrations
(`resources.py:363–386`).** Each is an identical `@app.resource(uri) def _x(): return fn()`.
Replace with a `_SCHEMA_RESOURCES = [(uri, description, content_fn), …]` table looped in
`register_resources`. ~24 lines → ~10, and adding a schema resource becomes a one-line
entry. *Effort: low · Risk: low.*

**[Verified 2026-08-12 — ✅ RESOLVED.** `resources.py` now has a `_SCHEMA_RESOURCES`
table looped in `register_resources`, exactly as recommended. Fixed by `329614c`,
deliberate.]

**M5. `health.py` — extract a `_probe(label, fn)` helper (`health.py:68–151`).** Five/six
probe blocks repeat the same ok/CredentialError/Exception status-dict shape. The helper
turns each into a one-liner. Keep the write-prefix probe (`:113–137`) bespoke for its
`finally` cleanup. *Effort: med · Risk: low–med.* The clearest single-file win.

**[Verified 2026-08-12 — ✅ RESOLVED.** `health.py` now has a `_probe(fn)` helper used
by every probe (`s3`, `vectors`, `bedrock`, `bedrock_text_model`, `read_prefix:*`); the
write-prefix probe remains bespoke for its `finally` cleanup, exactly as the finding
recommended. Fixed by `329614c`, deliberate.]

**M6. Shared metadata helpers for the read path.** Two patterns are copy-pasted across
`search.py`, `synthesise.py`, `list.py`, `read.py`, `reconcile.py`:
- list-or-comma-string coercion → `coerce_list_field(meta, key)` (5+ sites)
- the `user_filters` clause builder (`type/team/project/tier/tags`) →
  `build_user_filters(...)` in `_search_helper.py` (`search.py:117–128`,
  `synthesise.py:102–111`, `list.py:96–111`)

Do the low-risk `coerce_list_field` + `build_user_filters` extraction first. Defer the
full "metadata → result dict" projection: `read.py` reads **S3** string metadata while the
others read **vector** metadata (`list[str]`), so a unified projection must handle both
encodings carefully (this divergence is an intentional High-Friction Area). *Effort: low
(helpers) / med (full projection) · Risk: low / med.*

**[Verified 2026-08-12 — ✅ RESOLVED (low-risk half only, as recommended).**
`_search_helper.py` now has both `coerce_list_field(meta, key)` and
`build_user_filters(...)`, used by `search.py`, `synthesise.py`, `list.py`, `read.py`, and
`reconcile.py`. The full "metadata → result dict" projection was correctly left
undone — `read.py` still reads S3 string metadata while the others read vector `list[str]`
metadata, per the documented High-Friction divergence. Fixed by `329614c`, deliberate.]

**M7. `write.py` — extract `_record_partial_write(...)` and linearize the doc-fallback
(`write.py:405–528`).** The failure-log-and-return dict is built ~4 times across the
sections path and the document-fallback path (~40 lines of duplication). Also, the
fallback's `doc_embed_error`/`doc_embedding = None` sentinel dance plus the impossible
`raise RuntimeError("…is a bug")` (`:466–502`) can become a linear try/except that
guarantees `doc_embedding` is bound. *Effort: low–med · Risk: low.* Materially shrinks the
longest file.

**[Verified 2026-08-12 — ✅ RESOLVED.** `write.py` now has a `_record_partial_write(...)`
helper used at every partial-write return site, and the doc-fallback path is linearized.
Fixed by `329614c`, deliberate. Note `write.py` has grown again since (931 lines today) from
unrelated ADR-011/ADR-012 CAS-retry and annotation work — it is once again the longest
file in the codebase, though not for the reason this finding described.]

### Minor (polish)

- **`read.py:88–118`** — own-scope and foreign-scope branches duplicate the same
  `head_object` + CredentialError/KeyError handling. Fetch once, then gate. ~12 lines.
  **[Verified 2026-08-12 — ✅ RESOLVED.** `_read_artifact_inner` now fetches
  `head_object` once (Step 2) and both scopes gate off the single result. Fixed by
  `329614c`, deliberate.]
- **`list.py:153–154`** — `own_scope`/`read_prefixes` recomputed (already set at `:113–115`);
  delete the second pair.
  **[Verified 2026-08-12 — ✅ RESOLVED.** `own_scope`/`read_prefixes` are now computed
  exactly once, near the top of the function. Fixed by `329614c`, deliberate.]
- **`vectors.py`** — `put_vector` can delegate to `put_vectors_batch` (one-element payload);
  a `_chunked(seq, size)` generator DRYs the three identical chunk loops (keep the three
  named size constants); `describe_index` two-step collapses to `return dict(response.get("index", {}))`.
  **[Verified 2026-08-12 — ✅ RESOLVED.** All three: `put_vector` is now a one-line
  delegation to `put_vectors_batch`; a generic `_chunked[T](seq, size)` module function is
  used by the chunk loops; `describe_index` returns `dict(response.get("index", {}))`
  directly. Fixed by `329614c`, deliberate.]
- **`s3.py:117–123`** — `list_objects` nested loop → comprehension; the credential
  try/except is the same boilerplate addressed by M3.
  **[Verified 2026-08-12 — ✅ RESOLVED.** `list_objects` is now a list comprehension over
  the paginator; the credential handling goes through `wrap_credential_errors` (M3). Fixed
  by `329614c`, deliberate.]
- **`purge.py:93–109`** — two identical empty-result dicts; define once as a local.
  **[Verified 2026-08-12 — ✅ RESOLVED.** A single `empty_result` local is defined once
  and reused at both early-return sites. Fixed by `329614c`, deliberate. `purge.py` was
  also independently rewritten shortly after (`a0be166`, best-effort partial-failure
  contract — see the Observation below), which restructured this area further but kept
  the single-local pattern.]
- **`migrate_artifacts.py:196–213`** — the `if warning is not None` spread is duplicated on
  the dry-run and live return paths; a tiny `_with_warning(resp)` dedupes.
  **[Verified 2026-08-12 — ✅ RESOLVED.** A `_with_warning(resp)` helper exists and is
  used at every return site (dry-run, live, and error paths). Fixed by `329614c`,
  deliberate.]
- **`artifact.py:84–91` vs `:218–253`** — type/tier/date validation (and identical message
  strings) duplicated between `generate_artifact_id` and the `Artifact` validators; extract
  module-level `_require_valid_{type,date,tier}` helpers (must stay in `artifact.py`; do not
  duplicate `ARTIFACT_TYPES`).
  **[Verified 2026-08-12 — ✅ RESOLVED.** Module-level `_require_valid_type`,
  `_require_valid_date`, `_require_valid_tier` exist in `artifact.py` and are used by both
  `generate_artifact_id` and the `Artifact` field validators; `ARTIFACT_TYPES` is not
  duplicated. Fixed by `329614c`, deliberate.]
- **Magic strings** — error codes (`"credential_error"` ×46, `"internal_error"` ×17, …) and
  status literals (`"active"`/`"inactive"`) are scattered. Centralising into an
  `ErrorCode`/`ArtifactStatus` constants module is low-effort and aids IDE-wide refactoring.
  Metadata-key strings (`"artifact_id"`, `"scope"`, …) are higher churn — lower priority.
  **[Verified 2026-08-12 — ✅ RESOLVED.** `src/arkeology/constants.py` now holds
  `ErrorCode` and `ArtifactStatus` as `enum.StrEnum` (per `AGENTS.md`: "Centralised
  string-literal constants: error codes, artifact status"), used throughout `tools/` and
  `clients/`. Metadata-key strings were, as recommended, not centralised. Fixed by
  `329614c`, deliberate — this module did not exist before that commit.]
- **`resources.py`** — extract `_error_markdown(result)` (duplicated at `:469–473` and
  `:569–572`); tidy the 4× pipe-escaping into one cell loop (`:532–542`); fix the
  `_arkeology_studior_html` typo (`:428`).
  **[Verified 2026-08-12 — ✅ RESOLVED.** `_error_markdown(result)` exists and is used at
  both former duplication sites; the typo is fixed (`_arkeology_studio_html`). Fixed by
  `329614c`, deliberate.]
- **`fake_bedrock.py:69–75`** — `set_throttle_once()` is just `set_throttle_count(1)`;
  consolidate the throttle/timeout setter API (also touches 3 test call sites).
  **[Verified 2026-08-12 — ✅ RESOLVED.** `fake_bedrock.py` now exposes only
  `set_throttle_count(count)` and `set_timeout_count(count)`; `set_throttle_once` is gone.
  Fixed by `329614c`, deliberate.]

### Verified NOT a defect (corrected during review)

- **`except A, B:` without parentheses** (`fake_bedrock.py:111`, `write_artifacts.py:152`).
  Two analysis passes flagged this as a possible latent bug (Python-2 `except E, name:`
  semantics, catching only the first type). **Verified false on this project:** under
  Python 3.14 (`requires-python = ">=3.14"`) the runtime catches **both** exceptions as a
  tuple — confirmed by direct execution — and ruff passes. It is therefore **not** a bug
  and not a portability issue within the supported range. It remains a **clarity** nit only:
  it reads like removed Python-2 syntax, so parenthesizing to `except (A, B):` is worth doing
  for the next reader. *Minor.*

**[Verified 2026-08-12 — STILL VALID (unparenthesized form still present, reasoning
still holds).** The pattern still exists today, at different locations —
`fake_bedrock.py:94` (`except ThrottlingError, ModelTimeoutError:`) and
`write_artifacts.py:168` (`except KeyError, ValueError, TypeError:`) — neither was
parenthesized by the simplification pass or since. Re-confirmed on the current
`requires-python = ">=3.14"` project: `ruff check` is clean and this remains valid PEP 758
tuple-exception syntax, not a Python-2 latent bug. Still just a clarity nit, unchanged
from the original finding.]

### Observation worth a closer look (not simplification)

- **`purge.py` partial-failure reporting** — on a mid-loop S3 failure the success path
  reports `purge_set` (the full intended set) rather than `purged_so_far` (actually
  deleted). This is a behaviour nuance, not a simplification; flagging so it is not
  accidentally "cleaned up" without thought, and so it can be triaged separately. *Low
  confidence — verify against intended semantics.*

**[Verified 2026-08-12 — ✅ RESOLVED (separately, as a behaviour fix, not a
simplification).** `purge.py` was rewritten by `a0be166` ("best-effort bulk
partial-failure contract", p3-t13), landing after `329614c` on the same
`refactor/codebase-simplification-2026-06-29` branch. The success and credential-abort
paths now both report `purged_ids`/`purged_count` built incrementally via a
`_record_success` closure as each artifact is actually deleted — never the full intended
`purge_set`. This confirms the review's flag was correct to raise and not
"clean up without thought"; it was triaged separately, exactly as recommended, and fixed
as a genuine behaviour change (not folded into the simplification commit).]

### Explicitly leave as-is (deliberate trade-offs — do not "simplify")

- **`config.py:332–451`** — the 24 snake_case passthrough properties. The largest verbose
  block, but the inline comment documents a deliberate IDE/mypy-transparency trade-off; a
  `__getattr__`/`alias_generator` approach would defeat that and break type-checking. The
  project's "explicit over clever" convention endorses keeping these.
  **[Verified 2026-08-12 — CONFIRMED, trade-off still real.** 22 properties today (count
  drifted slightly as settings were added/removed, not a regression); the same inline
  comment, verbatim reasoning, still documents the deliberate IDE/mypy-transparency
  trade-off. Still correctly left alone.]
- **`server.py:66–315`** — the 15 explicit tool wrappers. FastMCP introspects these
  signatures to build the LLM-facing JSON schema, so they cannot be loop-generated without
  changing tool behaviour. At most, bind the injected clients once via a `deps` dict
  (marginal). Largely irreducible.
  **[Verified 2026-08-12 — CONFIRMED, trade-off still real.** 16 explicit tool wrappers
  today (grew from 15 as new tools were added, e.g. `link_metadata`, `arkeology_studio`);
  same FastMCP signature-introspection constraint applies to each. Still correctly left
  alone.]
- **`startup.py`** — the six-check sequence repeats an error-wrapping idiom, but each check
  carries a distinct user-facing remediation message and special-case handling
  (`finally` cleanup, `VectorIndexNotFoundError`, dimension return), so a generic helper
  saves little and risks genericizing the messages.
  **[Verified 2026-08-12 — 🔄 CHANGED ENOUGH TO NEED RESTATING (trade-off itself still
  holds).** `startup.py` is now a **seven**-check sequence (per `AGENTS.md`: "Seven-check
  startup validation sequence") — Check 7 (probe `BEDROCK_TEXT_MODEL` when configured) was
  added after this review. The underlying reasoning is unchanged and still applies to the
  new check: it carries its own distinct skip-when-unconfigured logic and remediation
  message, so the "a generic helper saves little" trade-off still holds. Restate as
  "seven-check", not "six-check", if this note is carried forward.]
- **`interfaces.py`** (must stay `Protocol`), **`errors.py`**, **`failure_log.py`**,
  **`credentials.py`**, **`filter.py`** dispatch chain — clean and idiomatic as written.
  **[Verified 2026-08-12 — CONFIRMED, still clean.** All five files still exist with the
  same shape; `interfaces.py` is still `typing.Protocol`-based (per the project's
  Non-Negotiable Rule), and `credentials.py` grew (M3's `wrap_credential_errors` was added
  to it, plus ADR-011 annotation-unavailable detection) without losing its clean,
  idiomatic structure.]
- **`resources.py:479–516`** — `_artifact_last_modified` is unused production code but is a
  **documented waiver** tied to a spec and a unit test. Do not delete blindly; if revisited,
  the consolidation is to drop the `_read_artifact` round-trip and de-duplicate the
  triplicated waiver comment, not to remove the retention.
  **[Verified 2026-08-12 — CONFIRMED, still a documented waiver.** `_artifact_last_modified`
  is still present, still unwired, still explicitly commented as an intentional retention
  tied to the T42 waiver (`docs/specs/p10-t42-mcp-data-resources.md`) referenced at both its
  definition and the resource handler. Still correctly left alone.]

## Recommendations

Suggested order (value × safety):

1. **C2** (delete no-ops in `reconcile.py`) and **C1** (`list.py` → `build_scope_filter`) —
   zero/low risk, and C1 also removes a Non-Negotiable-Rule drift hazard. Do first.
2. **C3 + M3** together — the credential-error boilerplate is the single biggest source of
   repetition in the codebase; tackling tool-side folding and the shared client context
   manager in one pass avoids touching the same files twice.
3. **M1** (config validators), **M4** (resources table), **M5** (`health` `_probe`),
   **M7** (`write` partial-write helper) — independent, each a clean per-file win.
4. **M2** (bedrock `_invoke`) and **M6** (`coerce_list_field` + `build_user_filters`) —
   slightly broader; gate on the test suite.
5. Minor items opportunistically; the magic-string constants module when convenient.

**Process guardrails:** every change is behaviour-preserving by intent, so the existing
test suite is the safety net — run `uv run pytest tests/unit/ -q -m 'not integration'`,
`ruff check`, `ruff format --check`, and `mypy src/` after each item. Before M1 and any
config/validator change, grep `tests/` for assertions on exact error-message text. Tests
import several `_inner` functions directly, so do not rename them.

Indicative reduction if C1–C3, M1–M7 are applied: roughly **350–450 lines** removed with no
behaviour change, concentrated in the most-repeated paths (credential handling, config
validation, the read/metadata path, and `write.py`/`bedrock.py`).

## Items Resolved Since Last Review

<!-- changelog-style: prepend new entries -->
- 2026-08-12 — **Re-verification pass (developer): C1–C3, M1–M7, all 10 Minor items, and
  the Observation confirmed resolved; three items require restating or are no longer
  applicable; five leave-as-is trade-offs reconfirmed.** This review sat unclosed for
  ~1.5 months despite the code having been fixed the same day it was authored. Findings:
  **C1** `list.py` uses `build_scope_filter`. **C2** `reconcile.py` no-op reraises removed
  (now meaningful early returns) and the dead branch is gone. **C3** folded per-phase as
  recommended, but flagged as needing restating: unrelated later CAS-retry/annotation work
  (ADR-011/012) regrew the per-call credential-catch fragment count in `archive.py` and
  `write.py`. **M1** `config.py` uses declarative `Field(ge=/le=)`. **M2** `bedrock.py` has
  a shared `_invoke` helper. **M3** `clients/credentials.py` has
  `wrap_credential_errors(service)`, used by S3/vectors/bedrock. **M4** `resources.py` has
  a data-driven `_SCHEMA_RESOURCES` table. **M5** `health.py` has a shared `_probe` helper.
  **M6** `_search_helper.py` has `coerce_list_field` + `build_user_filters`; the full
  metadata-projection was correctly left deferred. **M7** `write.py` has
  `_record_partial_write`. All ten Minor items (read.py scope dedup, list.py recompute,
  vectors.py put_vector/_chunked/describe_index, s3.py list_objects comprehension,
  purge.py empty_result local, migrate_artifacts.py `_with_warning`, artifact.py
  `_require_valid_*` helpers, the `ErrorCode`/`ArtifactStatus` StrEnum module in the new
  `constants.py`, resources.py `_error_markdown` + typo fix, fake_bedrock.py setter
  consolidation) confirmed resolved. The Observation (`purge.py` partial-failure reporting)
  was independently resolved as a genuine behaviour fix, not a simplification. The
  "Verified NOT a defect" `except A, B:` note still holds (present at new locations,
  still valid PEP 758 syntax on Python 3.14). Of the "no dead code" health-check preamble,
  the `link_commit.py` bullet is no longer applicable (`link_commit.py` was retired,
  superseded by `link_metadata.py` in Phase 12 T49); the other two bullets still hold. Of
  the five "leave as-is" trade-offs, four are reconfirmed unchanged and one
  (`startup.py`) needs restating: it is now a seven-check sequence, not six, though the
  underlying "each check has distinct remediation" trade-off still applies. Root cause of
  the near-total resolution: `329614c` (merged `acff8c3`, 2026-06-29, same day as this
  review) applied C1–C3/M1–M7/all Minors deliberately per this document (707 unit tests
  passing, ruff/mypy clean); `a0be166` shortly after fixed the Observation as a behaviour
  change. Neither commit updated this document. No code was changed by this
  re-verification pass — see inline `[Verified 2026-08-12 — …]` markers throughout for
  per-finding detail and current gates (`ruff check` clean at HEAD `3bd9944`).
