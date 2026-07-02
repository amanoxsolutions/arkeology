# Spec — Critical review fixes C-1, C-2, C-3, C-5

**Status:** frozen · **Source:** `.docs/reviews/review-2026-07-02-full-project-review.md`
**Testing approach:** TDD (write failing tests first, then implement)
**Scope:** four independent critical findings. C-4 is already resolved; do not touch it.

---

## C-1 — Semantic search ranking is broken (`returnDistance` never requested)

### Problem
`clients/vectors.py` builds the `query_vectors` request with `returnMetadata: True` but omits
`returnDistance` (AWS default `false`). Line ~148 then does `item.get("distance", 0.0)`, so every
result gets `score = 1.0 - 0.0 = 1.0`. Ranked semantic recall silently does not rank. The moto
extension in `tests/unit/conftest.py` always returns `distance`, masking this in every unit test.

### Required changes
1. Add `"returnDistance": True` to the `query_vectors` request kwargs in `clients/vectors.py`.
2. Treat a **missing** `distance` in a returned vector as an **error**, never as `0.0`/perfect
   similarity. Raise a clear exception (a `CairnError` subclass, or the closest existing typed
   error) rather than silently defaulting. `get_vectors` (non-query) is unaffected — this applies
   to the `query_vectors` scored path only.
3. Make the moto `query_vectors` extension in `tests/unit/conftest.py` honour the `returnDistance`
   flag: only include `distance` in each returned vector when `returnDistance` is truthy. This
   makes the simulation faithful to real AWS and would have caught the bug.
4. Since the production code now always requests distances, the server path is unaffected by (3);
   but any test that relies on scores must pass `returnDistance`. Verify the full unit suite stays
   green after the extension change.

### Acceptance criteria
- Unit test proving `query_vectors` sends `returnDistance: True` to the client.
- Unit test proving a returned vector **without** `distance` raises (not `score = 1.0`).
- Unit test proving scores are non-trivially ordered (distinct, correctly ranked) for a query with
  vectors of differing similarity — i.e. not all `1.0`.
- Integration test (`@pytest.mark.integration`) asserting search scores are non-trivially ordered
  against real AWS (guard so it is skipped without credentials, per existing integration patterns).

---

## C-2 — Stored XSS in Cairn Studio

### Problem
`src/cairn_mcp/static/cairn-studio.html` (~line 282) does
`contentArea.innerHTML = marked.parse(content)` with no sanitizer. `marked` passes raw HTML through.
Cross-scope tier-3 `shared` artifacts are readable by design, so a malicious/compromised foreign
team can store `<img src=x onerror=...>`; the script runs inside the Studio iframe where the
ext-apps SDK's `callServerTool` is reachable and can invoke `delete_artifact`,
`purge_archived(confirm=true)`, or `write_artifact` **in the reader's scope with the reader's
credentials**.

### Required changes
1. Sanitize before injecting: `contentArea.innerHTML = DOMPurify.sanitize(marked.parse(content))`.
   Load DOMPurify from jsdelivr (already an allowed CSP origin — confirm the existing CSP/allowed
   origins in the HTML and add the DOMPurify script tag consistently with how marked/mermaid are
   loaded). Pin the DOMPurify version explicitly.
2. Set mermaid `securityLevel: "strict"` explicitly in the mermaid initialize/config call.
3. Sanitize any **other** place raw artifact-derived strings reach `innerHTML` (e.g. list rows) —
   at minimum ensure the primary reader pane is safe; note any additional unescaped sinks found.

### Acceptance criteria
- The reader pane no longer executes injected event handlers / script from artifact content
  (payload such as `<img src=x onerror=...>` is neutralised by DOMPurify).
- Mermaid runs with `securityLevel: "strict"`.
- DOMPurify is loaded from an already-allowed CSP origin with a pinned version; the page still
  renders normal markdown + mermaid correctly.
- Manual verification note added to the dispatch report (this is browser JS — no unit-test harness;
  describe how the sanitisation was confirmed, e.g. by asserting the sanitized output string).

---

## C-3 — Deterministic ID scheme silently destroys artifacts on slug collision

### Problem
`artifact.py` `generate_artifact_id` / `_slugify`: (a) any title with no Latin/digit content
(CJK, Cyrillic, Arabic, emoji) slugifies to empty → falls back to the constant `"artifact"`, so all
such artifacts of one type share one key and each write silently destroys the previous; (b) 60-char
truncation collides distinct long titles; (c) punctuation collapse collides
`"Auth: Module Review"` / `"Auth module (review)"`. For a store whose purpose is never losing
memory, silent overwrite-by-collision is the worst failure mode.

### Frozen design decisions (operator-approved 2026-07-02)
1. **Always** append a short deterministic hash suffix derived from the **full original title** to
   the generated key. This guarantees distinct titles produce distinct keys, structurally
   eliminating the empty-slug, truncation, and punctuation-collapse collision classes.
   - New tier-2 format: `{type_slug}-{date}-{title_slug}-{hash}`
   - New tier-3 format: `{type_slug}-{title_slug}-{hash}`
   - `hash` = a short, stable hex digest of the full original title (e.g. first 8 hex chars of a
     SHA-256 of the raw title). Deterministic — same title always yields the same suffix. Must not
     use random/UUID (project rule). Choose the digest length to make collisions negligible while
     keeping IDs readable; document the choice in the docstring.
2. A write whose generated key **already exists** (true same type+date+title → identical key) is
   **rejected by default** with a `validation_error`, rather than silently overwriting.
3. The caller may pass an **explicit overwrite/replace flag** (default `False`) to intentionally
   update an existing artifact (preserves tier-3 living-doc updates and corrections). When the flag
   is set, the existing key is overwritten as today.

### Required changes
- `artifact.py`: update `generate_artifact_id` to append the full-title hash suffix for both tiers;
  update the docstring to reflect the new scheme. Keep `_slugify` fallback (`"artifact"`) — the
  hash suffix now disambiguates, but a readable slug portion is still desirable.
- `tools/write.py` (and the batch path `write_artifacts.py` if present): before writing, detect an
  existing artifact at the target key. If it exists and the overwrite flag is not set, return a
  `validation_error` explaining the collision and how to override. If the flag is set, proceed.
  Expose the overwrite/replace flag on the write tool's public signature and register it over MCP
  in `server.py`.
- Keep behaviour consistent between single and batch writes (per-descriptor overwrite flag or a
  batch-level flag — pick the option consistent with the existing `write_artifacts` shape and note
  the choice).
- Update code-adjacent docs that state the OLD scheme so they are not left false: the ID-scheme
  bullet(s) in `AGENTS.md`, the schema/description text in `resources.py` that tells agents content
  "cannot be updated", and ADR-005's normalisation-dedup note (add a `revised` entry rather than
  rewriting history). PRD FR-08/FR-13/CA-2 reconciliation is a **separate PM follow-up** — do not
  edit the PRD here; just flag it in the dispatch report.

### Acceptance criteria
- Distinct titles that previously collided (empty-slug/CJK pair, two >60-char titles differing only
  past char 60, `"Auth: Module Review"` vs `"Auth module (review)"`) now produce **distinct** keys.
- The hash suffix is deterministic: same title → same key across calls.
- A same-key write without the overwrite flag returns `validation_error` and does **not** mutate or
  delete the existing artifact or its vectors.
- A same-key write **with** the overwrite flag succeeds and updates the artifact.
- The overwrite flag is reachable by MCP callers (registered in `server.py`).
- Existing tests that assert the old key format are updated to the new format.

---

## C-5 — Cross-scope gate bypass in `check_synthesis_freshness`

### Problem
`tools/freshness.py` Step 6 (~lines 123-140) looks up each source artifact by bare
`{"artifact_id": {"$eq": source_id}}` with no scope/tier/visibility gate. It is the only read path
touching foreign vectors ungated: it reads and reports `date`/`status` (existence, archival state,
update recency) of foreign tier-2 or hidden artifacts that `read_artifact` would deny. AGENTS.md
lists "never bypass the cross-scope gate" as non-negotiable.

### Required changes
- Apply the same cross-scope gate used in `list.py` (lines 143-150) to each source metadata result
  in freshness Step 6. `own_scope = settings.write_prefix`;
  `read_prefixes = settings.read_prefixes_list`. Use the `startswith(scope + "/")` form (never bare
  `startswith`).
- For a source whose `artifact_id` is **not** own-scope and is **not** (foreign ∧ tier 3 ∧
  `visibility == "shared"`), classify it as **inaccessible**: treat it exactly as an unresolved
  source (`source_meta[source_id] = None`) so it surfaces as missing, and its `date`/`status` are
  never read or reported. Do not leak that the foreign artifact exists.

### Acceptance criteria
- Unit test: a synthesis referencing a foreign **tier-2** (or foreign hidden) source does **not**
  report that source's `date`/`status`; the gated-out source is classified inaccessible/missing.
- Unit test: a synthesis referencing a foreign **tier-3 `shared`** source is still read normally
  (the gate allows it, matching `list.py`).
- Own-scope sources continue to work unchanged.
- Scope check uses `scope + "/"`.

---

## Addendum — follow-ups from the independent review (2026-07-02, operator-approved)

The independent review confirmed C-1, C-2, C-5, and the C-3 core mechanism clean, and raised two
C-3-area items. Both decisions below are frozen.

### A-1 (from review MAJOR) — `migrate_artifacts` must SKIP existing artifacts, not overwrite them
**Problem:** `tools/migrate_artifacts.py` forwards `overwrite=True` unconditionally into
`write_artifacts`, reopening the silent-overwrite class C-3 exists to close, on the bulk path.

**Frozen decision — skip-existing:** bulk migration must **never overwrite** a pre-existing key.
- Do not pass `overwrite=True` from migration. Before writing each candidate, detect whether its
  generated key already exists; if it does, **skip** it (do not write, do not error) and record it.
- The migrate result must surface skipped items so the operator sees them — e.g. a
  `skipped_existing` list / count alongside the existing write results (pick a shape consistent
  with the current `migrate_artifacts` return dict; do not break existing keys).
- Re-running a migration over an already-imported corpus must be **idempotent and non-destructive**
  (every already-present artifact is skipped, nothing is overwritten or deleted).
- Update the `migrate_artifacts` tool docstring / MCP description to state the skip-existing
  behaviour explicitly (so the collision-guard exception is not hidden).
- Do NOT reintroduce a silent-overwrite path. If a genuine "update existing during migration" mode
  is ever wanted, that is a separate future feature — out of scope here.

**Acceptance criteria:**
- A migration run where some candidate keys already exist writes only the new ones and reports the
  rest as skipped; no existing S3 content or vectors are mutated.
- Re-running the same migration a second time writes nothing and skips everything (idempotent).
- Unit test covers the cross-call collision case (a pre-existing key from a prior write is skipped).

### A-2 (from review MAJOR/PLAUSIBLE) — make the collision guard atomic (close the TOCTOU race)
**Problem:** the C-3 guard is `head_object` (check) then `put_object` (act) — two concurrent
same-key `write_artifact` calls can both pass the check and the second silently overwrites the first.

**Frozen decision — atomic conditional write:** use S3 conditional `PutObject` with
`IfNoneMatch: "*"` so the existence check and the write are a single atomic operation.
- Extend `clients/s3.py` `put_object` to support a conditional-create mode (`IfNoneMatch: "*"`).
- In the write path, when `overwrite` is `False`, perform the conditional put; on a
  `PreconditionFailed` (HTTP 412) response, return the **same** `validation_error` the current
  check produces (include the `artifact_id`). When `overwrite` is `True`, put unconditionally.
- Ensure a failed conditional put does **not** proceed to write vectors (no partial write on a
  rejected collision).
- **moto caveat:** confirm moto supports `IfNoneMatch` on `PutObject` before writing tests
  (per the project testing convention). If moto does not support it, keep behaviour correct against
  real AWS and simulate/patch minimally for the unit test rather than dropping the guarantee —
  document whatever approach you take.
- The pre-write `head_object` check may remain as a friendly fast-path error, but the atomic
  conditional put is the authoritative guard.

**Acceptance criteria:**
- Unit test proving a conditional-create put against an existing key surfaces as `validation_error`
  and writes no vectors.
- `overwrite=True` still overwrites as before.
- Existing C-3 collision tests still pass.

## Cross-cutting requirements
- Follow TDD: write failing tests first for each finding, then implement.
- Mock AWS with moto + `FakeBedrockClient` per project testing conventions; do not add
  `set_credential_failure` fakes.
- Full quality gate must pass before hand-back:
  `uv run pytest tests/unit/ -q -m 'not integration'`, `uv run ruff check src/ tests/`,
  `uv run ruff format --check src/ tests/`, `uv run mypy src/`.
- Do not print to stdout anywhere; use `logging`.
- Report per-finding: what changed, files touched, tests added, and any follow-ups for the PM
  (notably the PRD FR-08/FR-13/CA-2 reconciliation from C-3).
