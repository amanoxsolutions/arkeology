---
name: backfilling-references
description: Content-scan own-scope Arkeology artifacts for unresolved frontmatter reference paths, resolve them against the migration path→artifact_id map, and backfill confirmed matches into the structured references field via link_metadata after a single dry-run batch report. Optional, decoupled, post-hoc cleanup for references that could not be resolved at migration time — declining leaves every artifact unchanged.
---

# Backfilling references

`references:` entries in migrated artifacts sometimes stay unresolved: the target file was
absent from the original migration batch, discovered after a write, or migrated in a later
session (ADR-012 D10). This skill is the decoupled, **optional, skippable-by-default** cleanup
pass for that gap. It never touches stored content — resolved references are rewritten into
content only once, at first-write time (ADR-012 D8) — and it never mutates metadata without
operator confirmation of a single consolidated dry-run report. Run it any time after
`migrating-to-arkeology`, or periodically as new artifacts are written.

`link_metadata` is the only write tool this skill calls. It backfills the structured
`references` field on existing artifacts without re-embedding and without touching content —
see `link_metadata`'s own docstring for its exact merge/dedup contract.

Before starting, read the project's `AGENTS.md` `<!-- arkeology:config` block (team/project
scope, `local_only_paths`) and, if present, `ARKEOLOGY_IMPORT.yaml` in the repo root — both carry
context this skill depends on: the config block supplies the own-scope `team`/`project` filter
for every tool call, and a still-present manifest is the most accurate source for the
path→full-key map (Step 2 below). The map's values are the full S3 key — the operative
`artifact_id` used everywhere else in Arkeology — not a bare id (review finding C1).

## Gotchas

- **`link_metadata` merges the same list into every artifact in one call.** Calling
  `link_metadata(artifact_ids=[A, B], references=[X])` adds `X` to both `A` and `B` — it does
  not let `A` get `X` and `B` get `Y` in a single call. When two artifacts need different
  backfills, call `link_metadata` once per artifact (or once per group of artifacts that share
  the exact same new-reference set).
- **In-body markdown links are advisory-only — never auto-applied.** Only frontmatter
  `references:` entries are proposed as backfill candidates. A resolved in-body link match is
  surfaced in its own report section for operator awareness; it never appears in the applied
  batch even under a wholesale "approve all" (ADR-012 D1, mirrored from the migration rewrite).
- **A resolved full key must belong to a currently active own-scope artifact.** The path→full-key
  map can compute a full key for any candidate file, whether or not that file was ever actually
  migrated. Cross-check every resolution against the artifact IDs gathered in Step 4 before
  proposing it — a full key with no matching live artifact is not a valid candidate (leave it out
  of the report entirely, do not list it as unresolved either, since it never was a match).
- **`arkeology://artifact/{id}` entries are already resolved — skip them.** Only raw path text (not
  already a `arkeology://` URI, not `http(s)://`) is a candidate for resolution.
- **Zero candidates is a normal, complete outcome**, not an error — say so explicitly and stop.
- **`link_metadata` is idempotent.** Re-running this skill after a previous run (or after new
  artifacts have since been written) never duplicates a reference already present.
- **Own-scope only.** This skill discovers and backfills only the deployment's own artifacts —
  never foreign-scope ones, consistent with every other reverse-lookup in Arkeology.

## Workflow

1. **Health check** — call `health_check`. If any component reports `"status": "error"`, stop
   and report it; do not proceed.

2. **Pre-flight — scope and manifest** — read the project `AGENTS.md` for the
   `<!-- arkeology:config` block. If absent, stop: run `setting-up-arkeology` first. Parse `team`
   and `project`; carry them through every tool call below. Then check whether
   `ARKEOLOGY_IMPORT.yaml` exists in the repo root — it changes how Step 3 builds the map.

3. **Build the path→full-key map**

   The map's values must be the **full S3 key** (`{write_prefix}/{bare_id}{extension}`), not the
   bare id alone — the full S3 key is the operative `artifact_id` everywhere else in Arkeology
   (`write_artifact`'s vector metadata, `read_artifact`'s scope gate, the own-scope existence
   check in step 4 below, and `link_metadata`'s target ids in step 8) — a map keyed to the bare
   id alone never matches any of them (review finding C1).

   **Determine `write_prefix` first.** Call `list_artifacts(team=<team>, project=<project>,
   status="active")` (this doubles as the enumeration needed in step 4 below — do not call it
   twice). If it returns at least one entry, take any one, compute its *bare* id from its own
   `type`/`tier`/`title`/`date` with the script below, and strip the trailing
   `/{bare_id}{extension}` from its `artifact_id` — what remains is `write_prefix`. If the list is
   empty (no own-scope artifacts exist yet), ask the operator directly for the deployment's exact
   `WRITE_PREFIX` (check the MCP server's `.env` / client config; by convention it is
   `<team>/<project>`, but confirm rather than assume). Never guess it silently.

   - **`ARKEOLOGY_IMPORT.yaml` found** — use its entries directly (every entry, any `status` —
     `written`, `pending`, or `failed` — the map must be as complete as possible, not limited to
     what a prior run actually wrote).
   - **No manifest found** — reconstruct an equivalent entry list by re-running the
     `migrating-to-arkeology` skill's Step 2 discovery scan and Step 2c/Step 3 classification rules
     (folder scan → filename/path-segment classification tables → operator confirmation) against
     the repo's current documentation tree. Do not duplicate those tables here — open that
     skill's `SKILL.md` and follow Steps 2–3 verbatim, stopping once you have, per candidate
     file, its `path`, `type`, `tier`, `title`, and `date`.

   For every entry (either source), compute its full key — the exact algorithm implemented and
   unit-tested as `generate_artifact_id` / `build_path_to_id_map` in
   `src/arkeology/references.py` (`$EXTENSION` is the entry's own file extension including the
   dot, e.g. `.md`; default `.md` if the path has none — same default `write_artifact`'s
   `file_extension` parameter uses; `$WRITE_PREFIX` is the value determined above):

   ```bash
   python3 - "$TYPE" "$TIER" "$DATE" "$TITLE" "$EXTENSION" "$WRITE_PREFIX" <<'PY'
   import hashlib, re, sys, unicodedata

   type_, tier, date, title, extension, write_prefix = sys.argv[1:7]
   tier = int(tier)

   def slugify(text, fallback):
       ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
       slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:60].rstrip("-")
       return slug or fallback

   type_slug = type_.replace("_", "-")
   title_slug = slugify(title, "artifact")
   title_hash = hashlib.sha256(title.encode("utf-8")).hexdigest()[:8]
   bare_id = (
       f"{type_slug}-{title_slug}-{title_hash}"
       if tier == 3
       else f"{type_slug}-{date}-{title_slug}-{title_hash}"
   )
   full_key = f"{write_prefix}/{bare_id}{extension}"
   print(full_key)
   PY
   ```

   Keep the resulting `{path: full_key}` map in memory for the rest of this run — it is not
   written to disk.

4. **Enumerate own-scope active artifacts** — call `list_artifacts(team=<team>,
   project=<project>, status="active")`. Keep the returned `artifact_id` list (filtering out any
   entry that does not start with `<team>/<project>/` — cross-scope visibility can surface
   foreign-scope tier-3/shared artifacts here, and those must never be scanned or backfilled by
   this skill). This is both the scan universe (Step 5) and the existence check for Step 3's map
   (an id absent from this list is not a valid backfill candidate, however it was computed).

5. **Content-scan each artifact for unresolved references**

   For each own-scope `artifact_id` from Step 4, call `read_artifact(artifact_id)` and read its
   `content` and its already-populated structured `references` field.

   - Parse the frontmatter `references:` YAML list from `content` (if present). For each entry:
     - Skip it if it already starts with `arkeology://` (already resolved at first-write time) or
       `http://` / `https://` (never a path candidate, ADR-012 D5).
     - Otherwise, if the entry is a well-formed relative path (starts with `./` or `../`), join
       it against the *current artifact's own source file path* first — the same
       `join_reference_path` algorithm in `src/arkeology/references.py`: convert `\` to `/`,
       then POSIX-join the relative path against the referencing file's directory (not the repo
       root) and normalize the result. A path that escapes above the repo root simply normalizes
       to something absent from the map — it falls through to unresolved, not an error. If the
       artifact's original source path is unknown (e.g. it was authored directly via
       `write_artifact`, never migrated from a file), skip this join step for that entry — there
       is no directory to join against — and proceed straight to normalization below.
     - Take the entry as written (if not relative) or the joined path from the step above, and
       normalize it — convert `\` to `/`, then strip exactly one of a leading `./`, a single
       leading `/`, or neither — and look it up in the Step 3 map.
     - If it resolves to a full key (the operative `artifact_id`) that (a) is present in the
       Step 4 own-scope list and (b) is **not already** in this artifact's structured
       `references` field, record it as a proposed candidate:
       `(artifact_id, original path text, resolved full key)`.
     - A well-formed relative path that still fails to resolve after the join step above is a
       genuinely broken or out-of-tree reference — not the canonical "just needs joining" case
       anymore — and should be reported as unresolved like any other non-match.
   - Separately, scan the rest of `content` (outside frontmatter) for Markdown links
     (`[text](target)`) whose `target` is not `http(s)://` and not already `arkeology://`. Resolve
     each the same way (including the relative-join step above). Any that resolve are **advisory
     findings only** — record them in a separate list; never add them to the proposed-candidates
     list.

6. **Present the dry-run batch report** — a single consolidated report, before any write:

   ```markdown
   ## Proposed reference backfills

   | Artifact | Target path | Resolves to |
   |----------|-------------|-------------|
   | myteam/myproject/adr-...-a1b2c3d4.md | docs/specs/search.md | myteam/myproject/spec-search-e5f6a7b8.md |

   ## Advisory — in-body link matches (not applied automatically)

   | Artifact | In-body link path | Resolves to |
   |----------|--------------------|-------------|
   | myteam/myproject/adr-...-a1b2c3d4.md | ./decisions/xyz.md | myteam/myproject/adr-2026-...-c9d0e1f2.md |
   ```

   `Artifact` and `Resolves to` are always the full S3 key (the operative `artifact_id`,
   review finding C1) — never the bare id shown without its `write_prefix`.

   If the proposed-candidates table is empty, say so explicitly ("No backfill candidates
   found — every resolvable frontmatter reference is already backfilled") and stop; there is
   nothing to confirm.

7. **Operator batch approval** — present the report and ask the operator to:
   - approve the whole batch as-is, or
   - remove or edit specific rows before applying, or
   - decline entirely.

   **Wait for explicit confirmation. Make no `link_metadata` call until the operator responds.**
   If the operator declines, stop here — report "No changes made" and end the skill. Declining
   never leaves any artifact touched.

8. **Apply confirmed backfills** — group the confirmed rows by `artifact_id` (an artifact may
   have more than one new reference in this run) and, for each artifact, call:

   ```
   link_metadata(artifact_ids=[<artifact_id>], references=[<resolved_id_1>, <resolved_id_2>, ...])
   ```

   Call once per distinct artifact (or once per group of artifacts sharing an identical new-
   reference set, if you prefer fewer calls — never assume a single call can apply different
   reference sets to different artifacts). Report progress as a count (e.g. "Backfilled 4 of 9
   artifacts"). If any call returns a structured error (`credential_error`,
   `annotation_unavailable`, or similar), report it against that artifact and continue with the
   rest — do not halt the whole batch on one failure.

9. **Final summary** — report: candidates proposed, candidates applied, candidates declined/
   removed by the operator, and the count of advisory (in-body) findings surfaced but not
   applied. If the operator wants any advisory finding applied, that requires a follow-up run
   after adding it to the artifact's frontmatter `references:` list, or a manual
   `link_metadata` call — this skill does not do it automatically.
