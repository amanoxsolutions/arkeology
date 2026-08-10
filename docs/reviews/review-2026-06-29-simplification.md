---
type: code_review
title: "Codebase simplification review — reuse, redundancy, dead code, clarity"
description: "Whole-codebase review identifying simplification opportunities (DRY, dead code, over-engineering, clarity) across src/cairn_mcp; report only, no changes applied."
tags: [simplification, refactoring, dry, maintainability, code-review]
timestamp: 2026-06-29T00:00:00Z
okf_version: "0.1"
status: draft # draft | ready | in-progress | done
references: []
authored:
  by: "architect"
  date: "2026-06-29"
revised:
  by: ""
  date: ""
---

# Codebase simplification review — reuse, redundancy, dead code, clarity

## Description

A whole-codebase simplification pass over `src/cairn_mcp/` (~6,900 LOC, 30 files). The
goal was to find where code can be made simpler — duplication that should be shared, dead
code, over-engineering, and clarity issues — **without changing behaviour**. This is a
review only; no code was modified. Every finding preserves the project's Non-Negotiable
Rules (no stdout, `_inner` try/except safety net, `startswith(scope + "/")` scope checks,
no content in vector metadata, `typing.Protocol` client interfaces, `filter_expr` naming,
`1.0 - distance` scores).

Analysis was run as six parallel passes (core/config, clients, server/startup/resources,
write/read/search tools, lifecycle tools, and a cross-module duplication map), then
consolidated and independently verified.

## Spec and ADRs Consulted

- `AGENTS.md` / `CLAUDE.md` — conventions, Non-Negotiable Rules, High-Friction Areas
- `pyproject.toml` — `requires-python = ">=3.14"`, ruff/mypy config
- Prior review logs in `docs/reviews/` (e.g. `review-2026-06-25-full-codebase.md`,
  `review-2026-05-31-fix-11-search-synthesise-shared-helper.md`) for context on
  decisions already made
- No feature spec — this is a maintainability review of existing code, not a feature change.

## Files Reviewed

All `.py` under `src/cairn_mcp/`: `artifact.py`, `config.py`, `errors.py`,
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
- **`link_commit.py` vs `propose_commit_links.py` are complementary**, not overlapping
  (propose = read-only discovery; link = write the SHA). Keep both.
- **All 16 tool files are registered** in `server.py::register_tools()`; `_search_helper.py`
  is correctly a shared module, not a tool. `search.py` and `synthesise.py` both correctly
  delegate the re-fetch loop to `run_search_loop` — the documented single-source contract holds.

### Critical (highest-value, low-risk — do these first)

**C1. `list.py` rebuilds the scope filter instead of calling `build_scope_filter`
(`list.py:113–133`).** `_search_helper.build_scope_filter(settings)` already produces the
exact `$or`/`$and` scope clause; `list.py` re-implements it inline (the inline comment even
says "same logic as search.py"). The scope gate is a **Non-Negotiable Rule**, so two copies
is a real drift risk — a future fix to one can silently miss the other. Replace the inline
block with `clauses.append(build_scope_filter(settings))`. ~18 lines removed, output
identical. *Effort: low · Risk: low.*

**C2. Delete the no-op `try/except CredentialError: raise` blocks in `reconcile.py`
(`reconcile.py:99–131`).** Four blocks catch `CredentialError` only to re-raise it
unchanged — identical to not catching it. Pure deletion, ~16–20 lines, zero behaviour
change. Also dead: the `else` at `reconcile.py:276–278` re-sets
`failure_log_entries_before/after = 0`, already initialised at `:193–194`.
*Effort: low · Risk: none.*

**C3. Collapse the per-call `except CredentialError → {"error": "credential_error", ...}`
blocks.** This exact 2–3 line fragment recurs ~30 times across `archive`, `delete`,
`purge`, `reconcile`, `freshness`, `link_commit`, `propose_commit_links` (and ~59 times if
you count clients). Where every catch in a tool is identical, fold them into **one `try`
per logical phase** wrapping several client calls. Caveat: a few sites carry extra fields
(`delete.py:155`, `purge.py:172` add `artifact_id`) or map non-credential exceptions
differently (`delete`'s `partial_delete`/`delete_vectors_failed`) — leave those bespoke;
the win is in the files where the catch is uniform. *Effort: low–med · Risk: low.*

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

**M2. `bedrock.py` — `embed` and `invoke_text_model` are near-identical
(`bedrock.py:72–104, 136–168`).** Both share the `range(2)` retry loop, `invoke_model`
call, JSON parse, credential block, and transient-retry-with-jitter block verbatim;
only the request body and response-extraction path differ. Extract one
`_invoke(model_id, request_body, extract)` helper → each method becomes 3–4 lines.
Removes ~50 lines and the two `raise RuntimeError("Unreachable")` tails. *Effort: med ·
Risk: low–med (retry/credential semantics must stay byte-identical; throttle/timeout tests
cover this).*

**M3. Shared credential-error construction across clients.** The same message string and
`CredentialError(message=…, service=…, original=exc)` construction appear in
`s3.py::_credential_error`, `vectors.py::_wrap_credential_error`, and `bedrock.py` (inline
×2), plus the `if is_credential_error(exc): raise … from exc; raise` boilerplate ~13 times.
`clients/credentials.py` already exists and is imported by all three — add a
`@contextmanager wrap_credential_errors(service)` there and reuse it. Pairs naturally with
C3. *Effort: med · Risk: low.* Constraint-safe (does not touch `interfaces.py`, `filter_expr`,
or score logic).

**M4. `resources.py` — data-drive the five schema-resource registrations
(`resources.py:363–386`).** Each is an identical `@app.resource(uri) def _x(): return fn()`.
Replace with a `_SCHEMA_RESOURCES = [(uri, description, content_fn), …]` table looped in
`register_resources`. ~24 lines → ~10, and adding a schema resource becomes a one-line
entry. *Effort: low · Risk: low.*

**M5. `health.py` — extract a `_probe(label, fn)` helper (`health.py:68–151`).** Five/six
probe blocks repeat the same ok/CredentialError/Exception status-dict shape. The helper
turns each into a one-liner. Keep the write-prefix probe (`:113–137`) bespoke for its
`finally` cleanup. *Effort: med · Risk: low–med.* The clearest single-file win.

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

**M7. `write.py` — extract `_record_partial_write(...)` and linearize the doc-fallback
(`write.py:405–528`).** The failure-log-and-return dict is built ~4 times across the
sections path and the document-fallback path (~40 lines of duplication). Also, the
fallback's `doc_embed_error`/`doc_embedding = None` sentinel dance plus the impossible
`raise RuntimeError("…is a bug")` (`:466–502`) can become a linear try/except that
guarantees `doc_embedding` is bound. *Effort: low–med · Risk: low.* Materially shrinks the
longest file.

### Minor (polish)

- **`read.py:88–118`** — own-scope and foreign-scope branches duplicate the same
  `head_object` + CredentialError/KeyError handling. Fetch once, then gate. ~12 lines.
- **`list.py:153–154`** — `own_scope`/`read_prefixes` recomputed (already set at `:113–115`);
  delete the second pair.
- **`vectors.py`** — `put_vector` can delegate to `put_vectors_batch` (one-element payload);
  a `_chunked(seq, size)` generator DRYs the three identical chunk loops (keep the three
  named size constants); `describe_index` two-step collapses to `return dict(response.get("index", {}))`.
- **`s3.py:117–123`** — `list_objects` nested loop → comprehension; the credential
  try/except is the same boilerplate addressed by M3.
- **`purge.py:93–109`** — two identical empty-result dicts; define once as a local.
- **`migrate_artifacts.py:196–213`** — the `if warning is not None` spread is duplicated on
  the dry-run and live return paths; a tiny `_with_warning(resp)` dedupes.
- **`artifact.py:84–91` vs `:218–253`** — type/tier/date validation (and identical message
  strings) duplicated between `generate_artifact_id` and the `Artifact` validators; extract
  module-level `_require_valid_{type,date,tier}` helpers (must stay in `artifact.py`; do not
  duplicate `ARTIFACT_TYPES`).
- **Magic strings** — error codes (`"credential_error"` ×46, `"internal_error"` ×17, …) and
  status literals (`"active"`/`"inactive"`) are scattered. Centralising into an
  `ErrorCode`/`ArtifactStatus` constants module is low-effort and aids IDE-wide refactoring.
  Metadata-key strings (`"artifact_id"`, `"scope"`, …) are higher churn — lower priority.
- **`resources.py`** — extract `_error_markdown(result)` (duplicated at `:469–473` and
  `:569–572`); tidy the 4× pipe-escaping into one cell loop (`:532–542`); fix the
  `_cairn_studior_html` typo (`:428`).
- **`fake_bedrock.py:69–75`** — `set_throttle_once()` is just `set_throttle_count(1)`;
  consolidate the throttle/timeout setter API (also touches 3 test call sites).

### Verified NOT a defect (corrected during review)

- **`except A, B:` without parentheses** (`fake_bedrock.py:111`, `write_artifacts.py:152`).
  Two analysis passes flagged this as a possible latent bug (Python-2 `except E, name:`
  semantics, catching only the first type). **Verified false on this project:** under
  Python 3.14 (`requires-python = ">=3.14"`) the runtime catches **both** exceptions as a
  tuple — confirmed by direct execution — and ruff passes. It is therefore **not** a bug
  and not a portability issue within the supported range. It remains a **clarity** nit only:
  it reads like removed Python-2 syntax, so parenthesizing to `except (A, B):` is worth doing
  for the next reader. *Minor.*

### Observation worth a closer look (not simplification)

- **`purge.py` partial-failure reporting** — on a mid-loop S3 failure the success path
  reports `purge_set` (the full intended set) rather than `purged_so_far` (actually
  deleted). This is a behaviour nuance, not a simplification; flagging so it is not
  accidentally "cleaned up" without thought, and so it can be triaged separately. *Low
  confidence — verify against intended semantics.*

### Explicitly leave as-is (deliberate trade-offs — do not "simplify")

- **`config.py:332–451`** — the 24 snake_case passthrough properties. The largest verbose
  block, but the inline comment documents a deliberate IDE/mypy-transparency trade-off; a
  `__getattr__`/`alias_generator` approach would defeat that and break type-checking. The
  project's "explicit over clever" convention endorses keeping these.
- **`server.py:66–315`** — the 15 explicit tool wrappers. FastMCP introspects these
  signatures to build the LLM-facing JSON schema, so they cannot be loop-generated without
  changing tool behaviour. At most, bind the injected clients once via a `deps` dict
  (marginal). Largely irreducible.
- **`startup.py`** — the six-check sequence repeats an error-wrapping idiom, but each check
  carries a distinct user-facing remediation message and special-case handling
  (`finally` cleanup, `VectorIndexNotFoundError`, dimension return), so a generic helper
  saves little and risks genericizing the messages.
- **`interfaces.py`** (must stay `Protocol`), **`errors.py`**, **`failure_log.py`**,
  **`credentials.py`**, **`filter.py`** dispatch chain — clean and idiomatic as written.
- **`resources.py:479–516`** — `_artifact_last_modified` is unused production code but is a
  **documented waiver** tied to a spec and a unit test. Do not delete blindly; if revisited,
  the consolidation is to drop the `_read_artifact` round-trip and de-duplicate the
  triplicated waiver comment, not to remove the retention.

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
- (none yet — initial simplification review)
