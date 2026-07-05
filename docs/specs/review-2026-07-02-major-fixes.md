# Spec — Major review fixes (M-1 … M-16)

**Status:** frozen · **Source:** `.docs/reviews/review-2026-07-02-full-project-review.md`
**Testing approach:** TDD (write failing tests first, then implement) per NFR-07
**Branch:** `phase-12-cross-referencing`

## Scope and current status (verified against code 2026-07-05)

The five Critical findings and CA-1/CA-2/CA-3 are already resolved. CA-4 Option A shipped
(T54); Option B is backlog B-6. This spec covers the **Major** cluster only.

| Finding | Status at spec time | Owner |
|---------|---------------------|-------|
| M-5  | ✅ ALREADY FIXED by Phase 12 T55 (`p12-t55-metadata-validation.md`) — mark resolved, no work | — |
| M-1, M-2, M-3, M-4 | STILL PRESENT — Cluster A | developer |
| M-6, M-7, M-8, M-9 | STILL PRESENT — Cluster B | developer |
| M-10, M-11, M-12 | STILL PRESENT — Cluster C | developer |
| M-13 | PARTIALLY FIXED — residual items — Cluster D | PM (PRD) |
| M-14, M-15 | PARTIALLY (M-14) / PRESENT (M-15) — Cluster D | tech-writer |
| M-16 | STILL PRESENT — Cluster E | developer |

**Commit cadence:** one commit per cluster (operator decision). Do not push. Use the project's
emoji conventional-commit style; end each commit message with:
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

**Cross-cutting requirements (every code cluster):**
- TDD: failing tests first, then implement.
- Mock AWS with moto + `FakeBedrockClient`; do not add `set_credential_failure` fakes; use
  `mocker.patch.object(..., side_effect=CredentialError(...))` and `mocker.spy` per conventions.
- Confirm any S3 / S3 Vectors operation is moto-supported before testing it; self-mock minimally
  if not (mirror the existing `query_vectors` / annotation extensions in `conftest.py`).
- All tool public functions delegate to an `_inner` wrapped in `try/except Exception`.
- Never print to stdout; use `logging`.
- Full gate must pass before commit: `uv run pytest tests/unit/ -q -m 'not integration'`,
  `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run mypy src/`.
- Update code-adjacent docs (specs / ADRs) that your change makes false — add a `revised` entry,
  do not rewrite history. Flag any interface/usage doc change (README / SERVER-REFERENCE /
  AGENTS.md) for the tech-writer pass, and any PRD change for the PM.

---

## Cluster A — Recovery path & write integrity (M-1 … M-4)

Shared theme: the self-healing story (failure log + `reconcile_index`) has holes exactly where
healing is needed. Address in order; commit as one unit.

### M-1 — Archive partial failure is unrepairable
**Current:** `tools/archive.py` idempotency check (~L104-110) tests only S3 `status == INACTIVE`;
status flip is S3-first (~L135) before the vector loop (~L156-166); a vector failure returns
`credential_error` with **no failure-log append**, and retry hits the `already_archived` early
return forever. Neither purge (selects by vector status) nor reconcile (artifact still indexed)
repairs it.
**Required:**
1. The idempotency / `already_archived` determination must consider **vector** status too, so a
   half-archived artifact (S3 inactive, vectors active) is NOT treated as fully archived — the
   retry must be able to complete the vector-side flip.
2. On any partial archive (S3 flipped, vector flip failed — credential or otherwise), append a
   failure-log entry (the log is local, needs no AWS) so the state is recoverable/visible.
**Acceptance:** a vector-side failure mid-archive leaves a repairable trace (failure-log entry);
a retry after a partial archive completes the vector flip instead of early-returning
`already_archived`; existing archive tests still pass.

### M-2 — `reconcile_index` Phase 3 can delete vectors of a concurrently-written artifact
**Current:** `tools/reconcile.py` lists S3 first (~L292) then vectors (~L300); Phase 3 (~L344-365)
prunes `vectors_by_artifact.keys() - own_keys_set` with no re-`head_object`. An artifact fully
written between the two listings is classified dangling and its fresh vectors pruned.
**Required:** eliminate the race — list **vectors first, then S3**, and/or re-`head_object` each
candidate immediately before pruning it; only prune when the S3 object is confirmed absent at
prune time. Preserve the own-scope gate.
**Acceptance:** a test simulating an artifact written after the vector listing but present at
prune time proves its vectors are **not** pruned; genuine dangling vectors are still pruned;
own-scope gate preserved.

### M-3 — `reconcile_index` re-embeds without the write path's section pipeline
**Current:** `reconcile.py::_reindex_artifact` (~L110-145) parses sections and embeds each directly;
it does **not** apply the write path's min-length filter, `embed_max_sections` cap, or
`embed_max_section_length` truncation (`write.py` Steps 5a/5b). Only the `_build_*_embedding_text`
helpers are shared. A section truncated at write time is sent full-length on every reconcile replay
and fails Titan's input limit forever (stuck failure-log entry).
**Required:** factor the write-path section pipeline (min-length filtering, max-sections cap,
per-section truncation, and the embedding-text building) into a single shared helper and call it
from **both** `write.py` and `reconcile.py` so reconcile reproduces write-time behaviour exactly.
**Acceptance:** a section that write-time truncates is truncated identically on reconcile (test
asserts the embedded text passed to Bedrock matches between the two paths); min-length and
max-sections behaviour is identical; existing write + reconcile tests pass.

### M-4 — `write_artifact`: credential error after the S3 put writes no failure-log entry
**Current:** `write.py` credential branches after the S3 put (annotation write, section-embed,
`put_vectors_batch`, doc-path) return `credential_error` with no failure-log entry, while
non-credential failures call `_record_partial_write`. For an `overwrite=True` tier-3 rewrite, old
vectors survive → reconcile sees "indexed" → the index permanently serves the previous version
against new S3 content.
**Required:** append a failure-log entry on the credential-error branches too (after the S3 put has
succeeded), so every post-S3-put failure leaves a repairable trace. The failure log is local and
needs no AWS.
**Acceptance:** a credential failure after the S3 put (including the tier-3 overwrite rewrite case)
produces a failure-log entry; non-credential partial writes still log as today.

---

## Cluster B — Search & error handling / async (M-6 … M-9)

### M-6 — Search re-fetch loop: unbounded `$nin` growth + all-or-nothing error handling
**Current:** `tools/_search_helper.py::run_search_loop` exclusion filter
`{"artifact_id": {"$nin": list(seen_ids)}}` (~L145) grows unbounded (will exceed the S3 Vectors
filter-size limit on broad searches); only `CredentialError` is caught (~L154), so any other
failure (e.g. `ValidationException`) propagates and the tool's top-level handler discards all
already-collected results as `internal_error`.
**Required:**
1. Bound the `$nin` exclusion list by a byte budget (stop growing / stop iterating gracefully
   before the filter-size limit); when the budget is hit, stop the re-fetch loop and return what
   was collected rather than erroring.
2. On a **non-credential** failure mid-loop, return the results already collected (partial
   success) instead of discarding everything. Credential errors keep their current classification.
**Acceptance:** a test proving the exclusion list is byte-bounded (loop terminates without
exceeding the budget); a test proving a non-credential failure after N collected results returns
those N results (not `internal_error`); credential-error behaviour unchanged. This is shared by
`search` and `synthesise` — fix in `_search_helper.py` only.

### M-7 — Credential-error classification misses the codes AWS actually returns
**Current:** `clients/credentials.py` `CREDENTIAL_ERROR_CODES` lacks S3 XML codes (`ExpiredToken`,
`InvalidAccessKeyId`, `SignatureDoesNotMatch`, and S3's `AccessDenied` form) and
`UnrecognizedClientException`; `wrap_credential_errors` catches only `ClientError`, so
`NoCredentialsError` and the SSO token exceptions escape as `internal_error`. `startup.py`
check-2 read probe catches only `KeyError` (a GetObject `AccessDenied` crashes with a raw
traceback); `__main__.py` `boto3.Session(profile_name=…)` construction is uncaught.
**Required:**
1. Add the missing credential error codes. **Caveat:** `AccessDenied`/`AccessDeniedException` is
   deliberately part of the annotation-unavailable handling (T52) — do not break that; ensure the
   annotation-availability path still classifies its `AccessDenied` correctly and the credential
   classifier does not swallow it wrongly. Reconcile the two consumers explicitly.
2. Catch `NoCredentialsError` and the SSO/token exceptions in `wrap_credential_errors` (not only
   `ClientError`) and classify them as credential errors (the `aws sso login` remediation path).
3. `startup.py` check 2: catch credential/`AccessDenied` on the read probe and surface a structured
   startup error, not a raw traceback.
4. `__main__.py`: wrap client/session construction so a bad `profile_name` surfaces a structured
   error, not an uncaught exception.
**Acceptance:** unit tests proving each newly-added code and `NoCredentialsError`/SSO exception is
classified as a credential error; a startup read-probe `AccessDenied` yields a structured error;
the annotation-unavailable `AccessDenied` path still works. Do not leak raw boto messages
(bucket/index names) to MCP callers.

### M-8 — Blocking I/O on the asyncio event loop
**Current:** `search`/`read`/`list`/`reconcile` call boto3 synchronously; only `write` offloads via
`_EMBED_EXECUTOR`; `bedrock.py` throttle `time.sleep(...)` (~L80) blocks the loop, freezing
concurrent MCP requests (e.g. Studio's parallel `read_artifact` + `search_artifacts`).
**Required:** route blocking client calls through `asyncio.to_thread` (or the existing executor
pattern) uniformly across `search`, `read`, `list`, `reconcile`, and `freshness`; replace the
blocking sleep in the Bedrock retry path with a non-blocking wait when on the event loop (or move
the whole client call off-loop so the sleep no longer blocks it). Keep the write path's existing
offload. Preserve `SECTION_CONCURRENCY` bounding.
**Acceptance:** a test demonstrating a read/search path does not block the loop during a client
call (e.g. two coroutines make progress concurrently, or the call is asserted to run via
`to_thread`); existing behaviour/results unchanged. Note: keep the change surgical and typed
(mypy clean).

### M-9 — Startup validation never probes the embedding model
**Current:** `startup.py::_check_model_dimension` only compares configured
`BEDROCK_EMBEDDING_DIMENSIONS` to the index dimension; no check calls `bedrock.embed`. A
wrong/unentitled embedding model passes all checks and every write/search then fails.
**Required:** add a startup check that embeds a short probe string via `bedrock.embed` and asserts
the returned vector dimension equals the configured/index dimension; classify a
credential/entitlement failure with a structured, actionable error (reuse M-7 classification).
This **adds one startup check** — update the check count everywhere it is stated (see M-13 FR-07,
the startup spec `p1-t5`, and any "N checks" text). Coordinate the final number with the doc
cluster.
**Acceptance:** a test proving startup fails with a clear error when the embed probe returns the
wrong dimension or raises a credential/entitlement error; a test proving a correct probe passes;
the check-count references are updated to the new total.

---

## Cluster C — Tool surface (M-10 … M-12)

### M-10 — `write_artifacts` does not expose `artifact_concurrency` over MCP
**Operator decision (frozen): EXPOSE the parameter.**
**Current:** `server.py` registers `write_artifacts(artifacts, overwrite=False)`; the inner
`_write_artifacts` accepts `artifact_concurrency` but it is not in the MCP signature, though PRD
FR-25, spec `p10-t39`, and SERVER-REFERENCE document it as caller-controllable.
**Required:** register `artifact_concurrency` on the MCP `write_artifacts` signature in `server.py`
and forward it to the inner function, matching the shape and validation described in
`p10-t39-caller-controlled-artifact-concurrency.md` (same bounds/defaults the inner function
already enforces). Do not change `overwrite` behaviour.
**Acceptance:** an MCP-level test proving `write_artifacts` accepts `artifact_concurrency` and
forwards it; out-of-range values are validated consistently with the inner function; default
behaviour unchanged. This closes the doc-vs-code contradiction (no PRD/spec change needed beyond
confirming they now match — flag to PM/tech-writer if any wording still drifts).

### M-11 — Studio error masking and dead code
**Current (all four sub-items present):**
(a) `studio.py` `_cairn_studio_inner` does `listing.get("artifacts", [])` — an error dict from
`_list_artifacts_inner` (credential failure) becomes a successful empty listing.
(b) `cairn-studio.html` `loadList` renders `data.artifacts || []` → error dict shows "No artifacts
found."; `doSearch` discards the server error message.
(c) `app.ontoolresult` does `JSON.parse(text)` on the plain-text confirmation supporting hosts
receive → throws on every render; `scopeLabel` reads `data.write_prefix` (sent only to
non-supporting hosts) → dead code in the iframe.
(d) status filter "All" option sends `value=""` → `loadList` omits the param → `list_artifacts`
defaults to `active` → "All" is unreachable.
**Required:**
1. (a) In `studio.py`, detect an error dict from the inner list call and propagate a structured
   error (do not coerce to an empty listing). Expired credentials must surface as an error, not
   "store looks empty" (PRD FR-12).
2. (b) In the JS, when the server payload is an error, render the server-provided message
   (list + search) instead of "No artifacts found." / a generic "Search failed."
3. (c) Stop `JSON.parse`-ing the plain-text supporting-host confirmation (guard by payload type);
   remove or correctly source the dead `scopeLabel` code.
4. (d) Make the "All" status filter actually reach all statuses — pass an explicit all-inclusive
   request (or omit-means-all handled server-side) so the option is not a no-op.
**Acceptance:** a `studio.py` unit test proving a credential-error inner listing yields a
structured error (not empty success). Browser JS: no unit harness — verify by asserting the
sanitized/branch behaviour in jsdom or document the manual verification (matching the C-2
approach). Note any resources/`server.py` change needed to make "All" reachable.

### M-12 — `migrate_artifacts` silently writes empty descriptions
**Current:** `migrate_artifacts.py` — a failed Nova generation `continue`s leaving the description
unset; Step 3 falls back to `description: ""`, which passes validation and writes a degraded,
near-unsearchable artifact. The generation prompt also interpolates full untruncated artifact
content.
**Required:**
1. A failed description generation must NOT produce an empty-description write. Either skip the
   artifact and report it (consistent with the T55/A-1 `skipped`/failure reporting shape) or fail
   that item with a structured error — do not write an empty description. Pick the shape consistent
   with the current `migrate_artifacts` return dict and document it.
2. Truncate/bound the artifact content interpolated into the generation prompt (do not send
   unbounded full content).
**Acceptance:** a test proving a failed generation does not write an empty-description artifact
(item is skipped/reported); a test proving the prompt content is bounded; existing migration tests
pass.

---

## Cluster D — Documentation & governance (M-13, M-14, M-15) — run LAST

Run after Clusters A-C so docs reflect the final code (notably the startup check count after M-9
and the `artifact_concurrency` registration after M-10). PRD (M-13) owned by PM; ADRs +
reference docs (M-14, M-15) by tech-writer.

### M-13 — PRD self-contradictions (residual, after partial fix)
Still present in `docs/planning-artifacts/prd.md` (fix without introducing "how" — no env var
names, paths, CLI, permission strings):
- FR-23 corrupted merge text "…so long runs are never **silentnything**" — repair the sentence and
  resolve the batching-vs-single-call contradiction.
- Migration thresholds "< 5 / ≥ 5 / 5+ files" and the `write_artifacts`-vs-`migrate_artifacts`
  split contradict the shipped skill (≤10 / >10; `migrate_artifacts`). Reconcile to shipped.
- "feature tags" persists throughout — rename to `tags` (T41 rename).
- AC-47 still tests the removed skill (FR-36 superseded) — remove/replace AC-47.
- AC-25 references "the migration script" deleted in Phase 9 — remove/replace.
- FR-07 enumerates five checks; server runs six today and **seven after M-9** — state the final
  number (confirm with the delivered startup code).
- FR-26 says "default: Amazon Nova Lite" and names the text-model env var (a what/how violation)
  while the code has no default (returns a configuration error when unset) — correct to "no
  default; text model must be configured" and strip the env var name.
- Sweep the ~20 catalogued "what never how" violations (env vars, paths, CLI invocations,
  permission strings) flagged in the docs review pass.

### M-14 — ADR drift (residual, after partial fix)
- **ADR-008** (`adr-2026-06-02-async-concurrent-embedding.md`): still instructs configuring the
  deleted `ARTIFACT_CONCURRENCY` env var and promises startup rejection that no longer exists. Add
  a `revised` entry recording that per-request concurrency is now a **caller parameter**
  (`artifact_concurrency` on `write_artifacts`, exposed per M-10), not an env var, and there is no
  startup rejection for it. Populate the empty `revised:` frontmatter.
- **ADR-006** (`adr-2026-05-29-section-level-embedding.md`): section-key scheme states
  `{artifact_id}#slug`; the code and ADR-005 use `{s3_key}#slug`. Correct ADR-006 (with a `revised`
  entry) to match the code.
- (ADR-009 / PRD Known Limitations commit_refs behaviour already reconciled — verify only.)

### M-15 — Reference-doc drift
- `SERVER-REFERENCE.md`: (1) `cairn_studio` supporting vs non-supporting payloads are inverted —
  the `{write_prefix, artifacts}` structured dict goes to **non**-supporting hosts (confirm against
  `studio.py`); (2) remove the GDPR-rejected Google Fonts CSP origins; (3) remove the
  `audience: ["assistant"]` claim (`resources.py` only emits `audience=["user"]`); (4) add the
  `commit_refs` / `references` filters to the `list_artifacts` row; (5) remove the invalid
  `"Comment"` element(s) from the IAM policy so it pastes valid (AC-29).
- `README.md`: version says v0.2.0 → correct to the actual shipped version (0.5.0).
- `AGENTS.md`: repo table omits `constants.py`, `link_metadata.py` (was `link_commit.py`),
  `propose_commit_links.py`, `write_artifacts.py`, `migrate_artifacts.py`; and describes a
  "two-pane" Studio that shipped single-pane (view-switching). Regenerate the table from the actual
  `src/cairn_mcp/tools/` listing and correct the Studio description.
- `fastmcp[apps]` is documented as optional (PRD FR-47, `adr-2026-06-24-*`, plan.md) but is a hard
  base dependency in `pyproject.toml` — reconcile the docs to "required base dependency."
- Coordinate the M-13 FR-07 check count and the M-10 `artifact_concurrency` wording so all
  documents agree on the final delivered behaviour.

---

## Cluster E — Tests (M-16)

**Current:** the moto `query_vectors` extension filters with the production `matches_filter`
(circular — server-side filter semantics asserted nowhere); no integration tests exist for the
newest tools (`link_metadata`, `propose_commit_links`, `migrate_artifacts`, `write_artifacts`,
`cairn_studio`).
**Required:**
1. Add `@pytest.mark.integration` tests (real AWS, skipped without credentials, run under the
   isolated run-scoped prefix from `tests/integration/_isolation.py` — C-4) covering the five newest
   tools: at minimum a round-trip / happy-path per tool asserting real-AWS behaviour.
2. Address the circular simulation boundary: add integration assertions that pin the real
   server-side filter semantics the moto extension currently self-defines — `$eq` on array
   (list-membership), string `$gte`/range on ULIDs (used by `propose_commit_links`), the
   plain-equality shorthand, and behaviour at/over the filter-size and topK caps. These belong in
   integration (real AWS) since that is exactly what moto cannot faithfully simulate.
3. Do not weaken the existing unit suite; keep the moto extension as-is for unit speed but document
   that its fidelity is now backed by the new integration assertions.
**Acceptance:** integration tests for all five tools present and passing against real AWS (or
cleanly skipped without credentials); server-side filter-semantics assertions present in the
integration suite; unit suite + ruff + format + mypy remain clean. `log()`/report any coverage
intentionally deferred (do not silently cap).
