# Spec — Optimistic Concurrency, Reference-Field Semantics, and Response-Size Bounding

**Status:** frozen · **Source:** `docs/planning-artifacts/review-remediation-plan-2026-07-06.md`,
"Design decisions (✅ ALL DECIDED 2026-07-06)"
**Testing approach:** TDD (write failing tests first, then implement) per NFR-07
**Branch:** `review-followup-2026-07-06`
**Design record:** ADR-011 —
`docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md`; ADR-012 —
`docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md`; PRD
retrofits — `docs/planning-artifacts/prd.md` (FR-10, FR-19, FR-51, FR-53, FR-54, FR-55, NFR-02,
Known Limitations).

## Scope

The four decisions below are **operator-frozen (2026-07-06)** — do not re-litigate or offer
alternatives while implementing. This spec is what the developer clusters implement against; it
supersedes the "Recommendation" column of the design-decisions table in the remediation plan
(which recorded the *initial* recommendation before operator sign-off — the concurrency-control
decision in particular was initially recommended as "document only," then the operator chose the
stronger fix). Where a
"Required changes" item names a concrete file/symbol that does not yet exist, create it; where it
names an existing one, extend it — do not duplicate logic that already exists elsewhere in the
codebase (reuse `annotations.py`, `_search_helper.py`, `filter.py` per the project's existing
conventions).

**Cross-cutting requirements (every cluster below):**
- TDD: failing tests first, then implement.
- Mock AWS with moto + `FakeBedrockClient`; do not add hand-rolled credential-failure fakes — use
  `mocker.patch.object(..., side_effect=CredentialError(...))` and `mocker.spy` per AGENTS.md.
- Confirm any new S3 / S3 Vectors operation is moto-supported before testing it; self-mock
  minimally if not, following the existing `query_vectors` / annotation self-mock precedent in
  `tests/unit/conftest.py` — do not reimplement per-test.
- All tool public functions delegate to an `_inner` wrapped in `try/except Exception`.
- Never print to stdout; use `logging`.
- Full gate must pass before commit: `uv run pytest tests/unit/ -q -m 'not integration'`,
  `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run mypy src/`.
- Update code-adjacent docs (specs) that a change makes false — add a `revised` entry, do not
  rewrite history. The ADR and PRD updates for these four fixes are already done by this spec's
  companion architect pass; flag any further drift discovered during implementation to the
  tech-writer, do not silently re-edit ADRs/PRD from the developer cluster.
- Commit cadence and push policy follow the remediation plan's stated working method (commit per
  cluster, full gate before each commit, no push until asked).

---

## Optimistic-Concurrency Writes (ETag Compare-and-Swap) for Durable Read-Modify-Write Cycles

### Problem

Every merge-read-modify-write cycle on an artifact's durable link-field state —
`write.py`'s overwrite read-forward, `link_metadata.py`'s fetch-merge-reput, and
`archive_artifact`'s status re-PUT + link re-apply — issues **unconditional** `PutObject` /
`PutObjectAnnotation` / `DeleteObjectAnnotation` calls. Two callers racing on the same artifact can
silently drop each other's contribution: whichever call's read happens first computes a merge
against a state the other caller has since changed, and its unconditional write clobbers the newer
state with a stale merge. This is undocumented and untested today.

### Frozen decision

On every such cycle: capture the object's ETag on read (`head_object`); make the subsequent
`PutObject` conditional (`IfMatch=ETag₀`); use the object's *new* ETag (`ETag₁`, from that
`PutObject`'s response) as `ObjectIfMatch` on the `PutObjectAnnotation` / `DeleteObjectAnnotation`
calls that follow it. On `412 PreconditionFailed` from either conditional call: bounded CAS retry
(re-read → re-merge the caller's *original* supplied values into the fresh state → re-write
conditionally again), roughly 3 attempts, then return a structured `conflict` error. Vector writes
stay **unconditional** — no S3 Vectors CAS surface exists (`PutVectors` has no conditional
parameter, verified 2026-07-06) — vector metadata is the recoverable/derived copy, healed by
`reconcile_index` from the CAS-guarded annotations. **Accepted residual:** two simultaneous
`link_metadata` calls modifying the *same field* of the *same artifact* can still race past each
other, because writing an annotation does not change the object's ETag (annotations are
deliberately ETag-stable — decision 1 of ADR-011); different-field concurrent calls are already
safe. Full rationale: ADR-011, decision 6 ("Optimistic concurrency (ETag compare-and-swap) for
durable read-modify-write cycles").

### Required changes (files/symbols)

**Client interface and implementation:**
- `src/cairn_mcp/clients/interfaces.py` (`S3ClientInterface`):
  - `head_object` gains the current ETag in its return: reserve a capitalised `"ETag"` key in the
    returned dict (all real metadata keys are lowercase, so this cannot collide) so a single
    `head_object` round trip captures both the metadata and the CAS token needed for the
    subsequent conditional write — avoids a second round trip.
  - `put_object(..., if_match: str | None = None) -> str` — new optional parameter alongside the
    existing `if_none_match`; **the method now returns the new ETag** (boto3's `put_object`
    response already includes `"ETag"` — extract and return it). This is a signature change:
    update every call site (`write.py`, `archive.py`) and every fake/implementation.
  - `put_object_annotation(key, annotation_name, payload, *, if_match: str | None = None) -> None`
    and `delete_object_annotation(key, annotation_name, *, if_match: str | None = None) -> None` —
    new optional parameter, sent as `ObjectIfMatch` to the underlying boto3 call.
- `src/cairn_mcp/clients/s3.py` — implement the above: thread `IfMatch`/`ObjectIfMatch` kwargs
  through to boto3; on `botocore.exceptions.ClientError` with `Code == "PreconditionFailed"` raised
  by an `if_match`-guarded call (object or annotation), raise the new `ArtifactConflictError` (see
  below) — **distinct from** the existing `ArtifactCollisionError`, which means "conditional
  *create* rejected, an object already exists" (the `if_none_match` case); `ArtifactConflictError`
  means "conditional *update* rejected, someone else already changed this since we read it."
- `src/cairn_mcp/errors.py` — new `ArtifactConflictError(CairnError)`, carrying `key`, mirroring
  `ArtifactCollisionError`'s shape but with update-conflict wording.
- `src/cairn_mcp/constants.py` — new `ErrorCode.CONFLICT = "conflict"`.
- `src/cairn_mcp/annotations.py` — `apply_link_annotations(s3, key, *, commit_refs, references,
  if_match: str | None = None)` threads the CAS token through to both the put- and
  delete-annotation calls it makes internally.

**Write path / link_metadata / archive:**
- `src/cairn_mcp/tools/write.py` — restructure Steps 4a/4b into a bounded CAS retry loop
  (~3 attempts) around: capture ETag (from the `head_object` already performed at Step 4) → read
  current link fields (`read_current_link_fields`) → merge with the *original* caller-supplied
  `refs`/`references` (never with a previous retry attempt's already-merged output, to avoid
  compounding) → `PutObject(if_match=ETag₀)` → capture `ETag₁` from the response →
  `apply_link_annotations(if_match=ETag₁)`. On `ArtifactConflictError` from either call: re-read and
  retry the cycle; on exhaustion, return `{"error": ErrorCode.CONFLICT, "message": ..., "artifact_id":
  s3_key}` — never a raw exception, never a silent partial write.
- `src/cairn_mcp/tools/link_metadata.py` — wrap each `artifact_id`'s fetch → read-current →
  merge → `apply_link_annotations` → `put_vectors_batch` cycle in the same bounded CAS retry;
  each `artifact_id` in the loop retries independently (one artifact's conflict must not affect
  another's processing).
- `src/cairn_mcp/tools/archive.py` — the status-flip `PutObject` (Step 4) and the following
  annotation re-apply (Step 4b) need the same `if_match`/`ObjectIfMatch` guard and bounded retry
  (re-read status + link fields, re-flip) — on exhaustion, a structured `conflict` error, following
  the same failure-log-on-partial-progress discipline the tool's existing partial-archive handling
  already established.

**Test infrastructure (moto self-mock extension — required for this fix):**
- `tests/unit/conftest.py` — the existing annotation self-mock (`_annotation_put` /
  `_annotation_delete`, ~lines 178–195) must be extended to honour an `ObjectIfMatch` parameter:
  before applying the write, compare it against the *current* object's ETag (via
  `self.backend.get_object(bucket, key).etag`) and raise moto's own `PreconditionFailed` (imported
  from `moto.s3.exceptions`, already used natively by moto's own `If-Match` handling on the object
  body — see `moto/s3/responses.py` around the existing `if_match` checks) on a mismatch. **Before
  writing this**, determine how boto3 serialises the `ObjectIfMatch` member for
  `PutObjectAnnotation`/`DeleteObjectAnnotation` requests (a header vs. a query-string parameter) by
  inspecting the installed botocore's S3 service model (`s3-2006-03-01.normal.json` or equivalent) —
  do not guess; the existing self-mock reads other annotation parameters (`annotationName`) from
  `query`, but `ObjectIfMatch` may be a header like the native `If-Match` handling, in which case it
  must be read from `self.headers` instead. This determination is exactly the "moto/annotation
  self-mock work" flagged as needed before this fix can be tested.
- The regular object-body `IfMatch`/`IfNoneMatch` conditional-write behaviour needs **no** new
  self-mock — moto 5.2.2 already natively supports both (`moto/s3/responses.py`; confirmed
  2026-07-06), which is why the pre-existing `if_none_match=True` create-collision guard (A-2) works
  today without any conftest extension.
- Existing tests asserting `if_none_match=True/False` kwargs (`tests/unit/test_tools_write.py`,
  ~lines 416–470) need extending, not rewriting, to also assert the new `if_match` threading.

### Acceptance criteria

- A concurrent modification detected mid-cycle (simulated by mutating the object/annotations
  between a test's read and write, or via a `mocker` side-effect sequence that raises
  `ArtifactConflictError` once) causes a retry that re-reads and re-merges, eventually succeeding
  with a state that includes **both** callers' contributions — not one silently dropped.
- After exhausting retries (a persistent simulated conflict), the tool returns
  `{"error": "conflict", ...}` — never a raw exception, never a silent partial write, and no
  failure-log entry is falsely omitted if the object/annotation side was already durably written
  before the conflict was hit (mirror the existing partial-write discipline).
- Vector writes remain unconditional in every scenario — a test asserts `put_vectors_batch` /
  `put_vector` is called with no conditional parameter, regardless of CAS outcome on the object
  side.
- Two concurrent `link_metadata` calls touching **different** fields of the same artifact both
  succeed with no false-positive conflict/retry.
- The accepted residual is explicit and regression-proof: a test demonstrates that two concurrent
  `link_metadata` calls touching the **same** field are *not* required to detect each other (the
  test documents the gap rather than silently relying on it going undetected forever).
- Pre-existing `if_none_match` create-collision tests continue to pass unmodified in behaviour.

### Testing approach (TDD)

1. `tests/unit/conftest.py` (or a small dedicated moto-extension test) → extend the annotation
   self-mock's `ObjectIfMatch` handling — Red first: a test that writes an annotation with a stale
   `ObjectIfMatch` and expects a conflict.
2. `tests/unit/clients/test_s3_annotations.py` (or the client's existing test module) →
   `put_object(if_match=...)` returns the new ETag and raises `ArtifactConflictError` on mismatch;
   `put_object_annotation`/`delete_object_annotation(if_match=...)` same.
3. `tests/unit/test_tools_write.py` → CAS retry loop: one simulated conflict then success (assert
   re-read + re-merge occurred, final state includes both writers' values); persistent conflict →
   `conflict` error after the bounded attempt count, no partial/duplicated write.
4. `tests/unit/test_tools_link_metadata.py` → same CAS pattern, per-`artifact_id` independence,
   different-field concurrent safety, same-field residual documented.
5. `tests/unit/test_tools_archive.py` → CAS on the status-flip `PutObject` + annotation re-apply,
   consistent with the tool's existing partial-archive failure-log behaviour.

---

## Reference-Field Value Semantics (Replace vs Accrete)

### Problem

`write.py`'s overwrite read-forward (Step 4a) currently treats `references` exactly like
`commit_refs`: it reads the union of both durable stores and merges the caller's supplied values
into that union, so a stale or typo'd reference can never be shed by editing the frontmatter and
rewriting, and `references` conflates an audit trail (accretion is correct) with a claim about the
artifact's *current* outbound links (which must be able to shrink).

### Frozen decision

`references` becomes a plain **REPLACE**, mirroring the frontmatter: on every write it is set to
exactly the (resolved) list supplied with that call — additions, removals, and swaps in the
frontmatter are all reflected, and a write supplying no `references` **clears** the field
(operator-confirmed intended). `commit_refs` stays **UNION/accretive**, unchanged, because it is a
git audit trail with no frontmatter counterpart, backfilled by `link_metadata`. No separate removal
primitive is needed on `link_metadata` — removal is "edit the frontmatter, rewrite." This makes the
two fields asymmetric for write-time semantics only — the storage mechanism (S3 object annotations,
dual-write ordering, reconcile-from-union) is unaffected. Full rationale: ADR-011, decision 4
("Overwrite preservation for `commit_refs`; replace semantics for `references`") and its Consequences
"Authority model" entry, and ADR-012, decision D8 ("Mutability split by representation").

### Required changes (files/symbols)

- `src/cairn_mcp/tools/write.py` — Step 4a: split the read-forward. `commit_refs` keeps its
  existing union-merge against `read_current_link_fields`. For `references`, **drop the
  read-forward entirely**: `final_references = references` (exactly the value supplied to this
  call, including `[]`). `vector_metadata`'s `references` key is set/omitted from `final_references`
  the same way it is today; `apply_link_annotations` already deletes the annotation when its input
  list is empty, so passing `final_references` (possibly `[]`) through unchanged is sufficient — no
  change needed inside `annotations.py` for this fix.
  - Consider (not required, flagged for the implementer's judgement): since write.py's overwrite
    path no longer needs the `references` half of `read_current_link_fields`'s return value, a
    narrower helper that reads only `commit_refs` would save one small piece of redundant work; not
    required for correctness and left as an optional efficiency improvement.
  - Update the Step 4a inline comment/docstring, which currently states the merge applies to
    "the artifact's existing `commit_refs` and `references`" uniformly — this is no longer accurate
    for `references`.
- `src/cairn_mcp/tools/link_metadata.py` — **no behavioural change.** `link_metadata` remains the
  post-hoc, accretive backfill primitive for *both* fields (its whole purpose), unaffected by this
  fix. Add a code comment (not a behaviour change) noting the resulting interaction: a `references`
  value it adds to a tier 3 artifact can later be superseded by an ordinary overwriting write whose
  supplied `references` does not also carry that value, because that write replaces rather than
  merges. This is intentional (`references` mirrors current state), not a defect to fix here.
- `src/cairn_mcp/tools/archive.py` — **no change.** Archive's status-flip re-PUT has no
  caller-supplied `references` input to replace *from* — it exists purely to preserve whatever is
  currently stored across a re-PUT that would otherwise wipe annotations. It must continue to
  read-forward and re-apply **both** `commit_refs` and `references` unconditionally, exactly as
  today. This is called out explicitly to prevent an implementer from mistakenly propagating the
  write-path's replace-semantics into archive, which would silently wipe `references` on every
  archive operation — a real regression risk given how similar the two code paths look.
- `src/cairn_mcp/tools/reconcile.py` — **no change.** Reconcile restores whatever is durably stored
  for each field as the union of the annotation and existing vector-metadata copies, regardless of
  how that stored value came to be written; this is a repair operation, not write-time policy, and
  is unaffected.
- `src/cairn_mcp/artifact.py` — update the `references`/`commit_refs` field docstrings on
  `Artifact` to state the replace-vs-accrete distinction.
- `src/cairn_mcp/resources.py` — the artifact-schema resource text (read by agents at runtime,
  FR-18) should state that omitting `references` on a write clears it, so agents do not
  accidentally wipe it by re-writing without re-supplying the list.

### Acceptance criteria

- Given a tier 3 artifact with stored `references=["a-1"]` (no `commit_refs`), when overwritten
  with `references=["b-2"]`, the post-write state is exactly `references=["b-2"]` — not
  `["a-1","b-2"]`.
- Given the same artifact, when overwritten with `references` omitted (normalised to `[]` by the
  public wrapper), the post-write `references` is `[]` and the annotation is deleted.
- Given a tier 3 artifact with stored `commit_refs=["abc1234"]`, when overwritten with
  `commit_refs=["def5678"]`, the post-write state is `["abc1234","def5678"]` — union, unchanged
  regression behaviour.
- Given `link_metadata` backfills `references=["z-9"]` onto an artifact whose current `references`
  is `["a-1"]`, the immediate result is the union `["a-1","z-9"]` (link_metadata's own merge is
  unchanged); a subsequent ordinary overwrite supplying only `references=["a-1"]` then replaces the
  field back down to `["a-1"]`, dropping `z-9` — a test makes this interaction explicit and asserts
  it is expected, not a bug.
- `archive_artifact`'s status-flip continues to preserve both `commit_refs` and `references`
  unchanged across the re-PUT — a regression test guards against write-path semantics leaking into
  archive.
- Existing `commit_refs` union-merge tests (T47/T49) continue to pass unmodified.

### Testing approach (TDD)

1. `tests/unit/test_tools_write.py` — Red first: new/modified tests asserting REPLACE for
   `references` and unchanged UNION for `commit_refs` on an overwriting write.
2. `tests/unit/test_tools_link_metadata.py` — regression test confirming `link_metadata`'s merge
   mechanic for both fields is untouched.
3. `tests/unit/test_tools_archive.py` — regression test: archive's status-flip preserves
   `references` unconditionally (guards against the replace-semantics regression risk called out
   above).
4. `tests/unit/test_tools_write.py` (or a small cross-tool test) — the documented
   `link_metadata`-then-overwrite interaction: backfill → ordinary overwrite without that value →
   value dropped, asserting this matches the frozen decision rather than flagging as a bug.

---

## Cross-Scope Reference Filtering

### Problem

A `references` entry cannot itself *encode* an unresolvable/fabricated foreign identifier, since
entries only ever hold already-resolved `artifact_id`s — but `read_artifact` and `list_artifacts`
currently return a foreign-scope tier 3 shared artifact's `references` list unfiltered to any
reader, even when a listed target is not itself independently readable by that reader (e.g. a
hidden tier 2 artifact in the author's own scope). The reader never gets the target's *content*, but
the identifier string itself reveals that such an artifact exists and its naming pattern.

### Frozen decision

Filter `references` on cross-scope read (option 1): when `references` is returned to a foreign-scope
reader via `read_artifact` or `list_artifacts`, drop any entry the reader could not independently
read (i.e. not itself tier 3 shared). Filtering runs **only on cross-scope reads** — the own-scope
hot path is untouched. `list_artifacts` batches the tier/visibility lookup for every distinct
reference id appearing across the whole foreign-scope result set into a single query, to avoid an
N×M cost. A missing or unresolvable entry is treated as not-readable and stripped (fail safe). Full
rationale: ADR-012, "Cross-scope reference visibility" section.

### Required changes (files/symbols)

- **New shared helper** (propose `src/cairn_mcp/tools/_reference_filter.py`, or add to
  `_search_helper.py` alongside `find_referrers`/`build_scope_filter` — either is acceptable, do not
  duplicate the readability predicate in two places):
  - `resolve_readable_targets(vectors, settings, candidate_ids) -> set[str]` — given a set of
    candidate `artifact_id`s, returns the subset that are *independently readable* by a reader
    scoped as `settings` describes. **Reuse the exact same access predicate `read_artifact` already
    applies** (own-scope → always readable; foreign-scope → readable iff `tier == 3` and
    `visibility == "shared"`) rather than re-deriving a parallel rule that could drift from it. A
    single batched `list_vectors_by_metadata` query (an `$in`-style filter on `artifact_id`,
    mirroring the existing `{"scope": {"$in": read_prefixes}}` pattern already used in
    `build_scope_filter`) fetches tier/visibility for the whole candidate set in one round trip;
    build an in-process `id -> (tier, visibility)` map from the results and evaluate the predicate
    per id. An id with no match in the results (deleted, never existed) is excluded from the
    returned set (not-readable, fail safe).
  - Decide and document (own-scope note): if a `references` target on a foreign-scope artifact
    happens to resolve into the *reader's own* scope, it should be treated as readable — the
    predicate above should reduce to "would `read_artifact(target_id)` succeed for this reader,"
    which already covers the own-scope-always-readable case naturally.
- `src/cairn_mcp/tools/read.py` — Step 4: when the read is cross-scope (the same condition already
  computed at Step 2 — `foreign_prefix is not None and not own_scope`), pass the fetched
  `references` list through `resolve_readable_targets` before it enters the response dict; own-scope
  reads bypass this entirely and return `references` exactly as stored, as today.
- `src/cairn_mcp/tools/list.py` — Step 6: for each result classified as foreign-scope at Step 5,
  its `references_val` must be filtered the same way. To avoid N×M round trips across a whole result
  page, collect the full set of distinct reference ids appearing across **all** foreign-scope
  entries in one pass over `items` *before* building the final `artifacts` list, issue **one**
  `resolve_readable_targets` call for that combined set, then filter each foreign entry's
  `references_val` against the returned set when assembling its result dict. Own-scope entries are
  never filtered.

### Acceptance criteria

- Given a foreign-scope tier 3 shared artifact `T` whose `references` includes a hidden tier 2
  target `H` in `T`'s own (foreign) scope, when a reader in a different scope calls
  `read_artifact(T)`, `H` is absent from the returned `references`.
- Given `T` also references a tier 3 shared artifact `S`, `S` is present in the cross-scope read
  (independently readable).
- Given a reader calls `read_artifact` on an artifact in its **own** scope whose `references`
  includes a hidden own-scope target, that target is present, unfiltered (own-scope reads are never
  filtered).
- Given a `references` entry names a target that no longer exists, it is stripped on a cross-scope
  read (fail-safe default).
- Given `list_artifacts` returns several foreign-scope tier 3 shared entries with different
  `references` lists, filtering is applied per entry using no more than **one** additional batched
  vector-client query for the whole page — asserted via `mocker.spy` call count — regardless of how
  many foreign entries or distinct reference ids are present.
- Own-scope entries returned by `list_artifacts` are never filtered.

### Testing approach (TDD)

1. New/extended unit test for `resolve_readable_targets` (wherever it lands) — Red first: own-scope
   always readable, foreign tier-3-shared readable, foreign tier-2/hidden not readable, missing
   target not readable.
2. `tests/unit/test_tools_read.py` — cross-scope filtering present/stripped/missing-target cases;
   own-scope unaffected regression case.
3. `tests/unit/test_tools_list.py` — batched filtering across multiple foreign-scope entries; single
   batched-query call-count assertion; own-scope entries unfiltered regression case.

---

## Synthesise Response-Size Budget

### Problem

`synthesise_artifacts`'s artifact-count ceiling (100) bounds the number of full-content results but
not their total size — a query matching 100 unusually large artifacts can produce an unbounded
response, which contradicts the bounded-payload principle (NFR-02). The default of 10 is fine; the
ceiling alone is not a sufficient guard.

### Frozen decision

Add a configurable response-size (byte) budget: assemble results in rank order and stop before
adding any result that would push the response past the budget, then signal `truncated: true` plus
the count actually included. Keep the count ceiling as a cheap secondary guard, not the primary
bound. Default budget generous enough that a normal ~10-artifact synthesis never trips it.

**Default: 1,000,000 bytes (1 MB), measured as the UTF-8-encoded byte length of each result's
`content` field (operator-confirmed 2026-07-06; overridable via config).** Reasoning:

- This repository's own artifact corpus (ADRs, specs, code reviews, session summaries) runs
  roughly 2–20 KB of markdown per document; long specs/ADRs can reach 30–50 KB.
- At the default `top_k=10`, even 10 of the largest observed documents (~50 KB each) sum to ~500 KB
  — comfortably under 1 MB, so a default-sized synthesis essentially never trips the budget,
  matching the frozen requirement.
- At the ceiling (`top_k=100`), unmodified content could reach many megabytes unbounded; a 1 MB
  budget caps that firmly while still allowing a meaningfully sized batch (roughly 15–30
  typical-sized artifacts, fewer if unusually long ones rank highly) before truncating.
- 1 MB of raw UTF-8 markdown is roughly 200–250K tokens by a rough 4–5-characters-per-token
  heuristic — within the context-window budget of current-generation models with headroom left for
  the query, tool-call overhead, and the agent's own synthesis output, without assuming a specific
  model or provider.
- It is a round, easily-overridden number.
- The value was an estimate rather than a measurement against a real corpus; operator-confirmed as
  the default (2026-07-06), overridable per deployment if documents are consistently larger.

### Required changes (files/symbols)

- `src/cairn_mcp/config.py` — new `Settings` field (e.g. `SYNTHESISE_MAX_RESPONSE_BYTES`) with
  `Field(default=1_000_000, ge=1, description=...)` and a matching snake_case property, following
  the exact existing pattern of `SEARCH_FETCH_TOP_K` / `EMBED_MAX_SECTION_LENGTH`.
- `src/cairn_mcp/tools/synthesise.py` — Step 6 becomes budget-aware: track a running total of
  assembled response bytes as candidates (already rank-ordered by the search loop) are processed;
  before appending each candidate, compute its marginal contribution and check whether adding it
  would exceed `settings.synthesise_max_response_bytes`; if so, **stop assembling** (do not fetch or
  include this or any further candidate), and add `truncated: true` plus an included-count field to
  the response; otherwise fetch, append, and continue. The existing `clamped`/`effective_top_k`
  fields (from the count-ceiling clamp) are unaffected and may co-occur with the new fields if both
  conditions triggered independently.
- Response shape (operator-confirmed 2026-07-06): `{"artifacts": [...], "truncated": true,
  "included": N}` — the `truncated` and `included` fields present only when truncation actually
  occurred, mirroring the existing optional-field pattern used by `clamped`/`effective_top_k`.
- Measurement method (operator-confirmed 2026-07-06): the UTF-8 byte length of each result's
  `content` field only — the dominant, budget-driving contributor (per-entry metadata is small
  fixed overhead); document it in a code comment.
- `docs/specs/p3-t16-synthesise-artifacts.md` — flag for a tech-writer `revised` entry noting the
  new byte-budget behaviour (its Story 3 currently describes only the count ceiling); not this
  cluster's job to edit.
- `src/cairn_mcp/resources.py` — if the schema/tool-usage resource text mentions the synthesise
  ceiling, add a one-line mention of the size budget for agent-facing clarity (FR-18).

### Acceptance criteria

- Given `top_k=10` and normal-sized artifacts well under the budget, the response is unaffected —
  no `truncated` field, all matching results included, existing behaviour unchanged byte-for-byte.
- Given a query whose top-ranked results include artifacts large enough that including the next one
  would exceed the configured budget, assembly stops before that artifact; the response includes
  `truncated: true` and an included-count matching the actual number of results returned.
- Given the byte budget is configured unusually small, the count ceiling (100) still applies as an
  upper bound regardless — both guards active simultaneously, byte budget typically binding first.
- Given a `CredentialError` during a content fetch, the existing structured-error behaviour is
  unaffected by the new budget logic (the budget check runs only on already-successfully-fetched
  content).
- The single-oversized-first-result edge case (the very first ranked candidate alone exceeds the
  budget): the one result is **included anyway** (never return zero results for a single relevant
  oversized hit), with `truncated: true` set — operator-confirmed 2026-07-06.

### Testing approach (TDD)

1. `tests/unit/test_tools_synthesise.py` — Red first: byte budget stops assembly and sets
   `truncated` + included-count; a generously-configured budget leaves normal synthesis unaffected
   (regression); count ceiling and byte budget both exercised together; the single-oversized-result
   edge case per the confirmed resolution.
2. Settings validation test (wherever `Settings` fields are tested) — new field's `ge=1` bound and
   default value.
3. Any existing integration test for `synthesise_artifacts` — confirm the new optional response
   fields are absent/present as expected; real oversized content is not required for integration
   coverage.

### Resolved decisions (operator-confirmed 2026-07-06)

All four previously-open CA-5 questions are now frozen:
- **Default budget:** 1,000,000 bytes (1 MB), overridable via config.
- **Response field names:** `truncated: true` + `included: N` (present only when truncation occurred).
- **Byte measurement:** the `content` field only (UTF-8 byte length).
- **Oversized-first-result:** include the single result anyway, with `truncated: true` set.
