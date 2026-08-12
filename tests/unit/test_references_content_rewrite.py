"""Unit tests for arkeology.references.rewrite_content_references (T56 / FR-52 extension).

Maps to T56 Stories 1-6: deterministic, markdown-aware, server-side content rewrite of
already-resolved frontmatter ``references:`` paths — in the frontmatter block itself AND
in matching markdown body link targets. No AWS, no I/O — this helper is pure.

Frontmatter matching is EXACT (map key == unquoted entry text, byte-for-byte). Body-link
matching normalizes both the candidate path portion and each map key via
``normalize_reference_path`` before comparing (never ``join_reference_path`` — see
Boundaries/Never in the spec and OQ-T56-e). Anchor handling: a matched link's ``#anchor``
is dropped from the rewritten URI and preserved verbatim as a trailing
``("<anchor>" section)`` note. Fenced code blocks (``` ... ```) are never scanned.
"""

from arkeology.references import rewrite_content_references

_B_ID = "myteam/myproject/adr-b-decision-abcd1234.md"

# ---------------------------------------------------------------------------
# Frontmatter — exact match, quote-style preservation, list position/order
# ---------------------------------------------------------------------------


def test_rewrite_frontmatter_unquoted_entry_rewritten() -> None:
    """An unquoted references: entry that exactly matches a map key is rewritten,
    remaining unquoted."""
    content = "---\nreferences:\n  - ../decisions/B.md\n---\n\nBody text.\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert f"  - arkeology://artifact/{_B_ID}\n" in result
    assert "../decisions/B.md" not in result


def test_rewrite_frontmatter_double_quoted_entry_preserves_quotes() -> None:
    """A double-quoted references: entry is rewritten with double quotes preserved."""
    content = '---\nreferences:\n  - "../decisions/B.md"\n---\n\nBody text.\n'
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert f'  - "arkeology://artifact/{_B_ID}"\n' in result


def test_rewrite_frontmatter_single_quoted_entry_preserves_quotes() -> None:
    """A single-quoted references: entry is rewritten with single quotes preserved."""
    content = "---\nreferences:\n  - '../decisions/B.md'\n---\n\nBody text.\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert f"  - 'arkeology://artifact/{_B_ID}'\n" in result


def test_rewrite_frontmatter_mixed_list_only_matching_entry_rewritten_preserves_order() -> None:
    """Given three entries where only the second resolves, only the second is rewritten;
    the first and third are untouched and the list still has three entries in order."""
    content = (
        "---\n"
        "references:\n"
        "  - ../unresolved-1.md\n"
        "  - ../decisions/B.md\n"
        "  - ../unresolved-2.md\n"
        "---\n\nBody text.\n"
    )
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    lines = result.split("\n")
    ref_lines = [line for line in lines if line.strip().startswith("- ")]
    assert ref_lines == [
        "  - ../unresolved-1.md",
        f"  - arkeology://artifact/{_B_ID}",
        "  - ../unresolved-2.md",
    ]


def test_rewrite_frontmatter_empty_references_list_is_noop() -> None:
    """An empty flow-style references: [] list is left completely untouched."""
    content = "---\nreferences: []\ntitle: X\n---\n\nBody text.\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert result == content


def test_rewrite_frontmatter_no_references_key_is_noop() -> None:
    """A file with no references: key at all is a no-op for the frontmatter section."""
    content = "---\ntitle: X\n---\n\nBody text.\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert result == content


# ---------------------------------------------------------------------------
# Body links — exact/normalized match, collision safety, multiple occurrences
# ---------------------------------------------------------------------------


def test_rewrite_body_link_exact_match_rewritten() -> None:
    """A body markdown link using the exact resolved path text is rewritten; the link
    text is left unchanged."""
    content = "---\ntitle: X\n---\n\nSee [the decision](../decisions/B.md) for context.\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert f"[the decision](arkeology://artifact/{_B_ID})" in result
    assert "../decisions/B.md" not in result


def test_rewrite_body_link_longer_token_not_rewritten_collision_safety() -> None:
    """A body link to a longer token that merely contains the map key as a substring
    (docs/a.md vs docs/a.md.bak) is left completely untouched (whole-value equality)."""
    content = "---\ntitle: X\n---\n\n[other](docs/a.md.bak) and [ok](docs/a.md)\n"
    resolved_map = {"docs/a.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert "[other](docs/a.md.bak)" in result
    assert f"[ok](arkeology://artifact/{_B_ID})" in result


def test_rewrite_body_link_two_occurrences_both_rewritten() -> None:
    """The same resolved path appearing as two separate body links is rewritten both
    times, not just the first."""
    content = (
        "---\ntitle: X\n---\n\n"
        "First mention [one](../decisions/B.md).\n"
        "Second mention [two](../decisions/B.md).\n"
    )
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert result.count(f"arkeology://artifact/{_B_ID}") == 2
    assert "../decisions/B.md" not in result


def test_rewrite_body_link_normalization_equivalent_leading_dot_slash_rewritten() -> None:
    """A body link spelled with a leading './' that normalizes (via
    normalize_reference_path) to the map key is rewritten."""
    content = "---\ntitle: X\n---\n\n[link](./decisions/B.md)\n"
    resolved_map = {"decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert f"[link](arkeology://artifact/{_B_ID})" in result


def test_rewrite_body_link_normalization_equivalent_backslash_rewritten() -> None:
    """A body link spelled with backslash separators that normalizes to the map key is
    rewritten."""
    content = "---\ntitle: X\n---\n\n[link](decisions\\B.md)\n"
    resolved_map = {"decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert f"[link](arkeology://artifact/{_B_ID})" in result


def test_rewrite_body_link_join_only_equivalent_left_untouched() -> None:
    """OQ-T56-e: a body link spelled in the already-joined form ('decisions/B.md') when
    the map key is still the original, un-joined relative text ('../decisions/B.md') is
    NOT rewritten — only normalize_reference_path is applied, never join_reference_path,
    inside the pure content helper (no per-occurrence file context is available)."""
    content = "---\ntitle: X\n---\n\n[link](decisions/B.md)\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert result == content


def test_rewrite_body_link_text_never_altered_even_if_matches_key() -> None:
    """Link text (inside [...]) is never rewritten even if it textually matches a map
    key — only the target is a rewrite candidate."""
    content = "---\ntitle: X\n---\n\n[../decisions/B.md](../decisions/B.md)\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert f"[../decisions/B.md](arkeology://artifact/{_B_ID})" in result


def test_rewrite_body_link_url_never_candidate_even_if_text_matches_key() -> None:
    """An http(s):// link target is never a rewrite candidate, even when its link text
    matches a map key, and even when the map (pathologically) contains a URL key."""
    content = "---\ntitle: X\n---\n\n[../decisions/B.md](https://example.com/../decisions/B.md)\n"
    resolved_map = {"../decisions/B.md": _B_ID, "https://example.com/../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert result == content


# ---------------------------------------------------------------------------
# Body-link anchors — drop from URI, preserve as a verbatim trailing note
# ---------------------------------------------------------------------------


def test_rewrite_body_link_with_anchor_drops_anchor_appends_note() -> None:
    """A matched link carrying an anchor is rewritten with the anchor dropped from the
    URI and a human-readable note appended immediately after the closing ')'."""
    content = "---\ntitle: X\n---\n\n[the decision](../decisions/B.md#outcome)\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert f'[the decision](arkeology://artifact/{_B_ID}) ("outcome" section)' in result
    assert "#outcome" not in result


def test_rewrite_body_link_hyphenated_anchor_kept_verbatim() -> None:
    """A hyphenated/multi-word anchor is preserved verbatim in the note, never
    de-slugified to 'my decision'."""
    content = "---\ntitle: X\n---\n\n[x](../decisions/B.md#my-decision)\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert f'[x](arkeology://artifact/{_B_ID}) ("my-decision" section)' in result
    assert "my decision" not in result


def test_rewrite_body_link_no_anchor_no_note() -> None:
    """A matched link with no anchor is rewritten with no appended note."""
    content = "---\ntitle: X\n---\n\n[the decision](../decisions/B.md)\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert result.count("(") == result.count(")") == 1  # only the link's own parens
    assert "section)" not in result


def test_rewrite_body_link_anchored_idempotent_no_double_note() -> None:
    """Running the helper twice on an already-anchor-rewritten link yields identical
    output — the note is not re-appended (the rewritten target has no '#', and
    arkeology://... is never a resolved_map key)."""
    content = "---\ntitle: X\n---\n\n[the decision](../decisions/B.md#outcome)\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    once = rewrite_content_references(content, resolved_map)
    twice = rewrite_content_references(once, resolved_map)

    assert once == twice
    assert once.count("section)") == 1


def test_rewrite_hash_inside_fenced_code_block_is_skipped() -> None:
    """A '#' appearing inside a fenced code block is still skipped — the whole fenced
    region is untouched and anchor logic never runs on it."""
    content = "---\ntitle: X\n---\n\n```\n[link](../decisions/B.md#outcome)\n```\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert result == content


# ---------------------------------------------------------------------------
# Non-goals — undeclared links, bare prose, fenced code blocks
# ---------------------------------------------------------------------------


def test_rewrite_body_link_undeclared_path_left_untouched() -> None:
    """A body link to a path never present in resolved_map (i.e. never declared in this
    file's own frontmatter references:) is left completely untouched — even though the
    helper has no way to know whether it is resolvable elsewhere; this is D1's discovery
    boundary, enforced simply by the map never containing that key."""
    content = "---\ntitle: X\n---\n\n[unrelated](../decisions/C.md)\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert result == content


def test_rewrite_bare_prose_mention_left_untouched() -> None:
    """A bare prose mention with no markdown link syntax is left untouched, even though
    the path did resolve from this file's frontmatter."""
    content = "---\ntitle: X\n---\n\nsee ../decisions/B.md for details\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert result == content


def test_rewrite_fenced_code_block_left_untouched_byte_for_byte() -> None:
    """Text inside a fenced code block is left byte-for-byte untouched even though it
    would otherwise match a frontmatter or body pattern."""
    content = (
        "---\n"
        "references:\n"
        "  - ../decisions/B.md\n"
        "---\n\n"
        "Example:\n"
        "```\n"
        "[link](../decisions/B.md)\n"
        "```\n"
    )
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert "```\n[link](../decisions/B.md)\n```" in result
    # But the frontmatter occurrence (outside the fence) IS rewritten.
    assert f"  - arkeology://artifact/{_B_ID}" in result


def test_rewrite_unterminated_fence_treated_as_code_to_end_of_content() -> None:
    """An unterminated (odd count) code fence does not raise — everything from the
    unmatched opening fence to end-of-content is treated as still-inside-code and left
    untouched."""
    content = "---\ntitle: X\n---\n\n```\n[link](../decisions/B.md)\nMore text.\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert result == content


# ---------------------------------------------------------------------------
# Purity / determinism
# ---------------------------------------------------------------------------


def test_rewrite_same_inputs_twice_produces_identical_output() -> None:
    """The same (content, resolved_map) produces byte-identical output across two calls."""
    content = "---\nreferences:\n  - ../decisions/B.md\n---\n\n[x](../decisions/B.md)\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    result1 = rewrite_content_references(content, resolved_map)
    result2 = rewrite_content_references(content, resolved_map)

    assert result1 == result2


def test_rewrite_idempotent_on_already_rewritten_content() -> None:
    """Content already rewritten once, passed through again with the same map, is
    unchanged — no double-wrapping, no nested arkeology://artifact/arkeology://artifact/..."""
    content = "---\nreferences:\n  - ../decisions/B.md\n---\n\n[x](../decisions/B.md)\n"
    resolved_map = {"../decisions/B.md": _B_ID}

    once = rewrite_content_references(content, resolved_map)
    twice = rewrite_content_references(once, resolved_map)

    assert once == twice
    assert "arkeology://artifact/arkeology://artifact/" not in twice


def test_rewrite_empty_map_returns_content_unchanged() -> None:
    """An empty resolved_map returns content completely unchanged, including whitespace
    and formatting in the frontmatter block."""
    content = "---\nreferences:\n  - ../decisions/B.md\ntitle:   X  \n---\n\nBody.\n"

    result = rewrite_content_references(content, {})

    assert result == content


def test_rewrite_absent_map_returns_content_unchanged() -> None:
    """A None resolved_map (the 'absent' case) returns content completely unchanged."""
    content = "---\nreferences:\n  - ../decisions/B.md\n---\n\nBody.\n"

    result = rewrite_content_references(content, None)

    assert result == content


def test_rewrite_key_with_no_occurrence_anywhere_is_safe_noop() -> None:
    """A map key with no occurrence anywhere in content is a safe no-op — it does not
    raise and content is returned unchanged."""
    content = "---\ntitle: X\n---\n\nNo references here at all.\n"
    resolved_map = {"../decisions/never-mentioned.md": _B_ID}

    result = rewrite_content_references(content, resolved_map)

    assert result == content
