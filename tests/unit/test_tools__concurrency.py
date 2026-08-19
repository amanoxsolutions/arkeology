"""Direct unit tests for arkeology.tools._concurrency._clamp_concurrency.

Task 68 (Phase 13, codebase-hygiene batch 2): _clamp_concurrency is a newly
extracted shared helper (review finding G-3), replacing the artifact_concurrency
clamp-with-warning logic previously duplicated verbatim in write_artifacts.py and
migrate_artifacts.py, so TDD applies to it directly.
"""

from arkeology.tools._concurrency import _clamp_concurrency


def test_value_within_range_passes_through_with_no_warning() -> None:
    effective, warning = _clamp_concurrency(5, default=3, max_=15)
    assert effective == 5
    assert warning is None


def test_value_above_max_is_capped_with_warning() -> None:
    effective, warning = _clamp_concurrency(20, default=3, max_=15)
    assert effective == 15
    assert warning == (
        "artifact_concurrency=20 exceeds the maximum of 15; effective concurrency capped to 15."
    )


def test_value_below_one_is_substituted_with_default_and_warning() -> None:
    effective, warning = _clamp_concurrency(0, default=3, max_=15)
    assert effective == 3
    assert warning == (
        "artifact_concurrency=0 is below the minimum of 1; "
        "effective concurrency substituted with the default 3."
    )


def test_negative_value_is_substituted_with_default_and_warning() -> None:
    effective, warning = _clamp_concurrency(-5, default=3, max_=15)
    assert effective == 3
    assert warning is not None


def test_value_exactly_at_max_passes_through_with_no_warning() -> None:
    effective, warning = _clamp_concurrency(15, default=3, max_=15)
    assert effective == 15
    assert warning is None


def test_value_exactly_one_passes_through_with_no_warning() -> None:
    effective, warning = _clamp_concurrency(1, default=3, max_=15)
    assert effective == 1
    assert warning is None
