---
status: ready # draft | ready | in-progress | done
references:
  - https://openknowledgeformat.com/
  - https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
  - https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing/
  - docs/brainstorming/brainstorming-2026-06-14-visual-reading-interface.md
  - docs/architecture-decisions/adr-2026-05-29-section-level-embedding.md
  - docs/architecture-decisions/adr-2026-05-29-tier-based-access-control.md
  - src/arkeology/artifact.py
authored:
  by: "analyst"
  date: 2026-06-15
revised:
  by: ""
  date:
---

# OKF (Open Knowledge Format) Alignment for Arkeology

## Description

Google Cloud published the Open Knowledge Format (OKF) v0.1 on 2026-06-12: a vendor-neutral
spec representing knowledge as a directory of markdown files with YAML frontmatter, cross-linked
into a graph, distributable as a git repo / tarball / subdirectory, with a hand-written `index.md`
for progressive disclosure. This session explores what OKF means for Arkeology — a service that
already stores markdown artifacts with rich metadata, backed by S3 + S3 Vectors + Bedrock semantic
search — covering both the strategic relationship and the concrete export/import/schema options.

## Decisions

### Locked

- D1
- D2
- D3
- D4
- D5
- D6

### Pending

_None._

### Closed — Not Applicable

- OQ1
- OQ2
- OQ3

## Techniques Used

- inversion ("what would make OKF adoption a mistake for Arkeology?")
- perspective-shift (Arkeology as a service vs OKF as a file format)
- cross-pollination (linked OKF export to the in-flight visual-reading-interface Idea 3/Surface B)
- challenge (contradiction surfaced in the D2-before-D1 sequencing)

## Assumptions Challenged

- "OKF is a competitor to Arkeology → reframed: OKF is a file/interchange format; Arkeology is a service. They sit in different layers and are complementary."
- "Adopting OKF means changing Arkeology's native schema → an adapter (export/import) isolates the v0.1-draft churn risk better than a native rewrite."
- "Updating the README fully delivers D3 → the positioning half does; the underlying moat claim (semantic recall > index.md navigation at scale) is an unvalidated assumption."
- "Frontmatter alignment (D2) is an all-or-nothing choice (adopt OKF names vs keep ours) → false: it is per-field. The one clean alignment (`feature_tags`→`tags`) is adopted internally; `date` is kept because OKF `timestamp` is a different concept (last-modified, not the immutable identity date) and would map from `last_edited_ulid`. Wholesale renaming is rejected because the boundary mapping function exists regardless."
- "OKF's index.md progressive-disclosure model is strictly weaker than Arkeology → LLMs navigate tables of contents well; the recall-degrades-at-scale claim must be tested, not assumed."
- "Arkeology stores OKF-style YAML frontmatter inside the document → false today: `content` is written to S3 as a pure markdown body (`write.py:262`); metadata lives separately in S3 object metadata and vector metadata. OKF frontmatter would be *synthesized at export*, not stored."
- "S3 Vectors metadata must match OKF field names to be OKF-compliant → no: OKF is a document-serialization format with no opinion on internal index metadata; vector metadata is query-filter infrastructure (`tier` as int, `feature_tags` as `list[str]`) and stays OKF-agnostic."
- "Making documents OKF-compliant is Arkeology's responsibility (a transform/mapping Arkeology performs) → no: OKF authoring is the writing agent's job and is out of scope for Arkeology. Arkeology stores content verbatim; any future export is best-effort enrichment of the existing frontmatter, never a transform of non-OKF content."

## Session 2026-06-15

### Problem Statement

OKF standardizes almost exactly the kind of artifact Arkeology **stores** (typed markdown knowledge
artifacts — produced by agents and humans, not by Arkeology itself), while deliberately omitting
everything Arkeology provides around them (durable storage, semantic search, access control). Is OKF a
threat, an opportunity, or both — and how far, if at all, should Arkeology lean into it?

### Known Constraints

| Constraint | Source |
|---|---|
| Arkeology artifacts are markdown `content` + structured metadata (`type`, `team`, `project`, `tier`, `date`, `status`, `title`, `description`, `visibility`, `feature_tags`, `author_role`, `source_artifacts`, `commit_refs`) | `artifact.py` |
| 14 fixed artifact types; `ARTIFACT_TYPES` is the single source of truth | `artifact.py` / AGENTS.md |
| Content lives in S3; embeddings + metadata in S3 Vectors; embeddings via Bedrock Titan v2 | AGENTS.md |
| Tier + visibility cross-scope gate is a **soft** server-side control; IAM is the hard boundary | tier-based-access-control ADR |
| Deterministic, non-random artifact IDs (tier-2 date-anchored, tier-3 date-independent) | AGENTS.md |
| S3-object metadata (comma-joined strings) and vector metadata (`list[str]`) encode tags differently **on purpose**; schema migrations are costly | AGENTS.md |
| Project "owns no infra" — deployment-agnostic stance | AGENTS.md |
| OKF v0.1 is a **draft**; one required field (`type`); recommends `title`/`description`/`resource`/`tags`/`timestamp`; permits custom keys; consumers MUST NOT reject unknown types/keys/broken links | OKF SPEC.md |

### OKF ↔ Arkeology field mapping (reference)

| OKF frontmatter | Arkeology `Artifact` field |
|---|---|
| `type` (required) | `type` (14-type enum) |
| `title` | `title` |
| `description` | `description` |
| `tags` | `feature_tags` |
| `timestamp` | `date` |
| `resource` (URI) | *(no equivalent today)* — candidate: git ref / source file |
| markdown body | `content` |
| concept ID = file path | deterministic `artifact_id` |
| markdown cross-links (graph) | `source_artifacts`, `commit_refs` |
| *(none)* | `tier`, `visibility`, `team`, `project`, `author_role` (arkeology-only; ride along as custom keys) |

### Ideas Explored

**A. Export / interchange.** `arkeology export --okf <scope>` → conformant bundle (git repo + `index.md`
+ `log.md`); `index.md` generated from faceted listing; `log.md` from `date`/changelog artifacts;
cross-links from `source_artifacts`/`commit_refs`; synthesis artifacts exported as concepts linking
their sources. This subsumes the visual-reading-interface Idea 3 / Surface B — OKF *is* the standard
for that export, and a bundle is rendered for free by Google's static visualizer, GitHub, Obsidian,
and MkDocs.

**B. Import / ingestion.** `migrating-to-arkeology` accepts an OKF bundle as an input source; an
`import_okf` tool ingests foreign bundles (e.g. Google's BigQuery enrichment output) and embeds each
concept; free-form OKF `type` mapped onto Arkeology's enum with an `okf:unknown` fallback.

**C. Native schema alignment.** Rename/add fields (`tags`↔`feature_tags`, `timestamp`↔`date`, add
`resource`) for lossless round-trip; track `okf_version`; carry arkeology-only fields as OKF-legal custom
keys.

**D. Strategic positioning.** Position Arkeology as the durable, searchable, access-controlled backend for
the format Google standardized — the service layer OKF omits. OKF validates Arkeology's tier-2 artifact-gap
thesis. Treat Google's free bundle (Knowledge Catalog + enrichment agent + visualizer) as a competitive
signal and name Arkeology's differentiated lane.

**E. Governance / risk.** Export flattens access control — a bundle is ungoverned once it leaves;
`hidden`/cross-scope artifacts must be excluded or partitioned at export; v0.1 churn risk argues for
adapters over native rewrite; ID↔path mapping must be stable and reversible.

### Clusters

- **Adapter layer** (A, B): export + import as adapters; Arkeology schema unchanged.
- **Native alignment** (C): bend Arkeology's model toward OKF.
- **Strategic positioning** (D): how Arkeology relates to Google's stack.
- **Governance & risk** (E): access control, spec maturity, ID mapping.

### The threat (inversion result)

The concrete commoditization threat is OKF's distribution model: a bundle ships as **a git repo /
tarball / subdirectory**, and an agent navigates it via a hand-written **`index.md` for progressive
disclosure** — no S3, no Vectors, no Bedrock, no MCP server required. For small corpora this is a
"good-enough, zero-infra" substitute for Arkeology's entire backend.

**Counter-thesis (Arkeology's moat):** progressive-disclosure / structural navigation degrades in recall
as the corpus grows and as queries become fuzzy or cross-cutting; semantic search over section-level
embeddings is what `index.md` navigation cannot match at scale. This is the differentiator — but it
is currently an **assumption, not a measured fact** (see OQ1).

### Whose job is OKF authoring, and which layer does it touch? (grounding — `write.py`)

Arkeology stores `content` **verbatim** (`write.py:262`) — it never adds, parses, validates, or
transforms any YAML frontmatter inside it. Whatever frontmatter a document carries is whatever the
**authoring agent/human** wrote (OKF-shaped, amanox-template-shaped, or none). Separately, Arkeology keeps
two metadata structures of its own:

| Layer | What it is | Arkeology's role re: OKF |
|---|---|---|
| **1. Document frontmatter** | A YAML block inside the stored `content`. **Authored by the agent/human, not Arkeology.** | **Out of scope.** Making a document OKF-compliant is the *writer's* responsibility. |
| **2. S3 object metadata** (`s3_metadata`, `write.py:234`) | String key-values Arkeology attaches to the S3 object. | Not a document; a *source* for best-effort enrichment on export. |
| **3. Vector metadata** (`vector_metadata`, `write.py:286`) | The search filter index; `tier` as `int`, `feature_tags` as `list[str]` for element-level `$eq`. | **OKF-agnostic** (D5). |

**Conclusion (corrected in session — scope boundary):** Arkeology does **not** convert non-OKF documents
into OKF format. That is explicitly **out of scope** and is the authoring agent's responsibility. If
Arkeology ever offers an OKF *export*, it is **best-effort**: take the document's existing frontmatter,
adapt it, fill gaps from Arkeology's own stored metadata where possible, and add Arkeology's extra tags — with
no guarantee of OKF compliance. The vector index (layer 3) stays OKF-agnostic regardless (D5). This
reframes D2 (see below).

### Selected Directions

- **D1 — OKF as an export/interchange adapter (not a native rewrite).** `arkeology export --okf`; optional
  import. Arkeology's S3/Vectors/Bedrock service stays authoritative; OKF is a portability skin. Also
  resolves the visual-reading-interface debate. *Status: committed (D6); sequencing and scope are the PM's
  call. Backlog B-2.*

- **D2 — Frontmatter handling, decided field-by-field. (LOCKED → boundary mapping + one internal rename.)**
  Arkeology maps to OKF at the **export boundary** as best-effort enrichment of the document's existing
  (agent-authored) frontmatter — it does not author OKF or transform non-OKF documents (out of scope,
  the writer's job). Naming is decided per field, not by slogan:
  - **`feature_tags` → `tags`: rename internally (DECIDED).** Same concept, no semantic loss; the one
    field where alignment with OKF is clean. Cross-cutting code change (Artifact model, `write.py` S3 +
    vector metadata keys, `filter.py`, `list.py` faceting, tests, AGENTS.md, install/migrate skills),
    preserving the deliberate S3-string vs vector-`list[str]` dual-encoding. No data migration (no live
    data). Tracked as dev task **B-3**.
  - **`date`: keep internal; map at the boundary — do NOT rename to `timestamp`.** Arkeology `date` is a
    date-only, immutable **identity** field (part of the tier-2 ID); OKF `timestamp` means
    *last-modified datetime* — a different concept. Honest export mapping: OKF `timestamp` ← derived
    from `last_edited_ulid` (Arkeology's real last-modified); Arkeology `date` has no native OKF slot → rides as
    a custom key.
  - **`type` / `title` / `description`:** names already match OKF; no action.
  - **`resource` (D2c):** adding to the model is independently considerable (a git ref / source file).
  - **Option A (wholesale adopt OKF names) rejected** — it would force the `date`→`timestamp` error,
    and since the export mapping function exists regardless, wholesale renaming buys almost nothing.
  - **D2a — Best-effort OKF enrichment on export (layer 1).** On export, preserve the document's
    existing agent-authored frontmatter and *enrich* it from Arkeology's stored metadata where possible
    (`tags`; `timestamp` ← `last_edited_ulid`; `date` → custom key; add `resource`; carry arkeology-only
    fields as custom keys). Best-effort, **not** authoritative — Arkeology never guarantees OKF compliance
    and never transforms non-OKF content. Rides with the exporter (D1, deferred).
    *Open detail for D1: precedence when existing frontmatter and Arkeology metadata disagree — default
    proposal: existing frontmatter is authoritative, Arkeology only fills gaps and appends its extra tags.*
  - **D2b — Rename internal fields (layers 2–3) to "look like OKF".** *Not recommended.* OKF does not
    govern the index; vector metadata encodings are deliberate and OKF-agnostic (see D5). With zero
    users/data the *cost* is low, but the change is unmotivated and the wrong layer.
  - **D2c — Add a `resource` URI field to the model.** Independently considerable (a git ref / source
    file an artifact describes) regardless of OKF; the only model-level addition with standalone value.

  **Fork raised in session — does aligning internal names to OKF *simplify* things?** A real kernel:
  one shared vocabulary across `Artifact` model + S3 object metadata + document frontmatter makes
  export a pass-through and import symmetric. Weighed against: it is a ~3-field win; name-alignment
  hides a *semantic* mismatch (Arkeology `date` is date-only vs OKF `timestamp` datetime; Arkeology `type` is a
  14-value enum vs OKF free-form `type`) — renaming would mislabel the data; and layer 3 must diverge
  regardless (D5), yielding only *partial* alignment. This is a sub-question of OQ3:
  - **Option A — adopt OKF vocabulary as Arkeology's canonical names.** Max simplicity now (greenfield, no
    migration); couples the core model to a v0.1 draft and inherits the semantic mismatches.
  - **Option B — keep Arkeology vocabulary, align only at the boundary (= D2a mapping).** Captures the
    simplification for export/import, stays insulated from v0.1 churn, keeps names semantically honest.
  - *Analyst recommendation: B. A is defensible only on strong conviction that OKF is the durable
    lingua franca (decide via OQ3).*

  Note: existing repo docs already carry frontmatter, but it is the **amanox doc-template vocabulary**
  (`status`/`references`/`authored`/`techniques_used`/`decisions_*`) — neither Arkeology's metadata nor
  OKF. Three vocabularies coexist; "the docs already have frontmatter" does not yield free OKF alignment.

- **D5 — Keep the vector index OKF-agnostic (design principle). (LOCKED.)** OKF compliance is confined
  to the document-serialization boundary (layer 1). S3 object metadata and vector metadata retain their
  query-driven names and encodings (`tier` int, `tags` `list[str]`). Holds regardless of field-naming
  choices.

- **D6 — OKF compatibility is a first-class product commitment. (LOCKED — resolves OQ3.)** Arkeology commits
  to OKF interoperability as a product pillar, not a one-off convenience: (a) advertise Arkeology as
  "OKF-compatible" (reinforces D3 positioning); (b) build best-effort OKF **export** (B-2) **and import**
  of foreign bundles (B-4 — previously optional, now in scope); (c) track the OKF spec over time.
  *Consequence to manage:* this accepts an ongoing spec-tracking cost against a currently **v0.1 draft**;
  revisit the depth of commitment if OKF v1 diverges materially from v0.1. Sequencing and
  vision.md/requirements.md scope are the PM's call.

- **D3 — Strategic positioning: "semantic memory" vs "progressive-disclosure wiki." (LOCKED.)** Update
  the project README (and `docs/architecture-decisions/overview.md` if appropriate) to position Arkeology as
  the durable, searchable, access-controlled backend for OKF-style knowledge — explicitly the service
  layer OKF omits — and to name the moat (semantic recall at scale + access control + MCP-native
  write-at-session-time). Assert the moat now on first-principles grounds; the supporting benchmark is
  backlog, not a blocker (OQ1).

- **D4 — Governance-preserving export.** Any export must reuse the scope/tier/visibility gate at export
  time, exclude or partition `hidden`/cross-scope artifacts, and stamp the bundle as ungoverned
  downstream. *Status: committed as part of D1/D6; actionable once export is built. Backlog B-2.*

### Open Questions

None — all questions raised this session (OQ1–OQ3) were resolved; see `decisions_closed_not_applicable`
in the frontmatter and the Selected Directions above.
