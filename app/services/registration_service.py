from __future__ import annotations

from app.models.enums import BlindLevelKind
from app.models.tournament import BlindLevel


def late_registration_phase(
    levels: list[BlindLevel], current_level_index: int, end_level_index: int | None
) -> str:
    """Возвращает серверную фазу поздней регистрации для текущего уровня."""
    if end_level_index is None:
        return "open"

    if current_level_index > end_level_index:
        next_item = next((level for level in levels if level.order_index == end_level_index + 1), None)
        if (
            next_item is not None
            and next_item.kind == BlindLevelKind.BREAK
            and current_level_index == next_item.order_index
        ):
            return "grace_break"
        return "closed"
    if current_level_index == end_level_index:
        return "closing"

    play_levels_until_end = sum(
        1
        for level in levels
        if level.kind == BlindLevelKind.PLAY
        and current_level_index < level.order_index <= end_level_index
    )
    return "next_level" if play_levels_until_end == 1 else "open"
