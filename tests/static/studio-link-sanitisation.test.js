// Guards the security property documented inline in arkeology-studio.html around
// classifyContentLinks and renderDetailContent: an arkeology://artifact/{id} link must
// resolve to a data-artifact-id control and never to an href DOMPurify's URI allow-list
// would otherwise strip, and target/rel must only ever be set after sanitising, on hrefs
// that survived it — never smuggled in by artifact content or added before DOMPurify runs.
//
// Runs the actual classifyContentLinks / renderDetailContent source sliced out of the
// shipped HTML file (see extractBlock below) against the real `dompurify` package, so this
// fails the moment either function's behaviour drifts from what the file's own comments
// promise — not a reimplementation that could silently diverge from the shipped logic.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { JSDOM } from "jsdom";
import createDOMPurify from "dompurify";

const here = path.dirname(fileURLToPath(import.meta.url));
const studioPath = path.join(here, "..", "..", "src", "arkeology", "static", "arkeology-studio.html");
const html = readFileSync(studioPath, "utf8");

const moduleMatch = html.match(/<script type="module">([\s\S]*?)<\/script>/);
assert.ok(moduleMatch, 'expected a <script type="module"> block in arkeology-studio.html');
const moduleSource = moduleMatch[1];

// ponytail: a brace-depth counter, not a JS parser — sound only because none of the four
// functions/consts sliced out below contain an unmatched `{`/`}` inside a string, regex, or
// comment (verified by hand; the module has no other candidates for this test). If a future
// edit to one of those bodies introduces one, this throws "unbalanced braces" rather than
// silently mis-slicing — reach for a real parser (e.g. acorn) only if that ever fires.
function extractBlock(source, signature) {
  const start = source.indexOf(signature);
  assert.ok(start !== -1, `expected to find "${signature}" in arkeology-studio.html`);
  const braceStart = source.indexOf("{", start);
  let depth = 0;
  for (let i = braceStart; i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}") {
      depth--;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error(`unbalanced braces extracting "${signature}"`);
}

function extractStatement(source, prefix) {
  const start = source.indexOf(prefix);
  assert.ok(start !== -1, `expected to find "${prefix}" in arkeology-studio.html`);
  const end = source.indexOf(";", start);
  return source.slice(start, end + 1);
}

const artifactUriPrefixSrc = extractStatement(moduleSource, "const ARTIFACT_URI_PREFIX");
const artifactTargetSrc = extractBlock(moduleSource, "function artifactTarget(href)");
const classifyContentLinksSrc = extractBlock(moduleSource, "function classifyContentLinks(html)");
const escHtmlSrc = extractBlock(moduleSource, "function escHtml(str)");
const renderDetailContentSrc = extractBlock(moduleSource, "async function renderDetailContent(content)");

// Builds classifyContentLinks/renderDetailContent from the sliced source above, wired to a
// real DOMPurify (same version pinned in the HTML's CDN import) backed by a fresh jsdom
// window. `marked` and `mermaid` are stubbed: neither is part of the security path under
// test, and every payload below is already HTML, so marked's real behaviour ("passes raw
// HTML through unchanged", per the import comment in arkeology-studio.html) is exactly what
// the passthrough stub does.
function loadStudioFunctions() {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://studio.invalid/" });
  const DOMPurify = createDOMPurify(dom.window);
  const marked = { parse: (s) => s };
  const mermaid = { run: async () => {} };

  const factory = new Function(
    "document",
    "DOMParser",
    "DOMPurify",
    "marked",
    "mermaid",
    `${artifactUriPrefixSrc}
     ${artifactTargetSrc}
     ${classifyContentLinksSrc}
     ${escHtmlSrc}
     ${renderDetailContentSrc}
     return { classifyContentLinks, renderDetailContent };`,
  );

  return { ...factory(dom.window.document, dom.window.DOMParser, DOMPurify, marked, mermaid), window: dom.window };
}

test("classifyContentLinks is only ever invoked as the argument to DOMPurify.sanitize(...)", () => {
  // One match is the function declaration itself, the other the single call site — proves
  // the classified-but-unsanitised string never reaches anywhere else in the module,
  // matching the "runs before the sanitiser, never after" comment on classifyContentLinks.
  const callSites = moduleSource.match(/classifyContentLinks\(/g) ?? [];
  assert.equal(callSites.length, 2, "expected exactly one declaration and one call site");
  assert.match(moduleSource, /DOMPurify\.sanitize\(classifyContentLinks\(/);
});

test("classifyContentLinks resolves an arkeology:// artifact link to data-artifact-id, never to an href", () => {
  const { classifyContentLinks } = loadStudioFunctions();
  const out = classifyContentLinks('<a href="arkeology://artifact/note-2026-08-01-bar-deadbeef">Related note</a>');
  assert.ok(!out.includes("arkeology:"), "arkeology: scheme must never survive classification");
  assert.match(out, /data-artifact-id="note-2026-08-01-bar-deadbeef"/);
});

test("classifyContentLinks strips non-artifact, non-http(s) hrefs (e.g. javascript:) while keeping the link text", () => {
  const { classifyContentLinks } = loadStudioFunctions();
  const out = classifyContentLinks('<a href="javascript:alert(document.cookie)">evil</a>');
  assert.ok(!out.includes("javascript:"));
  assert.ok(out.includes("evil"));
});

test("classifyContentLinks leaves ordinary http(s) links untouched", () => {
  const { classifyContentLinks } = loadStudioFunctions();
  const out = classifyContentLinks('<a href="https://example.com/docs">Example</a>');
  assert.match(out, /href="https:\/\/example\.com\/docs"/);
});

test("renderDetailContent: arkeology link becomes an inert control, smuggled target/javascript: never survive, plain http(s) links keep working", async () => {
  const { renderDetailContent, window } = loadStudioFunctions();
  const contentArea = window.document.createElement("div");
  contentArea.id = "rp-content-area";
  window.document.body.appendChild(contentArea);

  const payload = [
    '<a href="arkeology://artifact/note-2026-08-01-bar-deadbeef">Related note</a>',
    '<a href="javascript:alert(document.cookie)" target="_blank">smuggled js</a>',
    '<a href="https://example.com/docs" target="_self" onclick="alert(1)">legit link</a>',
  ].join("\n");

  await renderDetailContent(payload);
  const result = contentArea.innerHTML;

  assert.ok(!/arkeology:/i.test(result), "arkeology: must never reach the DOM as a URI");
  assert.ok(!/javascript:/i.test(result), "javascript: must never reach the DOM");

  const artifactLink = contentArea.querySelector('a[data-artifact-id="note-2026-08-01-bar-deadbeef"]');
  assert.ok(artifactLink, "artifact link must be classified as a data-artifact-id control");
  assert.ok(!artifactLink.hasAttribute("href"), "artifact control must carry no href");

  const httpLink = contentArea.querySelector('a[href="https://example.com/docs"]');
  assert.ok(httpLink, "ordinary http(s) link must survive sanitisation");
  assert.equal(httpLink.getAttribute("target"), "_blank", "target is set only after sanitising, overriding any smuggled value");
  assert.equal(httpLink.getAttribute("rel"), "noopener noreferrer");
  assert.ok(!httpLink.hasAttribute("onclick"), "inline event handlers must not survive DOMPurify");

  // No surviving anchor other than the legitimate http(s) one carries a target — proves the
  // target smuggled directly on the javascript: link (and DOMPurify's own attribute
  // allow-list) never leak one through some other path.
  for (const a of contentArea.querySelectorAll("a")) {
    if (a === httpLink) continue;
    assert.ok(!a.hasAttribute("target"), `unexpected target on ${a.outerHTML}`);
  }
});
