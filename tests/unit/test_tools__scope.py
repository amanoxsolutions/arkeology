"""Direct unit tests for arkeology.tools._scope — is_own_scope / is_cross_scope_readable.

Task 63 (Phase 12, codebase-hygiene pass): these predicates are newly extracted
shared helpers, so TDD applies to them directly (unlike the pure-refactor call-site
updates that follow, which are covered by the existing tool test suites).
"""

from decimal import Decimal

import pytest

from arkeology.clients.filter import matches_filter
from arkeology.tools._scope import (
    build_scope_filter,
    is_cross_scope_readable,
    is_own_scope,
)


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

    def test_tier_is_coerced_so_both_metadata_encodings_gate_identically(self) -> None:
        """``tier`` reaches this gate as an ``int`` from vector metadata and as a
        *stringified* int from S3 object metadata, and both must gate the same way.

        ``list_artifacts`` and ``search_artifacts`` pass vector metadata, where AGENTS.md
        requires ``tier`` be stored as an int for filter compatibility. ``read_artifact``
        passes S3 object metadata, where the S3 API permits only string values. The
        ``int()`` coercion in this predicate is the only thing reconciling them.

        Simplifying that coercion away — ``meta.get("tier") == 3`` — would leave
        ``list_artifacts`` working while every cross-scope ``read_artifact`` started
        denying tier-3 shared artifacts, because ``"3" == 3`` is False. The break would be
        fail-closed and therefore silent: a total loss of cross-team reads presenting as
        an access denial, with search still listing the artifacts as readable.
        """
        for tier in (3, "3"):
            meta = {"tier": tier, "visibility": "shared"}
            assert (
                is_cross_scope_readable(meta, "team-b/x", "team-a", read_prefixes=["team-b"])
                is True
            ), f"tier={tier!r} ({type(tier).__name__}) should be readable"

        for tier in (2, "2"):
            meta = {"tier": tier, "visibility": "shared"}
            assert (
                is_cross_scope_readable(meta, "team-b/x", "team-a", read_prefixes=["team-b"])
                is False
            ), f"tier={tier!r} ({type(tier).__name__}) should be denied"

    def test_empty_read_prefixes_denies_foreign(self) -> None:
        meta = {"tier": 3, "visibility": "shared"}
        assert is_cross_scope_readable(meta, "team-b/x", "team-a", read_prefixes=[]) is False


class _StringifiesToShared:
    """A stored value that is not ``"shared"`` but whose text is — the case a ``str()``
    coercion inside the gate would wrongly admit."""

    def __str__(self) -> str:
        return "shared"


class TestTheGateIsTotal:
    """The gate is a predicate over data this deployment did not write, so it must
    answer for every stored value rather than raising for some of them.

    It is applied per candidate inside a loop, so one foreign record another team's
    deployment wrote badly used to abort the whole listing, search, or reference
    resolution for that scope — an availability outage caused by someone else's data
    quality. Denial is the only admissible answer: it is what the server-side filter
    form already does, and it is never an allow.
    """

    @staticmethod
    def _verdict(tier: object = 3, visibility: object = "shared") -> bool:
        return is_cross_scope_readable(
            {"tier": tier, "visibility": visibility},
            "team-b/x",
            "team-a",
            read_prefixes=["team-b"],
        )

    @pytest.mark.parametrize(
        "tier",
        ["abc", "", None, "3.5", [3], {"tier": 3}, object(), float("inf"), Decimal("Infinity")],
        ids=[
            "non-numeric",
            "empty",
            "null",
            "non-integer",
            "list",
            "dict",
            "opaque",
            "infinity",
            "decimal-infinity",
        ],
    )
    def test_an_unreadable_tier_denies_rather_than_raising(self, tier: object) -> None:
        assert self._verdict(tier=tier) is False

    @pytest.mark.parametrize(
        "visibility",
        [None, 3, ["shared"], {"visibility": "shared"}, object(), _StringifiesToShared()],
        ids=["null", "int", "list", "dict", "opaque", "stringifies-to-shared"],
    )
    def test_an_unreadable_visibility_denies_rather_than_raising(self, visibility: object) -> None:
        """Only a stored ``visibility`` that *is* ``"shared"`` is an affirmative reading.

        The ``stringifies-to-shared`` case is the one that bites: coercing with
        ``str()`` before comparing admits any object whose text happens to read
        ``shared``, which is a value no writer ever stored. The server-side filter form
        compares the stored value itself and would never match it.
        """
        assert self._verdict(visibility=visibility) is False

    def test_a_wholly_unreadable_candidate_denies(self) -> None:
        """Neither field readable — still an answer, still a denial."""
        assert self._verdict(tier="?", visibility=None) is False

    def test_own_scope_is_unaffected_by_unreadable_metadata(self) -> None:
        """Own scope never consults either field, so corruption there cannot deny a
        caller access to its own artifact."""
        meta: dict[str, object] = {"tier": "corrupt", "visibility": None}
        assert is_cross_scope_readable(meta, "team-a/x", "team-a", read_prefixes=["team-b"]) is True

    def test_a_well_formed_candidate_is_still_readable(self) -> None:
        """The totality guard must not have narrowed the rule itself: the one
        affirmative reading still passes."""
        assert self._verdict() is True


class TestBuildScopeFilter:
    """The gate expressed as a server-side S3 Vectors filter, rather than as an
    in-process predicate.

    ``is_cross_scope_readable`` decides one already-fetched candidate; this builds the
    filter that stops most foreign candidates being fetched at all. The filter is a
    prefetch optimisation and the predicate is the authority — every read path runs the
    predicate — so the filter may admit more than the predicate does, but must never
    admit less. See ``test_never_rejects_a_candidate_the_predicate_would_admit``.

    Assertions here evaluate the returned filter with ``matches_filter`` — the project's
    own in-process implementation of the same operator set S3 Vectors applies — rather
    than comparing the filter dict literally. A shape assertion breaks on any harmless
    re-nesting and, worse, still passes if a clause is present but wrong. Evaluating it
    pins the decision, which is the thing that must not change.

    The ``visibility`` clause is the one that fails *open*: drop it and every foreign
    tier-3 ``hidden`` artifact becomes searchable from another scope. That is the case
    ``test_foreign_tier3_hidden_is_denied`` exists for.
    """

    OWN = "team-a"
    FOREIGN = ["team-b"]

    def _allows(self, meta: dict[str, object], read_prefixes: list[str] | None = None) -> bool:
        expr = build_scope_filter(
            self.OWN, self.FOREIGN if read_prefixes is None else read_prefixes
        )
        return matches_filter(meta, expr)

    def test_own_scope_allowed_regardless_of_tier_and_visibility(self) -> None:
        assert self._allows({"scope": "team-a", "tier": 2, "visibility": "hidden"}) is True

    def test_foreign_tier3_shared_is_allowed(self) -> None:
        assert self._allows({"scope": "team-b", "tier": 3, "visibility": "shared"}) is True

    def test_foreign_tier3_hidden_is_denied(self) -> None:
        """The fail-open direction: without the visibility clause this returns True."""
        assert self._allows({"scope": "team-b", "tier": 3, "visibility": "hidden"}) is False

    def test_foreign_tier2_shared_is_denied(self) -> None:
        """The other fail-open direction: without the tier clause this returns True."""
        assert self._allows({"scope": "team-b", "tier": 2, "visibility": "shared"}) is False

    def test_unconfigured_foreign_scope_is_denied(self) -> None:
        assert self._allows({"scope": "team-c", "tier": 3, "visibility": "shared"}) is False

    def test_no_read_prefixes_denies_every_foreign_artifact(self) -> None:
        """With no read prefixes the filter must admit no foreign artifact at all, not
        fall back to an unrestricted filter."""
        assert self._allows({"scope": "team-a", "tier": 2, "visibility": "hidden"}, []) is True
        assert self._allows({"scope": "team-b", "tier": 3, "visibility": "shared"}, []) is False

    def test_never_rejects_a_candidate_the_predicate_would_admit(self) -> None:
        """The filter may be *more* permissive than the predicate, never less.

        The two forms are not peers. The predicate is the authority — every read path
        runs it against the candidate's own metadata — and the filter is a prefetch
        optimisation that narrows what is fetched. So the directions are not
        symmetrical:

        - Filter admits, predicate denies → **harmless.** The predicate drops it. This
          is the list-valued case below: ``$eq`` is value-in-list for a list field, the
          semantics ``tags`` depends on, so ``tier: [3]`` matches the filter clause and
          the filter cannot be narrowed without breaking tag matching.
        - Filter rejects, predicate would admit → **a bug.** The candidate is never
          fetched, so the predicate never sees it and a readable artifact silently
          vanishes from every search, synthesise, and listing.

        Only the second direction is asserted, which is why this is an implication and
        not an equality.
        """
        cases: list[dict[str, object]] = [
            {"scope": "team-a", "tier": 2, "visibility": "hidden"},
            {"scope": "team-b", "tier": 3, "visibility": "shared"},
            {"scope": "team-b", "tier": 3, "visibility": "hidden"},
            {"scope": "team-b", "tier": 2, "visibility": "shared"},
            {"scope": "team-c", "tier": 3, "visibility": "shared"},
            # Malformed foreign candidates, scalar — both forms deny these.
            {"scope": "team-b", "visibility": "shared"},
            {"scope": "team-b", "tier": 3},
            {"scope": "team-b", "tier": None, "visibility": "shared"},
            {"scope": "team-b", "tier": "abc", "visibility": "shared"},
            {"scope": "team-b", "tier": "", "visibility": "shared"},
            {"scope": "team-b", "tier": 3, "visibility": None},
            {"scope": "team-b", "tier": 3, "visibility": 3},
            {"scope": "team-b"},
            # Non-scalar: the filter admits these and the predicate denies them. The
            # implication still holds, and the tools' own suites pin that the predicate
            # actually runs — see test_search_never_returns_a_candidate_the_predicate_denies.
            {"scope": "team-b", "tier": [3], "visibility": "shared"},
            {"scope": "team-b", "tier": 3, "visibility": ["shared"]},
        ]
        for meta in cases:
            artifact_id = f"{meta['scope']}/some-artifact"
            if is_cross_scope_readable(meta, artifact_id, self.OWN, self.FOREIGN):
                assert self._allows(meta), (
                    f"the filter would never fetch {meta}, which the predicate admits"
                )
