# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Breaking:** the `warning` family of response keys is unified — one name per meaning,
  each named for what its value is. `archive_artifact` returned the own-scope referrer id
  list under `warning` and `delete_artifact` returned the identical list under `warnings`;
  both now return it under `referrers`. `write_artifacts` and `migrate_artifacts` returned
  the `artifact_concurrency` clamp message under `warning`, a string sharing a key name with
  a list; both now return it under `concurrency_warning`. `warning` and `warnings` no longer
  appear in any tool response, and no alias is emitted. A caller reading `warning` or
  `warnings` must read `referrers` (archive, delete) or `concurrency_warning`
  (write_artifacts, migrate_artifacts) instead; `warning_message`, the human-readable text
  accompanying `referrers`, is unchanged in both name and behaviour
- **Breaking:** an unavailable annotation store now surfaces as a single error code,
  `annotation_unavailable`, from every tool that can meet the condition — `read_artifact`,
  `list_artifacts`, `propose_commit_links`, `link_metadata`, `write_artifact` and
  `archive_artifact`. The first three returned `internal_error` and `write_artifact` returned
  `partial_write`, so one condition — post-setup IAM drift on the four annotation actions — had
  three names, and the read-path contracts named none of them. A caller that branched on
  `internal_error` or `partial_write` to detect it must now branch on `annotation_unavailable`.
  The mapping lives in the shared tool-layer helper module that already owns the
  `CredentialError` mapping, so it cannot drift per tool again. `reconcile_index` is deliberately
  excluded: there an annotation failure fails one artifact rather than the run, and is already
  reported per artifact in `failed`. `partial_write` keeps its meaning and narrows to it — the
  residual state where content is durable and no cause is separately diagnosable. What is durable
  in each case is unchanged; only what the caller is told about why
- **Breaking:** `write_artifact` no longer returns `conflict` for a write that is durable. An
  overwriting write's compare-and-swap cycle returned `conflict` whenever it exhausted, including
  the case where the final attempt's `put_object` had landed and only the trailing annotation write
  kept conflicting — so the caller was told nothing changed while the new content was in S3 with its
  annotations cleared and no failure-log entry recorded. That case now returns `partial_write` with
  a failure-log entry whose `failure_step` names the annotation write, so `reconcile_index` can
  complete it; `conflict` is returned only when every attempt's `put_object` conflicted and nothing
  durable was written. A caller that treated `conflict` as "safe to retry from scratch" must now
  treat `partial_write` as the repairable state it already is on every other post-PUT failure
- **Breaking:** `archive_artifact` now reports a half-archived artifact as `partial_write`, a
  response code it did not previously return — its codes were `credential_error`,
  `annotation_unavailable`, `internal_error`, and `conflict`. Once the status re-PUT has landed, the
  artifact is `inactive` in S3 with its annotations cleared while the vectors still say `active`;
  any failure from that point — an unknown error on the annotation re-apply, on either vector-flip
  call, or on any step of a compare-and-swap retry attempt, and the compare-and-swap cycle
  exhausting on the annotation re-apply — was reported as `internal_error` (or `conflict` for the
  exhaustion case), indistinguishable from a failure that changed nothing. The failure-log entry
  was already recorded on every such path and `reconcile_index` already repaired the divergence;
  only the response code hid the durable state from the caller. Every such failure now returns
  `partial_write`, with the same failure-log entry whose `failure_step` names the step that
  failed. `internal_error` and `conflict` are reserved for failures that left nothing
  durable; `credential_error` and `annotation_unavailable` are unchanged. A caller that treated
  `internal_error` from `archive_artifact` as "nothing happened" must now check for
  `partial_write`
- **Breaking:** an artifact whose stored `visibility` is absent now re-indexes as `hidden`, not
  `shared`. `visibility` is one of the two fields the cross-scope access gate keys on, and the
  gate's two forms disagreed: the in-process check behind `read_artifact` reads an absent S3 value
  as `""` and denies, while `reconcile_index` wrote `shared` into the rebuilt vector metadata — so
  `search_artifacts` and `list_artifacts` returned such an artifact cross-scope and `read_artifact`
  then refused it. Rebuilding as `hidden` fails closed, which is the only default both forms of the
  gate agree on. A foreign-scope caller that received these artifacts from search or list results
  will no longer see them once their vectors are rebuilt; the S3 object is left exactly as it is,
  and no response field reports the substitution
- documented the exact boundary of the ETag compare-and-swap guard in ADR-011 decision 6 and in
  the `s3-annotations` and `link_metadata` contracts: the token is the *object's* ETag, so the
  cycle serialises annotation writers against object-body writers (an overwriting `write_artifact`,
  an `archive_artifact` status re-PUT) and not annotation-only writers against each other, which
  leave the ETag unchanged. Two same-field annotation writes whose reads both post-date the last
  object-body PUT both pass the check and the later one wins, with no `conflict` and no failure-log
  entry. The residual was previously described as two simultaneous `link_metadata` calls only; it
  also covers a `link_metadata` call racing the trailing annotation re-apply of a write or archive.
  No annotation-level precondition exists in the S3 API (verified against the installed botocore
  service model), so the residual is accepted, not further mitigated. Behaviour is unchanged
- **the server now refuses to start where S3 object annotations are unavailable.** A new
  eighth startup check round-trips one annotation through all four required IAM actions on
  a throwaway probe object, and distinguishes the two causes an operator acts on
  differently: a missing IAM action (fixable in the policy) versus a region or bucket type
  that does not offer annotations at all (only fixable by relocating the bucket).
  Annotations are now the sole durable store for `commit_refs`/`references`, so a
  deployment that cannot use them is unsupported rather than degraded
- **a write whose durable link write fails no longer reports success.** `write_artifact`
  previously returned a success response carrying a top-level `warning` when the annotation
  write was unavailable; it now returns `annotation_unavailable` with a failure-log entry
  recording the values it was applying, so `reconcile_index` can restore them. `archive_artifact`
  likewise no longer returns an `annotation_warning` alongside a successful archive. A
  caller can now treat the absence of an `error` key as proof the link fields are durable
- link fields are read from the S3 object annotations alone. The union-of-both-durable-stores
  read model is retired, and with it a full vector-index scan per artifact on every read:
  the index API has no server-side filter for `commit_refs`, so reading the vector copy back
  meant paginating the whole index in memory, once per artifact. A `list_artifacts` page of
  200 artifacts performed 200 such scans, to return at most a capped most-recent-20
  `commit_refs` and never any `references`. The vector copy is still written — it is the
  derived filter index answering "which artifacts carry commit ref X" — but never read back
- `build_scope_filter` moved from `arkeology.tools._search_helper` to
  `arkeology.tools._scope`, joining `is_cross_scope_readable` so that every implementation
  of the cross-scope access gate lives in one module. Its signature changed from
  `build_scope_filter(settings)` to `build_scope_filter(own_scope, read_prefixes)`, keeping
  the gate free of any configuration dependency. Both are private helpers — no MCP tool
  signature, response shape, or stored data shape changes
- the ruff quality gate now covers `scripts/` and `plugins/` in addition to `src/` and
  `tests/`, which had left the repository's non-package Python unlinted
- `.pre-commit-config.yaml` now runs the project's own pinned tooling via `uv run` instead
  of independently-versioned upstream mirrors, which had drifted to ruff 0.11 and mypy 1.x
  while the project ran ruff 0.16 and mypy 2.x
- documented that filtering `list_artifacts(commit_refs=[...])` searches only an artifact's
  most-recent 20 commit refs — the filterable index copy is capped at that many entries, so
  an artifact linked to more commits is not matched on its oldest SHAs even though the
  returned `commit_refs` field still shows the full list. Behaviour is unchanged; the
  window was previously undocumented in the list contract and the runtime schema resource
- the `arkeology://artifacts` resource is now documented as returning `list_artifacts`'
  default scope — own-scope artifacts plus shared tier-3 artifacts from readable foreign
  scopes — rather than own-scope only, which the contract and docstrings had claimed while
  the code always applied the wider gate. Behaviour is unchanged
- the freshness contract now records that a synthesis source failing the cross-scope gate is
  reported as missing, deliberately indistinguishable from a genuinely absent one, because a
  separate "inaccessible" category would leak the existence of foreign tier-2 and hidden
  artifacts. Behaviour is unchanged
- a `references` element is now documented consistently as a **full** operative `artifact_id`
  — scope prefix and file extension included — in the `arkeology://schema/artifact` resource,
  the `Artifact` model, the `write_artifact` docstring, and the annotation contract. The model
  and tool docstrings had said "bare artifact IDs … no path text", which reads as an
  instruction to strip the scope prefix; an element written that way fails the cross-scope
  readability check and is silently dropped from a foreign reader's view. The same
  `write_artifact` docstring also still claimed `references` is stored in vector metadata,
  which stopped being true when T58 removed it. Behaviour is unchanged
- the read-forward of `commit_refs` on an overwriting write is documented as applying to
  **every** overwrite rather than only a tier-3 living-document update. The S3, annotation,
  and write contracts had all scoped it to tier 3, while the code has always keyed it on
  `overwrite` against an existing key. A caller could have concluded that replacing a tier-2
  artifact drops its commit-ref trail. Behaviour is unchanged
- response keys that were always returned but never contracted are now documented:
  `delete_failed` on `check_synthesis_freshness` (including its effect on `all_fresh`),
  `skipped_unindexed` on `migrate_artifacts`, and `zero_results`, `clamped`,
  `effective_top_k`, `truncated`, `included`, and `skipped_count` on `synthesise_artifacts`,
  each with the condition under which it is present. The `migrate_artifacts` contract also no
  longer implies that an unindexed candidate is routed into the repair path — the tool reports
  it and names `reconcile_index`, and repairs nothing itself. Behaviour is unchanged
- the `arkeology_studio` contract documents a fourth `ToolResult` shape it had called
  exhaustive at three: the outer catch-all returns `is_error=True` with **no**
  `structured_content`, so a host that reads errors only from `structured_content` sees
  nothing on that path. `generate_artifact_id`'s contracted error surface is likewise
  corrected — it raises for an invalid `type`, `date`, or `tier`, never for an over-long or
  control-character-bearing title, which are `Artifact` model validators. Behaviour is
  unchanged
- **Breaking:** the cross-scope access gate no longer raises when a candidate's stored
  `tier` or `visibility` cannot be read as expected — absent, wrong type, non-scalar, or
  an out-of-range numeric `tier` — it denies the candidate instead. The gate's coercion
  was previously unguarded, so such a value escaped as an unhandled exception from every
  call site that runs the gate. On `read_artifact`, a foreign-scope artifact in this state
  now returns `access_denied` instead of `internal_error`. A caller that branched on
  `internal_error` from `read_artifact` to detect this condition must now branch on
  `access_denied`; nothing becomes readable that was not readable before
- **Breaking:** `read_artifact` returns a new error code, `corrupt_metadata`, naming the
  offending field, instead of `internal_error`, when its own stored metadata cannot be
  parsed. It never invents a default for the unreadable value — `tier` is one of the two
  fields the cross-scope gate keys on, so reporting a defaulted `tier` would teach the
  caller a value the gate never agreed to. The cross-scope gate still runs first: a
  foreign-scope artifact with corrupt metadata is denied and returns `access_denied`,
  never `corrupt_metadata`, so a gated artifact's stored state is never disclosed through
  this path. A caller that branched on `internal_error` from `read_artifact` to detect
  unparseable own-scope metadata must now branch on `corrupt_metadata`
- an unexpected failure of a resource read or of `arkeology_studio` now returns a fixed
  generic message instead of the underlying exception string, bringing those two surfaces
  in line with the pattern `write_artifacts` already used; the exception detail is logged
  server-side instead. A caller that parsed the exception text out of a resource body or
  out of the Studio error content will no longer find it there. This covers those two
  surfaces only — every other tool still returns the exception string in its error
  `message` — so it is a consistency step, not a closed leak class

### Security
- `search_artifacts` and `synthesise_artifacts` now re-check every candidate against the
  cross-scope access gate in process, matching what `read_artifact` and `list_artifacts`
  already did. The server-side vector filter that pre-narrows candidates is a prefetch
  optimisation, not the gate itself, and its `$eq` value-in-list semantics admit a
  non-scalar `tier` or `visibility` that the in-process gate would deny — so a
  foreign-scope tier-2 or hidden artifact carrying such a value could previously be
  returned in search or synthesis results. Both tools now apply the same denial
  `read_artifact` and `list_artifacts` already enforced, closing that gap

### Added
- `health_check` reports an `annotations` component, probed unconditionally. Startup check 8
  proves the annotation store works before the server accepts a request, but nothing re-checked
  it afterwards, so post-setup IAM drift on the four annotation actions left every read of the
  link fields failing while every other component still reported `ok`. The probe is read-only —
  it reads one annotation name off the write-prefix probe key and never writes one — and a
  missing object or annotation still counts as reachable
- CI: `.github/workflows/ci.yml` runs the ruff, mypy, pytest, and `npm test` gates on push
  to `main` and on every pull request — the repository's first automated checks
- direct unit tests for `build_scope_filter`, asserting the gate's semantics by evaluating
  the returned filter rather than comparing it literally, plus a test pinning that both
  forms of the gate agree on the same candidate
- a test pinning that `tier` gates identically whether it arrives as an `int` (vector
  metadata) or a stringified int (S3 object metadata), which the read and list paths
  respectively depend on
- a test pinning that the `arkeology://artifacts` resource applies the cross-scope gate
  rather than listing own-scope artifacts only — a foreign-scope tier-3 shared artifact is
  listed, a foreign-scope tier-2 one is not, matching `list_artifacts`' default scope

### Fixed
- `disambiguate_section_slugs` (the shared write-path helper both `write_artifact` and
  `reconcile_index` use to build each section's vector-key suffix) could still produce a
  collision it was meant to prevent: it suffixed repeat headings as `{slug}-{n}` but never
  checked that suffix against the *natural* slug of a different, real heading elsewhere in
  the same artifact. Two sections titled "Step" produced `"step"`/`"step-2"`; a third,
  distinct section literally titled "Step 2" also normalises to `"step-2"` — so two
  different sections ended up sharing one vector key, and whichever embedded second
  silently overwrote the first's vector, with `sections_indexed` under-reporting the true
  section count. The function now precomputes every section's own natural slug up front and
  skips any synthetic suffix that would collide with one, bumping the suffix number until a
  free one is found; a section's own natural slug is never itself perturbed to resolve
  someone else's collision. Every section in an artifact is now guaranteed a distinct
  vector key regardless of heading text or document order
- `list_artifacts` and `propose_commit_links` each fetched every distinct artifact's
  `commit_refs`/`references` annotations via an unbounded `asyncio.gather` — a large page or
  discovery batch could drive an unbounded number of concurrent blocking S3 annotation reads
  at once, unlike every comparable fan-out elsewhere in the codebase (`archive_artifact`'s
  bulk deletes, `purge_archived`, `link_metadata`, `reconcile_index`), which are all bounded
  by a semaphore. Both fan-outs are now capped at 5 concurrent reads each, matching that
  established pattern; behaviour and response shape are otherwise unchanged
- `reconcile_index`'s failure-log replay no longer loses link fields when several entries share
  one artifact and kind. It kept the first entry it read and pruned the rest, so consecutive failed
  writes to one artifact lost every other entry's `commit_refs` and `references` — the only
  surviving copy, since the S3 object annotations are the sole durable store and each re-PUT
  cleared what the previous entry had recorded. The replay now restores the union of every entry's
  `commit_refs`, and for `references` the union of every entry whose recorded `last_edited_ulid`
  still equals the artifact's current one, plus every tokenless entry's copy. Which line an
  appender happened to write first no longer affects what is restored
- a re-indexed artifact's vector set now exactly matches its rebuilt set. `reconcile_index` wrote
  the rebuilt section vectors without removing the ones they replaced, so a section slug that no
  longer exists in the current content stayed searchable indefinitely — an artifact with vectors is
  neither an orphan nor dangling, so no later pass removed the leftovers and only a manual
  overwrite could. The rebuilt vectors are now written first, the artifact's vector keys are then
  listed, and only the keys that listing shows absent from the rebuilt set are deleted, so a key a
  concurrent writer re-created in the window is kept
- `reconcile_index`'s orphan-vector cleanup no longer deletes a vector that a later write
  re-created. A recorded key list says what was stale when the entry was written, not what is stale
  now, and the replay deleted every recorded key verbatim — so an overwrite that had legitimately
  re-created one of those section slugs lost its live vector, and the orphan scan could not restore
  it because the artifact's remaining vectors kept it out of the scan. Each recorded key is now
  re-checked at prune time against the object's current `last_edited_ulid` and spared unless its
  vector's token is strictly older, or the key is absent from the index
- a failed post-write prune no longer fails the re-index. By the time that delete runs the rebuilt
  vectors are written and the artifact is correctly indexed, so the re-index now resolves as normal
  and the keys that could not be deleted are recorded as a new failure-log entry for the next run's
  cheap delete, with no re-embedding. A correctly indexed artifact therefore no longer consumes its
  retry budget, re-embeds every section on each retry, or reaches `stuck_failures` over leftovers
  alone. A failure of the *listing* itself still fails the re-index: without it there are no keys
  to record
- a credential failure during that prune now abandons the whole `reconcile_index` run and returns
  `credential_error`, as one raised in any other phase already did. It was caught alongside
  ordinary transient failures, so for the duration of a credential outage the tool reported
  per-artifact success and appended one failure-log entry per artifact naming keys it had never
  proven stale
- `reconcile_index`'s orphan scan no longer indexes stray objects. A key under the write prefix
  that no Arkeology tool wrote — a manual upload, a `.DS_Store`, a partial multipart artefact — was
  embedded and indexed as an artifact, adding a typeless, titleless entry that then surfaced in
  searches and listings. The scan now re-indexes a candidate only when its S3 object metadata
  carries a recognised artifact `type`, and reports the keys it declined in a new
  `skipped_non_artifacts` response field, present only when non-empty. An artifact whose `type`
  metadata is missing or corrupt is now skipped and reported rather than indexed with an empty type
  A skipped key is not counted in `orphans_found`, which counts artifact orphans needing
  re-index — a permanent stray would otherwise hold that number at a non-zero floor forever
- `check_synthesis_freshness` decides staleness by write recency (`last_edited_ulid`) instead of
  the artifact's subject `date`. Comparing `date` was wrong in both directions: a tier-3 source
  overwritten in place under an unchanged date was never reported stale, and a source carrying a
  later subject date but written *before* the synthesis was flagged even though it is already
  reflected in it. `date` remains the fallback when either side has no recorded write ULID. Where
  an artifact has several vectors that disagree about `last_edited_ulid` — the residue of a
  partial overwrite whose stale-vector cleanup failed — the newest is now taken rather than
  whichever the index happened to return first, which could otherwise mask staleness until a
  `reconcile_index` run pruned the orphans. Both dedup passes, over syntheses and over their
  sources, apply the same rule
- `delete_artifact` failure responses now carry `vectors_deleted`, so a caller can tell a
  half-deleted artifact — vectors gone, S3 object still standing, unsearchable but not destroyed and
  repairable by `reconcile_index` — from a delete that never started. The error code still names
  what the caller must act on, so a credential failure remains `credential_error`. The field
  describes the vector *side*, not a vector count: an artifact that had no vectors at all — a
  never-indexed partial write — now reports `True`, where it previously reported `False` and so
  told the caller its vectors were still standing when there were none
- `arkeology_studio`'s plain-text fallback returns a structured error code for every failure of
  its listing call. It called the internal listing function, so a condition only the public tool
  maps — an unavailable annotation store — reached the module's catch-all as a bare exception and
  came back with `is_error` set but no code at all, while a credential failure on the same call
  got one. It now calls the public `list_artifacts` and propagates whatever code that returns, so
  a host on the fallback path can always tell "the store could not be reached" from "the store is
  empty"
- an overwriting `write_artifact` or an `archive_artifact` whose target is deleted by someone else
  between the first read and a compare-and-swap retry now returns `not_found` rather than
  `internal_error`, and a credential failure on a retry's re-read now returns the structured
  `credential_error` the first attempt already returned. Nothing is written in either case, so no
  failure-log entry is appended
- the unbounded `$in` metadata filters in `check_synthesis_freshness`'s source lookup and
  `_reference_filter`'s target resolution are chunked to the same filter-expression byte budget the
  search loop already bounds its `$nin` list with. Both lists are caller-shaped and unbounded — a
  page's `references`, every synthesis's `source_artifacts` — so a large enough corpus could build a
  filter expression S3 Vectors rejects outright
- `health_check` runs its probes off the event loop via `asyncio.to_thread`, matching every other
  tool; they previously ran inline and blocked the loop for the duration of the slowest probe
- a failure-log entry is now recorded for any failure that strikes once the S3 object is
  durable, not only a credential failure. `write_artifact`'s compare-and-swap retry loop logged
  the credential case alone, so a `SlowDown` on the re-read or a budget breach on the re-merge
  escaped to the catch-all having recorded nothing — leaving S3 holding this write's content, the
  link fields cleared by the re-PUT, and the index still on the previous version. That state is
  invisible to `reconcile_index` on its own, because the artifact still has vectors and so the
  orphan scan skips it. While nothing is durable the failure stays the clean no-op it always was:
  a budget breach still rejects with no write and no entry
- an annotation read failure now raises instead of degrading to empty. With the union read
  model retired there is no second copy to cover for it, and an empty result caused by a
  transient failure would have been written straight back over good data by any of the three
  read-modify-write paths: `reconcile_index` rebuilding vector metadata, an overwriting
  `write_artifact`, and `archive_artifact` restoring the link fields after the status re-PUT
  that clears annotations
- `link_metadata` now records a failure-log entry when the vector write fails after the
  annotation write has succeeded, which is what makes the self-heal its contract and ADR-011
  promise actually happen. `reconcile_index` visits only artifacts named by a failure-log
  entry and S3 keys with zero vectors, and such an artifact fell into neither — it still had
  its (now stale) vectors — so the two durable copies stayed divergent indefinitely and a
  `list_artifacts(commit_refs=[sha])` or Studio facet query silently omitted it while
  `read_artifact` showed the link. The entry carries the `commit_refs`/`references` that were
  applied, so the existing failure-log replay restores them and re-indexes from the annotation
  copy. The failure is also contained per artifact: it previously escaped `asyncio.gather` and
  collapsed the whole call to `internal_error`, discarding the `linked`/`skipped` counts for
  artifacts that had already succeeded. Caller-visible: affected ids are now reported in a new
  `vector_write_failed` list, included only when non-empty, and counted in neither `linked`
  nor `skipped`
- `archive_artifact` now records a failure-log entry when an unknown error (not a conflict,
  not annotation-unavailable, not a credential failure) breaks the annotation re-apply that
  follows the status flip. Such an error previously reached the blanket handler and returned
  `internal_error` having recorded nothing, leaving S3 flipped to `inactive`, the annotations
  cleared by the re-PUT, and every vector still `active`, with no trace for `reconcile_index`
  to repair from. The error still surfaces as `internal_error`; only the missing entry is new
- the failure-log entry written when an annotation re-apply fails now carries the `commit_refs`
  and `references` that re-apply was holding, and `reconcile_index` restores them. The
  preceding object re-PUT clears the object's annotations, so the entry had been dropping the
  only remaining copy: `references` is not in vector metadata at all and the vector
  `commit_refs` copy keeps at most the most-recent 20 entries, making anything past that window
  permanently unrecoverable without telling the caller. Both fields are optional. `commit_refs`
  is restored as a union with the artifact's current value — it is an append-only trail on which
  removal is not a supported operation, so a value re-added in the meantime is not lost.
  `references` is replaced outright by every write, so it is restored only while the
  `last_edited_ulid` the entry recorded still equals the artifact's current one; a differing ULID
  means a later successful write has already established what the field says, and restoring the
  entry's copy over it would resurrect exactly the references that write deliberately removed. An
  entry carrying no ULID unions as entries did before the token existed — an absent token is
  missing evidence of supersession, not evidence of it
- a read prefix at or beneath the write prefix is now rejected at startup. The scope model
  assumes disjoint scopes, and every own-scope guard is a `startswith(write_prefix + "/")`
  test, so with `WRITE_PREFIX=team` and `READ_PREFIXES=team/proj` another deployment's
  artifacts read as this server's own: they passed the own-scope-only tools
  (`archive_artifact`, `delete_artifact`, `purge_archived`, `link_metadata`) and
  `reconcile_index` re-indexed them under the wrong scope. Caller-visible: a configuration
  that was previously accepted now refuses to start, with an error naming the offending
  read prefix, the write prefix, and the consequence. A read prefix *equal* to the write
  prefix is rejected too — harmless at runtime, but never intentional. Three shapes stay
  valid and are pinned by tests: a write prefix nested under a read prefix (the legitimate
  "write to my sub-scope, subscribe to the whole org" deployment), read prefixes nested
  among themselves, and siblings that merely share a textual prefix (`team-a` / `team-abc`).
  Duplicate read prefixes are silently de-duplicated rather than rejected
- `synthesise_artifacts` result entries now carry `score`, `source_artifacts`,
  `last_edited_ulid` and `last_edited_at`, which its contract promised but the response omitted
  — the score was computed by the search loop and then discarded, so a caller following the
  contract to rank or age-discount results got a `KeyError`. The entries are now built from the
  same shared helper `search_artifacts` uses, so the two tools cannot drift into reporting
  different fields for the same artifact, and `score` is the same `1.0 - cosine_distance` value
  in both. The response also surfaces `fetch_exhausted` under the same key and meaning as
  `search_artifacts`, so a budget-limited synthesis result set is distinguishable from an
  exhaustive one
- `reconcile_index` no longer discards a failure-log entry appended while it was running.
  It read the log at the start of the replay and, minutes later, wrote back only the
  entries it had read minus the resolved ones, so a partial write recorded in between — by
  a concurrent tool call or another server process sharing the same log — was overwritten
  and its artifact never reconciled. The end-of-run rewrite now re-reads the log under the
  same exclusive lock the appender takes and removes only the entries it actually
  resolved. A drained log is now truncated in place rather than unlinked, and flushed before the
  lock is released. An appender that opened the file before the rewrite and is still blocked on
  the lock would otherwise write into an unlinked inode, or have its entry landed on by a flush
  deferred to close — losing exactly the entry the re-read under the lock exists to preserve. A
  log missing entirely is read as an empty one, so a concurrent run draining it between another's
  existence check and its open no longer collapses that run to `internal_error`
- `reconcile_index` no longer replays a failure-log entry whose artifact has since been
  deleted. Such an entry was reported in `failed` with reason `S3 object not found` on
  every run forever, and `failure_log_entries_after` never dropped, because a `failed`
  entry is retained by the end-of-run log rewrite and never increments the retry counter
  that leads to `stuck_failures`. Caller-visible: the entry now appears once in
  `reconciled` with the new `source` value `failure_log_obsolete` and is then pruned from
  the log. It is deliberately not routed through the retry counter — `stuck_failures` asks
  an operator to fix an underlying cause, and a deleted artifact presents none
- a comma inside a `tags` or `source_artifacts` element is now rejected with
  `validation_error` on every write path. Both fields are stored comma-joined in S3 object
  metadata and as a native list in the vector index, so an element carrying a literal comma
  split into two on the `read_artifact` path while `list_artifacts` and `search_artifacts`
  returned it whole, and a tag filter for either half matched nothing. `commit_refs` and
  `references` already rejected commas for the same reason. Caller-visible: a write that
  previously succeeded and silently diverged the two stores is now refused before anything
  is written. Data written before this guard converges on its next `reconcile_index` run
- the `write_artifact` and `write_artifacts` MCP tools now accept and forward
  `file_extension`, which both module contracts list and both underlying functions
  implement but neither FastMCP wrapper declared — so no MCP caller could set the S3
  key extension on a single write or as a batch default. It was already reachable per
  descriptor inside `write_artifacts`, so this exposes no new capability
- `archive_artifact` double-encoded non-ASCII and `%`-bearing S3 metadata values on every
  archive (a title of `Café review` became `Caf%25C3%25A9 review`): `put_object`
  percent-encoded values for transport but `head_object` returned them still encoded, so
  the archive status re-PUT re-encoded what it had read. `S3ClientImpl.head_object` now
  decodes every value (except the reserved `ETag`), making the transport encoding symmetric
  and owned by the client; the ad-hoc decode sites in `read_artifact`, `reconcile_index`,
  and `archive_artifact`'s failure-log entry are removed as redundant
- corrected the normative contracts under `docs/contracts/` where they misstated the
  implementation: the Studio design-token layer still defined tokens for the removed `prd`
  artifact type and omitted the `vision`, `requirements`, and `--text-h4` tokens actually
  in use; `read_artifact`'s contract claimed a gated foreign artifact is indistinguishable
  from an absent one, which its own governing spec forbids; `health_check`'s contract
  declared all probes read-only despite the write-prefix probe performing a real
  put/get/delete cycle, and omitted the conditional `bedrock_text_model` key;
  `write_artifact`'s contract omitted the `warning` key returned when the durable
  annotation write is unavailable; the S3 data contract mislabelled per-field encoding when
  transport encoding is applied uniformly to every value; the resources contract omitted
  the `ui://` Studio resource and its content-security-policy origin allow-list
- `scripts/validate.py` formatting, which no quality gate had ever checked
- `list_artifacts`, `search_artifacts`, `synthesise_artifacts`, and
  `check_synthesis_freshness` no longer fail their entire call when a foreign-scope
  candidate's `tier` or `visibility` cannot be parsed. The cross-scope gate now denies
  that one candidate and the call returns the rest of its results as normal, instead of
  the whole call escaping to `internal_error`. The denied candidate is silently excluded,
  the same way any other gate-denied foreign artifact already is, and is not counted in
  `skipped_malformed_count` — counting it would disclose the existence of a foreign
  artifact the gate is withholding
- `search_artifacts`, `synthesise_artifacts`, `list_artifacts`, and
  `check_synthesis_freshness` no longer fail the whole call when one candidate's stored
  metadata cannot be read into the tool's own result shape for a reason other than the
  cross-scope gate — a missing identifier, for instance. The candidate is skipped and the
  call completes with the rest of its results. The skip is now reported in a new
  `skipped_malformed_count` field, present only when non-zero, so a result set thinned by
  unreadable records is distinguishable from a genuinely small one; a non-zero count also
  forces `check_synthesis_freshness`'s `all_fresh` to `False`, since a run that could not
  audit part of its input has not established that everything is fresh.
  `check_synthesis_freshness`'s existing eight-key promise on a successful call is
  unaffected — this is a ninth, conditional key
- `list_artifacts` now distinguishes an artifact deleted mid-listing from one whose
  link-field read genuinely failed. A deleted artifact is omitted from the page and
  counted separately in a new `skipped_deleted_count` field, present only when non-zero;
  a failed or ambiguous read still fails the whole page, as before. The two counts are
  never merged: a non-zero `skipped_deleted_count` is ordinary churn that `reconcile_index`
  self-heals, while a non-zero `skipped_malformed_count` is corrupt data worth
  investigating, and merging them would let the benign one hold the serious one's signal
  at a permanent non-zero floor
- the durable link-field read now distinguishes a deleted object, a genuinely absent
  annotation, and an ambiguous not-found, instead of collapsing all three into the same
  empty result. Only a genuinely absent annotation degrades to `[]`; the other two now
  raise. This closes a gap where `propose_commit_links` aborted its entire call with
  `internal_error` over a single dangling vector — a vector index entry whose underlying
  S3 object no longer exists — instead of skipping that one candidate and continuing
- two concurrent `health_check` calls no longer report a spurious `write_prefix` failure. The
  write-prefix probe wrote, read, and deleted one fixed key under the write prefix, so one
  call's delete could land between the other's put and get and report `error` on a deployment
  whose write permissions were fine. The probe key now carries a per-invocation ULID, the
  pattern startup validation already used; `reconcile_index` excludes probe keys by matching the
  probe marker as a prefix, so the suffix changes nothing about the orphan scan
- the startup write-prefix check now reports an unmapped exception from its read step as a
  structured validation error instead of letting it escape as a raw traceback. Its sibling write
  step already had that fallback and the read step did not, so any failure neither branch mapped
  aborted startup with a stack trace rather than the actionable message every other startup
  check produces

## [0.6.0] - 2026-08-28

### Changed
- **Breaking:** the `prd` artifact type is removed and replaced by two new types,
  `vision` and `requirements`, mirroring this project's own migration from a single
  `prd.md` to `vision.md` + `requirements.md`. Callers writing or filtering on
  `type="prd"` must switch to `type="vision"` or `type="requirements"`; existing
  `prd`-typed artifacts are unaffected in storage but no longer match schema
  validation on new writes
- `search_artifacts` and `synthesise_artifacts` responses now include
  `index_corruption_detected: true` when a `VectorDistanceMissingError` — an S3
  Vectors index-corruption signal, distinct from an ordinary transient error — is
  encountered mid-search; the call still returns whatever partial results were
  already collected rather than aborting
- The `AnnotationUnavailableError` message's bucket-type guidance now correctly
  describes directory buckets and Outposts buckets as the two affected bucket
  types, with S3 Express One Zone named as the storage class directory buckets
  use rather than a third, separately-counted bucket type
- **Breaking:** the project is renamed from `cairn-mcp` to `arkeology`, because
  `cairn-mcp` collided with several unrelated existing projects on GitHub and PyPI.
  The Python package, CLI entrypoint, plugin and skill assets, and the MCP resource
  scheme (`cairn://` → `arkeology://`) all change accordingly. Existing installations
  must update their MCP client configuration to point at the new entrypoint; stored
  artifacts and AWS resources are unaffected
- **Breaking:** `references` now has plain replace semantics on write, mirroring the
  supplied frontmatter exactly — an ordinary overwrite sets `references` to the value
  supplied and omitting it clears the field. Previously an overwrite union-merged the
  new value with whatever was already stored, which silently accumulated stale
  reference targets over repeated writes. `commit_refs` is unaffected: it remains a
  union-merge accretive field, since it is a git-derived audit trail rather than a
  claim about current state. Callers relying on the old union-merge behaviour for
  `references` must now resend the full desired list on every write.
- `link_metadata` tool replaces the retired `link_commit` tool — appends
  `commit_refs` and `references` to an artifact's durable S3 annotation copy
  without re-embedding, where `link_commit` only handled `commit_refs`.
  `commit_refs` in vector metadata is capped to the most-recently-appended 20
  entries (the complete list stays in the durable annotation); `references` is
  no longer written to vector metadata at all
- Durable read-modify-write cycles (`write_artifact` overwrite, `link_metadata`,
  `archive_artifact` status re-PUT) are now guarded by ETag compare-and-swap:
  `PutObject` / `PutObjectAnnotation` / `DeleteObjectAnnotation` calls are made
  conditional on the ETag captured at read time, with a bounded retry (~3 attempts)
  on detected concurrent modification before returning a structured `conflict` error,
  instead of silently racing another writer
- `references` returned to a **foreign-scope** reader via `read_artifact` or
  `list_artifacts` is now filtered to targets the reader is actually permitted to
  read (own-scope, or an independently readable tier-3 shared artifact); own-scope
  reads are unaffected and continue to return `references` exactly as stored.
  `list_artifacts` now issues one additional batched query page for this filtering
- Invalid or wrong-type `tier` values on `write_artifact` now return
  `validation_error` instead of `internal_error` (`Artifact.tier` is now
  strict-typed)
- `top_k <= 0` on `search_artifacts` / `synthesise_artifacts` now returns
  `validation_error` instead of being silently accepted
- Typo'd or invalid `type` / `tier` / `status` filter values on `search_artifacts`
  now return `validation_error` instead of silently matching zero results
- Duplicate H2-heading slugs within a single artifact are now disambiguated at write
  time, so `sections_indexed` is accurate and no section's vector silently overwrites
  another's; the same disambiguation is shared between `write_artifact` and
  `reconcile_index`
- `WRITE_PREFIX` validation now matches `READ_PREFIXES`'s strictness — it rejects
  internal whitespace and values that collapse to empty after slash-stripping,
  instead of accepting them
- Metadata filter evaluator's `filter` parameter renamed to `filter_expr`, so it no
  longer shadows the `filter` builtin
- `check_synthesis_freshness` now batches its per-source vector lookups into a
  single query instead of issuing one per unique source
- The write path's section-embedding thread pool is now constructed lazily on
  first use instead of at module import time
- The reverse-reference lookup used by `delete_artifact` / `archive_artifact`
  (checking whether other artifacts still reference the one being acted on) now
  issues one vector-index query instead of two
- `arkeology_studio`'s plain-text fallback listing, used on hosts that cannot render
  the visual browser, is now capped at the 50 most recent artifacts and reports the
  total count, pointing at `list_artifacts` when truncated. Previously it emitted every
  artifact, so the listing grew without bound on large stores
- `reconcile_index`'s orphan scan now skips every own-scope key whose final path
  segment begins with `_arkeology_`, a prefix now reserved for internal probe objects.
  Previously two specific probe names were hard-coded, so the setup skill's annotation
  probe could be reported as an orphaned artifact. No generated artifact id can collide
  with the prefix
- `reconcile_index`'s failure-log replay now tracks a per-entry retry count. An entry
  that fails to re-index 3 times in a row stops being auto-retried and is reported once,
  loudly, in a new `stuck_failures` response field, instead of blending indistinguishably
  into `failed` on every run. Previously a genuinely unfixable entry would be replayed
  identically forever
- `write_artifact`'s Step 8 orphan-vector cleanup now retries a transient
  `delete_vectors` failure inline, bounded with backoff, so it self-heals without
  reaching the durable failure path. If the retry budget is exhausted, the failure
  is logged with the exact orphan vector keys still needing deletion, and
  `reconcile_index` gains a new repair path that recognises this failure kind and
  deletes exactly those keys directly, without re-indexing. `reconcile_index`'s
  response reports these as a `reconciled` entry shaped `orphan_keys_deleted` /
  `source: "orphan_vector_cleanup"` (in place of `sections_indexed`), and they
  participate in the existing `failed`/`stuck_failures` bounding, carrying an
  additional `orphan_keys` field when present
- `link_metadata` and `reconcile_index` now validate metadata size budgets before
  writing (previously only `write_artifact` did), closing a gap where either could
  durably write metadata a fresh `write_artifact` call would reject outright and
  permanently desync the annotation/vector stores. `link_metadata`'s validation of
  supplied `commit_refs`/`references` values now also rejects control characters
  (previously only checked for commas and empty/whitespace-only values)
- **Breaking:** `list_artifacts`' `references=` filter parameter is removed entirely
  — a caller supplying it now gets a `TypeError`, not a silently-empty result.
  `references` stopped being vector-filterable once `commit_refs`/`references`
  vector-metadata hardening shipped, so the parameter could never match anything for
  artifacts written after that. `commit_refs=` filtering is unaffected
- `delete_artifact`'s and `archive_artifact`'s reverse-lookup warning (checking
  whether other artifacts refer to the one being acted on) now only checks
  `source_artifacts` — the `references`-half of that check is dropped, since
  `references` stopped being vector-filterable and could never match anything there
  either. This is a separate, more recent change from the reverse-reference lookup's
  earlier one-query-instead-of-two optimisation documented above
- `migrate_artifacts`' skip-existing check can now report a candidate under a new
  `skipped_unindexed` field (distinct from `skipped_existing`) when its S3 object
  exists but its vectors are missing — a partial-write state previously silently
  treated as "already migrated." Points the operator at `reconcile_index` for
  remediation
- `check_synthesis_freshness(confirm=True)`'s `all_fresh` field now also requires no
  synthesis deletions to have failed, not just no malformed syntheses reported —
  previously it could report `all_fresh: true` while a malformed synthesis was still
  present in S3 because its deletion had failed

### Security
- Bumped the pinned DOMPurify dependency used by `arkeology_studio`'s browser-side
  sanitisation (both the CDN import in `arkeology-studio.html` and the `package.json`
  devDependency backing the sanitisation regression test) from `3.4.11` to `3.4.13`,
  addressing two moderate-severity advisories in hook and custom-element handling.
  Neither advisory is reachable through the studio's actual usage, which calls
  `DOMPurify.sanitize(html)` with no config object, no custom elements, and no hooks
  registered

### Added
- `search_artifacts` now accepts `status="all"`, the same all-inclusive sentinel
  `list_artifacts` already accepted, returning matches regardless of status. It was
  previously rejected with a `validation_error`, which left a caller holding an
  explicit "any status" filter — such as the studio's status facet, whose default is
  `"all"` — with no correct way to express it. This is a strict widening: omitting
  `status` still defaults to active-only, `"active"` / `"inactive"` are unchanged, and
  any unrecognised value still returns a `validation_error`
- The studio renders `arkeology://artifact/{id}` links in artifact content as
  activatable controls that open the target in its own detail view. Links that cannot
  be resolved — non-artifact `arkeology://` resources, malformed URIs, and the raw
  repository paths migration leaves behind — render as inert text rather than as dead
  or navigable links. Access control is unchanged; the server-side scope gate remains
  the sole authority
- The studio's artifact list now renders 50 rows at a time behind a "Show more"
  control that reports how many of how many artifacts are shown
- `synthesise_artifacts` gained a configurable response-size budget — new
  `SYNTHESISE_MAX_RESPONSE_BYTES` setting (default 1,000,000 bytes / 1 MB), measured
  as the UTF-8 byte length of the result's `content` field. Results assemble in rank
  order and stop before the next result would exceed the budget, adding
  `truncated: true` and `included: N` to the response (both omitted when not
  triggered); a single oversized top result is still included rather than returning
  zero results. The existing 100-result count ceiling remains a secondary guard
- `search_artifacts` response now includes `fetch_exhausted: true` when the
  re-fetch loop's own fetch budget — not the true number of matching artifacts — is
  what limited the result count below `top_k`
- `synthesise_artifacts` response now includes `zero_results` (matching
  `search_artifacts`'s existing convention) and `skipped_count`, the latter
  reporting per-candidate content-read failures that were previously dropped
  silently
- Vector client's `get_vectors` supports `include_data=False` for metadata-only
  reads, skipping the underlying vector-float payload

### Fixed
- A `read_artifact` failure in the studio now shows the server's own error message with
  the detail view open, instead of a blank body
- The `setting-up-arkeology` skill's annotation probe now always removes its probe
  object, reporting the exact key and removal command if cleanup fails. Previously an
  `AccessDenied` during the probe could strand the object in the bucket
- Unknown/transient `ClientError`s during annotation writes on `write_artifact` no
  longer escape as `internal_error`; the S3 content is already durable, so the
  failure is now logged and surfaced as `partial_write`, matching existing
  `CredentialError` handling
- `commit_refs` / `references` values containing a literal comma are now
  rejected up front on write and on `link_metadata`, instead of silently diverging
  between the comma-joined S3 annotation encoding and the native `list[str]` vector
  metadata encoding
- `put_object_annotation` now maps `NoSuchKey` / 404 the same way its sibling S3
  methods do; `link_metadata`'s batch loop now skips and counts orphaned-vector
  artifacts (vector index entries whose underlying S3 object no longer exists)
  instead of aborting the whole batch with `internal_error`
- Migration reference-rewrite path now normalises manifest path keys before
  matching, fixing a silent no-op on `./`- or backslash-spelled paths
- `search_artifacts` / `synthesise_artifacts` now default missing vector `tier`
  metadata to `0` instead of raising `KeyError`
- Startup's write-prefix probe now uses a unique key per invocation instead of a
  fixed one, so concurrent server starts against the same prefix no longer race on
  the same S3 object
- Startup's read-prefix check now verifies actual object-read access, not just
  `ListBucket`, catching an IAM misconfiguration (list-but-not-read) at startup
  instead of on the first `read_artifact` call
- Startup's credentials check now distinguishes a missing/misnamed bucket from an
  actual credentials failure, instead of reporting both under a misleading
  "re-authenticate" message
- A fresh artifact write with no `commit_refs` / `references` supplied no longer
  issues two pointless annotation-delete calls
- `link_metadata` now preserves partial `linked` / `skipped` progress in its
  response when an annotation-unavailable condition cuts a batch short, instead of
  discarding it
- The local failure log is now guarded against concurrent-writer corruption with a
  `flock`-based lock, gracefully degrading on non-POSIX platforms
- Raw AWS/boto error text no longer leaks into `write_artifacts` error responses,
  on both the top-level and per-artifact error paths
- An unsupported filter operator or a mixed-type comparison (e.g. an int field
  compared against a string operand) now raises a typed, catchable error instead
  of a bare `ValueError` / `TypeError` that could abort a paginated query mid-way
  and discard already-collected results
- `decode_link_list` now drops empty segments produced by a malformed
  comma-joined payload (e.g. a double comma) instead of including them as
  empty-string list entries
- A non-UTF-8 S3 object or annotation payload now raises a typed, classified
  error instead of a bare `UnicodeDecodeError`
- Metadata byte-budget validation now measures true UTF-8 size for non-ASCII
  content (CJK, Arabic, etc.) instead of the inflated size of `json.dumps`'s
  default ASCII-escaped representation, which could reject a value that actually
  fit within budget
- A migration manifest with two entries that normalise to the same path now
  raises instead of silently letting the second entry overwrite the first
- `migrate_artifacts`' skip-existing pre-check now rejects a candidate whose
  `file_extension` does not start with `.` up front, with the same
  `validation_error` shape as `write_artifact`'s own guard. Previously a
  malformed value silently built an unreachable candidate key and was deferred
  to `write_artifacts`' own validation
- A newline embedded in an artifact's title or description no longer corrupts the
  `arkeology://artifacts` markdown table's row structure
- Investigated and left unchanged: the `coerce_list_field` inconsistency flagged
  for `delete_artifact` / `purge_archived` / `check_synthesis_freshness` is not a
  real bug — vector metadata natively stores lists, so the direct access already
  in use is behaviourally equivalent
- Documented as an accepted limitation rather than fixed: a metadata value
  written before the transport-encoding scheme existed (v0.5.0-era) that happens
  to contain a literal `%XX`-shaped substring cannot be reliably distinguished on
  read from an intentionally-encoded value without a persistent per-object
  encoding-version marker — a schema-level decision out of scope for this fix
- `write_artifact`'s overwrite compare-and-swap retry loop's `CredentialError`
  response on the conditional `put_object` call now includes `artifact_id`,
  matching its two sibling `CredentialError` handlers in the same loop iteration

## [0.5.0] - 2026-06-29

### Added
- `arkeology_studio` MCP tool — two-pane visual artifact browser rendered as an MCP App in
  supporting hosts (Claude Desktop, claude.ai, VS Code Copilot); falls back to a
  structured artifact listing on non-supporting hosts
- `purge_archived` best-effort bulk partial-failure: non-credential failures on individual
  artifacts are collected in a `failed` list without aborting the purge; `CredentialError`
  during the deletion phase aborts early and reports the artifacts purged so far in
  `purged_ids`

### Changed
- `ErrorCode` and `ArtifactStatus` StrEnum constants extracted to `constants.py`,
  replacing ~75 scattered string literals across the codebase
- Config range constraints migrated from imperative `@field_validator` to declarative
  `Field(ge=…, le=…)` in `Settings`
- `wrap_credential_errors(service)` context manager introduced in `credentials.py`;
  all three AWS client implementations use it, removing per-method `except` boilerplate
- `build_user_filters` and `coerce_list_field` helpers extracted to `_search_helper.py`;
  used by `search_artifacts`, `list_artifacts`, and `reconcile_index`
- `_SCHEMA_RESOURCES` table-driven loop replaces five identical `@app.resource`
  registrations in `resources.py`
- All dependencies pinned with compatible-release operator (`~=`)

### Fixed
- `reconcile_index` now preserves `commit_refs` and `last_edited_ulid` fields when
  re-indexing artifacts
- `check_synthesis_freshness` reports sources missing from the vector index directly;
  removes the unreliable S3 fallback
- `write_artifact` enforces `file_extension` on bulk-write paths and performs
  best-effort orphan cleanup on partial write failures
- `READ_PREFIXES` config value now normalises surrounding slashes on load
- `get_vectors` and `delete_vectors` now chunk requests to the S3 Vectors API cap
  (≤ 100 keys per call), preventing `ValidationException` on large artifact sets
- Minor code quality fixes across tools and clients (codebase review 2026-06-25)

## [0.4.0] - 2026-06-23

### Added
- `arkeology://artifact/{id}` and `arkeology://artifacts` MCP data resources — human-browsable
  resources backed by existing `read_artifact` and `list_artifacts` logic; carry
  `audience: ["user"]` annotations and apply the same cross-scope gate as the tools;
  browsable in MCP Inspector and Claude Desktop
- `learning` artifact type — fifteenth first-class type (tier 3, date-independent ID)
  backing the `capturing-learnings` skill's living `learnings.md`
- `propose_commit_links` tool — discovers own-scope artifacts with no `commit_refs`,
  optionally bounded to artifacts written at or after a session-start ULID (`since_ulid`)
- `link_commit` tool — appends a commit SHA to vector metadata of confirmed own-scope
  artifacts without re-embedding
- `commit_refs` optional field — list of git commit SHAs; accepted by `list_artifacts`
  as a filter and returned by `read_artifact` and `list_artifacts`
- `last_edited_ulid` system-generated field — ULID assigned at every `write_artifact`
  call; suitable for use as `since_ulid` in `propose_commit_links`
- `$gte` and `$lte` string comparison operators in the metadata filter evaluator;
  enable range queries on string-valued metadata fields

### Changed
- `feature_tags` field renamed to `tags` across all tools, metadata, and resources (T41)
- All dependencies upgraded to latest versions
- Minimum Python version raised from 3.12 to 3.14

### Fixed
- `list_artifacts` now batches `GetVectors` calls in chunks of ≤100 — deployments
  with more than 100 artifacts were getting a `ValidationException` from the S3
  Vectors API

## [0.3.1] - 2026-06-11

### Added
- `artifact_concurrency` optional per-call parameter on `write_artifacts` and
  `migrate_artifacts` (default 3, ceiling 15); values outside [1, 15] are clamped
  with a top-level `"warning"` field rather than rejected; removes the
  `ARTIFACT_CONCURRENCY` env var

### Fixed
- `setting-up-arkeology` skill: installation now requires a single MCP client restart
  instead of two — AGENTS.md is written before the restart so both files are picked
  up in one reload
- `setting-up-arkeology` skill: removed the "When to write artifacts" section from the
  generated AGENTS.md snippet, which was triggering spurious `session_summary` writes
  at the end of skill-driven operations
- `migrating-to-arkeology` skill: dot-prefix directories (e.g. `.docs/`) are now surfaced
  in the 2b discovery scan; the blanket `.docs/` exclusion is removed
- `migrating-to-arkeology` skill: ARKEOLOGY_IMPORT.yaml is no longer printed to the terminal;
  operators are directed to open the file in their editor

## [0.3.0] - 2026-06-10

### Added
- `setting-up-arkeology` skill — guided per-project Arkeology configuration for OpenCode, Claude Code, GitHub Copilot, and Claude Desktop
- `sync-arkeology-plugin` skill — updates the Arkeology plugin in place for any supported AI coding tool without manual config edits
- Native plugin support for OpenCode, Claude Code, and GitHub Copilot via `install.sh` and `marketplace.json`
- `reconcile_index` Scenario 3 — dangling vector pruning: removes vector entries with no corresponding S3 object

## [0.2.0] - 2026-06-03

### Added
- `write_artifacts` bulk write tool for importing multiple artifacts in a single MCP call (T30, FR-25)
- `migrate_artifacts` migration tool for server-side parallel migration with automatic chunking (FR-26)
- Concurrent section embedding and batched `put_vectors` calls in `write_artifact` — reduces write latency by up to 80% on multi-section documents (Phase 8)
- Bedrock throttle retry with exponential backoff and jitter
- `SECTION_CONCURRENCY`, `EMBED_MAX_SECTIONS`, and `EMBED_MIN_SECTION_LENGTH` configuration variables for write-path tuning

### Changed
- `migrating-to-arkeology` skill rewritten with server-side parallel migration paths (Path B concurrent script, Path C sub-agent fan-out)

### Fixed
- `READ_PREFIXES` validated at startup to reject template placeholder text
- AWS credential values suppressed from `LOG_LEVEL=DEBUG` output
- Migration parallelism gate added — skill now surfaces concurrency settings before migration starts
- Required field validation added to `write_artifacts`; returns structured `validation_error` on missing fields

## [0.1.1] - 2026-06-01

### Added
- `brainstorming` artifact type
- Artifact type vocabulary extended from 9 to 14 types: `prd`, `plan`, `runbook`, `changelog`, and `postmortem`
- OpenCode-specific MCP client configuration example in README

### Changed
- Migration skill document classification replaced fragile docs-root detection with a two-pass system — filename rules fire first, followed by path-segment rules matching at any depth

### Fixed
- S3 object metadata values sanitised to ASCII to prevent boto3 encoding errors on non-ASCII content

## [0.1.0] - 2026-06-01

### Added
- FastMCP server skeleton with stdio transport and structured logging to stderr
- AWS client layer — S3, S3 Vectors, and Amazon Bedrock each behind a typed `Protocol` interface; all boto3 calls catch and re-raise credential errors as structured `CredentialError` exceptions
- Configuration model (`pydantic-settings`) with environment variable validation and five-check startup validation sequence
- Artifact model with deterministic key generation (date-anchored tier 2, date-independent tier 3) and section parsing
- `write_artifact` tool — embeds sections at write time via Amazon Bedrock Titan Text Embeddings v2 and stores content in S3
- `search_artifacts` tool — vector similarity search with metadata filtering (`$eq`, `$in`, `$nin`, `$and`, `$or`)
- `read_artifact` tool — full content retrieval from S3 by artifact ID with cross-scope visibility checks
- `list_artifacts` tool — filtered artifact listing by scope, type, status, and feature tags
- `archive_artifact` and `purge_archived` tools — two-phase soft delete lifecycle
- `delete_artifact` tool — hard delete with synthesis reference guard (scoped to own scope only)
- `health_check` tool — validates all three AWS service connections and reports configuration
- Partial write failure log — JSONL-format append log for embed and vector write failures
- `synthesise_artifacts` tool — LLM-ready cross-artifact synthesis with source tracing and freshness metadata
- `reconcile_index` tool — scans S3 prefix and re-indexes any artifacts with no corresponding vector entry
- `check_synthesis_freshness` tool — detects synthesis artifacts whose source artifacts have changed since last synthesis
- MCP resources for artifact type vocabulary and scope discovery
- `migrating-to-arkeology` skill for migrating existing project documentation into Arkeology
- Full integration test suite against live AWS (S3, S3 Vectors, Bedrock) with automatic teardown
- Configurable `BEDROCK_EMBEDDING_DIMENSIONS` (default 1024)
- In-process metadata filter evaluator enabling client-side filtering when S3 Vectors filter is not supported

### Changed
- Visibility value renamed from `confidential` to `hidden`

### Fixed
- Vector metadata excludes empty list fields to avoid S3 Vectors schema validation errors
- Bedrock embed API called with correct `dimensions` parameter
- `WRITE_PREFIX` validated to require a non-empty value; defaults to `artifacts`

### Security
- Credential-related boto3 exceptions caught at the AWS client layer and re-raised as structured typed errors; never exposed as raw stack traces to MCP callers

[0.3.0]: https://github.com/amanoxsolutions/arkeology/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/amanoxsolutions/arkeology/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/amanoxsolutions/arkeology/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/amanoxsolutions/arkeology/releases/tag/v0.1.0
