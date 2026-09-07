---
type: Contract
title: arkeology.tools.reconcile
description: "The reconcile_index MCP tool — the repair path: replays the partial-write failure log, re-indexes S3 objects absent from the vector index, prunes dangling vectors, and gives up loudly on entries that cannot be fixed."
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p5-t21-reconciliation-tool.md
  - docs/specs/p9-t32-reconcile-phase3-dangling-vectors.md
  - docs/specs/p12-t48-reconcile-from-annotations.md
  - docs/specs/p12-t62-bounded-reconcile-retry.md
  - docs/specs/p12-t67-orphan-vector-retry-and-selfheal.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "developer"
  date: 2026-09-07
---

# arkeology.tools.reconcile

## Scope

The repair boundary. Every other tool's partial-failure mode is designed on the assumption that
this one can finish the job, which makes its rebuild fidelity a system-wide invariant rather than a
local one.

## Symbols

### reconcile_index

```python
async def reconcile_index(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Every failure is a returned dict carrying an `"error"` key.

- `credential_error` — an AWS call raised `CredentialError`.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- S3 is the rebuild source of record. The entire vector index can be reconstructed from S3 objects
  plus their annotations; the reverse is not possible, and no reconcile path may assume otherwise.
- The rebuild is **lossless for link fields**: `commit_refs` and `references` are read from the
  durable annotation store and re-applied to rebuilt vector metadata. A rebuild that read only
  vector metadata would erase the annotation-only `references` copy entirely.
- Only the **capped** `commit_refs` value is placed into rebuilt vector metadata; the annotation
  copy is left complete and uncapped.
- Re-embedding uses the same shared `_section_pipeline` as `write_artifact` — same minimum-length
  filter, same maximum-sections cap, same per-section truncation. Bypassing it would re-submit a
  section that was truncated at write time at full length, failing the embedding input limit
  forever on every replay.
- Metadata budgets are checked before the vector write, exactly as on the write path. Without it
  the repair tool can recreate the very oversize write it exists to fix.
- The automatic retry loop is **bounded**. An entry reaching the maximum attempt count is no longer
  auto-retried and is surfaced in `stuck_failures`, so a genuinely unfixable entry fails loudly
  once rather than retrying forever.
- A failure-log entry whose S3 object **no longer exists** is **resolved, not retried** — it is pruned
  from the log and reported in `reconciled` with the `failure_log_obsolete` source. There is nothing
  left to reconcile: the artifact is gone, and Phase 3 already prunes any vectors it left behind. This
  is deliberately not routed through the attempt counter, because `stuck_failures` asks an operator to
  fix an underlying cause and a deleted artifact presents none. Classifying it `failed` instead would
  breach the bounded-retry invariant above: `failed` entries are retained in the rewritten log and do
  not increment the counter, so such an entry would be replayed and re-reported on every run forever
  and `failure_log_entries_after` would never drop. Safety rests on three properties that must hold
  together — the absence check distinguishes a genuine 404 from a transient or credential failure,
  which keep their existing counter-bearing paths; the dangling-vector prune re-checks existence at
  prune time, so it cannot race a concurrent write; and if the object reappears after the entry is
  pruned, the orphan scan re-indexes any S3 key carrying zero vectors on the following run. Weakening
  any one of the three invalidates this classification.
- **An entry's `failure_step` names the step that failed, and the set of values is open.** Nothing
  in this tool branches on it: an entry's kind is derived from whether it carries `orphan_keys`, and
  its identity for pruning is the whole entry as read back from disk. A producer may therefore split
  one step name into several without a schema change here, and an entry written before such a split
  keeps its own value through both the replay and the prune, because both sides read it from the same
  bytes. The field exists for the operator reading the log to learn why a given artifact is in it, so
  a producer that can tell its steps apart is expected to stamp them apart rather than fix one value
  standing for all of them.
- A failure-log entry may carry two **optional** link-field copies, `commit_refs` and `references`,
  recorded by whichever producer wrote it when a step failed after the object had already been
  re-PUT. Phase 1 re-applies them before re-indexing, so the rebuilt vector metadata is derived from
  the restored value. This is the only path by which they can come back: the re-PUT
  cleared the annotation copy, `references` is in vector metadata nowhere, and the vector
  `commit_refs` copy is capped, so every entry past that cap would otherwise be lost permanently.
- An entry carrying either copy also records, as a third **optional** field, the artifact's
  `last_edited_ulid` as it stood when the failure was recorded. It is the supersession token the
  `references` restore rule below is decided on, and it is the entry's only purpose — nothing else
  reads it. See `s3.artifact` for the field itself.
- **Absence of either link field means "nothing to restore", never "clear the field".** Entries
  written before the fields existed carry neither and must replay unchanged, leaving the object's
  annotations exactly as they are.
- `commit_refs` is restored as the **union** of the entry's copy and the artifact's current
  annotation value, unconditionally and with no supersession test. It is an append-only audit trail
  on which removal is not a supported operation, so a value re-added between the failure and the
  replay lives only in the current copy and the union is the only way to keep both.
- `references` is restored **only while the entry's recorded `last_edited_ulid` still equals the
  artifact's current one.** When the two differ, the entry's copy is discarded and the current
  annotation value is left exactly as it stands. Every write replaces `references` outright (see
  `arkeology.tools.write`), so a differing ULID means a later successful write has already
  established what the field says, and restoring the entry's copy over it would resurrect
  references that write deliberately removed. Unioning here — the rule this replaces — weighed
  additions only and contradicted the replace semantics on every removal.
- The supersession token is `last_edited_ulid`, never the object's ETag. The ULID changes on exactly
  the operation whose `references` semantics are replacement — a `write_artifact` write — and is
  deliberately left untouched by an archive status flip, a `link_metadata` backfill, and a reconcile
  re-index, none of which replace `references`. An ETag tracks bytes rather than writes: an
  overwriting write that changes only `references` and leaves the body byte-identical carries the
  **same** ETag, so an ETag comparison would miss precisely the supersession this rule exists to
  detect. How an ETag is derived at all also varies with bucket encryption, making it
  deployment-dependent where the ULID is not.
- An entry recording **no** `last_edited_ulid` — one written before the token existed, or one for an
  artifact that carries none — restores `references` by union, exactly as entries did before. An
  absent token is missing evidence of supersession, not evidence of it, and discarding on it would
  destroy the only surviving copy of a value no later write had touched.
- The rebuilt vector metadata's `commit_refs` is derived from the artifact's annotation, its sole
  source of truth, never carried over from the vector being replaced. A failed annotation read fails
  that artifact — it is reported under `failed` and no vectors are written for it — because rebuilding
  from a spurious empty would write that emptiness over the artifact's real link fields. The run
  itself still completes; the failure is per artifact.
- Failure-log entries are classified by their own shape — the presence of `orphan_keys` marks the
  cheap orphan-cleanup kind — so a reindex-kind and an orphan-cleanup-kind entry for the same
  artifact are processed and pruned independently.
- **Several entries sharing one `(artifact_id, kind)` are resolved together, never first-one-wins.**
  Consecutive failed overwrites of one artifact each record the link-field copy they were applying,
  and each re-PUT cleared what the previous entry had recorded, so no single entry holds the whole
  value and the annotations hold none of it. The replay therefore restores the **union of every such
  entry's `commit_refs`** and, for `references`, the **union of every tokened entry whose recorded
  `last_edited_ulid` still equals the artifact's current one**, **plus the union of every tokenless
  entry's copy** with no supersession test, exactly as a lone tokenless
  entry restores. A group may mix the two: a tokenless entry — one `link_metadata` or
  `archive_artifact` recorded for an artifact carrying no token — alongside a tokened one a failed
  overwrite recorded. The tokened half answers "has a later write superseded this?"; the tokenless
  half cannot be asked that question (`s3.artifact` states when the token is absent) and holds the
  only surviving copy of a value no later write touched, so it is never discarded on the strength of
  a sibling's token — dropping it would be the
  same loss the tokenless-entry rule above forbids.
  **Tokened siblings recording the *same* token union with each other, and a sibling recording a
  different one never suppresses them.** Equal tokens mean no write intervened between those
  entries, so there is no supersession between them and the argument that makes tokenless entries
  union applies verbatim; resolving the tie by read order would discard the only copy of the loser's
  `references`. This is the ordinary shape rather than an exotic one: only `write_artifact` mints a
  new token, while `link_metadata` records the object's existing one and `archive_artifact`
  preserves it across the status re-PUT that clears the annotations, so a run of those failures
  leaves several entries all carrying one token. A recorded token *above* the artifact's current one
  is a clock skew across hosts or a hand-edited log rather than evidence of a later write, so the
  equality test discards it like any other mismatch and it cannot decide the fate of a sibling whose
  token *is* current. The two fields are treated differently on purpose
  and must not be collapsed into one rule: `commit_refs` is an append-only audit trail whose merge is
  union (see `arkeology.tools.write`), so every entry's contribution is real and only the union keeps
  them all; `references` is replaced outright by every write (ADR-011 decision 4), so a tokened entry
  the current token no longer matches has been superseded, and unioning it in would resurrect links
  the artifact had already dropped. The group's other properties fold the same
  way: its retry budget is the **highest** `reconcile_attempts` any member carries, so whether an
  artifact reaches `stuck_failures` does not depend on which line an appender happened to write
  first; an orphan-cleanup group's recorded keys are the **union** of every member's
  `orphan_keys`, because two failed cleanups may have recorded different stale sets and pruning the
  group as resolved while deleting only one set would leak the other with no record left that it
  should go; and the descriptive fields a group reports — the `reason` and `title` on its
  `stuck_failures` entry, and the `title` on the `reconciled` entry of an orphan-cleanup or
  obsolete-object resolution — are the **newest member's** by recorded timestamp. `reason` is
  precisely the field that differs between members, so taking it from whichever line an appender
  happened to write first would report the oldest failure of a group whose budget the newest member
  exhausted.
  All entries sharing the key resolve and are pruned together; an entry restored to a
  partially different value than it recorded is still resolved, because the combined value is what
  the artifact should hold.
- **A re-index replaces the artifact's vector set; it never merges into it.** After a re-index the
  vectors keyed under the artifact — `{artifact_id}` and every `{artifact_id}#{slug}` — are exactly
  the rebuilt set. The order is fixed: the rebuilt vectors are written first; **then** the
  artifact's current vector keys are listed; and only the keys absent from the rebuilt set in
  **that** listing are deleted. The difference is always computed from a listing taken after the
  write, never before it — a listing taken before the write would prune a key a concurrent writer
  re-created in the window, re-opening the defect the orphan-cleanup replay rule below closes. A
  listed key whose vector's `last_edited_ulid` is **strictly newer** than the token this re-index
  wrote belongs to a later write and is not deleted either; a key carrying the **same** token but
  absent from the rebuilt set is deleted — it was written under the current version but is not one
  of its slugs, which two runs under different section caps can produce under one ULID. This is
  where the two prune paths part, and **not** over which token they compare against: both compare
  against the object's current one — this rebuild reads it from the same `head_object` metadata and
  writes it into the vectors it creates, so "the token it wrote itself" and "the object's current
  token" are one value. They part on the *other* side of the test. The re-index has just rebuilt the
  artifact's entire key set, so a same-token key outside that set is provably not a slug of the
  current content and is stale. The orphan-cleanup replay has only a key list some earlier write
  recorded, and no knowledge of what the current content's slugs are, so a same-token key there must
  be assumed live (see that rule); unifying the two breaks one of them.
  When the object carries no token (`s3.artifact` states when) the rebuild has nothing to order
  against, so the newer-token exemption does not apply and every listed key absent from the rebuilt
  set is deleted — the same boundary decision the orphan-cleanup replay makes for a tokenless object.
  So a section slug that
  no longer exists in the current content does not survive as a
  searchable vector, while a repaired artifact is never left with zero vectors mid-run. Without the
  prune a repaired artifact is neither an orphan nor dangling, so no later pass would ever remove the
  stale sections and only a manual overwrite could. `write_artifact` already prunes in this order.
  **A failed prune does not fail the re-index.** By the time the delete runs the rebuilt vectors are
  written and the artifact is correctly indexed; only the removal of leftovers failed. The re-index
  therefore resolves as normal and the keys that could not be deleted are recorded in a new
  failure-log entry carrying `orphan_keys` with `failure_step` `orphan_vector_cleanup` — the
  orphan-cleanup kind, whose replay on the next run is the cheap delete, no re-embedding — as
  `write_artifact` records on the same failure. The two are not identical: `write_artifact` retries
  the delete before recording, and this records on the first transient failure. Deliberately so —
  reconcile is itself the retry, so the next run's cheap delete is the retry a write path has to
  perform inline because it has no later run to defer to. Failing the re-index instead would keep a
  budget-consuming entry that can reach `stuck_failures` for a correctly indexed artifact and
  re-embed every section on each retry to redo work that already landed; resolving with only a log
  line would prune the record and leave the stale vectors permanently, since an artifact with vectors
  is neither an orphan nor dangling. A failure of the *listing* itself still fails the re-index:
  without the listing there are no keys to record, and the re-index retry is the only path that
  re-derives them. **A `CredentialError` from the delete is not a failed prune and is not recorded**
  — it propagates and abandons the whole run, as it does from every other phase of this tool.
  Recording it would report per-artifact success and append one spurious entry per artifact for the
  duration of a credential outage, of keys that were never proven stale. **A failure of the *append*
  itself does not invert the re-index either**: the artifact is indexed, so reporting it `failed`
  would be untrue and would re-embed it next run to fix something re-embedding cannot fix, and the
  orphan scan would never revisit it in any case. The stale keys are then leaked, and one logged
  error naming both failures and the leaked keys is their only remaining record — the one outcome
  the paragraph above rejects, admitted here only because it requires the failure log to be
  unwritable, which is also what defeats every alternative to it. The appended entry is not one
  this run read, so the end-of-run rewrite passes it through, and on the next run it is grouped
  with any orphan-cleanup entry already recorded for the
  artifact under the grouping rule above. The log cannot grow without bound from this: the appended
  entry resolves on the first run whose delete succeeds, and a re-index that keeps failing its prune
  is bounded by its own entry's retry budget. One case does accumulate, bounded by events rather
  than by runs: once an orphan-cleanup group has reached `CAS_MAX_ATTEMPTS`, a freshly appended
  entry joins that group, inherits the group's exhausted budget under the highest-counter rule
  above, and goes straight to `stuck_already` without ever being attempted — so every later
  re-index whose prune fails adds one more never-attempted entry. That is contract-compliant and
  loud rather than silent: the group is reported in `stuck_failures` on every run with the union of
  every member's `orphan_keys`, which is exactly the state an operator is being asked to fix.
  Accepted cost: on every re-index, in both the failure-log replay and the orphan scan, one
  per-artifact vector listing **plus** one `get_vectors` over the keys it returns — the same-token
  test needs each leftover vector's metadata, where `write_artifact`'s own prune deletes every
  listed key and so lists only; and, in the orphan-cleanup replay, one `head_object` plus the same
  listing-and-fetch pair per entry, to learn the reference token and the vectors it decides over.
- **An absent `visibility` rebuilds as `"hidden"`, never `"shared"`.** When the S3 object metadata
  carries no `visibility`, the rebuilt vector metadata gets `"hidden"`. `visibility` is one of the
  two fields the cross-scope gate keys on, and the gate has two forms that must agree: the in-process
  predicate `is_cross_scope_readable` in `_scope.py` reads an absent S3 value as `""` and denies, so
  the server-side filter form must not be handed a value that admits the same artifact. Defaulting to
  `"shared"` here would let `search_artifacts` and `list_artifacts` return cross-scope an artifact
  that `read_artifact` then refuses. Failing closed is the only default consistent with both forms;
  the S3 object is left as it is (see `s3.artifact`), and no response field reports the substitution.
- Dangling vectors, whose S3 object no longer exists, are pruned rather than re-indexed.
- **An orphan-cleanup replay re-checks each recorded key at prune time, as the dangling-vector
  prune re-checks existence at prune time.** A recorded `orphan_keys` list describes what was stale
  when the entry was written, not what is stale now: a later successful overwrite may have
  re-created one of the slugs, and that vector is live. Before deleting, the replay reads the
  object's current `last_edited_ulid` as its reference token and lists the artifact's current
  vectors. Presence in the index alone cannot tell a stale key from a re-created one — both are
  present — so the token decides: a recorded key is deleted only when its vector's
  `last_edited_ulid` is **strictly older** than the reference token, or the key is absent from the
  index; a key whose token is equal to or newer than the reference is spared. Equal means the
  vector was written under the content version the artifact holds now. Newer means a write landed
  between the token read and the prune and re-created the key, and deleting on an equals-only test
  would destroy exactly the live vector this rule exists to protect. ULIDs sort lexicographically by
  generation time, so the comparison is a plain string ordering, as in the re-index prune above —
  and both rules compare against the same value, the object's current token, so the equal case does
  not part on that. It parts on what each side knows about the key set. The re-index has just
  rebuilt the artifact's whole key set and can therefore prove an equal-token leftover is not one of
  the current content's slugs. This replay knows only a key list an earlier write recorded as stale,
  and cannot tell a key that is still stale from one a later successful overwrite re-created under
  the same token, so an equal token is read as live and the key is spared. An artifact whose object
  no longer exists has no live vectors, so all its recorded keys are deleted, as before; an object
  that carries no token (`s3.artifact` states when) offers nothing for a vector to match, so its
  recorded keys are deleted as recorded. The `reconciled` entry's `orphan_keys_deleted` counts the
  keys actually deleted, so a recorded key spared as live shows as the difference from the entry's
  recorded list; no separate counter reports it.
- The orphan scan indexes **artifacts only**. A candidate key is re-indexed only when its S3 object
  metadata carries a `type` that is a member of `ARTIFACT_TYPES`; anything else under the write
  prefix — a manual upload, a `.DS_Store`, a partial multipart artefact — is skipped and reported.
  The discriminator is the object's metadata, not its key shape: an artifact id is deterministic and
  begins with a type slug, but title slugs and the configurable file extension make a key-shape match
  brittle, and a stray file can begin with a type slug by coincidence. Metadata is also free here —
  the scan already fetches it, so the check happens before any embedding or index write.
- Accepted trade-off: an artifact whose `type` metadata is missing or corrupt is skipped rather than
  indexed with an empty type. Such an artifact is already broken — `read_artifact` reports a blank
  type for it — and reporting it as unrecognisable is more honest than silently adding a typeless,
  titleless entry that then surfaces in searches and listings. `skipped_non_artifacts` is what keeps
  that case recoverable.

**Preconditions**

- All four clients required; re-indexing embeds, so `bedrock` is mandatory.
- Safe to run at any time, including concurrently with normal writes — it is idempotent with
  respect to already-consistent artifacts.

**Postconditions**

- Every `reconciled` entry carries a `source` discriminator naming which mechanism dealt with it:
  `failure_log` (replayed from the failure log and re-indexed), `orphan_scan` (an S3 key found with no
  vectors and re-indexed), `orphan_vector_cleanup` (leftover orphan vector keys deleted, nothing
  re-indexed), or `failure_log_obsolete` (entry dropped because its artifact no longer exists, nothing
  re-indexed). `reconciled` therefore means "this entry was dealt with", not "this artifact was
  re-indexed" — two of the four sources index nothing, and a consumer counting re-index work must
  filter on `source` rather than on the list's length.

- Returns `reconciled`, `failed`, `failure_log_entries_before`, `failure_log_entries_after`,
  `orphans_found`, `total_reconciled`, `dangling_artifacts_found`, `dangling_vectors_pruned`, and
  `dangling_artifacts`.
- `stuck_failures` is present **only when non-empty**, so its presence is itself the signal that
  manual intervention is required.
- `skipped_non_artifacts` — the own-scope keys the orphan scan found without vectors and declined to
  index, per the artifacts-only invariant above — is present **only when non-empty**, on the same
  terms as `stuck_failures`. Probe keys are excluded from the scan entirely and never appear in it.
  A skipped key does **not** count towards `orphans_found`, which counts artifact orphans needing
  re-index rather than every candidate key the scan examined. Probe keys are already excluded before
  that count for the same reason, and the two categories of "not an artifact" must agree: a permanent
  stray object would otherwise hold `orphans_found` at a non-zero floor on every future run, so an
  operator watching it trend to zero would never see it arrive. Strays are reported in
  `skipped_non_artifacts` instead, where their persistence is the point rather than a false signal.
- A successfully reconciled entry is pruned from the failure log. `failure_log_entries_after`
  counts what the log holds after the end-of-run rewrite, which re-reads it under the appender's
  lock and removes only the entries this run resolved — so an entry another writer appended while
  the run was in flight is retained and counted, and `failure_log_entries_after` is not guaranteed
  to be lower than `failure_log_entries_before` when that happens.
- An artifact rejected by the budget check is not silently retried into the same failure; it lands
  in `failed` or `stuck_failures`.
