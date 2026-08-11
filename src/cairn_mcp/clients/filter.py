"""Metadata filter evaluation for S3 Vectors.

Used by both the concrete VectorsClientImpl (client-side filtering in
list_vectors_by_metadata) and the moto query_vectors extension in tests/unit/conftest.py.
Having a single implementation guarantees that tests exercise exactly the
same filter logic that runs in production.

Supported operators:
    {"field": {"$eq": value}}   — exact match; for list fields, value-in-list.
    {"field": {"$in": [...]}}   — field value is in the provided list.
    {"field": {"$nin": [...]}}  — not-in list; for list fields, no element in list.
    {"field": {"$gte": value}}  — field value >= value (string comparison).
    {"field": {"$lte": value}}  — field value <= value (string comparison).
    {"$and": [expr, ...]}       — logical AND of sub-expressions.
    {"$or": [expr, ...]}        — logical OR of sub-expressions.
"""

from typing import Any

from cairn_mcp.errors import FilterEvaluationError


def matches_filter(metadata: dict[str, Any], filter_expr: dict[str, Any]) -> bool:
    """Evaluate a metadata filter expression against a metadata dict.

    Args:
        metadata: The metadata dict attached to a vector.
        filter_expr: A filter expression using the supported operators above.

    Returns:
        True if the metadata satisfies all filter conditions.

    Raises:
        FilterEvaluationError: If an unsupported operator is encountered, or a
            ``$gte``/``$lte`` comparison is attempted between incomparable types.
    """
    for field, expr in filter_expr.items():
        if field == "$and":
            if not all(matches_filter(metadata, sub) for sub in expr):
                return False
        elif field == "$or":
            if not any(matches_filter(metadata, sub) for sub in expr):
                return False
        elif isinstance(expr, dict):
            field_value = metadata.get(field)
            for op, operand in expr.items():
                if op == "$eq":
                    if isinstance(field_value, list):
                        if operand not in field_value:
                            return False
                    elif field_value != operand:
                        return False
                elif op == "$in":
                    if isinstance(field_value, list):
                        if not any(v in operand for v in field_value):
                            return False
                    elif field_value not in operand:
                        return False
                elif op == "$nin":
                    if isinstance(field_value, list):
                        if any(v in operand for v in field_value):
                            return False
                    elif field_value in operand:
                        return False
                elif op == "$gte":
                    if field_value is None:
                        return False
                    try:
                        if field_value < operand:
                            return False
                    except TypeError as exc:
                        raise FilterEvaluationError(
                            f"Cannot compare $gte field {field!r} value {field_value!r} "
                            f"({type(field_value).__name__}) against operand {operand!r} "
                            f"({type(operand).__name__})"
                        ) from exc
                elif op == "$lte":
                    if field_value is None:
                        return False
                    try:
                        if field_value > operand:
                            return False
                    except TypeError as exc:
                        raise FilterEvaluationError(
                            f"Cannot compare $lte field {field!r} value {field_value!r} "
                            f"({type(field_value).__name__}) against operand {operand!r} "
                            f"({type(operand).__name__})"
                        ) from exc
                else:
                    raise FilterEvaluationError(f"Unsupported filter operator: {op}")
        else:
            # Plain equality shorthand: {"field": value}
            if metadata.get(field) != expr:
                return False
    return True
