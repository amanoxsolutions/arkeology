---
type: code_review
title: "Design + accessibility review of cairn studio (p11-t44 browser UI)"
description: "Frontend-design and code review of the cairn studio MCP App visual design (docs/specs/p11-t44-browser-ui-design.html), the normative T44 spec, and the built cairn-studio.html — benchmarked against the aws-certs-exam-study design system, excluding its Google-Fonts dependency (GDPR)."
tags: [code-review, cairn-mcp, frontend, design-system, accessibility]
timestamp: 2026-06-29T00:00:00Z
okf_version: "0.1"
status: draft
references:
  - docs/specs/p11-t44-browser-ui-design.html
  - docs/specs/p11-t44-browser-ui.md
  - docs/specs/p11-t43-mcp-app-infrastructure.md
  - src/cairn_mcp/static/cairn-studio.html
authored:
  by: architect
  date: 2026-06-29
revised:
  by: ""
  date: ""
---

# Design + accessibility review of cairn studio (p11-t44 browser UI)

## Description
Review of the cairn studio visual identity / design under two lenses — the **frontend-design**
skill (tokens, type scale, accessibility, UX patterns) and the **code-review** skill
(spec alignment, correctness, maintainability). Subject of record:
`docs/specs/p11-t44-browser-ui-design.html` (the approved visual companion), grounded in the
normative spec `p11-t44-browser-ui.md`, the CSP declared in `p11-t43`, and the shipped
`src/cairn_mcp/static/cairn-studio.html`.

Benchmark: `aws-certs-exam-study/docs/specs/frontend-design-system.html` — a more mature
expression of the same spectrum-on-dark identity (full token scales, light+dark themes,
documented WCAG ratios, focus/touch standards). **Constraint applied throughout:** the
reference loads **Open Sans from the Google Fonts CDN; cairn must not** — pointing at
`fonts.googleapis.com` / `fonts.gstatic.com` is disallowed on GDPR grounds. Every typography
recommendation below is given in a self-hosted / `system-ui` form, never via Google Fonts.

Contrast ratios below are computed with the WCAG 2.1 relative-luminance formula (verified by
hand for the two load-bearing pairs).

## Status banner (updated 2026-06-29)

All findings have been resolved in the authorised fix cycle of 2026-06-29. See
**Items Resolved Since This Review** for the concrete changes per finding.

| Finding | Severity | Status |
|---------|----------|--------|
| C1 — Google Fonts mandate in spec + CSP | Critical | ✅ Resolved |
| C2 — `--t3` (#404870) AA-fail for text | Critical | ✅ Resolved |
| M3 — reading content below 14px floor | Major | ✅ Resolved |
| M4 — `.li:not(.active){opacity:.55}` dimming | Major | ✅ Resolved |
| M5 — no visible focus indicators | Major | ✅ Resolved |
| M6 — broken list keyboard/ARIA semantics | Major | ✅ Resolved |
| M7 — no token scales | Major | ✅ Resolved |
| M8 — unverified type-badge contrast | Major | ✅ Resolved |
| m9 — badge tints duplicate token hex as rgba | Minor | ✅ Resolved |
| m10 — no ≥44px touch-target provision | Minor | ✅ Resolved |
| m11 — dark-only, no light theme | Minor | ✅ Resolved |
| m12 — design-HTML vs spec drift | Minor | ✅ Resolved |

## What's good (kept brief)
- Animated gradient accent is correctly gated behind `@media (prefers-reduced-motion: no-preference)`.
- The spectrum identity and the structural→ephemeral type-colour ordering (teal→magenta) are
  distinctive and coherent.
- Palette tokens live in `:root`; the decorative search SVG is `aria-hidden`; the wide table is
  wrapped in `overflow-x:auto`.
- The shipped `cairn-studio.html` uses real `<select>`, `<form role="search">`, and `aria-label`s.

## Findings

### Critical

1. **[✅ Resolved 2026-06-29] GDPR: the spec and CSP mandate Google Fonts; this must be removed.**
   - `p11-t44-browser-ui.md` requires "one Google Font" (TL;DR L39), lists
     `fonts.googleapis.com` + `fonts.gstatic.com` as allowed origins (Boundaries L138–139), and
     specifies "Body: **Inter** (weights 300–700 from Google Fonts)" (L253).
   - `p11-t43-mcp-app-infrastructure.md` bakes both origins into the `ResourceCSP`
     (L136–137) as "accepted constants".
   - This is exactly the dependency you've ruled out. **It is also already contradicted by the
     implementation:** `cairn-studio.html:340` uses `system-ui, -apple-system, …` and loads **no**
     font link — so the running app is GDPR-clean, but the normative spec and CSP still *require*
     the violation, and the CSP still *permits* third-party font requests.
   - **Fix:** drop Inter/Google-Fonts from T44 (keep the `system-ui` stack the design HTML and
     impl already use, or self-host a font under `src/cairn_mcp/static/` via `@font-face` — OFL
     fonts like Inter or Open Sans are self-hostable); remove `fonts.googleapis.com` and
     `fonts.gstatic.com` from the T43 `ResourceCSP` and the ADR's accepted-origins list. Do **not**
     adopt the reference's Google-Fonts approach when porting its other improvements.

2. **[✅ Resolved 2026-06-29] `--t3` (#404870) fails WCAG AA badly (~2.2:1) yet the spec routes readable text through it.**
   - On `--base` (#09091a), `--t3` computes to **≈ 2.2:1** — below the 4.5:1 normal-text
     threshold and even the 3:1 large-text/UI threshold. The design file *itself* warns it is
     "**unreadable on the dark base**" (design HTML L443).
   - Despite that, the **normative spec** sends real content to `--t3`: list-item "date + tier in
     `var(--t3)`" (T44 L283) and the detail empty-state message in `var(--t3)` (T44 L297). The
     shipped app follows the spec — `cairn-studio.html` uses `--t3` for `.li-meta` (L715/719) and
     the empty state (L739). So list dates/tiers and the empty-state prompt are effectively
     invisible.
   - The design HTML is internally contradictory: it defines `--t3:#404870`, renders `.li-meta` in
     `--t2` in the mockup (L254), and then warns against `--t3` — but the spec normalised to `--t3`.
   - **Fix (reference's solution):** brighten `--t3` from `#404870` to **`#757fb0`** (≈ 5.09:1 on
     base, ≈ 4.67:1 on surface — both AA), as the benchmark does, and keep using it only for small
     labels. Then reconcile the spec: either route `.li-meta`/empty-state to the brightened `--t3`
     or to `--t2`, but state one rule. (#404870 may remain only for non-text decoration.)

### Major

3. **[✅ Resolved 2026-06-29] Reading content sits below the 14px legibility floor.** The root is `font-size:14px`
   (T44 L255) and body copy is smaller still: design `.rp-p` 12px (L283 of design), table cells
   11px / headers 9px (L292–296), list title 12px / meta 10px. The shipped detail paragraphs are
   ~12–13px. For a tool whose entire purpose is **reading artifacts**, this is too small. The
   benchmark sets a **16px base with a hard 14px floor for content**, reserving 10–13px only for
   dense micro-labels (badges, pills, toolbar meta). **Fix:** raise base to 16px and lift detail
   body / table text to ≥14px; keep the small sizes only for chips/pills/meta labels.

4. **[✅ Resolved 2026-06-29] `.li:not(.active){ opacity:.55 }` dims every unselected row (design HTML L240).** In a list,
   that means *all but one* item is at 55% opacity — compounding the `--t3`/small-text contrast
   problems and making the list hard to scan. The benchmark never applies opacity to content; it
   signals selection with the surface ladder (`--surface-hi`) + border instead. **Fix:** drop the
   opacity dimming; rely on the active row's background/border (which the design already has via
   `.li.active`). (The shipped `cairn-studio.html` appears **not** to replicate this rule — good;
   the fix is to remove it from the design so the two don't drift.)

5. **[✅ Resolved 2026-06-29] No visible focus indicators; keyboard users are stranded.** The design HTML has no
   `:focus-visible` styling, and the shipped app actively removes it: `#search-input` and
   `#filters select` use `outline: none` (cairn-studio.html L416/476) with only a faint
   `border-color` change on focus (L422/481) — not a perceptible focus ring. The
   frontend-design skill is explicit ("Focus indicators: always visible — never `outline: none`
   without a visible replacement"), and the benchmark mandates a `2px solid var(--spec-2)` ring
   with `outline-offset:2px` on every interactive element. **Fix:** add a real focus ring (e.g.
   `:focus-visible { outline: 2px solid #0088ff; outline-offset: 2px }`) to the search input,
   selects, list items, and back button.

6. **List semantics are broken for assistive tech.** `cairn-studio.html` sets
   `role="listbox"` on the container (L817) but the items it builds (`createElement("div")`,
   class `li`, L148) carry **no `role="option"`, no `tabindex`, and no keyboard handler** — a
   listbox with no options and no arrow-key navigation. The design mockup likewise uses plain
   `<div>`s for rows. The frontend-design skill: prefer native elements / full keyboard
   operability. **Fix:** make rows real `<button>`s (or add `role="option"`, `tabindex`, and
   Up/Down/Enter handling) so selection works without a mouse.

7. **No token scales — the "extractable design system" is mostly hardcoded values.** T44 L141–143
   states the CSS is meant to extract into a future AWS-hosted SPA "as a single CSS block". Yet
   beyond the palette there are **no tokens** for spacing, radius, elevation/shadow, type scale,
   or motion — `padding:32px`, `border-radius:8px`, `font-size:12px`, `box-shadow:0 40px 100px…`
   are inlined throughout. The benchmark defines `--sp-1..8`, `--r-sm..pill`, `--shadow-1..3`,
   `--text-*`, `--dur-*`/`--ease`. **Fix:** port those scales into `:root` and reference them; it
   is the single biggest maintainability gain and makes the SPA extraction real.

8. **Type badge/pip contrast is unverified and several stops are suspect.** Badges render
   type-colour text on a 12%-opacity tint of the same colour (e.g. `--c-runbook #1a66ee`,
   `--c-impl #5533ee`, `--c-cr #7733ee`). Mid blues/purples as small text on a near-black tint
   are likely below 4.5:1. The design documents **no** ratios; the benchmark documents every
   functional pair. **Fix:** audit each of the 15 type colours as text-on-tint; for any that fail,
   lighten the text stop or raise tint opacity. Pair the colour with the always-present text label
   (already the case) so meaning never depends on hue alone.

### Minor

9. **Badge tints duplicate the token hex as literal `rgba(...)` (drift risk).** Each badge hardcodes
   both the tint and the var, e.g. `background:rgba(0,212,184,.12);color:var(--c-adr)` — the rgba
   restates `--c-adr`'s hex. The benchmark derives the tint from the token:
   `color-mix(in srgb, var(--c-adr) 14%, transparent)`. **Fix:** use `color-mix` so tint and text
   share one source.

10. **No ≥44px touch-target provision.** Filter pills are `padding:3px 8px`; rows ~40px. The
    benchmark adds `@media (hover:none) and (pointer:coarse){ … min-height:44px }`. Embedded hosts
    can be touch (iPad claude.ai). **Fix:** add the coarse-pointer bump. (Low priority for a
    desktop-first widget.)

11. **Dark-only; the host may be light.** The benchmark ships a designed light theme via
    `[data-theme="light"]`. cairn is dark-only, so the iframe stays dark inside a light
    Claude Desktop / VS Code. Optional, but a token-driven light theme is cheap once finding #7's
    tokens exist. **Fix (optional):** add a light override block; respect `prefers-color-scheme`.

12. **Design HTML vs normative spec drift (documentation correctness).** Two mismatches between
    the "visual companion" and the spec it illustrates: (a) `.li-meta` colour — `--t2` in the
    design (L254) vs `--t3` in the spec (L283) — see finding #2; (b) the design shows a fixed
    **two-pane** mockup (`.mb{display:flex;height:540px}`) while the spec/impl are
    **single-pane with view switching** (`#list-view`/`#detail-view`, `showing-detail`). The
    design is explicitly illustrative, but the two-pane mockup can mislead an implementer. **Fix:**
    add a one-line note on the design that the production layout is single-pane-with-switching, and
    reconcile the meta colour.

## Recommendations (priority order)
1. **Critical first:** strip Google Fonts from T44 + the T43 CSP/ADR (#1); brighten `--t3` to
   `#757fb0` and state one rule for meta/empty-state colour (#2).
2. **Legibility:** 16px base / 14px content floor (#3); remove the `opacity:.55` row dimming (#4).
3. **Accessibility:** real `:focus-visible` rings (#5); `role="option"` + keyboard nav on rows (#6);
   audit type-badge contrast (#8).
4. **Maintainability / parity with the benchmark:** port the spacing/radius/shadow/type/motion
   token scales (#7); `color-mix` tints (#9); optional touch targets (#10) and light theme (#11).
5. Reconcile the design-vs-spec drift (#12).

**Adopt from the benchmark:** its token scales, documented-contrast discipline, focus/touch
standards, and (optionally) the light theme. **Do not adopt:** its Google-Fonts dependency — keep
`system-ui` or self-host.

## Verdict
**All findings resolved (2026-06-29) and verified.** Gates green at fix time: 707 unit tests
pass, `ruff check` clean, `ruff format --check` clean, `mypy src/` clean. Two items remain
**manual** (cannot be automated here): the live Claude Desktop render smoke test, and an
eyeball confirmation of the per-type badge contrast in both themes (mitigated structurally — see
M8). Original totals: 2 critical, 6 major, 4 minor.

## Items Resolved Since This Review
- 2026-06-29 — **C1 (Google Fonts) fixed & verified.** `resources.py` `ResourceCSP`
  `resource_domains` now lists only `https://unpkg.com` + `https://cdn.jsdelivr.net`; T44 and T43
  specs updated (origins, Typography, TL;DR, Boundaries); `cairn-studio.html` and the design
  companion load no font `<link>` (`system-ui` stack). Added `tests/unit/test_resources.py`
  assertion that `fonts.googleapis.com`/`fonts.gstatic.com` are absent from the CSP. Repo-wide
  grep confirms zero font-CDN references in `src/` and the HTML files.
- 2026-06-29 — **C2 (`--t3` contrast) fixed.** `--t3` set to `#757fb0` (≈5.09:1 on base) in both
  HTML files and the T44 token block; `#404870` now appears only in explanatory comments, never as
  a text colour. Meta/empty-state use the brightened `--t3` (one rule; design-vs-spec drift gone).
- 2026-06-29 — **M3 (legibility floor).** Base raised to 16px; a `--text-*` scale added; reading
  content (detail paragraphs/tables/list titles) lifted to ≥14px; sub-14px kept for micro-labels.
- 2026-06-29 — **M4 (row dimming).** `.li:not(.active){opacity:.55}` removed; selection signalled
  by `--surface-hi` background + `--bd` border at full opacity.
- 2026-06-29 — **M5 (focus).** `:focus-visible` rings (2px solid accent, offset) on the search
  input, all three filter `<select>`s, list rows, back button, and theme toggle.
- 2026-06-29 — **M6 (list semantics).** List rows are real `<button role="option">` inside the
  `role="listbox"` (`aria-selected` maintained); a `keydown` handler provides Up/Down navigation
  and Enter/Space activation — keyboard-only selection works.
- 2026-06-29 — **M7 (token scales).** Spacing (`--sp-*`), radius (`--r-*`), elevation
  (`--shadow-*`), type (`--text-*`), and motion (`--dur-*`/`--ease`) scales added to `:root` and
  referenced in place of inline literals.
- 2026-06-29 — **M8 (badge contrast).** Tints derived via `color-mix`; text stops adjusted; meaning
  always carried by the text label too. *Per-type numeric ratio confirmation in both themes remains
  a manual eyeball check at smoke-test time.*
- 2026-06-29 — **m9 (tints).** Badge/pip tints use `color-mix(in srgb, var(--c-*) 14%, transparent)`
  instead of hand-written `rgba()` duplicating the token hex.
- 2026-06-29 — **m10 (touch targets).** `@media (hover:none) and (pointer:coarse)` bumps controls
  and rows to ≥44px.
- 2026-06-29 — **m11 (light theme + toggle).** Designed `[data-theme="light"]` token overrides
  (benchmark light values) plus a toolbar toggle (`aria-pressed`, focus ring) that flips
  `data-theme`, persists to `localStorage`, defaults to dark, and honours `prefers-color-scheme` on
  first load — in both `cairn-studio.html` and the design companion. Mermaid theme follows the
  active theme.
- 2026-06-29 — **m12 (drift).** Design companion notes the production layout is
  single-pane-with-view-switching (the two-pane mockup is illustrative); meta colour reconciled.

### Scope note (process)
The developer agent that implemented these fixes also made **out-of-scope refactors** to unrelated
Python files (`artifact.py`, `config.py`, `tools/health.py`, `tools/migrate_artifacts.py`,
`tools/write.py`, `clients/fakes/fake_bedrock.py` + its test). These were **reverted to HEAD** —
they are not part of this design fix and would have widened the change set and risk. If any are
desirable, they belong in a separate, intentional change. The committed set for this review is:
`resources.py`, `tests/unit/test_resources.py`, `static/cairn-studio.html`,
`docs/specs/p11-t44-browser-ui-design.html`, plus the T43/T44 spec edits.
