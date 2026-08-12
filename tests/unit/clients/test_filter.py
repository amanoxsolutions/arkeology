"""Unit tests for arkeology.clients.filter.matches_filter.

Covers all supported operators: $eq, $in, $nin, $gte, $lte, $and, $or,
plus the plain equality shorthand and the unsupported-operator error.
"""

import pytest

from arkeology.clients.filter import matches_filter
from arkeology.errors import FilterEvaluationError

# ---------------------------------------------------------------------------
# $eq operator
# ---------------------------------------------------------------------------


def test_eq_scalar_match() -> None:
    """$eq matches a scalar field that equals the operand."""
    assert matches_filter({"type": "review"}, {"type": {"$eq": "review"}}) is True


def test_eq_scalar_no_match() -> None:
    """$eq does not match a scalar field that differs from the operand."""
    assert matches_filter({"type": "adr"}, {"type": {"$eq": "review"}}) is False


def test_eq_list_field_value_present() -> None:
    """$eq on a list field matches when the operand is contained in the list."""
    assert matches_filter({"tags": ["a", "b"]}, {"tags": {"$eq": "a"}}) is True


def test_eq_list_field_value_absent() -> None:
    """$eq on a list field does not match when the operand is absent from the list."""
    assert matches_filter({"tags": ["a", "b"]}, {"tags": {"$eq": "c"}}) is False


def test_eq_missing_field_no_match() -> None:
    """$eq on a missing field does not match (None != operand)."""
    assert matches_filter({}, {"type": {"$eq": "review"}}) is False


# ---------------------------------------------------------------------------
# $in operator
# ---------------------------------------------------------------------------


def test_in_scalar_match() -> None:
    """$in matches when the scalar field value is in the operand list."""
    assert matches_filter({"tier": 2}, {"tier": {"$in": [2, 3]}}) is True


def test_in_scalar_no_match() -> None:
    """$in does not match when the scalar field value is not in the operand list."""
    assert matches_filter({"tier": 1}, {"tier": {"$in": [2, 3]}}) is False


def test_in_list_field_any_element_present() -> None:
    """$in on a list field matches when any list element is in the operand."""
    meta = {"tags": ["payments", "auth"]}
    assert matches_filter(meta, {"tags": {"$in": ["auth", "infra"]}}) is True


def test_in_list_field_no_element_present() -> None:
    """$in on a list field does not match when no list element is in the operand."""
    assert matches_filter({"tags": ["payments"]}, {"tags": {"$in": ["auth", "infra"]}}) is False


def test_in_missing_field_no_match() -> None:
    """$in on a missing field does not match (None is not in the list)."""
    assert matches_filter({}, {"tier": {"$in": [2, 3]}}) is False


def test_in_empty_operand_no_match() -> None:
    """$in with an empty operand list never matches."""
    assert matches_filter({"tier": 2}, {"tier": {"$in": []}}) is False


# ---------------------------------------------------------------------------
# $nin operator
# ---------------------------------------------------------------------------


def test_nin_scalar_excluded() -> None:
    """$nin does not match when the scalar value is in the exclusion list."""
    assert matches_filter({"status": "inactive"}, {"status": {"$nin": ["inactive"]}}) is False


def test_nin_scalar_not_excluded() -> None:
    """$nin matches when the scalar value is not in the exclusion list."""
    assert matches_filter({"status": "active"}, {"status": {"$nin": ["inactive"]}}) is True


def test_nin_list_field_no_overlap() -> None:
    """$nin on a list field matches when no element overlaps with the exclusion list."""
    assert matches_filter({"tags": ["a", "b"]}, {"tags": {"$nin": ["c", "d"]}}) is True


def test_nin_list_field_partial_overlap() -> None:
    """$nin on a list field does not match when any element is in the exclusion list."""
    assert matches_filter({"tags": ["a", "c"]}, {"tags": {"$nin": ["c", "d"]}}) is False


# ---------------------------------------------------------------------------
# $and operator
# ---------------------------------------------------------------------------


def test_and_all_conditions_match() -> None:
    """$and matches when all sub-expressions match."""
    meta = {"type": "review", "status": "active"}
    f = {"$and": [{"type": {"$eq": "review"}}, {"status": {"$eq": "active"}}]}
    assert matches_filter(meta, f) is True


def test_and_one_condition_fails() -> None:
    """$and does not match when any one sub-expression fails."""
    meta = {"type": "review", "status": "inactive"}
    f = {"$and": [{"type": {"$eq": "review"}}, {"status": {"$eq": "active"}}]}
    assert matches_filter(meta, f) is False


def test_and_all_conditions_fail() -> None:
    """$and does not match when all sub-expressions fail."""
    meta = {"type": "adr", "status": "inactive"}
    f = {"$and": [{"type": {"$eq": "review"}}, {"status": {"$eq": "active"}}]}
    assert matches_filter(meta, f) is False


def test_and_empty_list_matches() -> None:
    """$and with empty sub-expression list vacuously matches (all() of empty is True)."""
    assert matches_filter({"x": 1}, {"$and": []}) is True


# ---------------------------------------------------------------------------
# $or operator
# ---------------------------------------------------------------------------


def test_or_first_condition_matches() -> None:
    """$or matches when the first sub-expression matches."""
    meta = {"type": "review"}
    f = {"$or": [{"type": {"$eq": "review"}}, {"type": {"$eq": "adr"}}]}
    assert matches_filter(meta, f) is True


def test_or_second_condition_matches() -> None:
    """$or matches when the second sub-expression matches."""
    meta = {"type": "adr"}
    f = {"$or": [{"type": {"$eq": "review"}}, {"type": {"$eq": "adr"}}]}
    assert matches_filter(meta, f) is True


def test_or_no_condition_matches() -> None:
    """$or does not match when no sub-expression matches."""
    meta = {"type": "spec"}
    f = {"$or": [{"type": {"$eq": "review"}}, {"type": {"$eq": "adr"}}]}
    assert matches_filter(meta, f) is False


def test_or_empty_list_no_match() -> None:
    """$or with empty sub-expression list does not match (any() of empty is False)."""
    assert matches_filter({"x": 1}, {"$or": []}) is False


def test_or_combined_with_and() -> None:
    """$or and $and can be nested: ($or outer, $and inner) works correctly."""
    meta = {"type": "review", "status": "active", "tier": 2}
    # Matches: (type=review AND status=active) OR (tier=3)
    f = {
        "$or": [
            {"$and": [{"type": {"$eq": "review"}}, {"status": {"$eq": "active"}}]},
            {"tier": {"$eq": 3}},
        ]
    }
    assert matches_filter(meta, f) is True


def test_or_combined_with_and_second_branch() -> None:
    """$or matches via the second branch when the first branch fails."""
    meta = {"type": "adr", "status": "inactive", "tier": 3}
    f = {
        "$or": [
            {"$and": [{"type": {"$eq": "review"}}, {"status": {"$eq": "active"}}]},
            {"tier": {"$eq": 3}},
        ]
    }
    assert matches_filter(meta, f) is True


# ---------------------------------------------------------------------------
# Plain equality shorthand
# ---------------------------------------------------------------------------


def test_plain_equality_match() -> None:
    """Plain {field: value} shorthand matches when field equals value."""
    assert matches_filter({"status": "active"}, {"status": "active"}) is True


def test_plain_equality_no_match() -> None:
    """Plain {field: value} shorthand does not match when field differs."""
    assert matches_filter({"status": "inactive"}, {"status": "active"}) is False


# ---------------------------------------------------------------------------
# Unsupported operator
# ---------------------------------------------------------------------------


def test_unsupported_operator_raises_filter_evaluation_error() -> None:
    """An unsupported operator raises the typed FilterEvaluationError (not a bare
    ValueError) with the operator in the message (07-02 #21)."""
    with pytest.raises(FilterEvaluationError, match="\\$gt"):
        matches_filter({"score": 5}, {"score": {"$gt": 3}})


# ---------------------------------------------------------------------------
# Multiple conditions in one dict (implicit AND)
# ---------------------------------------------------------------------------


def test_multiple_top_level_fields_all_must_match() -> None:
    """Two top-level conditions in one dict both must match (implicit AND)."""
    meta = {"type": "review", "status": "active"}
    assert matches_filter(meta, {"type": {"$eq": "review"}, "status": {"$eq": "active"}}) is True


def test_multiple_top_level_fields_one_fails() -> None:
    """Two top-level conditions — one failure means the whole filter fails."""
    meta = {"type": "review", "status": "inactive"}
    assert matches_filter(meta, {"type": {"$eq": "review"}, "status": {"$eq": "active"}}) is False


# ---------------------------------------------------------------------------
# $gte operator
# ---------------------------------------------------------------------------


def test_gte_value_above_operand_matches() -> None:
    """$gte matches when the field value is greater than the operand."""
    assert matches_filter({"ulid": "01JXYZ_Z"}, {"ulid": {"$gte": "01JXYZ_A"}}) is True


def test_gte_value_equal_operand_matches() -> None:
    """$gte matches when the field value equals the operand (inclusive lower bound)."""
    assert matches_filter({"ulid": "01JXYZ_M"}, {"ulid": {"$gte": "01JXYZ_M"}}) is True


def test_gte_value_below_operand_no_match() -> None:
    """$gte does not match when the field value is less than the operand."""
    assert matches_filter({"ulid": "01JXYZ_A"}, {"ulid": {"$gte": "01JXYZ_Z"}}) is False


def test_gte_missing_field_no_match() -> None:
    """$gte on a missing field does not match (None >= value is False)."""
    assert matches_filter({}, {"ulid": {"$gte": "01JXYZ_A"}}) is False


# ---------------------------------------------------------------------------
# $lte operator
# ---------------------------------------------------------------------------


def test_lte_value_below_operand_matches() -> None:
    """$lte matches when the field value is less than the operand."""
    assert matches_filter({"ulid": "01JXYZ_A"}, {"ulid": {"$lte": "01JXYZ_Z"}}) is True


def test_lte_value_equal_operand_matches() -> None:
    """$lte matches when the field value equals the operand (inclusive upper bound)."""
    assert matches_filter({"ulid": "01JXYZ_M"}, {"ulid": {"$lte": "01JXYZ_M"}}) is True


def test_lte_value_above_operand_no_match() -> None:
    """$lte does not match when the field value is greater than the operand."""
    assert matches_filter({"ulid": "01JXYZ_Z"}, {"ulid": {"$lte": "01JXYZ_A"}}) is False


def test_lte_missing_field_no_match() -> None:
    """$lte on a missing field does not match (None <= value is False)."""
    assert matches_filter({}, {"ulid": {"$lte": "01JXYZ_Z"}}) is False


# ---------------------------------------------------------------------------
# Combined $gte + $lte in an $and expression (closed interval)
# ---------------------------------------------------------------------------

_INTERVAL_FILTER = {
    "$and": [
        {"ulid": {"$gte": "01JXYZ_C"}},
        {"ulid": {"$lte": "01JXYZ_G"}},
    ]
}


def test_and_interval_value_within_bounds_matches() -> None:
    """Value within [lo, hi] matches the combined $gte + $lte interval."""
    assert matches_filter({"ulid": "01JXYZ_E"}, _INTERVAL_FILTER) is True


def test_and_interval_value_below_lower_no_match() -> None:
    """Value below lo does not match the combined interval."""
    assert matches_filter({"ulid": "01JXYZ_A"}, _INTERVAL_FILTER) is False


def test_and_interval_value_above_upper_no_match() -> None:
    """Value above hi does not match the combined interval."""
    assert matches_filter({"ulid": "01JXYZ_Z"}, _INTERVAL_FILTER) is False


def test_and_interval_value_equal_lower_bound_matches() -> None:
    """Value equal to lo matches (inclusive lower bound)."""
    assert matches_filter({"ulid": "01JXYZ_C"}, _INTERVAL_FILTER) is True


def test_and_interval_value_equal_upper_bound_matches() -> None:
    """Value equal to hi matches (inclusive upper bound)."""
    assert matches_filter({"ulid": "01JXYZ_G"}, _INTERVAL_FILTER) is True


# ---------------------------------------------------------------------------
# Regression guards — existing operators still work
# ---------------------------------------------------------------------------


def test_regression_eq_still_works() -> None:
    """$eq regression: scalar equality still works after adding range operators."""
    assert matches_filter({"type": "adr"}, {"type": {"$eq": "adr"}}) is True


def test_regression_in_still_works() -> None:
    """$in regression: scalar in-list still works after adding range operators."""
    assert matches_filter({"tier": 2}, {"tier": {"$in": [2, 3]}}) is True


def test_regression_nin_still_works() -> None:
    """$nin regression: scalar not-in-list still works after adding range operators."""
    assert matches_filter({"status": "active"}, {"status": {"$nin": ["inactive"]}}) is True


def test_regression_unknown_operator_raises_filter_evaluation_error() -> None:
    """Unknown operator still raises the typed FilterEvaluationError (regression
    guard)."""
    with pytest.raises(FilterEvaluationError, match="\\$gt"):
        matches_filter({"score": "5"}, {"score": {"$gt": "3"}})
