"""Metadata filter evaluation for S3 Vectors.

Used by both the concrete VectorsClientImpl (client-side filtering in
list_vectors_by_metadata) and the FakeVectorsClient (unit test simulation).
Having a single implementation guarantees that tests exercise exactly the
same filter logic that runs in production.

Supported operators:
    {"field": {"$eq": value}}  — exact match; for list fields, value-in-list.
    {"field": {"$nin": [...]}} — not-in list; for list fields, no element in list.
    {"$and": [expr, ...]}      — logical AND of sub-expressions.
"""

from typing import Any


def matches_filter(metadata: dict[str, Any], filter: dict[str, Any]) -> bool:
    """Evaluate a metadata filter expression against a metadata dict.

    Args:
        metadata: The metadata dict attached to a vector.
        filter: A filter expression using the supported operators above.

    Returns:
        True if the metadata satisfies all filter conditions.

    Raises:
        ValueError: If an unsupported operator is encountered.
    """
    for field, expr in filter.items():
        if field == "$and":
            if not all(matches_filter(metadata, sub) for sub in expr):
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
                elif op == "$nin":
                    if isinstance(field_value, list):
                        if any(v in operand for v in field_value):
                            return False
                    elif field_value in operand:
                        return False
                else:
                    raise ValueError(f"Unsupported filter operator: {op}")
        else:
            # Plain equality shorthand: {"field": value}
            if metadata.get(field) != expr:
                return False
    return True
