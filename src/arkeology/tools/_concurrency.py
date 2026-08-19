"""arkeology.tools._concurrency — shared artifact_concurrency clamp helper.

Extracted (G-3, Task 68) from the byte-for-byte-identical clamp-with-warning
logic previously duplicated in write_artifacts.py and migrate_artifacts.py.
"""

_ARTIFACT_CONCURRENCY_DEFAULT: int = 3
_ARTIFACT_CONCURRENCY_MAX: int = 15


def _clamp_concurrency(value: int, default: int, max_: int) -> tuple[int, str | None]:
    """Clamp a caller-supplied ``artifact_concurrency`` value to ``[1, max_]``.

    A value above ``max_`` is capped to ``max_``. A value below 1 is substituted
    with ``default``. Out-of-range values are never an error — only a warning.

    Args:
        value: The caller-requested artifact_concurrency.
        default: Substituted when ``value < 1``.
        max_: The ceiling; ``value`` is capped to this when exceeded.

    Returns:
        ``(effective, warning)`` — ``warning`` is ``None`` when ``value`` was
        already within ``[1, max_]``, otherwise a human-readable message
        describing the clamp that was applied.
    """
    if value > max_:
        return max_, (
            f"artifact_concurrency={value} exceeds the maximum of {max_}; "
            f"effective concurrency capped to {max_}."
        )
    if value < 1:
        return default, (
            f"artifact_concurrency={value} is below the minimum of 1; "
            f"effective concurrency substituted with the default {default}."
        )
    return value, None
