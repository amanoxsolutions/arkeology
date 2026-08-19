"""Direct unit tests for arkeology.tools._scope — is_own_scope / is_cross_scope_readable.

Task 63 (Phase 12, codebase-hygiene pass): these predicates are newly extracted
shared helpers, so TDD applies to them directly (unlike the pure-refactor call-site
updates that follow, which are covered by the existing tool test suites).
"""

from arkeology.tools._scope import is_cross_scope_readable, is_own_scope


class TestIsOwnScope:
    def test_matches_own_scope(self) -> None:
        assert is_own_scope("team-a/implementation-note-x", "team-a") is True

    def test_rejects_foreign_scope(self) -> None:
        assert is_own_scope("team-b/implementation-note-x", "team-a") is False

    def test_rejects_prefix_collision(self) -> None:
        """A scope of 'team-a' must never match 'team-abc/...' (AGENTS.md's own
        highest-friction correctness rule)."""
        assert is_own_scope("team-abc/implementation-note-x", "team-a") is False

    def test_rejects_scope_with_no_slash_separator(self) -> None:
        assert is_own_scope("team-a", "team-a") is False


class TestIsCrossScopeReadable:
    def test_own_scope_always_readable_regardless_of_meta(self) -> None:
        meta: dict[str, object] = {}
        assert is_cross_scope_readable(meta, "team-a/x", "team-a", read_prefixes=["team-b"]) is True

    def test_foreign_scope_tier3_shared_is_readable(self) -> None:
        meta = {"tier": 3, "visibility": "shared"}
        assert is_cross_scope_readable(meta, "team-b/x", "team-a", read_prefixes=["team-b"]) is True

    def test_foreign_scope_tier2_is_not_readable(self) -> None:
        meta = {"tier": 2, "visibility": "shared"}
        assert (
            is_cross_scope_readable(meta, "team-b/x", "team-a", read_prefixes=["team-b"]) is False
        )

    def test_foreign_scope_hidden_is_not_readable(self) -> None:
        meta = {"tier": 3, "visibility": "hidden"}
        assert (
            is_cross_scope_readable(meta, "team-b/x", "team-a", read_prefixes=["team-b"]) is False
        )

    def test_unconfigured_foreign_scope_is_not_readable(self) -> None:
        """artifact_id matches neither own_scope nor any read_prefixes entry."""
        meta = {"tier": 3, "visibility": "shared"}
        assert (
            is_cross_scope_readable(meta, "team-c/x", "team-a", read_prefixes=["team-b"]) is False
        )

    def test_missing_tier_defaults_gracefully_not_readable(self) -> None:
        meta = {"visibility": "shared"}
        assert (
            is_cross_scope_readable(meta, "team-b/x", "team-a", read_prefixes=["team-b"]) is False
        )

    def test_missing_visibility_defaults_gracefully_not_readable(self) -> None:
        meta = {"tier": 3}
        assert (
            is_cross_scope_readable(meta, "team-b/x", "team-a", read_prefixes=["team-b"]) is False
        )

    def test_empty_read_prefixes_denies_foreign(self) -> None:
        meta = {"tier": 3, "visibility": "shared"}
        assert is_cross_scope_readable(meta, "team-b/x", "team-a", read_prefixes=[]) is False
